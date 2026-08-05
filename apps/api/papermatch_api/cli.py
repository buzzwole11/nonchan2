"""Developer CLI.

``python -m papermatch_api.cli seed`` loads the field taxonomy and the sample corpus into
a migrated database. It is idempotent, so it is safe to re-run after pulling new fixtures.
"""

from __future__ import annotations

import argparse
import sys
import time

from sqlalchemy import select

from papermatch_api.config import get_settings
from papermatch_api.db import session_scope
from papermatch_api.models import Field
from papermatch_api.providers.base import PaperQuery
from papermatch_api.providers.registry import get_fulltext_provider, get_paper_provider
from papermatch_api.services.fulltext import load_full_texts
from papermatch_api.services.ingestion import ingest, load_fields
from papermatch_api.services.math_content import load_math_cards
from papermatch_api.services.metrics import collect
from papermatch_api.services.review import review_queue
from papermatch_api.services.worker import default_jobs, run_summary, summarise, tick


def seed(limit: int) -> int:
    settings = get_settings()
    with session_scope() as session:
        field_count = load_fields(session, settings.fixtures_dir)
        report = ingest(
            session,
            get_paper_provider(),
            query=PaperQuery(limit=min(limit, 100)),
            max_records=limit,
        )
        # After the papers: a maths card names its paper by canonical id.
        math = load_math_cards(session, settings.fixtures_dir)
        # And after those: a body is fetched per paper, and only kept when the licence
        # permits it. Refusals are expected here and are recorded, not silently dropped.
        bodies = load_full_texts(session, get_fulltext_provider())
    refused = ", ".join(f"{code}={count}" for code, count in sorted(bodies.refused.items()))
    print(
        f"fields: {field_count}\n"
        f"papers inserted: {report.inserted}\n"
        f"papers updated: {report.updated}\n"
        f"duplicates merged: {report.merged_duplicates}\n"
        f"skipped (licence unknown): {report.skipped_unlicensed}\n"
        f"maths cards: {math.cards} "
        f"({math.equations} equations, {math.symbols} symbols, {math.steps} steps; "
        f"{math.unverified_steps} step(s) unverified and hidden by default)\n"
        f"full texts stored: {bodies.stored} "
        f"({bodies.unavailable} not offered"
        f"{'; refused: ' + refused if refused else ''})"
    )
    if math.rejected_equations:
        print(f"formulas refused by the LaTeX check: {', '.join(math.rejected_equations)}")
    if math.missing_papers:
        print(f"maths cards with no matching paper: {', '.join(math.missing_papers)}")
    return 0


def worker(once: bool, interval_seconds: int) -> int:
    """Run the scheduled ingestion jobs.

    ``--once`` does a single pass and exits, which is the shape a cron entry or a container
    with a restart policy wants. Without it the process stays up and sleeps between passes.
    Both call the same `tick`, so the scheduled behaviour cannot drift from the one-shot.
    """
    provider = get_paper_provider()
    while True:
        with session_scope() as session:
            field_ids = list(session.execute(select(Field.id)).scalars())
            specs = default_jobs(provider.name, field_ids)
            # Rendered inside the session: once it closes the run rows are detached, and
            # reading `counts` off a detached instance is how a reporting line turns into
            # a DetachedInstanceError at 3am.
            lines = [
                summarise(run) if run.error is None else f"{summarise(run)} error={run.error}"
                for run in tick(session, {provider.name: provider}, specs)
            ]

        for line in lines or ["nothing due"]:
            print(line)

        if once:
            return 0
        # Sleeping here rather than inside `tick` keeps the scheduling decision (which jobs
        # are due) separate from the pacing, so the former stays testable without a clock.
        time.sleep(interval_seconds)


def runs(limit: int) -> int:
    """Print the recent run log — what an operator reads to answer "is it working?"."""
    with session_scope() as session:
        rows = run_summary(session, limit=limit)
    if not rows:
        print("no runs recorded yet")
        return 0
    for row in rows:
        print(f"{row.started_at.isoformat(timespec='seconds')}  {row.one_line()}")
        if row.error is not None:
            print(f"    error: {row.error}")
    return 0


def metrics(window: int) -> int:
    """Print section 27's numbers, including the ones nothing can compute yet."""
    with session_scope() as session:
        print(collect(session, window_days=window).render())
    return 0


def review(limit: int) -> int:
    """Print the human review queue (spec section 12, step 10).

    Read-only. Recording a decision is deliberately not a CLI flag: an approval is what
    lets a card's steps claim `human_reviewed`, and that should be a considered action in
    a reviewing surface, not one keystroke away from a listing command.
    """
    with session_scope() as session:
        items = review_queue(session, limit=limit)
        if not items:
            print("レビュー待ちのカードはありません。")
            return 0
        print(f"レビュー待ち {len(items)} 件（緊急なものから）\n")
        for item in items:
            print(f"[{item.card.review_status}] {item.card.title}")
            print(f"    理由: {item.reason_text}")
            print(
                f"    報告 {item.report_count} 件 / "
                f"未検証の変形 {item.unverified_step_count} / {item.total_step_count}"
            )
            print(f"    id: {item.card.id}")
            print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="papermatch")
    sub = parser.add_subparsers(dest="command", required=True)

    seed_parser = sub.add_parser("seed", help="load fields and the sample corpus")
    seed_parser.add_argument("--limit", type=int, default=500)

    worker_parser = sub.add_parser("worker", help="run scheduled ingestion and refresh")
    worker_parser.add_argument("--once", action="store_true", help="one pass, then exit")
    worker_parser.add_argument("--interval", type=int, default=600, help="seconds between passes")

    runs_parser = sub.add_parser("runs", help="show the recent ingestion run log")
    runs_parser.add_argument("--limit", type=int, default=20)

    metrics_parser = sub.add_parser("metrics", help="section 27's指標 and guardrails")
    metrics_parser.add_argument("--window", type=int, default=7, help="days to look back")

    review_parser = sub.add_parser("review", help="the human review queue (spec section 12)")
    review_parser.add_argument("--limit", type=int, default=20)

    args = parser.parse_args(argv)
    if args.command == "seed":
        return seed(args.limit)
    if args.command == "worker":
        return worker(args.once, args.interval)
    if args.command == "runs":
        return runs(args.limit)
    if args.command == "metrics":
        return metrics(args.window)
    if args.command == "review":
        return review(args.limit)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
