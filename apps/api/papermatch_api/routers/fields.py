"""Field taxonomy for onboarding (spec sections 18, 24)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from papermatch_api.db import get_db
from papermatch_api.models import Field, PaperField
from papermatch_api.schemas import FieldLabel, FieldOut, FieldsResponse

router = APIRouter(tags=["fields"])


@router.get("/fields", response_model=FieldsResponse)
def list_fields(db: Annotated[Session, Depends(get_db)]) -> FieldsResponse:
    counts: dict[str, int] = {
        field_id: int(count)
        for field_id, count in db.execute(
            select(PaperField.field_id, func.count(PaperField.paper_id)).group_by(
                PaperField.field_id
            )
        ).all()
    }
    rows = db.execute(select(Field).order_by(Field.parent_id.nullsfirst(), Field.id)).scalars()
    return FieldsResponse(
        fields=[
            FieldOut(
                id=row.id,
                parent_id=row.parent_id,
                label=FieldLabel(en=row.label_en, ja=row.label_ja),
                color=row.color,
                paper_count=int(counts.get(row.id, 0)),
            )
            for row in rows
        ]
    )
