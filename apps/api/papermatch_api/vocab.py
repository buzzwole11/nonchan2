"""Cross-language vocabularies.

The API does not keep its own copy of the enum values. It loads
``packages/shared-types/enums.json`` — the same file the TypeScript client reads — so
that a value added on one side cannot silently go missing on the other. A packaged
fallback copy is used when the API is installed outside the monorepo checkout.
"""

from __future__ import annotations

import json
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_MONOREPO_PATH = _HERE.parents[2] / "packages" / "shared-types" / "enums.json"
_PACKAGED_FALLBACK = _HERE / "data" / "enums.json"


def enums_path() -> Path:
    """Location the vocabularies are loaded from."""
    if _MONOREPO_PATH.is_file():
        return _MONOREPO_PATH
    if _PACKAGED_FALLBACK.is_file():
        return _PACKAGED_FALLBACK
    raise FileNotFoundError(
        "enums.json not found. Expected the monorepo copy at "
        f"{_MONOREPO_PATH} or a packaged copy at {_PACKAGED_FALLBACK}."
    )


@lru_cache(maxsize=1)
def _document() -> dict[str, Any]:
    with enums_path().open(encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)
    return data


@cache
def values(key: str) -> tuple[str, ...]:
    """Allowed values for a vocabulary, in the order declared in ``enums.json``."""
    entry = _document().get(key)
    if entry is None or "values" not in entry:
        available = ", ".join(sorted(k for k in _document() if not k.startswith("$")))
        raise KeyError(f"Unknown vocabulary '{key}'. Available: {available}")
    return tuple(entry["values"])


def all_keys() -> tuple[str, ...]:
    """Every vocabulary key, excluding ``$meta``-style annotations."""
    return tuple(k for k in _document() if not k.startswith("$"))


def is_valid(key: str, value: str) -> bool:
    return value in values(key)


# Section 12: 未検証の変形は既定で非表示 — anything not in this set requires an explicit
# opt-in before it reaches the user.
DEFAULT_VISIBLE_VERIFICATION_STATUSES: frozenset[str] = frozenset(
    {
        "source_exact",
        "mechanically_verified",
        "dimensionally_checked",
        "numerically_spot_checked",
        "human_reviewed",
    }
)


def is_visible_by_default(verification_status: str) -> bool:
    return verification_status in DEFAULT_VISIBLE_VERIFICATION_STATUSES


# Section 16: canonical identifier precedence, highest first.
IDENTIFIER_PRECEDENCE: tuple[str, ...] = values("identifierKind")
