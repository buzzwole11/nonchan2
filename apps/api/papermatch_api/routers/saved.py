"""The saved library (spec sections 9, 14, 24).

Phase 1 ships the Library View half of spec section 14: filtering, sorting and paging over
the same rows the Canvas will later place on a plane. The sort keys are the ones section 14
lists, so the Canvas work in Phase 6 does not need new query support.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from papermatch_api.db import get_db
from papermatch_api.models import AbstractSegment, Paper, SavedPaper
from papermatch_api.routers.papers import serialize_paper
from papermatch_api.schemas import (
    SavedEntryOut,
    SavedListResponse,
    SavedPaperOut,
    SavedPaperResponse,
    SavePaperRequest,
    SearchHitOut,
    SearchResponse,
    UpdateSavedRequest,
)
from papermatch_api.security import CurrentUser
from papermatch_api.services import activity
from papermatch_api.services.search import MAX_QUERY_LENGTH, search_library

router = APIRouter(tags=["saved"])


def abstract_segments_for(
    db: Session, paper_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[AbstractSegment]]:
    """Structure labels for a page of papers, in one query rather than one per paper."""
    grouped: dict[uuid.UUID, list[AbstractSegment]] = {}
    if not paper_ids:
        return grouped
    for segment in db.execute(
        select(AbstractSegment).where(AbstractSegment.paper_id.in_(paper_ids))
    ).scalars():
        grouped.setdefault(segment.paper_id, []).append(segment)
    return grouped


SORT_KEYS = (
    "recently_saved",
    "recently_visited",
    "interest",
    "year",
    "reading_time",
    "english_level",
    "math_density",
    "unread_first",
)


def _activity_error(exc: activity.ActivityError) -> HTTPException:
    code_to_status = {
        "paper_not_found": status.HTTP_404_NOT_FOUND,
        "not_saved": status.HTTP_404_NOT_FOUND,
    }
    return HTTPException(
        status_code=code_to_status.get(exc.code, status.HTTP_422_UNPROCESSABLE_ENTITY),
        detail={"code": exc.code, "message": exc.message},
    )


def _order_by(sort: str):  # type: ignore[no-untyped-def]
    match sort:
        case "recently_visited":
            # Never-visited rows sort last rather than first, which is what "recently
            # visited" means to a reader.
            return (SavedPaper.last_visited_at.desc().nullslast(), SavedPaper.saved_at.desc())
        case "interest":
            # Section 14's 関心度, ordered by the same inputs the Canvas sizes a tile by
            # (`services/canvas.personal_weight`): what the reader marked as important, and
            # whether they came back to it. The weight there is log-compressed, which is
            # monotone, so the two orderings agree — a paper that looks big on the plane
            # sorts high here, and a reader switching views does not see them disagree.
            return (
                (
                    SavedPaper.priority
                    + case((SavedPaper.last_visited_at.is_not(None), 1), else_=0)
                ).desc(),
                SavedPaper.last_visited_at.desc().nullslast(),
                SavedPaper.saved_at.desc(),
            )
        case "year":
            return (Paper.year.desc(), SavedPaper.saved_at.desc())
        case "reading_time":
            return (Paper.estimated_reading_minutes.asc(), SavedPaper.saved_at.desc())
        case "english_level":
            return (Paper.english_level.asc(), SavedPaper.saved_at.desc())
        case "math_density":
            return (Paper.math_density.desc(), SavedPaper.saved_at.desc())
        case "unread_first":
            return (
                (SavedPaper.status != "unread"),
                SavedPaper.priority.desc(),
                SavedPaper.saved_at.desc(),
            )
        case _:
            return (SavedPaper.saved_at.desc(),)


@router.get("/saved", response_model=SavedListResponse)
def list_saved(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    reason: Annotated[str | None, Query()] = None,
    field_id: Annotated[str | None, Query(alias="fieldId")] = None,
    sort: Annotated[str, Query()] = "recently_saved",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> SavedListResponse:
    if sort not in SORT_KEYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_sort",
                "message": f"sort must be one of: {', '.join(SORT_KEYS)}",
            },
        )

    offset = 0
    if cursor:
        try:
            offset = max(0, int(cursor))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_cursor", "message": "cursor must be an offset"},
            ) from None

    base = (
        select(SavedPaper, Paper)
        .join(Paper, Paper.id == SavedPaper.paper_id)
        .where(SavedPaper.user_id == user.id)
    )
    if status_filter:
        base = base.where(SavedPaper.status == status_filter)
    if field_id:
        base = base.where(Paper.primary_field_id == field_id)

    total_stmt = select(func.count()).select_from(base.subquery())
    total = int(db.execute(total_stmt).scalar_one())

    stmt = (
        base.options(selectinload(Paper.identifiers), selectinload(Paper.field_weights))
        .order_by(*_order_by(sort))
        .offset(offset)
        .limit(limit + 1)
    )
    rows = list(db.execute(stmt).all())

    # `reasons` is a JSON array, so it is filtered in Python rather than with a
    # dialect-specific containment operator. Phase 3 moves this to a join table if the
    # library grows large enough for it to matter.
    if reason:
        rows = [row for row in rows if reason in (row[0].reasons or [])]

    has_more = len(rows) > limit
    rows = rows[:limit]

    segments = abstract_segments_for(db, [paper.id for _, paper in rows])

    return SavedListResponse(
        saved=[
            SavedEntryOut(
                saved_paper=SavedPaperOut.model_validate(saved_row),
                paper=serialize_paper(paper, segments.get(paper.id, [])),
            )
            for saved_row, paper in rows
        ],
        next_cursor=str(offset + limit) if has_more else None,
        total=total,
    )


def _load_paper(db: Session, paper_id: uuid.UUID) -> Paper:
    paper = db.execute(
        select(Paper)
        .options(selectinload(Paper.identifiers), selectinload(Paper.field_weights))
        .where(Paper.id == paper_id)
    ).scalar_one_or_none()
    if paper is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "paper_not_found", "message": "Unknown paper"},
        )
    return paper


@router.post(
    "/saved/{paper_id}", response_model=SavedPaperResponse, status_code=status.HTTP_201_CREATED
)
def create_saved(
    paper_id: uuid.UUID,
    payload: SavePaperRequest,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> SavedPaperResponse:
    """Save a paper directly (the swipe path goes through ``POST /actions``).

    Saving is also recorded as an action so it shows up in the undo history exactly like a
    right swipe does — the two entry points must not behave differently.
    """
    try:
        activity.record_action(
            db,
            user,
            action_type="save",
            paper_id=paper_id,
            payload={"reasons": payload.reasons, "notes": payload.notes, "via": "saved_endpoint"},
        )
    except activity.ActivityError as exc:
        raise _activity_error(exc) from exc

    saved_row = db.execute(
        select(SavedPaper).where(SavedPaper.user_id == user.id, SavedPaper.paper_id == paper_id)
    ).scalar_one()
    return SavedPaperResponse(
        saved_paper=SavedPaperOut.model_validate(saved_row),
        paper=serialize_paper(_load_paper(db, paper_id)),
    )


@router.patch("/saved/{paper_id}", response_model=SavedPaperResponse)
def patch_saved(
    paper_id: uuid.UUID,
    payload: UpdateSavedRequest,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> SavedPaperResponse:
    try:
        saved_row = activity.update_saved(
            db,
            user,
            paper_id,
            status=payload.status,
            reasons=payload.reasons,
            notes=payload.notes,
            priority=payload.priority,
        )
    except activity.ActivityError as exc:
        raise _activity_error(exc) from exc

    return SavedPaperResponse(
        saved_paper=SavedPaperOut.model_validate(saved_row),
        paper=serialize_paper(_load_paper(db, paper_id)),
    )


@router.delete("/saved/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved(
    paper_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    removed = activity.remove_saved(db, user, paper_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_saved", "message": "This paper is not in the saved library"},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/search", response_model=SearchResponse)
def search(
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
    q: str = Query(default="", max_length=MAX_QUERY_LENGTH),
    limit: int = Query(default=30, ge=1, le=100),
) -> SearchResponse:
    """Search the reader's saved library (spec sections 2, 14, 24).

    Not the corpus. Section 2's fifth job is 保存した論文を後から検索し、学習素材として再利用
    したい, and section 16 makes discovery a feed rather than a query — see
    `services/search.py` for why that distinction is deliberate.

    An empty query is not an error and not "no results": it means the reader has not typed
    anything yet, and the client should show the library it already has.
    """
    if not q.strip():
        return SearchResponse(query=q, hits=[], empty_query=True)

    hits = search_library(db, user, q, limit=limit)
    segments = abstract_segments_for(db, [hit.paper.id for hit in hits])
    return SearchResponse(
        query=q,
        hits=[
            SearchHitOut(
                saved_paper=SavedPaperOut.model_validate(hit.saved),
                paper=serialize_paper(hit.paper, segments.get(hit.paper.id, [])),
                matched_field=hit.matched,
            )
            for hit in hits
        ],
    )
