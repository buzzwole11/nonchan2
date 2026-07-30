"""Equations and maths cards (spec sections 10, 11, 12, 24).

Two things this router is careful about.

**The renderability verdict is computed here, not on the client.** Spec section 25 keeps
security decisions on the server; a client that decided for itself whether a LaTeX string
was safe to hand to its WebView would be one client release away from getting it wrong.
The string always travels — section 11's fallback is to show the source — but the flag
that says whether to typeset it comes from the server.

**A withheld step is reported as a count, not omitted silently.** Section 12 hides
unverified transformations by default. Dropping them without a word would leave a
derivation that looks complete and is not, so the response says how many are missing.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from papermatch_api.db import get_db
from papermatch_api.models import DerivationStep, Equation, MathCard, Paper
from papermatch_api.schemas import (
    DerivationStepOut,
    EquationListResponse,
    EquationOut,
    EquationSymbolOut,
    MathCardDetailResponse,
    MathCardListResponse,
    MathCardOut,
)
from papermatch_api.services.equations import (
    derivation_steps_for,
    renderable,
    symbols_for,
    visible_equations,
)
from papermatch_api.text.latex_safety import check_latex

router = APIRouter(tags=["equations"])


def serialize_equation(session: Session, equation: Equation) -> EquationOut:
    verdict = renderable(equation.latex)
    return EquationOut(
        id=equation.id,
        paper_id=equation.paper_id,
        latex=equation.latex,
        equation_number=equation.equation_number,
        section=equation.section,
        display=equation.display,
        provenance_kind=equation.provenance_kind,
        verification_status=equation.verification_status,
        renderable=verdict.renderable,
        refusal_reasons=list(verdict.refusal_reasons),
        symbols=[
            EquationSymbolOut(
                symbol=s.symbol,
                local_meaning=s.local_meaning,
                general_meaning=s.general_meaning,
                unit=s.unit,
                scope=s.scope,
                provenance_kind=s.provenance_kind,
            )
            for s in symbols_for(session, equation.id)
        ],
    )


def serialize_step(step: DerivationStep) -> DerivationStepOut:
    return DerivationStepOut(
        id=step.id,
        from_equation_id=step.from_equation_id,
        to_equation_id=step.to_equation_id,
        latex=step.latex,
        operation=step.operation,
        rationale=step.rationale,
        verification_status=step.verification_status,
        provenance_kind=step.provenance_kind,
        renderable=check_latex(step.latex).safe,
        evidence=step.generation,
    )


def serialize_card(card: MathCard) -> MathCardOut:
    return MathCardOut(
        id=card.id,
        card_type=card.card_type,
        title=card.title,
        level=card.level,
        review_status=card.review_status,
        provenance_kind=card.provenance_kind,
        body=card.body,
    )


@router.get("/papers/{paper_id}/equations", response_model=EquationListResponse)
def list_paper_equations(
    paper_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    include_unverified: Annotated[bool, Query(alias="includeUnverified")] = False,
) -> EquationListResponse:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "paper_not_found", "message": "No paper with that id."},
        )
    equations = visible_equations(db, paper_id, include_unverified=include_unverified)
    return EquationListResponse(equations=[serialize_equation(db, e) for e in equations])


@router.get("/math-cards", response_model=MathCardListResponse)
def list_math_cards(
    db: Annotated[Session, Depends(get_db)],
    card_type: Annotated[str | None, Query(alias="cardType")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> MathCardListResponse:
    stmt = select(MathCard)
    if card_type is not None:
        stmt = stmt.where(MathCard.card_type == card_type)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    cards = list(db.execute(stmt.order_by(MathCard.created_at).limit(limit)).scalars())
    return MathCardListResponse(cards=[serialize_card(c) for c in cards], total=total)


@router.get("/math-cards/{card_id}", response_model=MathCardDetailResponse)
def get_math_card(
    card_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    include_unverified: Annotated[bool, Query(alias="includeUnverified")] = False,
) -> MathCardDetailResponse:
    card = db.get(MathCard, card_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "math_card_not_found", "message": "No maths card with that id."},
        )

    equation_ids = [uuid.UUID(str(i)) for i in card.source_equation_ids]
    by_id = {
        e.id: e for e in db.execute(select(Equation).where(Equation.id.in_(equation_ids))).scalars()
    }
    # The card's own order, not the database's: a derivation reads top to bottom.
    ordered = [by_id[i] for i in equation_ids if i in by_id]
    ids = [e.id for e in ordered]

    shown = derivation_steps_for(db, ids, include_unverified=include_unverified)
    everything = derivation_steps_for(db, ids, include_unverified=True)

    return MathCardDetailResponse(
        card=serialize_card(card),
        equations=[serialize_equation(db, e) for e in ordered],
        steps=[serialize_step(s) for s in shown],
        hidden_step_count=len(everything) - len(shown),
    )
