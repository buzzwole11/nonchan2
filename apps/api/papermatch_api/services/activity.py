"""Impressions, actions, undo and the saved library (spec sections 6, 9, 16, 23).

Undo is the part worth reading carefully. Spec section 6 promises that a skip can be
taken back, and the MVP completion list (section 29) requires it to actually work. That
means undo has to reverse *both* halves of an action:

* the **effect** — a save created a row in ``saved_papers``, so undoing it removes that
  row (but only if that action is what created it);
* the **trace** — the feed excludes anything already shown, so an undone card that stayed
  in ``impressions`` would silently never come back. Undo therefore clears the impressions
  for that paper. The action log keeps the full history, so nothing is lost for analytics:
  the shown → skipped → undone sequence is still there.

Actions are never deleted. They are marked ``undone`` and a compensating ``undo`` action
is appended, which is what makes the whole thing auditable and idempotent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from papermatch_api import vocab
from papermatch_api.models import Action, AuditLog, Impression, Paper, SavedPaper, User


class ActivityError(Exception):
    """Raised for a request that is well-formed but not applicable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ImpressionInput:
    paper_id: uuid.UUID
    position: int = 0
    feed_context: str = "discover"
    dwell_ms: int | None = None
    shown_at: datetime | None = None


def record_impressions(
    session: Session, user: User, items: list[ImpressionInput]
) -> list[Impression]:
    """Record that cards were shown.

    Re-posting the same paper updates the existing row rather than adding another. The
    client reports dwell time when a card leaves the screen, which arrives as a second
    post for a paper already recorded — treating that as a new impression would double
    every count.
    """
    known_paper_ids = set(
        session.execute(
            select(Paper.id).where(Paper.id.in_([item.paper_id for item in items]))
        ).scalars()
    )

    recorded: list[Impression] = []
    for item in items:
        if item.paper_id not in known_paper_ids:
            raise ActivityError("paper_not_found", f"Unknown paper {item.paper_id}")

        existing = (
            session.execute(
                select(Impression).where(
                    Impression.user_id == user.id,
                    Impression.paper_id == item.paper_id,
                    Impression.feed_context == item.feed_context,
                )
            )
            .scalars()
            .first()
        )

        if existing is None:
            row = Impression(
                user_id=user.id,
                paper_id=item.paper_id,
                position=item.position,
                feed_context=item.feed_context,
                dwell_ms=item.dwell_ms,
            )
            if item.shown_at is not None:
                row.shown_at = item.shown_at
            session.add(row)
            recorded.append(row)
        else:
            # Keep the longest dwell seen: a card can be revisited before it is acted on.
            if item.dwell_ms is not None:
                existing.dwell_ms = max(existing.dwell_ms or 0, item.dwell_ms)
            recorded.append(existing)

    session.flush()
    return recorded


# ----------------------------------------------------------------------------- actions


def _require_paper(session: Session, paper_id: uuid.UUID) -> Paper:
    paper = session.get(Paper, paper_id)
    if paper is None:
        raise ActivityError("paper_not_found", f"Unknown paper {paper_id}")
    return paper


def _validate_reasons(reasons: list[str]) -> list[str]:
    for reason in reasons:
        if not vocab.is_valid("saveReason", reason):
            allowed = ", ".join(vocab.values("saveReason"))
            raise ActivityError("invalid_save_reason", f"{reason!r} is not one of: {allowed}")
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(reasons))


def save_paper(
    session: Session,
    user: User,
    paper_id: uuid.UUID,
    *,
    reasons: list[str] | None = None,
    notes: str | None = None,
) -> tuple[SavedPaper, bool]:
    """Save a paper. Returns the row and whether it was newly created.

    The default reason is ``interesting`` — spec section 9: 右スワイプの既定は「気になる」.
    Saving something already saved merges the reasons instead of failing, because a user
    who saves from two entry points means both.
    """
    _require_paper(session, paper_id)
    wanted = _validate_reasons(reasons or ["interesting"])

    existing = session.execute(
        select(SavedPaper).where(SavedPaper.user_id == user.id, SavedPaper.paper_id == paper_id)
    ).scalar_one_or_none()

    if existing is not None:
        existing.reasons = list(dict.fromkeys([*existing.reasons, *wanted]))
        if notes is not None:
            existing.notes = notes
        session.flush()
        return existing, False

    row = SavedPaper(
        user_id=user.id,
        paper_id=paper_id,
        reasons=wanted,
        status="unread",
        notes=notes,
    )
    session.add(row)
    session.flush()
    return row, True


