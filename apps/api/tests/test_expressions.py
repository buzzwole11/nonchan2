"""Expression dictionary and review scheduling (spec sections 9, 30)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import Paper, User, UserSettings
from papermatch_api.services import expressions as service
from papermatch_api.services.activity import ActivityError
from papermatch_api.services.expressions import REVIEW_LADDER_DAYS, next_interval_days
from tests.conftest import requires_db

pytestmark = [pytest.mark.integration, requires_db]


@pytest.fixture
def user(seeded_db: Session) -> User:
    row = User(is_guest=True)
    seeded_db.add(row)
    seeded_db.flush()
    seeded_db.add(UserSettings(user_id=row.id))
    seeded_db.flush()
    seeded_db.refresh(row)
    return row


# ------------------------------------------------------------------------ scheduling


def test_the_ladder_only_ever_grows() -> None:
    assert list(REVIEW_LADDER_DAYS) == sorted(REVIEW_LADDER_DAYS)
    assert REVIEW_LADDER_DAYS[0] >= 1, "spec section 9 says 数日後, not minutes later"


def test_the_interval_saturates_rather_than_indexing_out_of_range() -> None:
    assert next_interval_days(0) == REVIEW_LADDER_DAYS[0]
    assert next_interval_days(99) == REVIEW_LADDER_DAYS[-1]
    assert next_interval_days(-5) == REVIEW_LADDER_DAYS[0]


# ---------------------------------------------------------------------------- saving


def test_saving_an_expression_schedules_its_first_showing(seeded_db: Session, user: User) -> None:
    card, created = service.save_expression(
        seeded_db, user, phrase="break down", meaning="成り立たなくなる"
    )
    assert created is True
    assert card.review_count == 0
    assert card.next_review_at is not None
    # Not due immediately: the reader has just met it.
    assert card.next_review_at > datetime.now(tz=UTC)


def test_the_kind_is_inferred_when_the_client_does_not_say(seeded_db: Session, user: User) -> None:
    """Spec section 9 lists 単語 / 連語 / 構文 / 一文 as distinct things to collect."""
    cases = {
        "renormalisation": "word",
        "break down": "collocation",
        "so that the gap closes": "pattern",
        "We find that the pairing susceptibility diverges only at strong coupling.": "sentence",
    }
    for phrase, expected in cases.items():
        card, _ = service.save_expression(seeded_db, user, phrase=phrase, meaning="—")
        assert card.kind == expected, f"{phrase!r} was classified {card.kind}"


def test_an_explicit_kind_wins_over_the_guess(seeded_db: Session, user: User) -> None:
    card, _ = service.save_expression(
        seeded_db, user, phrase="break down", meaning="—", kind="pattern"
    )
    assert card.kind == "pattern"


def test_saving_the_same_phrase_twice_merges_examples(seeded_db: Session, user: User) -> None:
    """Meeting a phrase in a second paper is a reason to keep both uses, not an error."""
    service.save_expression(
        seeded_db, user, phrase="break down", meaning="成り立たなくなる", example="first use"
    )
    card, created = service.save_expression(
        seeded_db, user, phrase="break down", meaning="", example="second use"
    )
    assert created is False
    assert card.examples == ["first use", "second use"]
    assert card.meaning == "成り立たなくなる", "an empty meaning must not erase the old one"


def test_whitespace_is_normalised_so_near_duplicates_merge(seeded_db: Session, user: User) -> None:
    service.save_expression(seeded_db, user, phrase="break  down", meaning="—")
    _, created = service.save_expression(seeded_db, user, phrase=" break down ", meaning="—")
    assert created is False


def test_an_empty_phrase_is_rejected(seeded_db: Session, user: User) -> None:
    with pytest.raises(ActivityError) as raised:
        service.save_expression(seeded_db, user, phrase="   ", meaning="—")
    assert raised.value.code == "empty_phrase"


def test_an_unknown_kind_is_rejected(seeded_db: Session, user: User) -> None:
    with pytest.raises(ActivityError):
        service.save_expression(seeded_db, user, phrase="x y", meaning="—", kind="idiom")


def test_an_unknown_source_paper_is_rejected(seeded_db: Session, user: User) -> None:
    import uuid as _uuid

    with pytest.raises(ActivityError) as raised:
        service.save_expression(
            seeded_db, user, phrase="x y", meaning="—", source_paper_id=_uuid.uuid4()
        )
    assert raised.value.code == "paper_not_found"


def test_the_context_sentence_is_kept(seeded_db: Session, user: User) -> None:
    """Spec section 9: 実際に読んだ論文の用例 — without context it is just a flashcard."""
    paper = seeded_db.execute(select(Paper)).scalars().first()
    assert paper is not None
    card, _ = service.save_expression(
        seeded_db,
        user,
        phrase="break down",
        meaning="成り立たなくなる",
        context="Existing results break down once the coupling leaves the perturbative regime.",
        source_paper_id=paper.id,
    )
    assert card.context is not None and "perturbative" in card.context
    assert card.source_paper_id == paper.id


# ---------------------------------------------------------------------------- review


def test_nothing_is_due_immediately_after_saving(seeded_db: Session, user: User) -> None:
    service.save_expression(seeded_db, user, phrase="break down", meaning="—")
    assert service.due_expressions(seeded_db, user) == []


def test_an_entry_becomes_due_once_its_interval_has_passed(seeded_db: Session, user: User) -> None:
    card, _ = service.save_expression(seeded_db, user, phrase="break down", meaning="—")
    later = datetime.now(tz=UTC) + timedelta(days=REVIEW_LADDER_DAYS[0] + 1)
    due = service.due_expressions(seeded_db, user, now=later)
    assert [d.id for d in due] == [card.id]


def test_got_it_moves_the_entry_up_the_ladder(seeded_db: Session, user: User) -> None:
    card, _ = service.save_expression(seeded_db, user, phrase="break down", meaning="—")
    now = datetime.now(tz=UTC)

    service.record_review(seeded_db, user, card.id, "got_it", now=now)
    assert card.review_count == 1
    first_gap = card.next_review_at - now

    service.record_review(seeded_db, user, card.id, "got_it", now=now)
    assert card.review_count == 2
    assert card.next_review_at - now > first_gap


def test_again_steps_back_one_rung_rather_than_resetting(seeded_db: Session, user: User) -> None:
    """Spec section 9: 評価や罰ではなく — one miss must not erase every past review."""
    card, _ = service.save_expression(seeded_db, user, phrase="break down", meaning="—")
    now = datetime.now(tz=UTC)
    for _ in range(3):
        service.record_review(seeded_db, user, card.id, "got_it", now=now)
    assert card.review_count == 3

    service.record_review(seeded_db, user, card.id, "again", now=now)
    assert card.review_count == 2, "an 'again' should not send the entry back to zero"


def test_again_on_a_brand_new_entry_does_not_go_negative(seeded_db: Session, user: User) -> None:
    card, _ = service.save_expression(seeded_db, user, phrase="break down", meaning="—")
    service.record_review(seeded_db, user, card.id, "again")
    assert card.review_count == 0
    assert card.next_review_at is not None


def test_a_review_records_when_it_happened(seeded_db: Session, user: User) -> None:
    card, _ = service.save_expression(seeded_db, user, phrase="break down", meaning="—")
    assert card.last_reviewed_at is None
    service.record_review(seeded_db, user, card.id, "got_it")
    assert card.last_reviewed_at is not None


def test_an_invalid_outcome_is_rejected(seeded_db: Session, user: User) -> None:
    card, _ = service.save_expression(seeded_db, user, phrase="break down", meaning="—")
    with pytest.raises(ActivityError) as raised:
        service.record_review(seeded_db, user, card.id, "excellent")
    assert raised.value.code == "invalid_review_outcome"


def test_the_most_overdue_entry_comes_first(seeded_db: Session, user: User) -> None:
    """Ordering by due date is what stops an entry being starved forever."""
    now = datetime.now(tz=UTC)
    older, _ = service.save_expression(seeded_db, user, phrase="alpha term", meaning="—")
    newer, _ = service.save_expression(seeded_db, user, phrase="beta term", meaning="—")
    older.next_review_at = now - timedelta(days=10)
    newer.next_review_at = now - timedelta(days=1)
    seeded_db.flush()

    due = service.due_expressions(seeded_db, user, now=now)
    assert [d.id for d in due] == [older.id, newer.id]


def test_the_queue_is_capped_so_it_never_feels_like_homework(
    seeded_db: Session, user: User
) -> None:
    now = datetime.now(tz=UTC)
    for index in range(10):
        card, _ = service.save_expression(seeded_db, user, phrase=f"term {index}", meaning="—")
        card.next_review_at = now - timedelta(days=1)
    seeded_db.flush()

    assert len(service.due_expressions(seeded_db, user, limit=3, now=now)) == 3


# ------------------------------------------------------------------ listing, deletion


def test_listing_filters_by_kind_and_reports_the_total(seeded_db: Session, user: User) -> None:
    service.save_expression(seeded_db, user, phrase="renormalisation", meaning="—")
    service.save_expression(seeded_db, user, phrase="break down", meaning="—")

    words, total = service.list_expressions(seeded_db, user, kind="word")
    assert total == 1
    assert [w.phrase for w in words] == ["renormalisation"]

    everything, total_all = service.list_expressions(seeded_db, user)
    assert total_all == 2 and len(everything) == 2


def test_deletion_removes_only_the_owners_entry(seeded_db: Session, user: User) -> None:
    other = User(is_guest=True)
    seeded_db.add(other)
    seeded_db.flush()
    seeded_db.add(UserSettings(user_id=other.id))
    seeded_db.flush()
    seeded_db.refresh(other)

    card, _ = service.save_expression(seeded_db, user, phrase="break down", meaning="—")
    assert service.delete_expression(seeded_db, other, card.id) is False
    assert service.delete_expression(seeded_db, user, card.id) is True
    assert service.delete_expression(seeded_db, user, card.id) is False


def test_one_users_dictionary_is_invisible_to_another(seeded_db: Session, user: User) -> None:
    other = User(is_guest=True)
    seeded_db.add(other)
    seeded_db.flush()
    seeded_db.add(UserSettings(user_id=other.id))
    seeded_db.flush()
    seeded_db.refresh(other)

    service.save_expression(seeded_db, user, phrase="break down", meaning="—")
    _, total = service.list_expressions(seeded_db, other)
    assert total == 0


def test_two_users_may_save_the_same_phrase(seeded_db: Session, user: User) -> None:
    """The uniqueness constraint is per user, not global."""
    other = User(is_guest=True)
    seeded_db.add(other)
    seeded_db.flush()
    seeded_db.add(UserSettings(user_id=other.id))
    seeded_db.flush()
    seeded_db.refresh(other)

    _, first = service.save_expression(seeded_db, user, phrase="break down", meaning="—")
    _, second = service.save_expression(seeded_db, other, phrase="break down", meaning="—")
    assert first is True and second is True
