"""Learn: the personal expression dictionary and its review nudge (spec sections 9, 24)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from papermatch_api.db import get_db
from papermatch_api.schemas import (
    CreateExpressionRequest,
    ExpressionListResponse,
    ExpressionOut,
    ExpressionResponse,
    ReviewQueueResponse,
    ReviewRequest,
)
from papermatch_api.security import CurrentUser
from papermatch_api.services import expressions as expression_service
from papermatch_api.services.activity import ActivityError

router = APIRouter(tags=["learn"])


def _error(exc: ActivityError) -> HTTPException:
    code_to_status = {
        "paper_not_found": status.HTTP_404_NOT_FOUND,
        "expression_not_found": status.HTTP_404_NOT_FOUND,
    }
    return HTTPException(
        status_code=code_to_status.get(exc.code, status.HTTP_422_UNPROCESSABLE_ENTITY),
        detail={"code": exc.code, "message": exc.message},
    )


@router.post("/expressions", response_model=ExpressionResponse, status_code=status.HTTP_201_CREATED)
def create_expression(
    payload: CreateExpressionRequest,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ExpressionResponse:
    """Save an expression, usually from the translation sheet (spec section 7: 表現保存).

    Saving the same phrase again merges instead of erroring, and the response says which
    happened so the UI can distinguish "added" from "you already had this".
    """
    try:
        card, created = expression_service.save_expression(
            db,
            user,
            phrase=payload.phrase,
            meaning=payload.meaning,
            kind=payload.kind,
            context=payload.context,
            source_paper_id=payload.source_paper_id,
            example=payload.example,
        )
    except ActivityError as exc:
        raise _error(exc) from exc

    return ExpressionResponse(expression=ExpressionOut.model_validate(card), created=created)


@router.get("/expressions", response_model=ExpressionListResponse)
def list_expressions(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    kind: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> ExpressionListResponse:
    offset = 0
    if cursor:
        try:
            offset = max(0, int(cursor))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_cursor", "message": "cursor must be an offset"},
            ) from None

    try:
        rows, total = expression_service.list_expressions(
            db, user, kind=kind, limit=limit, offset=offset
        )
    except ActivityError as exc:
        raise _error(exc) from exc

    due = expression_service.due_expressions(db, user, limit=200)
    return ExpressionListResponse(
        expressions=[ExpressionOut.model_validate(row) for row in rows],
        total=total,
        due_count=len(due),
    )


@router.delete("/expressions/{expression_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expression(
    expression_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    if not expression_service.delete_expression(db, user, expression_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "expression_not_found", "message": "No such expression"},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/learn/review", response_model=ReviewQueueResponse)
def review_queue(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> ReviewQueueResponse:
    """What is ready to be seen again.

    The default is deliberately small. Spec section 9 asks for 表現を1件提示 — a quiet
    re-encounter, not a backlog that makes the library feel like homework.
    """
    due = expression_service.due_expressions(db, user, limit=limit)
    total = len(expression_service.due_expressions(db, user, limit=500))
    return ReviewQueueResponse(
        due=[ExpressionOut.model_validate(row) for row in due], total_due=total
    )


@router.post("/learn/review/{expression_id}", response_model=ExpressionResponse)
def submit_review(
    expression_id: uuid.UUID,
    payload: ReviewRequest,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ExpressionResponse:
    """Record a review outcome and schedule the next showing.

    ``again`` steps back one rung rather than resetting: losing every past review over one
    miss is the punishment spec section 9 rules out.
    """
    try:
        card = expression_service.record_review(db, user, expression_id, payload.outcome)
    except ActivityError as exc:
        raise _error(exc) from exc
    return ExpressionResponse(expression=ExpressionOut.model_validate(card), created=False)
