"""Loading hand-authored maths cards (spec section 12, Phase 4).

Phase 4 asks for 手動作成した検証済み数式カード. The "検証済み" half is the part worth being
careful about: a fixture that simply *writes* `verification_status: "mechanically_verified"`
next to a formula has recorded a wish, not a fact.

So the fixture does not carry statuses at all. It carries *checks* — a numeric identity to
sample and a dimensional balance to compare — and this module runs them at load time and
stores whatever `mathcheck.combined_status` returns. A step that declares no check is
stored as `unverified`, and section 12 then hides it. That is why the corpus contains one
deliberately unverified card: the default-hidden branch should be exercised by real data
rather than only by a unit test.

The equations themselves are admitted by `text.latex_safety` before they are stored. A
formula the renderer must not be given has no business reaching the database, where a
later reader would assume everything present is displayable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from papermatch_api.mathcheck import (
    DimensionCheck,
    NumericCheck,
    combined_status,
    dimension_check,
    spot_check,
)
from papermatch_api.models import DerivationStep, Equation, EquationSymbol, MathCard, Paper
from papermatch_api.text.latex_safety import check_latex

__all__ = ["MathContentReport", "load_math_cards", "status_for_step"]


@dataclass
class MathContentReport:
    cards: int = 0
    equations: int = 0
    symbols: int = 0
    steps: int = 0
    #: Steps that earned nothing and are therefore hidden by default (section 12).
    unverified_steps: int = 0
    #: Formulas refused by the LaTeX admission check; these are not stored.
    rejected_equations: list[str] | None = None
    #: Cards whose paper is not in the corpus.
    missing_papers: list[str] | None = None

    def __post_init__(self) -> None:
        if self.rejected_equations is None:
            self.rejected_equations = []
        if self.missing_papers is None:
            self.missing_papers = []


def status_for_step(step: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Run whatever checks the step declares and return the status it earned.

    Also returns the evidence, which is stored on the step's ``generation`` column. A
    status with no record of how it was reached is not much better than an assertion —
    someone triaging this later needs to see which check ran and what it concluded.
    """
    evidence: dict[str, Any] = {}

    numeric_spec = step.get("numericCheck")
    numeric = None
    if numeric_spec is not None:
        check = NumericCheck(
            lhs=numeric_spec["lhs"],
            rhs=numeric_spec["rhs"],
            variables={k: (float(v[0]), float(v[1])) for k, v in numeric_spec["variables"].items()}
            if numeric_spec.get("variables")
            else {},
            samples=int(numeric_spec.get("samples", 25)),
            tolerance=float(numeric_spec.get("tolerance", 1e-9)),
        )
        numeric = spot_check(check)
        evidence["numeric"] = {
            "passed": numeric.passed,
            "detail": numeric.detail,
            "evaluated": numeric.evaluated,
            "lhs": check.lhs,
            "rhs": check.rhs,
            # The region is part of the claim: an identity is asserted *here*.
            "variables": {k: list(v) for k, v in check.variables.items()},
        }

    dimension_spec = step.get("dimensionCheck")
    dimensional = None
    if dimension_spec is not None:
        dimensional = dimension_check(
            DimensionCheck(lhs=dict(dimension_spec["lhs"]), rhs=dict(dimension_spec["rhs"]))
        )
        evidence["dimensional"] = {
            "passed": dimensional.passed,
            "detail": dimensional.detail,
        }

    status = combined_status(numeric, dimensional)
    evidence["status"] = status
    return status, evidence


def _paper_by_canonical_id(session: Session, canonical_id: str) -> Paper | None:
    return session.execute(
        select(Paper).where(Paper.canonical_id == canonical_id)
    ).scalar_one_or_none()


def load_math_cards(session: Session, fixtures_dir: Path) -> MathContentReport:
    """Load `math-cards.json`, replacing anything previously loaded from it.

    Idempotent by key: re-running replaces a card's equations, symbols and steps rather
    than duplicating them, so `make seed` can be run twice without the corpus growing.
    """
    report = MathContentReport()
    path = Path(fixtures_dir) / "math-cards.json"
    if not path.exists():
        return report

    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)

    for entry in document.get("cards", []):
        paper = _paper_by_canonical_id(session, entry["paperCanonicalId"])
        if paper is None:
            # The card names a paper this corpus does not have. Skipping is right — an
            # equation with no paper has lost its provenance, which is the one thing
            # section 21 says every record must keep.
            assert report.missing_papers is not None
            report.missing_papers.append(entry["key"])
            continue

        _replace_card(session, paper, entry, report)

    return report


def _replace_card(
    session: Session, paper: Paper, entry: dict[str, Any], report: MathContentReport
) -> None:
    existing = session.execute(
        select(MathCard).where(MathCard.title == entry["title"])
    ).scalar_one_or_none()
    if existing is not None:
        old_ids = list(existing.source_equation_ids)
        session.execute(delete(MathCard).where(MathCard.id == existing.id))
        # Equations cascade to their symbols and steps.
        for old in old_ids:
            session.execute(delete(Equation).where(Equation.id == old))
        session.flush()

    equations: dict[str, Equation] = {}
    for spec in entry["equations"]:
        verdict = check_latex(spec["latex"])
        if not verdict.safe:
            assert report.rejected_equations is not None
            report.rejected_equations.append(f"{entry['key']}/{spec['key']}")
            continue

        equation = Equation(
            paper_id=paper.id,
            latex=spec["latex"],
            equation_number=spec.get("equationNumber"),
            section=spec.get("section"),
            display=True,
            # The formula is the fixture paper's own equation, so it is the original as
            # far as this corpus is concerned; the prose around it is not (see below).
            provenance_kind="original",
            verification_status="source_exact",
            license_id="CC0-1.0",
            generation={"authoredFor": "fixture", "cardKey": entry["key"]},
        )
        session.add(equation)
        session.flush()
        equations[spec["key"]] = equation
        report.equations += 1

        for symbol in spec.get("symbols", []):
            session.add(
                EquationSymbol(
                    equation_id=equation.id,
                    symbol=symbol["symbol"],
                    local_meaning=symbol["localMeaning"],
                    general_meaning=symbol.get("generalMeaning"),
                    unit=symbol.get("unit"),
                    scope=symbol.get("scope", "equation"),
                    # The wording of a symbol's meaning is written prose, not something
                    # lifted from the paper.
                    provenance_kind="ai_explanation",
                )
            )
            report.symbols += 1

    for spec in entry.get("steps", []):
        source = equations.get(spec["from"])
        target = equations.get(spec["to"])
        if source is None or target is None:
            continue

        status, evidence = status_for_step(spec)
        if status == "unverified":
            report.unverified_steps += 1

        session.add(
            DerivationStep(
                from_equation_id=source.id,
                to_equation_id=target.id,
                latex=spec["latex"],
                operation=spec["operation"],
                rationale=spec.get("rationale", ""),
                verification_status=status,
                # A step that passed a mechanical check is a verified step; one that
                # passed nothing is an explanation and says so.
                provenance_kind=("verified_step" if status != "unverified" else "ai_explanation"),
                generation=evidence,
            )
        )
        report.steps += 1

    session.add(
        MathCard(
            card_type=entry["cardType"],
            title=entry["title"],
            level=entry.get("level", "level_2"),
            source_equation_ids=[str(e.id) for e in equations.values()],
            # Nothing here has been through the review queue in section 12, so `draft` is
            # the honest state. `approved` would claim a human signed it off.
            review_status="draft",
            provenance_kind="ai_explanation",
            body=entry["body"],
        )
    )
    report.cards += 1
    session.flush()
