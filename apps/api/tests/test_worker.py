"""Scheduled ingestion (spec sections 21, 25, 27).

The tests here are almost all about failure. A worker that ingests correctly on a good day
is easy; what decides whether it can be left running unattended is what it does when the
provider is down, when a paper disappears, and when a run dies halfway through.

The first test in the file is the one that matters most, because the bug it pins was not
found by reasoning about the code — it was found by running the worker twice and noticing
that the second pass had exactly as much work to do as the first.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import AuditLog, IngestionRun, Paper
from papermatch_api.providers.base import PaperQuery, PaperRecord, ProviderHealth
from papermatch_api.services.worker import (
    JobSpec,
    due_jobs,
    last_successful_run,
    run_discovery,
    run_refresh,
    stale_papers,
    tick,
)
from tests.conftest import requires_db

pytestmark = [pytest.mark.integration, requires_db]

NOW = datetime(2026, 8, 1, tzinfo=UTC)

#: These tests run against `seeded_db`, which already holds the 60-paper sample corpus —
#: and the refresh queue is "every paper from this source". They stay isolated because the
#: sample corpus is all `source_provider="mock"` while these records are `"arxiv"`, so the
#: queue only ever contains the paper the test just ingested. Load-bearing and easy to
#: break from the other end: change the fixtures to another provider and these tests start
#: seeing sixty papers they did not put there. `counts["missing"] == 1` below is what
#: notices if that ever happens.


def record(canonical_id: str, **overrides: object) -> PaperRecord:
    base = PaperRecord(
        canonical_id=canonical_id,
        title="Spectral Gaps in Sparse Expander Families",
        abstract=(
            "Expander graphs combine sparsity with strong connectivity. "
            "We construct an explicit family using a zig-zag product. "
            "We obtain a spectral gap of 0.31 at degree eight."
        ),
        authors=({"name": "K. Aoki"},),
        year=2025,
        identifiers=({"kind": "arxiv", "value": canonical_id.removeprefix("arxiv:")},),
        # A name the vocabulary allows: `source_provider` carries a CHECK constraint, and
        # inventing a value here would test the constraint rather than the worker.
        source_provider="arxiv",
        source_url=f"https://arxiv.org/abs/{canonical_id}",
        # Deliberately not "now": this is the provider's own timestamp, and the whole point
        # of the first test is that the refresh queue must not depend on it.
        acquired_at=datetime(2020, 1, 1, tzinfo=UTC),
        license_id="CC-BY-4.0",
        license_url=None,
        abstract_redistributable=True,
        primary_field_id="math.CO",
        field_weights={"math.CO": 0.7, "math": 0.2},
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


class FakeProvider:
    """A provider whose behaviour each test dictates."""

    name = "arxiv"

    def __init__(
        self,
        records: list[PaperRecord] | None = None,
        *,
        by_id: dict[str, PaperRecord | None] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._records = records or []
        self._by_id = by_id or {}
        self._raises = raises
        self.search_calls: list[PaperQuery] = []
        self.fetch_calls: list[str] = []

    def search(self, query: PaperQuery) -> tuple[list[PaperRecord], str | None]:
        self.search_calls.append(query)
        if self._raises is not None:
            raise self._raises
        return list(self._records), None

    def get_by_canonical_id(self, canonical_id: str) -> PaperRecord | None:
        self.fetch_calls.append(canonical_id)
        if self._raises is not None:
            raise self._raises
        return self._by_id.get(canonical_id)

    def health(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, healthy=True)


def _ingest_one(session: Session, canonical_id: str) -> Paper:
    provider = FakeProvider([record(canonical_id)])
    run_discovery(session, provider, JobSpec(source="arxiv", job="seed"), now=NOW)
    paper = session.execute(select(Paper).where(Paper.canonical_id == canonical_id)).scalar_one()
    return paper


# ------------------------------------------------------------------- the refresh queue


def test_the_refresh_queue_advances_instead_of_re_checking_one_batch(
    seeded_db: Session,
) -> None:
    """The bug that running it found, and the reason `last_refreshed_at` exists.

    Ordering by `acquired_at` looks right and is not: that column is provenance the
    *provider* supplies (spec section 21), so a source reporting anything other than our
    fetch time leaves every paper permanently past the staleness threshold. The queue then
    re-checks its oldest batch on every run, for ever, reporting healthy numbers throughout
    — which is precisely why nothing else in this file would have caught it.
    """
    paper = _ingest_one(seeded_db, "arxiv:2501.00001")
    assert paper.acquired_at < NOW - timedelta(days=7), "the provider's timestamp is ancient"

    spec = JobSpec(source="arxiv", job="refresh", kind="refresh")
    provider = FakeProvider(by_id={"arxiv:2501.00001": record("arxiv:2501.00001")})

    before = stale_papers(seeded_db, "arxiv", now=NOW)
    assert paper.id in {p.id for p in before}

    run_refresh(seeded_db, provider, spec, now=NOW)

    after = stale_papers(seeded_db, "arxiv", now=NOW)
    assert paper.id not in {p.id for p in after}, (
        "a paper just checked must leave the queue, or the next run redoes the same work"
    )
    assert paper.last_refreshed_at is not None


def test_a_paper_the_provider_cannot_resolve_still_leaves_the_queue(
    seeded_db: Session,
) -> None:
    """Otherwise one unresolvable paper sits at the head of the queue and blocks the rest.

    The same livelock as the test above, reached from the other direction.
    """
    paper = _ingest_one(seeded_db, "arxiv:2501.00002")
    provider = FakeProvider(by_id={})  # resolves nothing

    run_refresh(
        seeded_db, provider, JobSpec(source="arxiv", job="refresh", kind="refresh"), now=NOW
    )

    assert paper.last_refreshed_at is not None
    assert paper.id not in {p.id for p in stale_papers(seeded_db, "arxiv", now=NOW)}


# ------------------------------------------------------------- what absence does not mean


def test_a_paper_the_provider_stops_returning_is_not_treated_as_retracted(
    seeded_db: Session,
) -> None:
    """The single most consequential line in the worker.

    `get_by_canonical_id` returning None means the provider did not give us the record —
    a transient failure, a moved identifier, a source that never had it. Reading that as
    grounds to hide the paper would let one bad afternoon upstream silently empty a feed.
    """
    paper = _ingest_one(seeded_db, "arxiv:2501.00003")
    assert paper.retraction_status == "none"

    provider = FakeProvider(by_id={})
    run = run_refresh(
        seeded_db, provider, JobSpec(source="arxiv", job="refresh", kind="refresh"), now=NOW
    )

    assert paper.retraction_status == "none", "absence is not evidence of withdrawal"
    assert run.counts["missing"] == 1
    assert run.counts["retracted"] == 0


def test_a_real_retraction_is_applied_and_audited(seeded_db: Session) -> None:
    """Spec section 21: 削除・訂正・撤回情報を反映できる."""
    paper = _ingest_one(seeded_db, "arxiv:2501.00004")
    withdrawn = record("arxiv:2501.00004", retraction_status="withdrawn")

    run = run_refresh(
        seeded_db,
        FakeProvider(by_id={"arxiv:2501.00004": withdrawn}),
        JobSpec(source="arxiv", job="refresh", kind="refresh"),
        now=NOW,
    )

    assert paper.retraction_status == "withdrawn"
    assert run.counts["retracted"] == 1
    audited = seeded_db.execute(
        select(AuditLog).where(
            AuditLog.kind == "retraction_synced", AuditLog.entity_id == str(paper.id)
        )
    ).scalar_one()
    assert audited.detail["from"] == "none"
    assert audited.detail["to"] == "withdrawn"


# ----------------------------------------------------------------- surviving a bad day


def test_a_provider_that_raises_records_a_failed_run_rather_than_stopping(
    seeded_db: Session,
) -> None:
    """Spec section 25: an outage degrades freshness, it does not stop the process."""
    provider = FakeProvider(raises=RuntimeError("upstream is on fire"))
    run = run_discovery(seeded_db, provider, JobSpec(source="arxiv", job="field:math.CO"), now=NOW)

    assert run.status == "failed"
    assert run.error is not None
    assert "upstream is on fire" in run.error


def test_a_failed_run_is_not_what_the_next_run_resumes_from(seeded_db: Session) -> None:
    """A failed run's cursor points into a page whose records may never have been stored.

    Resuming from it would skip them silently and nothing later would notice; re-reading
    the page costs nothing, because upserting is idempotent.
    """
    spec = JobSpec(source="arxiv", job="field:math.CO")
    run_discovery(seeded_db, FakeProvider([record("arxiv:2501.00005")]), spec, now=NOW)
    good = last_successful_run(seeded_db, "arxiv", "field:math.CO")

    run_discovery(seeded_db, FakeProvider(raises=RuntimeError("boom")), spec, now=NOW)

    assert last_successful_run(seeded_db, "arxiv", "field:math.CO") is good


def test_one_failing_job_does_not_stop_the_others(seeded_db: Session) -> None:
    good = JobSpec(source="arxiv", job="field:math.CO")
    bad = JobSpec(source="missing-provider", job="field:hep-th")
    runs = tick(
        seeded_db,
        {"arxiv": FakeProvider([record("arxiv:2501.00006")])},
        [bad, good],
        now=NOW,
    )
    assert [run.job for run in runs] == ["field:math.CO"]
    assert runs[0].status == "succeeded"


# --------------------------------------------------------------------------- scheduling


def test_a_job_that_has_never_run_is_due_immediately(seeded_db: Session) -> None:
    """A fresh deployment should not wait six hours for its first card."""
    spec = JobSpec(source="arxiv", job="field:math.CO")
    assert due_jobs(seeded_db, [spec], now=NOW) == [spec]


def test_a_job_is_not_due_again_until_its_interval_elapses(seeded_db: Session) -> None:
    """Spec section 27 counts 同一ソースへの過剰APIアクセス as a guardrail breach."""
    spec = JobSpec(source="arxiv", job="field:math.CO", interval=timedelta(hours=6))
    run_discovery(seeded_db, FakeProvider([record("arxiv:2501.00007")]), spec, now=NOW)

    assert due_jobs(seeded_db, [spec], now=NOW + timedelta(hours=1)) == []
    assert due_jobs(seeded_db, [spec], now=NOW + timedelta(hours=7)) == [spec]


def test_a_failed_run_does_not_count_as_having_run(seeded_db: Session) -> None:
    """Otherwise an outage would also silence the retry for a whole interval."""
    spec = JobSpec(source="arxiv", job="field:math.CO", interval=timedelta(hours=6))
    run_discovery(seeded_db, FakeProvider(raises=RuntimeError("boom")), spec, now=NOW)

    assert due_jobs(seeded_db, [spec], now=NOW + timedelta(minutes=1)) == [spec]


def test_every_run_leaves_a_row_an_operator_can_read(seeded_db: Session) -> None:
    run_discovery(
        seeded_db,
        FakeProvider([record("arxiv:2501.00008")]),
        JobSpec(source="arxiv", job="field:math.CO"),
        now=NOW,
    )
    row = (
        seeded_db.execute(select(IngestionRun).where(IngestionRun.source == "arxiv"))
        .scalars()
        .first()
    )
    assert row is not None
    assert row.status == "succeeded"
    assert row.finished_at is not None
    assert "inserted" in row.counts
