"""The notification inbox (spec sections 9, 10, 26).

`may_notify` is tested elsewhere as a pure rule; these tests are about the writer that
consults it. The failure modes worth pinning: a `none` reader receiving rows the client is
merely trusted to hide, a re-run double-sending, ten due expressions burning the daily
budget as ten rows, and the one category that must get through (a retraction on a saved
paper) being rationed away.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import (
    Equation,
    ExpressionCard,
    MathCard,
    Notification,
    Paper,
    SavedPaper,
    User,
    UserSettings,
)
from papermatch_api.passwords import hash_password
from papermatch_api.services.notification_inbox import generate_for_user
from tests.conftest import requires_db

pytestmark = [pytest.mark.integration, requires_db]

#: 12:00 UTC on a Wednesday = 21:00 in Tokyo — inside working hours for both zones used
#: here, outside quiet hours. Fixed so these tests do not depend on when CI runs.
NOON = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)  # 12:00 JST


def _user(session: Session, slug: str, preset: str = "daily") -> User:
    row = User(
        email=f"{slug}@example.invalid",
        password_hash=hash_password("correct horse battery"),
        display_name=slug,
        is_guest=False,
    )
    session.add(row)
    session.flush()
    session.add(UserSettings(user_id=row.id, notification_preset=preset, timezone="Asia/Tokyo"))
    session.flush()
    return row


def _paper(session: Session, slug: str, retraction: str = "none") -> Paper:
    row = Paper(
        canonical_id=f"test:inbox-{slug}",
        title=f"Paper {slug}",
        normalized_title=f"paper {slug}",
        abstract="An abstract.",
        authors=[],
        year=2026,
        source_provider="mock",
        source_url=f"https://example.invalid/{slug}",
        acquired_at=NOON,
        retraction_status=retraction,
    )
    session.add(row)
    session.flush()
    return row


def _save(session: Session, user: User, paper: Paper) -> None:
    session.add(SavedPaper(user_id=user.id, paper_id=paper.id, saved_at=NOON))
    session.flush()


def _due_expression(session: Session, user: User, phrase: str) -> None:
    session.add(
        ExpressionCard(
            user_id=user.id,
            phrase=phrase,
            meaning="…",
            kind="word",
            next_review_at=NOON - timedelta(days=1),
        )
    )
    session.flush()


def _card_on(session: Session, paper: Paper) -> MathCard:
    equation = Equation(
        paper_id=paper.id,
        latex=r"E = mc^2",
        display=True,
        provenance_kind="original",
        verification_status="source_exact",
        license_id="CC0-1.0",
        generation={},
    )
    session.add(equation)
    session.flush()
    card = MathCard(
        card_type="derivation",
        title="カード",
        level="level_2",
        source_equation_ids=[str(equation.id)],
        review_status="draft",
        provenance_kind="ai_explanation",
        body="…",
    )
    session.add(card)
    session.flush()
    return card


def _rows(session: Session, user: User) -> list[Notification]:
    return list(
        session.execute(select(Notification).where(Notification.user_id == user.id)).scalars()
    )


def test_a_none_reader_gets_no_rows_at_all(db_session: Session) -> None:
    # Not rows the client hides — no rows. A retraction included: "do not contact me" has
    # no exception the reader cannot see.
    user = _user(db_session, "none", preset="none")
    _save(db_session, user, _paper(db_session, "retracted", retraction="retracted"))

    report = generate_for_user(db_session, user, NOON)

    assert report.written == 0
    assert _rows(db_session, user) == []
    assert any("no notifications" in reason for reason in report.withheld)


def test_a_retraction_on_a_saved_paper_reaches_an_important_only_reader(
    db_session: Session,
) -> None:
    user = _user(db_session, "important", preset="important_only")
    _save(db_session, user, _paper(db_session, "bad", retraction="retracted"))
    _due_expression(db_session, user, "nontrivial")  # must NOT get through

    generate_for_user(db_session, user, NOON)

    rows = _rows(db_session, user)
    assert [row.category for row in rows] == ["saved_paper_update"]
    assert "撤回" in rows[0].title


def test_running_twice_does_not_notify_twice(db_session: Session) -> None:
    # Idempotence is the crash-recovery story: a worker that died halfway resumes by
    # simply running again.
    user = _user(db_session, "twice")
    _save(db_session, user, _paper(db_session, "twice-paper", retraction="withdrawn"))

    first = generate_for_user(db_session, user, NOON)
    second = generate_for_user(db_session, user, NOON)

    assert first.written == 1
    assert second.written == 0
    assert len(_rows(db_session, user)) == 1


def test_ten_due_expressions_are_one_notification(db_session: Session) -> None:
    # Ten rows would spend the whole daily budget saying one fact, and teach the reader
    # to ignore the category.
    user = _user(db_session, "ten")
    for index in range(10):
        _due_expression(db_session, user, f"phrase-{index}")

    generate_for_user(db_session, user, NOON)

    rows = _rows(db_session, user)
    assert [row.category for row in rows] == ["review_due"]
    assert "10 件" in rows[0].body


def test_a_math_card_on_a_saved_paper_notifies_once(db_session: Session) -> None:
    # Section 10's first entrance. Once per card, however many passes run.
    user = _user(db_session, "mathcard")
    paper = _paper(db_session, "mathcard-paper")
    _save(db_session, user, paper)
    card = _card_on(db_session, paper)

    generate_for_user(db_session, user, NOON)
    generate_for_user(db_session, user, NOON)

    rows = [row for row in _rows(db_session, user) if row.category == "new_math_card"]
    assert len(rows) == 1
    assert rows[0].entity_id == str(card.id)


def test_quiet_hours_hold_everything_back(db_session: Session) -> None:
    user = _user(db_session, "night")
    _save(db_session, user, _paper(db_session, "night-paper", retraction="retracted"))

    # 03:00 in the reader's own timezone.
    night = datetime(2026, 8, 11, 18, 0, tzinfo=UTC)  # 03:00 JST
    report = generate_for_user(db_session, user, night)

    assert report.written == 0
    assert any("quiet hours" in reason for reason in report.withheld)
    # And the same pass at noon delivers it — withholding postponed, not cancelled.
    assert generate_for_user(db_session, user, NOON).written == 1


def test_daily_means_one_per_local_day(db_session: Session) -> None:
    user = _user(db_session, "daily", preset="daily")
    paper_a = _paper(db_session, "daily-a")
    paper_b = _paper(db_session, "daily-b")
    _save(db_session, user, paper_a)
    _save(db_session, user, paper_b)
    _card_on(db_session, paper_a)
    _card_on(db_session, paper_b)

    generate_for_user(db_session, user, NOON)
    assert len(_rows(db_session, user)) == 1

    # The next local day, the second card's turn comes.
    generate_for_user(db_session, user, NOON + timedelta(days=1))
    assert len(_rows(db_session, user)) == 2


def test_the_decision_reason_is_frozen_on_the_row(db_session: Session) -> None:
    # 「なぜ通知されたのか」 must be answerable from the row alone (section 0: 監査ログ).
    user = _user(db_session, "reason")
    _save(db_session, user, _paper(db_session, "reason-paper", retraction="corrected"))

    generate_for_user(db_session, user, NOON)

    assert _rows(db_session, user)[0].decision_reason


# ------------------------------------------------------------------ through the API


def test_the_inbox_lists_and_marks_read(client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    auth = client.post("/auth/guest", json={"locale": "ja-JP", "timezone": "Asia/Tokyo"})
    headers = {"Authorization": f"Bearer {auth.json()['accessToken']}"}
    me = client.get("/me", headers=headers).json()
    user = db_session.get(User, uuid.UUID(me["id"]))
    assert user is not None
    _save(db_session, user, _paper(db_session, "api-paper", retraction="retracted"))
    generate_for_user(db_session, user, NOON)

    listed = client.get("/notifications", headers=headers).json()
    assert listed["unreadCount"] == 1
    entry = listed["notifications"][0]
    assert entry["category"] == "saved_paper_update"
    assert entry["readAt"] is None

    read = client.post(f"/notifications/{entry['id']}/read", headers=headers).json()
    assert read["readAt"] is not None

    # Idempotent: the first read time is the answer to "when did they learn of it".
    again = client.post(f"/notifications/{entry['id']}/read", headers=headers).json()
    assert again["readAt"] == read["readAt"]
    assert client.get("/notifications", headers=headers).json()["unreadCount"] == 0


def test_another_readers_notification_is_a_404(client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    owner = _user(db_session, "owner")
    _save(db_session, owner, _paper(db_session, "owner-paper", retraction="retracted"))
    generate_for_user(db_session, owner, NOON)
    row = _rows(db_session, owner)[0]

    auth = client.post("/auth/guest", json={"locale": "ja-JP", "timezone": "Asia/Tokyo"})
    headers = {"Authorization": f"Bearer {auth.json()['accessToken']}"}

    assert client.post(f"/notifications/{row.id}/read", headers=headers).status_code == 404
