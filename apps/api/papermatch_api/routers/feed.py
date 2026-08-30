"""Discover feed, impressions, actions and undo (spec section 24)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.db import get_db
from papermatch_api.models import AbstractSegment, SavedPaper
from papermatch_api.providers.registry import health_snapshot
from papermatch_api.routers.papers import serialize_paper
from papermatch_api.schemas import (
    ActionOut,
    ActionResponse,
    CreateActionRequest,
    CreateImpressionsRequest,
    CreateImpressionsResponse,
    FeedItemOut,
    FeedResponse,
    MathCardTeaserOut,
    SavedPaperOut,
    UndoResponse,
)
from papermatch_api.security import CurrentUser
from papermatch_api.services import activity, mathcard_feed
from papermatch_api.services import feed as feed_service

router = APIRouter(tags=["feed"])


def _activity_error(exc: activity.ActivityError) -> HTTPException:
    code_to_status = {
        "paper_not_found": status.HTTP_404_NOT_FOUND,
        "action_not_found": status.HTTP_404_NOT_FOUND,
        "not_saved": status.HTTP_404_NOT_FOUND,
        "already_undone": status.HTTP_409_CONFLICT,
        "cannot_undo_undo": status.HTTP_409_CONFLICT,
    }
    return HTTPException(
        status_code=code_to_status.get(exc.code, status.HTTP_422_UNPROCESSABLE_ENTITY),
        detail={"code": exc.code, "message": exc.message},
    )


def _to_action_out(row) -> ActionOut:  # type: ignore[no-untyped-def]
    return ActionOut(
        id=row.id,
        type=row.action_type,
        paper_id=row.paper_id,
        created_at=row.created_at,
        undone=row.undone,
        undoes_action_id=row.undoes_action_id,
        payload=row.payload,
    )


@router.get("/feed", response_model=FeedResponse)
def get_feed(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    mode: Annotated[str, Query(pattern="^(discover|focus|learn|explore)$")] = "discover",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> FeedResponse:
    """A page of Abstract cards.

    Only ``discover`` is implemented in Phase 1; the other modes in spec section 5 are
    accepted so the client's routing does not have to change when they land, and they
    currently fall back to the discover ranking.
    """
    # A provider that is down does not stop the feed — it marks the page as cache-only so
    # the client can say why nothing new appeared (spec section 25).
    degraded = any(not health.healthy for health in health_snapshot().values())

    page = feed_service.build_feed(db, user, limit=limit, cursor=cursor, degraded=degraded)

    # Section 10: Discoverフィードへ低頻度で混ぜる. First page only, never inside the
    # 70/20/10 (same reasoning as the resurfaced paper), quiet for a week after each offer.
    teaser = None
    if cursor is None and page.items:
        offered = mathcard_feed.pick(db, user)
        if offered is not None:
            mathcard_feed.record(db, user, offered)
            teaser = MathCardTeaserOut(
                card_id=offered.card.id,
                card_type=offered.card.card_type,
                title=offered.card.title,
                level=offered.card.level,
                provenance_kind=offered.card.provenance_kind,
                paper_id=offered.paper.id,
                paper_title=offered.paper.title,
            )

    paper_ids = [candidate.paper.id for candidate in page.items]
    segments: dict[uuid.UUID, list[AbstractSegment]] = {}
    if paper_ids:
        for segment in db.execute(
            select(AbstractSegment).where(AbstractSegment.paper_id.in_(paper_ids))
        ).scalars():
            segments.setdefault(segment.paper_id, []).append(segment)

    locale = user.settings.locale
    return FeedResponse(
        items=[
            FeedItemOut(
                paper=serialize_paper(candidate.paper, segments.get(candidate.paper.id, [])),
                reasons=candidate.reasons,
                reason_text=feed_service.reason_text(candidate.reasons, locale),
                position=index,
                pool=candidate.pool,
                score_breakdown=candidate.breakdown,
            )
            for index, candidate in enumerate(page.items)
        ],
        next_cursor=page.next_cursor,
        degraded=page.degraded,
        math_card=teaser,
    )


@router.post(
    "/impressions",
    response_model=CreateImpressionsResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_impressions(
    payload: CreateImpressionsRequest,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> CreateImpressionsResponse:
    """Record that cards were shown, and how long they were looked at.

    This is what stops a card from coming back (spec section 16), so the client posts it
    when a card actually reaches the screen — not when it is prefetched.
    """
    try:
        recorded = activity.record_impressions(
            db,
            user,
            [
                activity.ImpressionInput(
                    paper_id=item.paper_id,
                    position=item.position,
                    feed_context=item.feed_context,
                    dwell_ms=item.dwell_ms,
                )
                for item in payload.impressions
            ],
        )
    except activity.ActivityError as exc:
        raise _activity_error(exc) from exc
    return CreateImpressionsResponse(recorded=len(recorded))


@router.post("/actions", response_model=ActionResponse, status_code=status.HTTP_201_CREATED)
def create_action(
    payload: CreateActionRequest,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ActionResponse:
    try:
        row = activity.record_action(
            db,
            user,
            action_type=payload.type,
            paper_id=payload.paper_id,
            payload=payload.payload,
        )
    except activity.ActivityError as exc:
        raise _activity_error(exc) from exc

    saved_out: SavedPaperOut | None = None
    if payload.paper_id is not None:
        saved_row = db.execute(
            select(SavedPaper).where(
                SavedPaper.user_id == user.id, SavedPaper.paper_id == payload.paper_id
            )
        ).scalar_one_or_none()
        if saved_row is not None:
            saved_out = SavedPaperOut.model_validate(saved_row)

    return ActionResponse(action=_to_action_out(row), saved=saved_out)


@router.post(
    "/actions/{action_id}/undo", response_model=UndoResponse, status_code=status.HTTP_201_CREATED
)
def undo(
    action_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> UndoResponse:
    """Reverse an action (spec section 6).

    The response names the paper that became eligible again so the client can put the card
    back at the top of the deck without refetching the feed.
    """
    try:
        compensating = activity.undo_action(db, user, action_id)
    except activity.ActivityError as exc:
        raise _activity_error(exc) from exc

    return UndoResponse(
        undo=_to_action_out(compensating),
        undone_action_id=action_id,
        restored_paper_id=compensating.paper_id,
    )


@router.get("/actions/undoable", response_model=ActionResponse | None)
def get_undoable(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ActionResponse | None:
    """What the Undo button would reverse, so the client can label it correctly."""
    row = activity.latest_undoable_action(db, user)
    if row is None:
        return None
    return ActionResponse(action=_to_action_out(row), saved=None)
