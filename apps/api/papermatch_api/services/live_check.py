"""One pass that proves the app works on real data (spec sections 21, 29).

Spec section 29's completion condition for Phase 1 is 実データ100件以上でフィードが構成できる,
and section 1-A's remaining item is 実 API への疎通確認. Both need outbound access to the
paper APIs, which the development environment blocks — so they have never been run, and
"the parser handles the documented shape" has never become "the shape is still what the
documentation says".

This is the single pass that answers both, in the order the answers depend on each other:
reach the APIs, parse what they return, store it, and build a feed from what was stored. A
failure at any step stops there and says which step it was, because "the feed is empty" has
four very different causes and guessing between them is what makes this kind of check
useless.

**It writes to the database it is pointed at.** Ingestion is the thing under test — a check
that ran against a scratch copy would prove the parser works and leave the actual question
(does *our* pipeline store what *this* API returns) unanswered. Point it at a scratch
database if that matters; it is idempotent either way, since ingestion deduplicates.

**It does not touch the reader's own settings or library.** The feed is built for a
throwaway user created inside the pass, so a real reader's history is neither read nor
disturbed by a diagnostic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from papermatch_api.models import Field, Paper, User, UserSettings
from papermatch_api.providers.base import PaperProvider, PaperQuery, ProviderUnavailable
from papermatch_api.services.feed import build_feed
from papermatch_api.services.ingestion import ingest

__all__ = ["LiveCheckReport", "StepResult", "run_live_check"]

#: Section 29 says 100件以上. Asked for a little more so a provider that returns slightly
#: fewer than requested still clears the bar.
TARGET_PAPERS = 120

#: Fields to pull from, chosen to span the three areas the corpus is meant to cover
#: (physics / maths / computing) so the 70/20/10 mix has something to be a mix *of*.
LIVE_FIELDS: tuple[str, ...] = ("hep-th", "math.PR", "cs.LG")


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str
    #: Seconds. Reported because a provider that answers in 40s is a different problem from
    #: one that refuses, and both look like "slow" from the outside.
    seconds: float = 0.0


@dataclass
class LiveCheckReport:
    steps: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(step.ok for step in self.steps)

    def add(self, name: str, ok: bool, detail: str, seconds: float = 0.0) -> StepResult:
        step = StepResult(name=name, ok=ok, detail=detail, seconds=seconds)
        self.steps.append(step)
        return step

    def render(self) -> str:
        lines = [
            f"{'✓' if step.ok else '✗'} {step.name}"
            + (f"  ({step.seconds:.1f}s)" if step.seconds else "")
            + f"\n    {step.detail}"
            for step in self.steps
        ]
        verdict = (
            "実データでの疎通とフィード構成を確認しました（仕様書 29 節）。"
            if self.ok
            else "途中で止まりました。上の ✗ が最初に失敗した段階です。"
        )
        return "\n".join(lines) + "\n\n" + verdict


def _reachable(provider: PaperProvider, report: LiveCheckReport) -> bool:
    """One small query, purely to separate "cannot reach" from "reached and parsed badly"."""
    started = time.monotonic()
    try:
        records, _ = provider.search(PaperQuery(field_ids=(LIVE_FIELDS[0],), limit=1))
    except ProviderUnavailable as exc:
        report.add(
            f"{provider.name}: 疎通",
            False,
            f"到達できません（{exc}）。egress の許可と、このセッションが許可の後に"
            "起動されたかを確認してください",
            time.monotonic() - started,
        )
        return False
    except Exception as exc:
        report.add(
            f"{provider.name}: 疎通",
            False,
            f"想定外の失敗 {type(exc).__name__}: {exc}",
            time.monotonic() - started,
        )
        return False

    report.add(
        f"{provider.name}: 疎通",
        True,
        f"{len(records)} 件返り、パースできました",
        time.monotonic() - started,
    )
    return True


def _parses(provider: PaperProvider, report: LiveCheckReport) -> bool:
    """Whether the live shape is still one the pipeline can use.

    Not a repeat of the unit tests: those prove the parser handles the *documented* shape.
    This proves the live shape is still that one — the only thing a recorded fixture can
    never tell us.

    **The bar is "some record is usable", not "every record is perfect."** A first draft
    failed on any record missing a licence, and that would have cried wolf on the first
    real run: OpenAlex legitimately returns works whose terms it does not know, and the
    ingestion gate is *built* to skip those (spec section 21). A record that cannot be used
    is normal; a *batch* in which none can be used means the shape moved, and that is the
    thing worth stopping for. Both counts are reported either way, because "45 of 50 had a
    licence" is the number that tells an operator whether a run will be worth making.
    """
    started = time.monotonic()
    try:
        records, _ = provider.search(PaperQuery(field_ids=(LIVE_FIELDS[0],), limit=10))
    except ProviderUnavailable as exc:
        report.add(f"{provider.name}: 形状", False, str(exc), time.monotonic() - started)
        return False

    usable = [
        record
        for record in records
        if record.title.strip()
        and record.abstract.strip()
        and record.canonical_id.startswith(("doi:", "arxiv:", "openalex:"))
    ]
    licensed = [record for record in usable if record.license_id]

    if not records:
        report.add(
            f"{provider.name}: 形状",
            False,
            "レコードが 1 件も返りませんでした（クエリか API の仕様変更）",
            time.monotonic() - started,
        )
        return False
    if not usable:
        report.add(
            f"{provider.name}: 形状",
            False,
            f"{len(records)} 件返りましたが、題名・Abstract・識別子が揃ったものが 0 件です。"
            "API の応答形状が変わった可能性があります",
            time.monotonic() - started,
        )
        return False

    report.add(
        f"{provider.name}: 形状",
        True,
        f"{len(records)} 件中 {len(usable)} 件が利用可能、うち {len(licensed)} 件に"
        "ライセンス記載（無いものは取り込み時に見送られます — 仕様書 21 節）",
        time.monotonic() - started,
    )
    return True


def _ingests(session: Session, provider: PaperProvider, report: LiveCheckReport) -> int:
    """Store real records through the real pipeline, across several fields."""
    started = time.monotonic()
    before = int(session.execute(select(func.count()).select_from(Paper)).scalar_one())

    inserted = skipped = merged = 0
    per_field = max(1, TARGET_PAPERS // len(LIVE_FIELDS))
    for field_id in LIVE_FIELDS:
        try:
            outcome = ingest(
                session,
                provider,
                query=PaperQuery(field_ids=(field_id,), limit=min(per_field, 100)),
                max_records=per_field,
            )
        except ProviderUnavailable as exc:
            # One field failing is not the run failing: the others may still clear the bar,
            # and a partial corpus is a more useful answer than an aborted check.
            report.add(f"取り込み: {field_id}", False, str(exc))
            continue
        inserted += outcome.inserted
        skipped += outcome.skipped_unlicensed
        merged += outcome.merged_duplicates

    after = int(session.execute(select(func.count()).select_from(Paper)).scalar_one())
    total = after - before
    report.add(
        "取り込み",
        after >= TARGET_PAPERS or total > 0,
        f"新規 {inserted} 件（重複統合 {merged}、ライセンス不明で見送り {skipped}）。"
        f"コーパス合計 {after} 件",
        time.monotonic() - started,
    )
    return after


def _builds_a_feed(session: Session, report: LiveCheckReport, corpus: int) -> None:
    """Section 29's actual condition: a feed, from that corpus, for a fresh reader."""
    started = time.monotonic()
    if corpus < TARGET_PAPERS:
        report.add(
            "フィード構成",
            False,
            f"コーパスが {corpus} 件で、仕様書 29 節の 100 件に届いていません",
            time.monotonic() - started,
        )
        return

    # A throwaway reader, so a real one's history is neither read nor disturbed.
    probe = User(is_guest=True, display_name="live-check")
    session.add(probe)
    session.flush()
    session.add(UserSettings(user_id=probe.id, locale="ja-JP", timezone="Asia/Tokyo"))
    session.flush()

    try:
        page = build_feed(session, probe, limit=20, now=datetime.now(tz=UTC))
        pools: dict[str, int] = {}
        for candidate in page.items:
            pools[candidate.pool] = pools.get(candidate.pool, 0) + 1
        mix = ", ".join(f"{name} {count}" for name, count in sorted(pools.items()))
        reasons = {reason for candidate in page.items for reason in candidate.reasons}
        report.add(
            "フィード構成",
            len(page.items) > 0,
            f"{len(page.items)} 枚（{mix}）。候補 {page.candidate_count} 件、"
            f"推薦理由 {len(reasons)} 種",
            time.monotonic() - started,
        )
    finally:
        # The probe reader is a diagnostic artefact, not a user. Removed whether or not the
        # feed built, so repeated runs do not leave a trail of ghost accounts.
        session.delete(probe)
        session.flush()


def run_live_check(session: Session, providers: dict[str, PaperProvider]) -> LiveCheckReport:
    """Reach, parse, store, and build — stopping at the first step that fails.

    `providers` is passed in rather than resolved here so the caller decides which sources
    are under test, and so the whole pass is drivable from a test with recorded responses.
    """
    report = LiveCheckReport()

    fields = int(session.execute(select(func.count()).select_from(Field)).scalar_one())
    if fields == 0:
        report.add(
            "分野タクソノミー",
            False,
            "fields テーブルが空です。先に `make seed`（または cli seed）を実行してください",
        )
        return report
    report.add("分野タクソノミー", True, f"{fields} 分野")

    usable: list[PaperProvider] = []
    for provider in providers.values():
        if _reachable(provider, report) and _parses(provider, report):
            usable.append(provider)
    if not usable:
        return report

    corpus = 0
    for provider in usable:
        corpus = _ingests(session, provider, report)

    _builds_a_feed(session, report, corpus)
    return report
