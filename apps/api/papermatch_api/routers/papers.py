"""Paper listing and retrieval.

Phase 0 exposes a plain, deduplicated listing. The ranked ``GET /feed`` of spec section 24
arrives in Phase 1 on top of the same storage and serialisation.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from papermatch_api.db import get_db
from papermatch_api.models import AbstractSegment, Paper
from papermatch_api.schemas import (
    AbstractSegmentOut,
    AuthorOut,
    PaperIdentifierOut,
    PaperListResponse,
    PaperOut,
    SourceProvenanceOut,
)

router = APIRouter(tags=["papers"])


def serialize_paper(paper: Paper, segments: list[AbstractSegment] | None = None) -> PaperOut:
    return PaperOut(
        id=paper.id,
        canonical_id=paper.canonical_id,
        identifiers=[
            PaperIdentifierOut(kind=i.kind, value=i.value)
            for i in sorted(paper.identifiers, key=lambda i: (i.kind, i.value))
        ],
        title=paper.title,
        abstract=paper.abstract,
        abstract_segments=[
            AbstractSegmentOut(
                start=s.start_offset,
                end=s.end_offset,
                section=s.section,
                detected_by=s.detected_by,
                confidence=s.confidence,
            )
            for s in sorted(segments or [], key=lambda s: s.start_offset)
        ],
        authors=[AuthorOut.model_validate(a) for a in paper.authors],
        year=paper.year,
        venue=paper.venue,
        paper_types=list(paper.paper_types or []),
        primary_field_id=paper.primary_field_id,
        field_weights={fw.field_id: fw.weight for fw in paper.field_weights},
        open_access=paper.open_access,
        retraction_status=paper.retraction_status,
        version=paper.version,
        english_level=paper.english_level,
        math_density=paper.math_density,
        equation_count=paper.equation_count,
        estimated_reading_minutes=paper.estimated_reading_minutes,
        source_url=paper.source_url,
        pdf_url=paper.pdf_url,
        provenance=SourceProvenanceOut(
            source_provider=paper.source_provider,
            acquired_at=paper.acquired_at,
            source_url=paper.source_url,
            license_id=paper.license_id,
            license_url=paper.license_url,
            abstract_redistributable=paper.abstract_redistributable,
            cache_policy=paper.cache_policy,
        ),
    )


@router.get("/papers", response_model=PaperListResponse)
def list_papers(
    db: Annotated[Session, Depends(get_db)],
    field_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> PaperListResponse:
    offset = 0
    if cursor:
        try:
            offset = max(0, int(cursor))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_cursor"
            ) from None

    stmt = (
        select(Paper)
        .options(selectinload(Paper.identifiers), selectinload(Paper.field_weights))
        # Stable ordering: without a tiebreaker, paging over equal years can repeat or
        # skip rows, which would show the same card twice (spec section 16).
        .order_by(Paper.year.desc(), Paper.canonical_id)
        .offset(offset)
        .limit(limit + 1)
    )
    if field_id:
        stmt = stmt.where(Paper.primary_field_id == field_id)

    rows = list(db.execute(stmt).scalars())
    has_more = len(rows) > limit
    rows = rows[:limit]

    return PaperListResponse(
        papers=[serialize_paper(paper) for paper in rows],
        next_cursor=str(offset + limit) if has_more else None,
    )


@router.get("/papers/{paper_id}", response_model=PaperOut)
def get_paper(paper_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]) -> PaperOut:
    paper = db.execute(
        select(Paper)
        .options(selectinload(Paper.identifiers), selectinload(Paper.field_weights))
        .where(Paper.id == paper_id)
    ).scalar_one_or_none()
    if paper is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="paper_not_found")

    segments = list(
        db.execute(select(AbstractSegment).where(AbstractSegment.paper_id == paper.id)).scalars()
    )
    return serialize_paper(paper, segments)
