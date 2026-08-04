"""The Knowledge Canvas plane (spec sections 13, 24).

Read the plane, and move a tile on it. Placement itself lives in `services/canvas.py`;
this router only decides what a request is allowed to ask for.

**Positions are created on read.** A reader who saves a paper and opens the Canvas should
see it there, not a gap that fills in after some later job runs. Creating on read is safe
here precisely because placement never moves anything that already exists (section 13:
全体再配置を最小化) — the write is purely additive.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from papermatch_api.db import get_db
from papermatch_api.models import Paper, SavedPaper
from papermatch_api.routers.papers import serialize_paper
from papermatch_api.schemas import CanvasResponse, CanvasTileOut, MoveTileRequest
from papermatch_api.security import CurrentUser
from papermatch_api.services.canvas import LAYOUT_VERSION, layout_for, move_tile

router = APIRouter(tags=["canvas"])


@router.get("/canvas", response_model=CanvasResponse)
def read_canvas(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> CanvasResponse:
    tiles = layout_for(db, user, limit=limit)
    if not tiles:
        return CanvasResponse(tiles=[], layout_version=LAYOUT_VERSION)

    papers = {
        paper.id: paper
        for paper in db.execute(
            select(Paper)
            .options(selectinload(Paper.identifiers), selectinload(Paper.field_weights))
            .where(Paper.id.in_([tile.entity_id for tile in tiles]))
        ).scalars()
    }

    return CanvasResponse(
        tiles=[
            CanvasTileOut(
                entity_type=tile.entity_type,
                entity_id=tile.entity_id,
                x=tile.x,
                y=tile.y,
                cluster_id=tile.cluster_id,
                weight=tile.weight,
                user_override=tile.user_override,
                paper=serialize_paper(papers[tile.entity_id]),
            )
            for tile in tiles
            if tile.entity_id in papers
        ],
        layout_version=LAYOUT_VERSION,
    )


@router.patch("/canvas/{paper_id}", response_model=CanvasResponse)
def move(
    paper_id: uuid.UUID,
    payload: MoveTileRequest,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> CanvasResponse:
    """Record where the reader put a tile (section 13: 手動配置を尊重)."""
    saved = db.execute(
        select(SavedPaper).where(SavedPaper.user_id == user.id, SavedPaper.paper_id == paper_id)
    ).scalar_one_or_none()
    if saved is None:
        # A tile only exists for a paper this reader saved. Placing one for anything else
        # would put a paper on their plane that is not in their library.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_saved", "message": "This paper is not in the saved library"},
        )

    move_tile(db, user, paper_id, x=payload.x, y=payload.y)
    return read_canvas(user, db)
