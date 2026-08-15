"""The notification inbox (spec section 26).

Rows are written by `services/notification_inbox` under the reader's own preset; this only
lists them and records reads. There is deliberately no "mark all read" and no delete: the
inbox is small by construction (the presets ration it), and a bulk dismissal is how a
retraction notice gets swept away with the reminders.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from papermatch_api.db import get_db
from papermatch_api.models import Notification
from papermatch_api.schemas import (
    NotificationListResponse,
    NotificationOut,
)
from papermatch_api.security import CurrentUser

router = APIRouter(tags=["notifications"])


def _serialize(row: Notification) -> NotificationOut:
    return NotificationOut(
        id=row.id,
        category=row.category,
        title=row.title,
        body=row.body,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        created_at=row.created_at,
        read_at=row.read_at,
    )


@router.get("/notifications", response_model=NotificationListResponse)
def list_notifications(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> NotificationListResponse:
    rows = list(
        db.execute(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        ).scalars()
    )
    unread = db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
    ).scalar_one()
    return NotificationListResponse(
        notifications=[_serialize(row) for row in rows], unread_count=int(unread)
    )


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> NotificationOut:
    """Record that the reader saw this one.

    Idempotent — reading twice keeps the *first* read time, because "when did they learn
    of the retraction" is the question the column exists to answer.
    """
    row = db.get(Notification, notification_id)
    if row is None or row.user_id != user.id:
        # The same 404 for "not yours" as for "not there": an id probe must not reveal
        # which notifications exist (same rule as every other per-user resource here).
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="notification_not_found")
    if row.read_at is None:
        row.read_at = datetime.now(tz=UTC)
        db.commit()
    return _serialize(row)
