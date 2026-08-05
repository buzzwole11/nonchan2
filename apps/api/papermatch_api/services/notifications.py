"""When a notification may be delivered (spec section 26).

Section 26 lists five presets — 通知なし / 静か / 1日1回 / 平日のみ / 重要時のみ — and five
things worth notifying about: today's abstract, important new arrivals, a version update or
formal publication of a saved paper, expressions due for review, and new maths cards.

**This decides; it does not deliver.** There is no push service wired up in this build, and
the part that would be wrong in a way nobody notices is not the transport — it is the rule.
A "quiet" preset that still buzzes at 03:00 is the bug, and it is a pure function of the
preset, the category and the local time, so it is testable without any of the rest.

**The reader's own timezone, not the server's.** 「1日1回」 means once during their day. Using
UTC would deliver the daily abstract in the middle of the night for most of the people this
app is written for.

**`none` means none.** Not "none except important". A preset that made its own exception for
what the app considers important would be the app overruling a setting whose whole content is
"do not contact me", and the reader has no way to find out it is doing that.

**Silence is never assumed to be an error.** A category that no preset allows simply does not
fire; nothing here retries, escalates, or falls back to a different channel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = [
    "NOTIFICATION_CATEGORIES",
    "NOTIFICATION_PRESETS",
    "QUIET_HOURS",
    "Decision",
    "may_notify",
]

#: Section 26's five presets, in the order that section lists them.
NOTIFICATION_PRESETS: tuple[str, ...] = ("none", "quiet", "daily", "weekdays", "important_only")

#: What a notification can be about (section 26), and section 9's 再提示 list.
NOTIFICATION_CATEGORIES: tuple[str, ...] = (
    "daily_abstract",
    "important_arrival",
    "saved_paper_update",
    "review_due",
    "new_math_card",
)

#: Categories that count as 重要 — the ones about a paper the reader already saved changing
#: under them. A recommendation is never important in this sense: "we found something you
#: might like" is the app's interest, not the reader's.
_IMPORTANT: frozenset[str] = frozenset({"important_arrival", "saved_paper_update"})

#: No notification of any category is delivered inside this window in the reader's own time.
#: Applied to every preset, not only `quiet`: nobody chose "1日1回" meaning 03:00.
QUIET_HOURS = (time(22, 0), time(8, 0))


@dataclass(frozen=True)
class Decision:
    allowed: bool
    #: Why, so a log or a settings screen can say it rather than leaving silence unexplained.
    reason: str


def _local_time(moment: datetime, timezone: str) -> datetime:
    try:
        return moment.astimezone(ZoneInfo(timezone))
    except (ZoneInfoNotFoundError, ValueError):
        # An unreadable timezone must not become "server time" — that is how the daily
        # abstract ends up arriving at 03:00 for someone. Treated as UTC and, because the
        # quiet-hours window then applies in UTC, the failure is conservative.
        return moment.astimezone(ZoneInfo("UTC"))


def _in_quiet_hours(moment: datetime) -> bool:
    start, end = QUIET_HOURS
    now = moment.time()
    # The window crosses midnight, so it is a union rather than an interval.
    return now >= start or now < end


def may_notify(
    preset: str,
    category: str,
    moment: datetime,
    timezone: str = "UTC",
    *,
    already_sent_today: int = 0,
) -> Decision:
    """Whether a notification of `category` may be delivered at `moment`.

    `already_sent_today` is how many have gone out in the reader's current local day, which
    is what makes 「1日1回」 mean what it says.
    """
    if preset not in NOTIFICATION_PRESETS:
        # An unknown preset is treated as `none`. Defaulting the other way would let a typo
        # in a settings migration start notifying everybody.
        return Decision(False, f"unknown preset '{preset}'; treated as none")
    if category not in NOTIFICATION_CATEGORIES:
        return Decision(False, f"unknown category '{category}'")

    if preset == "none":
        # No exception for "important". See the module comment.
        return Decision(False, "the reader asked for no notifications")

    local = _local_time(moment, timezone)

    if _in_quiet_hours(local):
        return Decision(False, f"quiet hours in {timezone} ({local:%H:%M})")

    if preset == "important_only" and category not in _IMPORTANT:
        return Decision(False, f"'{category}' is not one the reader called important")

    if preset == "weekdays" and local.weekday() >= 5:
        return Decision(False, "weekend")

    if preset in {"daily", "weekdays"} and already_sent_today >= 1:
        return Decision(False, "one already sent today")

    if preset == "quiet" and category not in _IMPORTANT and already_sent_today >= 1:
        # `quiet` is not silent: it lets the things about the reader's own saved papers
        # through, and rations the rest to one a day.
        return Decision(False, "quiet: one non-important notification a day")

    return Decision(True, f"{preset} allows '{category}' at {local:%H:%M} {timezone}")