def update_saved(
    session: Session,
    user: User,
    paper_id: uuid.UUID,
    *,
    status: str | None = None,
    reasons: list[str] | None = None,
    notes: str | None = None,
    priority: int | None = None,
) -> SavedPaper:
    row = session.execute(
        select(SavedPaper).where(SavedPaper.user_id == user.id, SavedPaper.paper_id == paper_id)
    ).scalar_one_or_none()
    if row is None:
        raise ActivityError("not_saved", "This paper is not in the saved library")

    if status is not None:
        if not vocab.is_valid("savedStatus", status):
            raise ActivityError("invalid_status", f"{status!r} is not a saved status")
        row.status = status
        row.last_visited_at = datetime.now(tz=UTC)
    if reasons is not None:
        row.reasons = _validate_reasons(reasons)
    if notes is not None:
        row.notes = notes
    if priority is not None:
        row.priority = priority

    session.flush()
    return row


def remove_saved(session: Session, user: User, paper_id: uuid.UUID) -> bool:
    row = session.execute(
        select(SavedPaper).where(SavedPaper.user_id == user.id, SavedPaper.paper_id == paper_id)
    ).scalar_one_or_none()
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def record_action(
    session: Session,
    user: User,
    *,
    action_type: str,
    paper_id: uuid.UUID | None,
    payload: dict[str, Any] | None = None,
) -> Action:
    """Log an action and apply its effect.

    The effect is applied here, not in the router, so that :func:`undo_action` has exactly
    one place to look when reversing it.
    """
    if not vocab.is_valid("actionType", action_type):
        raise ActivityError("invalid_action_type", f"{action_type!r} is not an action type")
    if action_type == "undo":
        raise ActivityError("use_undo_endpoint", "Undo is created by POST /actions/{id}/undo")

    payload = dict(payload or {})

    requires_paper = action_type in {"skip", "save", "open_source", "translate", "expand_math"}
    if requires_paper and paper_id is None:
        raise ActivityError("paper_required", f"{action_type} needs a paperId")
    # Loaded whenever one was supplied, not only when it is mandatory: `hide_topic` and
    # `hide_author` are usually sent from a card and fall back to that card's field or
    # first author when the client does not spell them out.
    paper = _require_paper(session, paper_id) if paper_id is not None else None

    if action_type == "save":
        reasons = payload.get("reasons")
        saved, created = save_paper(
            session,
            user,
            paper_id,  # type: ignore[arg-type]
            reasons=list(reasons) if isinstance(reasons, list) else None,
            notes=payload.get("notes") if isinstance(payload.get("notes"), str) else None,
        )
        # Remembered so undo knows whether it may delete the row or must only revert the
        # reasons it added.
        payload["createdSavedPaper"] = created
        payload["reasons"] = list(saved.reasons)

    elif action_type == "open_source":
        saved_row = session.execute(
            select(SavedPaper).where(SavedPaper.user_id == user.id, SavedPaper.paper_id == paper_id)
        ).scalar_one_or_none()
        if saved_row is not None and saved_row.status in {"unread", "abstract_in_progress"}:
            payload["previousStatus"] = saved_row.status
            saved_row.status = "source_opened"
            saved_row.last_visited_at = datetime.now(tz=UTC)

    elif action_type == "hide_topic":
        field_id = payload.get("fieldId")
        if not isinstance(field_id, str) or not field_id:
            # Fall back to the paper's own primary field, which is what the UI usually
            # means by "less of this".
            if paper is not None and paper.primary_field_id:
                payload["fieldId"] = paper.primary_field_id
            else:
                raise ActivityError("field_required", "hide_topic needs a fieldId")

    elif action_type == "hide_author":
        author_name = payload.get("authorName")
        if not isinstance(author_name, str) or not author_name.strip():
            authors = (paper.authors if paper else None) or []
            head = authors[0] if authors else None
            name = head.get("name") if isinstance(head, dict) else None
            if isinstance(name, str) and name.strip():
                payload["authorName"] = name
            else:
                raise ActivityError("author_required", "hide_author needs an authorName")

    row = Action(user_id=user.id, paper_id=paper_id, action_type=action_type, payload=payload)
    session.add(row)
    session.flush()
    return row


