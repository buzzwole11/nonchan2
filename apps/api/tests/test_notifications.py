"""When a notification may be delivered (spec section 26).

There is no push service in this build, and the part that would be wrong in a way nobody
notices is not the transport — it is the rule. A 「静か」 preset that still buzzes at 03:00
is the bug, and it is decidable without any of the rest.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from papermatch_api.services.notifications import (
    NOTIFICATION_CATEGORIES,
    NOTIFICATION_PRESETS,
    may_notify,
)

TOKYO = "Asia/Tokyo"

# 2026-08-05 is a Wednesday; 2026-08-08 a Saturday. Times are given in UTC and read in Tokyo.
MIDDAY = datetime(2026, 8, 5, 3, 0, tzinfo=UTC)  # 12:00 Tokyo
NIGHT = datetime(2026, 8, 4, 18, 0, tzinfo=UTC)  # 03:00 Tokyo
SATURDAY = datetime(2026, 8, 8, 3, 0, tzinfo=UTC)  # Saturday 12:00 Tokyo


def test_the_presets_are_the_five_the_spec_names() -> None:
    assert set(NOTIFICATION_PRESETS) == {
        "none",
        "quiet",
        "daily",
        "weekdays",
        "important_only",
    }


@pytest.mark.parametrize("category", NOTIFICATION_CATEGORIES)
def test_none_means_none_including_the_important_ones(category: str) -> None:
    # Not "none except important". A preset that made its own exception for what the app
    # considers important would be the app overruling a setting whose whole content is
    # "do not contact me" — and the reader has no way to find out it is doing that.
    assert may_notify("none", category, MIDDAY, TOKYO).allowed is False


@pytest.mark.parametrize("preset", [p for p in NOTIFICATION_PRESETS if p != "none"])
@pytest.mark.parametrize("category", NOTIFICATION_CATEGORIES)
def test_nothing_arrives_in_the_middle_of_the_night(preset: str, category: str) -> None:
    # Applied to every preset, not only `quiet`: nobody chose 「1日1回」 meaning 03:00.
    assert may_notify(preset, category, NIGHT, TOKYO).allowed is False


def test_the_night_is_the_readers_night_not_the_servers() -> None:
    # The same instant is 03:00 in Tokyo and 18:00 in London. Using the server's clock would
    # deliver the daily abstract in the middle of the night for most of the people this app
    # is written for.
    assert may_notify("daily", "daily_abstract", NIGHT, TOKYO).allowed is False
    assert may_notify("daily", "daily_abstract", NIGHT, "Europe/London").allowed is True


def test_an_unreadable_timezone_falls_back_conservatively() -> None:
    # Not to server-local time. The quiet window then applies in UTC, which errs towards
    # sending less rather than at the wrong hour.
    decision = may_notify(
        "daily", "daily_abstract", datetime(2026, 8, 5, 2, 0, tzinfo=UTC), "Mars/Olympus"
    )

    assert decision.allowed is False


def test_daily_allows_one_and_then_stops() -> None:
    assert may_notify("daily", "daily_abstract", MIDDAY, TOKYO).allowed is True
    assert (
        may_notify("daily", "daily_abstract", MIDDAY, TOKYO, already_sent_today=1).allowed is False
    )


def test_weekdays_is_silent_at_the_weekend() -> None:
    assert may_notify("weekdays", "daily_abstract", MIDDAY, TOKYO).allowed is True
    assert may_notify("weekdays", "daily_abstract", SATURDAY, TOKYO).allowed is False


def test_important_only_lets_through_what_changed_under_the_reader() -> None:
    # A recommendation is never important in this sense: "we found something you might like"
    # is the app's interest, not the reader's.
    assert may_notify("important_only", "saved_paper_update", MIDDAY, TOKYO).allowed is True
    assert may_notify("important_only", "important_arrival", MIDDAY, TOKYO).allowed is True
    assert may_notify("important_only", "daily_abstract", MIDDAY, TOKYO).allowed is False
    assert may_notify("important_only", "new_math_card", MIDDAY, TOKYO).allowed is False


def test_quiet_rations_the_rest_but_does_not_block_a_saved_paper_changing() -> None:
    assert (
        may_notify("quiet", "saved_paper_update", MIDDAY, TOKYO, already_sent_today=5).allowed
        is True
    )
    assert (
        may_notify("quiet", "new_math_card", MIDDAY, TOKYO, already_sent_today=1).allowed is False
    )


def test_an_unknown_preset_is_treated_as_none() -> None:
    # Defaulting the other way would let a typo in a settings migration start notifying
    # everybody.
    decision = may_notify("loud", "daily_abstract", MIDDAY, TOKYO)

    assert decision.allowed is False
    assert "unknown preset" in decision.reason


def test_an_unknown_category_is_refused() -> None:
    assert may_notify("daily", "marketing", MIDDAY, TOKYO).allowed is False


def test_every_decision_says_why() -> None:
    # So a settings screen or a log can explain the silence rather than leaving it bare.
    for preset in NOTIFICATION_PRESETS:
        for category in NOTIFICATION_CATEGORIES:
            assert may_notify(preset, category, MIDDAY, TOKYO).reason
