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
from papermatch_api.providers.registry import get_explanation_provider
from papermatch_api.schemas import (
    AbstractSegmentOut,
    AuthorOut,
    ExplanationItemOut,
    ExplanationSectionOut,
    PaperExplanationResponse,
    PaperIdentifierOut,
    PaperListResponse,
    PaperOut,
    PaperRelationOut,
    PaperRelationsResponse,
    ReadingPathResponse,
    ReadingRouteOut,
    ReadingStepOut,
    SourceProvenanceOut,
)
from papermatch_api.security import CurrentUser
from papermatch_api.services.explanations import (
    ExplanationResult,
    before_you_read,
    why_it_matters,
)
from papermatch_api.services.reading_path import routes_for
from papermatch_api.services.relations import relations_for

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


@router.get("/papers/{paper_id}/relations", response_model=PaperRelationsResponse)
def get_paper_relations(
    paper_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> PaperRelationsResponse:
    """How this paper sits among the reader's library (spec section 17).

    Authenticated because the candidate pool starts from the reader's own saved papers —
    section 17 is about organising 保存論文の周辺, and two readers looking at the same paper
    should see relations to *their* libraries.

    Returns only relations the evidence supports. An empty list is a real answer and the
    client says so plainly; it is not an error and not an invitation to fall back to
    "papers that look similar", which is the one thing section 17 forbids.
    """
    anchor = db.execute(
        select(Paper)
        .options(
            selectinload(Paper.identifiers),
            selectinload(Paper.field_weights),
        )
        .where(Paper.id == paper_id)
    ).scalar_one_or_none()
    if anchor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="paper_not_found")

    pairs = relations_for(db, anchor, user.id)
    db.commit()

    return PaperRelationsResponse(
        paper_id=anchor.id,
        relations=[
            PaperRelationOut(
                relation_type=row.relation_type,
                confidence=row.confidence,
                basis=str(row.evidence.get("basis", "similarity")),
                evidence=row.evidence,
                paper=serialize_paper(target),
            )
            for target, row in pairs
        ],
    )


@router.get("/papers/{paper_id}/explanation", response_model=PaperExplanationResponse)
def get_paper_explanation(
    paper_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> PaperExplanationResponse:
    """Section 8's Before you read and Why it matters, labelled as AI-generated.

    **Requested, never pushed.** Section 8 says this material is 強制表示しない, and the
    endpoint reflects that: it is reached by the reader asking (a downward swipe, or the
    button beside it), not by the feed attaching an explanation to every card.

    **An empty section is a normal answer.** The configured provider may be one that
    refuses to write anything it cannot ground in the paper, or the model may have judged
    the abstract insufficient. Either way the section comes back empty with a reason, and
    the card is still perfectly readable — which is why this is a 200 and not a 404.
    """
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="paper_not_found")

    provider = get_explanation_provider()
    before = before_you_read(db, provider, paper)
    why = why_it_matters(db, provider, paper)
    db.commit()

    return PaperExplanationResponse(
        paper_id=paper.id,
        before_you_read=_section(before),
        why_it_matters=[_section(result) for result in why],
    )


def _section(result: ExplanationResult) -> ExplanationSectionOut:
    return ExplanationSectionOut(
        kind=result.kind,
        audience=result.audience,
        items=[ExplanationItemOut(**item) for item in result.items],
        unavailable_reason=result.unavailable_reason,
        provenance_kind=result.provenance_kind,
        generation_provider=result.generation_provider,
        generation_model=result.generation_model,
        prompt_version=result.prompt_version,
    )


@router.get("/papers/{paper_id}/reading-path", response_model=ReadingPathResponse)
def get_reading_path(
    paper_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ReadingPathResponse:
    """Four routes through the paper, by what the reader came for (spec section 17).

    All four in one response. The choice between them is a tap, and a request per purpose
    would put a spinner between the reader and a decision they make in a second.
    """
    paper = db.execute(select(Paper).where(Paper.id == paper_id)).scalar_one_or_none()
    if paper is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="paper_not_found")

    return ReadingPathResponse(
        paper_id=paper.id,
        routes=[
            ReadingRouteOut(
                purpose=route.purpose,
                steps=[ReadingStepOut(**step.__dict__) for step in route.steps],
                missing=route.missing,
            )
            for route in routes_for(db, paper)
        ],
    )