def undo_action(session: Session, user: User, action_id: uuid.UUID) -> Action:
    """Reverse an action and append the compensating record.

    Returns the ``undo`` action. Reversing something already reversed is an error rather
    than a silent no-op, so a double-tap on the Undo button cannot quietly undo the action
    before it.
    """
    original = session.execute(
        select(Action).where(Action.id == action_id, Action.user_id == user.id)
    ).scalar_one_or_none()
    if original is None:
        raise ActivityError("action_not_found", "No such action")
    if original.action_type == "undo":
        raise ActivityError("cannot_undo_undo", "An undo cannot itself be undone")
    if original.undone:
        raise ActivityError("already_undone", "This action was already undone")

    if original.action_type == "save" and original.paper_id is not None:
        if original.payload.get("createdSavedPaper"):
            remove_saved(session, user, original.paper_id)
        else:
            # The row existed before; only strip the reasons this action contributed.
            saved_row = session.execute(
                select(SavedPaper).where(
                    SavedPaper.user_id == user.id, SavedPaper.paper_id == original.paper_id
                )
            ).scalar_one_or_none()
            added = original.payload.get("reasons")
            if saved_row is not None and isinstance(added, list):
                saved_row.reasons = [r for r in saved_row.reasons if r not in set(added)] or [
                    "interesting"
                ]

    elif original.action_type == "open_source" and original.paper_id is not None:
        previous = original.payload.get("previousStatus")
        if isinstance(previous, str):
            saved_row = session.execute(
                select(SavedPaper).where(
                    SavedPaper.user_id == user.id, SavedPaper.paper_id == original.paper_id
                )
            ).scalar_one_or_none()
            if saved_row is not None and saved_row.status == "source_opened":
                saved_row.status = previous

    # hide_topic / hide_author need no explicit reversal: the suppression query in
    # services.feed only counts actions that are not undone.

    if original.paper_id is not None:
        # Clear the trace so the card is eligible again. Without this, an undone skip
        # would look reversed in the library but never reappear in Discover.
        session.execute(
            delete(Impression).where(
                Impression.user_id == user.id, Impression.paper_id == original.paper_id
            )
        )

    original.undone = True
    compensating = Action(
        user_id=user.id,
        paper_id=original.paper_id,
        action_type="undo",
        undoes_action_id=original.id,
        payload={"undidActionType": original.action_type},
    )
    session.add(compensating)
    session.add(
        AuditLog(
            kind="action_undone",
            actor=f"user:{user.id}",
            entity_type="action",
            entity_id=str(original.id),
            detail={"actionType": original.action_type, "paperId": str(original.paper_id or "")},
        )
    )
    session.flush()
    return compensating


def latest_undoable_action(session: Session, user: User) -> Action | None:
    """The action the Undo button would reverse (spec section 6).

    Ordered by ``sequence``, not ``created_at``: PostgreSQL's ``now()`` is the transaction
    clock, so two actions written in one request carry the same timestamp and "the last
    one" would be decided by a random UUID.
    """
    return session.execute(
        select(Action)
        .where(
            Action.user_id == user.id,
            Action.undone.is_(False),
            Action.action_type.notin_(("undo",)),
        )
        .order_by(Action.sequence.desc())
        .limit(1)
    ).scalar_one_or_none()


__all__ = [
    "ActivityError",
    "ImpressionInput",
    "latest_undoable_action",
    "record_action",
    "record_impressions",
    "remove_saved",
    "save_paper",
    "undo_action",
    "update_saved",
]
