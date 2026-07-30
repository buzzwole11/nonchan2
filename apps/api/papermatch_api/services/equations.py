"""Equations, symbols, derivations and maths cards (spec sections 10, 11, 12).

Two rules from the spec live here, and both are about not overstating what we know.

**Unverified transformations are hidden by default** (section 12: 未検証の変形は既定で非表示).
A derivation step that no checker has confirmed is a plausible-looking claim about
mathematics, and a reader cannot tell one from a real one by looking. It is stored — the
review queue in section 12 needs it — but it does not reach the app unless the caller asks
for it explicitly, and then it arrives labelled.

**Nothing is rendered that we would not stand behind.** Every formula is admitted by
`text.latex_safety` before it leaves the API, so the client is never in the position of
deciding whether a string is safe to hand to its renderer (section 25 keeps that decision
on the server). A refused formula still travels — with its source and the reason — because
section 11's fallback is to show the LaTeX source, not to show nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import DerivationStep, Equation, EquationSymbol, MathCard
from papermatch_api.text.latex_safety import check_latex

__all__ = [
    "DEFAULT_VISIBLE_STATUSES",
    "RenderableEquation",
    "derivation_steps_for",
    "is_default_visible",
    "math_card_detail",
    "renderable",
    "symbols_for",
    "visible_equations",
]

#: Section 12 lists six verification states. These are the five that represent *some*
#: check having happened; ``unverified`` is the one that does not, and it is the one the
#: spec singles out as hidden by default.
DEFAULT_VISIBLE_STATUSES: frozenset[str] = frozenset(
    {
        "source_exact",
        "mechanically_verified",
        "dimensionally_checked",
        "numerically_spot_checked",
        "human_reviewed",
    }
)


def is_default_visible(verification_status: str) -> bool:
    return verification_status in DEFAULT_VISIBLE_STATUSES


@dataclass(frozen=True)
class RenderableEquation:
    """A formula plus the verdict on whether it may be typeset.

    ``renderable=False`` is not an error. Section 11 says the fallback for a formula the
    renderer cannot take is its LaTeX source and a link to the paper, so the string is
    still here — what changes is that the client shows it as source rather than passing it
    to KaTeX.
    """

    latex: str
    renderable: bool
    refusal_reasons: tuple[str, ...]


def renderable(latex: str) -> RenderableEquation:
    verdict = check_latex(latex)
    return RenderableEquation(
        latex=latex,
        renderable=verdict.safe,
        refusal_reasons=tuple(i.code for i in verdict.issues),
    )


def visible_equations(
    session: Session, paper_id: UUID, *, include_unverified: bool = False
) -> list[Equation]:
    """Equations for a paper, newest section order first seen.

    ``include_unverified`` exists for the review queue, not for the reading UI.
    """
    stmt = select(Equation).where(Equation.paper_id == paper_id)
    if not include_unverified:
        stmt = stmt.where(Equation.verification_status.in_(DEFAULT_VISIBLE_STATUSES))
    stmt = stmt.order_by(Equation.equation_number.nulls_last(), Equation.created_at)
    return list(session.execute(stmt).scalars())


def symbols_for(session: Session, equation_id: UUID) -> list[EquationSymbol]:
    """Symbols for one equation, in the order a reader meets them.

    Ordered by the symbol itself rather than by insertion: section 10's 記号タップ shows a
    list, and a stable alphabetical order is easier to scan than whatever order the
    extractor happened to emit.
    """
    stmt = (
        select(EquationSymbol)
        .where(EquationSymbol.equation_id == equation_id)
        .order_by(EquationSymbol.symbol)
    )
    return list(session.execute(stmt).scalars())


def derivation_steps_for(
    session: Session, equation_ids: list[UUID], *, include_unverified: bool = False
) -> list[DerivationStep]:
    """Steps between the given equations.

    A step is only useful if both of its ends are on screen, so the filter is on
    ``from``/``to`` rather than on a paper id — a derivation card can pull equations from
    more than one place in a paper.
    """
    if not equation_ids:
        return []
    stmt = select(DerivationStep).where(
        DerivationStep.from_equation_id.in_(equation_ids),
        DerivationStep.to_equation_id.in_(equation_ids),
    )
    if not include_unverified:
        stmt = stmt.where(DerivationStep.verification_status.in_(DEFAULT_VISIBLE_STATUSES))
    return list(session.execute(stmt).scalars().all())


def math_card_detail(
    session: Session, card: MathCard, *, include_unverified: bool = False
) -> dict[str, Any]:
    """Everything Focus Mode needs for one card, in one round trip.

    Focus Mode (section 10) shows the equation, its symbols and its derivation at the same
    time, behind tabs. Fetching them separately would mean the 記号 tab is empty for a beat
    after the reader taps it, on a screen whose whole point is unhurried attention.
    """
    equation_ids = [UUID(str(i)) for i in card.source_equation_ids]
    equations = list(
        session.execute(select(Equation).where(Equation.id.in_(equation_ids))).scalars()
    )
    # Preserve the card's own ordering; `IN` gives no order guarantee and the derivation
    # reads top to bottom.
    by_id = {e.id: e for e in equations}
    ordered = [by_id[i] for i in equation_ids if i in by_id]

    return {
        "card": card,
        "equations": ordered,
        "symbols": {e.id: symbols_for(session, e.id) for e in ordered},
        "steps": derivation_steps_for(
            session, [e.id for e in ordered], include_unverified=include_unverified
        ),
    }
