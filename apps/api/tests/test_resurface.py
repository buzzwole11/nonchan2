"""Bringing a saved paper back (spec section 9: 保存を墓場にしない再提示).

Section 9's worry is that saving becomes a way of not reading. The tests that matter are the
ones about papers that must *not* come back: a reminder about something the reader already
dealt with is nagging, and it is the failure that makes people turn the feature off.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from papermatch_api.models import Action, Paper, SavedPaper, User, UserSettings
from papermatch_api.services.resurface import (
    MIN_QUIET_DAYS,
    REPEAT_COOLDOWN_DAYS,
    candidates,
    longest_waiting_days,
    pick,
    record,
)
from tests.conftest import requires_db

pytestmark = [pytest.mark.integration, requires_db]

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def _user(session: Session) -> User:
    row = User(is_guest=True)
    session.add(row)
    session.flush()
    session.add(UserSettings(user_id=row.id))
    session.flush()
    return row


def _paper(session: Session, slug: str) -> Paper:
    row = Paper(
        canonical_id=f"test:resurface-{slug}",
        title=f"Paper {slug}",
        normalized_title=f"paper {slug}",
        abstract="x",
        authors=[],
        year=2026,
        source_provider="mock",
        source_url=f"https://example.invalid/{slug}",
        acquired_at=NOW,
    )
    session.add(row)
    session.flush()
    return row


def _save(
    session: Session,
    user: User,
    paper: Paper,
    *,
    days_ago: int,
    status: str = "unread",
    visited: bool = False,
) -> SavedPaper:
    row = SavedPaper(
        user_id=user.id,
        paper_id=paper.id,
        reasons=["interesting"],
        status=status,
        saved_at=NOW - timedelta(days=days_ago),
        last_visited_at=NOW - timedelta(days=1) if visited else None,
    )
    session.add(row)
    session.flush()
    return row


# ------------------------------------------------------------------ what comes back


def test_a_paper_saved_and_never_opened_comes_back(db_session: Session) -> None:
    user = _user(db_session)
    _save(db_session, user, _paper(db_session, "quiet"), days_ago=MIN_QUIET_DAYS + 5)

    found = pick(db_session, user, NOW)

    assert found is not None
    assert found.paper.canonical_id == "test:resurface-quiet"
    assert found.quiet_days == MIN_QUIET_DAYS + 5


def test_the_longest_waiting_one_comes_back_first(db_session: Session) -> None:
    user = _user(db_session)
    _save(db_session, user, _paper(db_session, "recent"), days_ago=MIN_QUIET_DAYS + 1)
    _save(db_session, user, _paper(db_session, "ancient"), days_ago=MIN_QUIET_DAYS + 60)

    found = pick(db_session, user, NOW)

    assert found is not None
    assert found.paper.canonical_id == "test:resurface-ancient"


def test_only_one_is_picked_however_many_qualify(db_session: Session) -> None:
    # A page returning five saved papers stops being a discovery feed and becomes a chore
    # list. Section 9 asks for 1件.
    user = _user(db_session)
    for index in range(5):
        _save(db_session, user, _paper(db_session, f"many{index}"), days_ago=MIN_QUIET_DAYS + 2)

    assert len(candidates(db_session, user, NOW)) == 5
    assert pick(db_session, user, NOW) is not None


# ------------------------------------------------------------------ what never comes back


def test_a_paper_saved_moments_ago_is_left_alone(db_session: Session) -> None:
    # A reminder that arrives while the reader still remembers saving it reads as the app
    # not having noticed.
    user = _user(db_session)
    _save(db_session, user, _paper(db_session, "fresh"), days_ago=0)

    assert pick(db_session, user, NOW) is None


def test_a_paper_the_reader_opened_is_not_brought_back(db_session: Session) -> None:
    user = _user(db_session)
    _save(db_session, user, _paper(db_session, "visited"), days_ago=30, visited=True)

    assert pick(db_session, user, NOW) is None


@pytest.mark.parametrize(
    "status",
    ["abstract_in_progress", "abstract_done", "source_opened", "focus", "finished", "archived"],
)
def test_a_paper_the_reader_is_dealing_with_is_not_brought_back(
    db_session: Session, status: str
) -> None:
    # Every status other than `unread` is the reader having engaged. An earlier version
    # excluded a hand-written list containing `reading`, which is not even in the
    # vocabulary — so `abstract_done` and `source_opened` papers came back to people who
    # had plainly dealt with them.
    user = _user(db_session)
    _save(db_session, user, _paper(db_session, f"status-{status}"), days_ago=30, status=status)

    assert pick(db_session, user, NOW) is None


def test_a_paper_with_an_action_against_it_is_not_brought_back(db_session: Session) -> None:
    # Translated or opened: that reader dealt with it. Reminding them is nagging.
    user = _user(db_session)
    paper = _paper(db_session, "translated")
    _save(db_session, user, paper, days_ago=30)
    db_session.add(Action(user_id=user.id, paper_id=paper.id, action_type="translate"))
    db_session.flush()

    assert pick(db_session, user, NOW) is None


def test_a_paper_already_brought_back_is_left_alone_for_a_while(db_session: Session) -> None:
    # It came back and was still not opened. That said something; repeating it next session
    # is the app insisting rather than reminding.
    user = _user(db_session)
    paper = _paper(db_session, "reminded")
    _save(db_session, user, paper, days_ago=30)
    record(db_session, user, paper.id)
    db_session.flush()

    assert pick(db_session, user, NOW) is None


def test_the_cooldown_ends_rather_than_being_permanent(db_session: Session) -> None:
    user = _user(db_session)
    paper = _paper(db_session, "cooled")
    _save(db_session, user, paper, days_ago=90)
    action = record(db_session, user, paper.id)
    action.created_at = NOW - timedelta(days=REPEAT_COOLDOWN_DAYS + 1)
    db_session.flush()

    assert pick(db_session, user, NOW) is not None


def test_another_readers_saved_papers_are_never_reachable(db_session: Session) -> None:
    mine = _user(db_session)
    stranger = _user(db_session)
    _save(db_session, stranger, _paper(db_session, "theirs"), days_ago=30)

    assert pick(db_session, mine, NOW) is None


def test_an_empty_library_has_nothing_to_bring_back(db_session: Session) -> None:
    assert pick(db_session, _user(db_session), NOW) is None


# ------------------------------------------------------------------ the health measure


def test_the_wait_is_zero_when_nothing_is_waiting(db_session: Session) -> None:
    # The healthy state, not a missing measurement.
    assert longest_waiting_days(db_session, _user(db_session), NOW) == 0


def test_the_wait_is_measured_from_the_oldest_untouched_save(db_session: Session) -> None:
    user = _user(db_session)
    _save(db_session, user, _paper(db_session, "old"), days_ago=40)
    _save(db_session, user, _paper(db_session, "newer"), days_ago=4)

    assert longest_waiting_days(db_session, user, NOW) == 40
