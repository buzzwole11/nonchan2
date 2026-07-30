"""Developer CLI.

``python -m papermatch_api.cli seed`` loads the field taxonomy and the sample corpus into
a migrated database. It is idempotent, so it is safe to re-run after pulling new fixtures.
"""

from __future__ import annotations

import argparse
import sys

from papermatch_api.config import get_settings
from papermatch_api.db import session_scope
from papermatch_api.providers.base import PaperQuery
from papermatch_api.providers.registry import get_paper_provider
from papermatch_api.services.ingestion import ingest, load_fields
from papermatch_api.services.math_content import load_math_cards


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
    print(
        f"fields: {field_count}\n"
        f"papers inserted: {report.inserted}\n"
        f"papers updated: {report.updated}\n"
        f"duplicates merged: {report.merged_duplicates}\n"
        f"skipped (licence unknown): {report.skipped_unlicensed}\n"
        f"maths cards: {math.cards} "
        f"({math.equations} equations, {math.symbols} symbols, {math.steps} steps; "
        f"{math.unverified_steps} step(s) unverified and hidden by default)"
    )
    if math.rejected_equations:
        print(f"formulas refused by the LaTeX check: {', '.join(math.rejected_equations)}")
    if math.missing_papers:
        print(f"maths cards with no matching paper: {', '.join(math.missing_papers)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="papermatch")
    sub = parser.add_subparsers(dest="command", required=True)

    seed_parser = sub.add_parser("seed", help="load fields and the sample corpus")
    seed_parser.add_argument("--limit", type=int, default=500)

    args = parser.parse_args(argv)
    if args.command == "seed":
        return seed(args.limit)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
