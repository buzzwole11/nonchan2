"""Scheduled ingestion (spec sections 21, 25, 27).

Two jobs, on separate schedules, because they answer different questions.

**Discovery** asks "what is new?" and pages forward through a source. It resumes from the
cursor of the last run that succeeded, which is what keeps section 27's guardrail
(同一ソースへの過剰APIアクセス) from being violated by every restart re-reading page one.

**Refresh** asks "is what we already hold still true?" Section 21 requires
削除・訂正・撤回情報を反映できる, and a copy taken once is a copy that goes stale: papers get
retracted, preprints get published, versions get replaced. Refresh walks the papers we have
gone longest without checking and asks the source about them again.

Four rules shape the implementation.

**"When we last checked" is not "when we acquired it".** `acquired_at` is provenance the
provider supplies (section 21); `last_refreshed_at` is our own note. Ordering the refresh
queue by the former looked equivalent and was not — running it showed every paper still
stale after a full pass, because a provider is free to report a timestamp that is not our
fetch time. The queue would re-check its oldest batch on every run, for ever, while
reporting healthy numbers throughout.

**A paper the provider no longer returns is not thereby retracted.** `get_by_canonical_id`
returning `None` means the provider did not give us the record — which happens on a
transient failure, a moved identifier, or a source that never had it. Treating that as
grounds to hide the paper would let one bad afternoon at an upstream API silently empty a
reader's feed. Absence is counted and logged; it never changes `retraction_status`.

**A failed run does not move the cursor.** The next run resumes from the last *successful*
one, so a crash halfway through a page re-reads that page rather than skipping past it.
Re-reading is free — `upsert_record` is idempotent — and skipping is not recoverable
without a full rescan.

**The worker never raises into the scheduler.** A provider outage should degrade the
feed's freshness, not stop the process (section 25: 外部API失敗時もキャッシュ済みフィードを
表示). Failures are recorded on the run row and the next job still gets its turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from papermatch_api.models import AuditLog, IngestionRun, Paper
from papermatch_api.providers.base import PaperProvider, PaperQuery
from papermatch_api.services.ingestion import ingest, upsert_record

__all__ = [
    "DEFAULT_DISCOVERY_INTERVAL",
    "DEFAULT_REFRESH_INTERVAL",
    "JobSpec",
    "RefreshReport",
    "due_jobs",
    "last_successful_run",
    "run_discovery",
    "run_refresh",
    "summarise",
    "tick",
]

#: How often a discovery job may run. Section 27 counts over-fetching a source as a
#: guardrail breach, and arXiv's own guidance asks for restraint; new preprints appear on a
#: daily cycle, so anything under an hour is asking for data that does not exist yet.
DEFAULT_DISCOVERY_INTERVAL = timedelta(hours=6)

#: How often the refresh job may run. Retractions are rare and not urgent to the minute,
#: but a day is too long to keep showing withdrawn work.
DEFAULT_REFRESH_INTERVAL = timedelta(hours=12)

#: A paper is eligible for refresh once its copy is this old. Also the reason refresh is
#: cheap: at any moment most of the corpus is younger than this.
DEFAULT_STALE_AFTER = timedelta(days=7)

#: How many papers one refresh run revisits. Bounded so a large corpus produces a long
#: series of small polite runs rather than one enormous one.
DEFAULT_REFRESH_BATCH = 50


@dataclass(frozen=True)
class JobSpec:
    """One unit of scheduled work."""

    source: str
    job: str
    kind: str = "discovery"
    query: PaperQuery | None = None
    interval: timedelta = DEFAULT_DISCOVERY_INTERVAL


@dataclass
class RefreshReport:
    """What one refresh pass learned. Every field is a different kind of news."""

    checked: int = 0
    unchanged: int = 0
    updated: int = 0
    #: Newly retracted or withdrawn since we copied them. The number section 21 cares about.
    retractions: list[str] = field(default_factory=list)
    #: Papers the provider did not return. Not evidence of anything — see the module
    #: docstring — but worth surfacing, because a sudden spike means the source is unwell.
    missing: list[str] = field(default_factory=list)

    def as_counts(self) -> dict[str, int]:
        return {
            "checked": self.checked,
            "unchanged": self.unchanged,
            "updated": self.updated,
            "retracted": len(self.retractions),
            "missing": len(self.missing),
        }


# ------------------------------------------------------------------------------ state


def last_successful_run(session: Session, source: str, job: str) -> IngestionRun | None:
    """The most recent run of this job that finished cleanly.

    Successful only, because a failed run's cursor points into a page whose records may
    never have been stored. Resuming from it would skip them silently, and nothing later
    would notice.
    """
    return session.execute(
        select(IngestionRun)
        .where(
            IngestionRun.source == source,
            IngestionRun.job == job,
            IngestionRun.status == "succeeded",
        )
        .order_by(IngestionRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def due_jobs(
    session: Session, specs: list[JobSpec], *, now: datetime | None = None
) -> list[JobSpec]:
    """The jobs whose interval has elapsed.

    A job that has never run is due immediately — a fresh deployment should not wait six
    hours for its first card.
    """
    now = now or datetime.now(tz=UTC)
    due: list[JobSpec] = []
    for spec in specs:
        previous = last_successful_run(session, spec.source, spec.job)
        if previous is None or previous.started_at + spec.interval <= now:
            due.append(spec)
    return due


def _start(session: Session, spec: JobSpec, *, now: datetime) -> IngestionRun:
    run = IngestionRun(
        source=spec.source, job=spec.job, kind=spec.kind, status="running", started_at=now
    )
    session.add(run)
    session.flush()
    return run


def _finish(
    session: Session,
    run: IngestionRun,
    *,
    counts: dict[str, int],
    cursor: str | None = None,
    error: str | None = None,
) -> IngestionRun:
    run.status = "failed" if error is not None else "succeeded"
    run.finished_at = datetime.now(tz=UTC)
    run.counts = counts
    run.error = error
    if error is None:
        run.cursor = cursor
    session.add(
        AuditLog(
            kind="ingestion_run",
            actor=f"provider:{run.source}",
            entity_type="ingestion_run",
            entity_id=str(run.id),
            detail={"job": run.job, "runKind": run.kind, "status": run.status, **counts},
        )
    )
    session.flush()
    return run


# --------------------------------------------------------------------------- discovery


def run_discovery(
    session: Session,
    provider: PaperProvider,
    spec: JobSpec,
    *,
    max_records: int = 200,
    now: datetime | None = None,
) -> IngestionRun:
    """Page forward through a source, resuming where the last successful run stopped."""
    now = now or datetime.now(tz=UTC)
    previous = last_successful_run(session, spec.source, spec.job)
    base = spec.query or PaperQuery(limit=50)
    query = PaperQuery(
        field_ids=base.field_ids,
        limit=base.limit,
        # The stored cursor wins over the spec's, so a job definition can be edited without
        # sending the next run back to page one.
        cursor=previous.cursor if previous is not None else base.cursor,
        year_from=base.year_from,
        year_to=base.year_to,
        exclude_canonical_ids=base.exclude_canonical_ids,
        include_types=base.include_types,
    )

    run = _start(session, spec, now=now)
    try:
        report = ingest(session, provider, query=query, max_records=max_records)
    # Broad on purpose: the scheduler must survive whatever a provider does.
    except Exception as exc:
        return _finish(session, run, counts={}, error=f"{type(exc).__name__}: {exc}")

    return _finish(
        session,
        run,
        counts={
            "inserted": report.inserted,
            "updated": report.updated,
            "merged": report.merged_duplicates,
            "skippedUnlicensed": report.skipped_unlicensed,
        },
        # `ingest` pages until it runs out; a `None` cursor means the source is exhausted
        # for this query and the next run should start over, which is what catches papers
        # published since. That is the correct reading of "resume", not a lost position.
        cursor=None,
    )


# ----------------------------------------------------------------------------- refresh


def stale_papers(
    session: Session,
    source: str,
    *,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    limit: int = DEFAULT_REFRESH_BATCH,
    now: datetime | None = None,
) -> list[Paper]:
    """The papers from this source we have gone longest without checking.

    Keyed on `last_refreshed_at`, falling back to `acquired_at` for papers never refreshed,
    and **not** on `acquired_at` alone. That looked equivalent and is not: `acquired_at` is
    provenance the provider supplies (section 21), so a source that reports a fixed
    timestamp — or any timestamp that is not our fetch time — leaves its papers permanently
    past the staleness threshold. The queue would then re-check the same oldest batch on
    every run and never reach anything else, while reporting healthy numbers the whole time.
    """
    now = now or datetime.now(tz=UTC)
    checked_at = func.coalesce(Paper.last_refreshed_at, Paper.acquired_at)
    return list(
        session.execute(
            select(Paper)
            .where(Paper.source_provider == source, checked_at <= now - stale_after)
            .order_by(checked_at.asc())
            .limit(limit)
        ).scalars()
    )


def refresh_paper(session: Session, provider: PaperProvider, paper: Paper) -> str:
    """Re-fetch one paper. Returns what happened, as a word.

    ``"missing"`` is not ``"retracted"``. See the module docstring — this is the single
    most consequential line in the file, because conflating the two turns a provider
    outage into a silently emptied feed.
    """
    before_status = paper.retraction_status
    before_version = paper.version

    record = provider.get_by_canonical_id(paper.canonical_id)
    if record is None:
        # Still counts as checked. Otherwise a paper the provider cannot resolve would sit
        # at the head of the queue forever, blocking everything behind it — the same
        # livelock as ordering by `acquired_at`, arrived at from the other direction.
        paper.last_refreshed_at = datetime.now(tz=UTC)
        return "missing"

    upsert_record(session, record)
    paper.last_refreshed_at = datetime.now(tz=UTC)
    if paper.retraction_status != before_status and paper.retraction_status in {
        "withdrawn",
        "retracted",
    }:
        session.add(
            AuditLog(
                kind="retraction_synced",
                actor=f"provider:{provider.name}",
                entity_type="paper",
                entity_id=str(paper.id),
                detail={
                    "canonicalId": paper.canonical_id,
                    "from": before_status,
                    "to": paper.retraction_status,
                },
            )
        )
        return "retracted"
    if paper.version != before_version or paper.retraction_status != before_status:
        return "updated"
    return "unchanged"


def run_refresh(
    session: Session,
    provider: PaperProvider,
    spec: JobSpec,
    *,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
    limit: int = DEFAULT_REFRESH_BATCH,
    now: datetime | None = None,
) -> IngestionRun:
    """Revisit the stalest copies from one source (spec section 21)."""
    now = now or datetime.now(tz=UTC)
    run = _start(session, spec, now=now)
    report = RefreshReport()

    try:
        papers = stale_papers(session, spec.source, stale_after=stale_after, limit=limit, now=now)
        for paper in papers:
            report.checked += 1
            outcome = refresh_paper(session, provider, paper)
            if outcome == "missing":
                report.missing.append(paper.canonical_id)
            elif outcome == "retracted":
                report.retractions.append(paper.canonical_id)
            elif outcome == "updated":
                report.updated += 1
            else:
                report.unchanged += 1
    # Broad on purpose: see run_discovery.
    except Exception as exc:
        return _finish(
            session, run, counts=report.as_counts(), error=f"{type(exc).__name__}: {exc}"
        )

    return _finish(session, run, counts=report.as_counts())


# --------------------------------------------------------------------------------- tick


def tick(
    session: Session,
    providers: dict[str, PaperProvider],
    specs: list[JobSpec],
    *,
    now: datetime | None = None,
) -> list[IngestionRun]:
    """Run every job that is due, once.

    One pass rather than a loop, so the caller owns the sleeping. That keeps this testable
    without a clock and lets the same function back a cron entry, a `--once` CLI run and a
    long-lived process.
    """
    now = now or datetime.now(tz=UTC)
    runs: list[IngestionRun] = []
    for spec in due_jobs(session, specs, now=now):
        provider = providers.get(spec.source)
        if provider is None:
            # A job naming a provider that is not configured is a deployment mistake, not
            # a reason to stop the others.
            continue
        if spec.kind == "refresh":
            runs.append(run_refresh(session, provider, spec, now=now))
        else:
            runs.append(run_discovery(session, provider, spec, now=now))
    return runs


def default_jobs(source: str, field_ids: list[str]) -> list[JobSpec]:
    """One discovery job per field, plus one refresh job for the source.

    Per field rather than one job for everything: a source that returns nothing for
    `math.NT` should not stop `hep-th` from paging forward, and the cursors are only
    comparable within one query anyway.
    """
    jobs = [
        JobSpec(
            source=source,
            job=f"field:{field_id}",
            kind="discovery",
            query=PaperQuery(field_ids=(field_id,), limit=50),
        )
        for field_id in field_ids
    ]
    jobs.append(
        JobSpec(source=source, job="refresh", kind="refresh", interval=DEFAULT_REFRESH_INTERVAL)
    )
    return jobs


@dataclass(frozen=True)
class RunSummary:
    """One line of the operator-facing run log."""

    source: str
    job: str
    kind: str
    status: str
    started_at: datetime
    counts: dict[str, int]
    error: str | None

    def one_line(self) -> str:
        return _one_line(self.source, self.job, self.kind, self.status, self.counts)


def _one_line(source: str, job: str, kind: str, status: str, counts: dict[str, int]) -> str:
    rendered = " ".join(f"{name}={value}" for name, value in sorted(counts.items()))
    return f"{source} {job} [{kind}] {status} {rendered}".rstrip()


def summarise(run: IngestionRun) -> str:
    """One line for a run that is still attached to its session."""
    return _one_line(
        run.source, run.job, run.kind, run.status, {str(k): int(v) for k, v in run.counts.items()}
    )


def run_summary(session: Session, limit: int = 20) -> list[RunSummary]:
    """Recent runs, newest first — what an operator reads to answer "is it working?"."""
    rows = session.execute(
        select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit)
    ).scalars()
    return [
        RunSummary(
            source=row.source,
            job=row.job,
            kind=row.kind,
            status=row.status,
            started_at=row.started_at,
            counts={str(k): int(v) for k, v in row.counts.items()},
            error=row.error,
        )
        for row in rows
    ]


def purge_runs(session: Session, keep: int = 500) -> int:
    """Keep the run log bounded. Returns how many rows went.

    The audit log keeps the permanent record; this table is operational state, and an
    unbounded one would eventually make `last_successful_run` slow for no benefit.
    """
    keep_ids = (
        select(IngestionRun.id).order_by(IngestionRun.started_at.desc()).limit(keep).subquery()
    )
    doomed = list(
        session.execute(
            select(IngestionRun.id).where(IngestionRun.id.notin_(select(keep_ids.c.id)))
        ).scalars()
    )
    if doomed:
        session.execute(delete(IngestionRun).where(IngestionRun.id.in_(doomed)))
        session.flush()
    return len(doomed)
