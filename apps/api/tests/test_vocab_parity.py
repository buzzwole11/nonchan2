"""The database, the Python code and the shared vocabularies must agree.

``enums.json`` is loaded by both the TypeScript client and this API. These tests are the
Python half of the guarantee that neither side drifts; ``packages/shared-types`` has the
matching test on the TypeScript side.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from papermatch_api import vocab
from papermatch_api.models import Base

REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED_ENUMS = REPO_ROOT / "packages" / "shared-types" / "enums.json"


def test_the_api_reads_the_same_enums_file_as_the_client() -> None:
    assert vocab.enums_path() == SHARED_ENUMS


def test_every_vocabulary_is_non_empty_and_has_unique_values() -> None:
    for key in vocab.all_keys():
        values = vocab.values(key)
        assert values, f"{key} has no values"
        assert len(set(values)) == len(values), f"{key} has duplicate values"


def test_values_are_snake_case_identifiers() -> None:
    """Wire values are stable identifiers, not display strings."""
    for key in vocab.all_keys():
        for value in vocab.values(key):
            assert re.fullmatch(r"[a-z][a-z0-9_]*", value), f"{key}.{value} is not snake_case"


def test_unknown_vocabulary_raises_with_a_helpful_message() -> None:
    with pytest.raises(KeyError, match="Unknown vocabulary"):
        vocab.values("notAVocabulary")


def _check_constraint_values(sql: str) -> set[str]:
    return set(re.findall(r"'([a-z0-9_]+)'", sql))


def test_every_check_constraint_matches_its_shared_vocabulary() -> None:
    """The CHECK constraints in the schema are generated from ``enums.json``.

    If a value is added to the JSON without a migration regenerating the constraint, the
    database would reject a value the client considers valid. This catches that at test
    time rather than at insert time in production.
    """
    checked = 0
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            name = getattr(constraint, "name", None)
            sqltext = getattr(constraint, "sqltext", None)
            if name is None or sqltext is None:
                continue
            match = re.fullmatch(r"ck_(?P<column>\w+?)_(?P<vocab>[a-z]+)", str(name))
            if match is None:
                continue
            # Find the vocabulary whose lower-cased key matches the constraint suffix.
            key = next(
                (k for k in vocab.all_keys() if k.lower() == match.group("vocab")),
                None,
            )
            if key is None:
                continue
            expected = set(vocab.values(key))
            actual = _check_constraint_values(str(sqltext))
            assert actual == expected, (
                f"{table.name}.{match.group('column')} CHECK constraint is out of sync "
                f"with enums.json '{key}': missing {sorted(expected - actual)}, "
                f"unexpected {sorted(actual - expected)}"
            )
            checked += 1
    assert checked >= 15, f"expected the schema to use many vocabulary constraints, found {checked}"


def test_default_visible_verification_statuses_exclude_only_unverified() -> None:
    """Spec section 12: 未検証の変形は既定で非表示."""
    all_statuses = set(vocab.values("verificationStatus"))
    assert all_statuses - {"unverified"} == vocab.DEFAULT_VISIBLE_VERIFICATION_STATUSES
    assert vocab.is_visible_by_default("unverified") is False
    assert vocab.is_visible_by_default("human_reviewed") is True


def test_identifier_precedence_is_the_order_from_spec_section_16() -> None:
    assert vocab.IDENTIFIER_PRECEDENCE == (
        "doi",
        "arxiv",
        "semantic_scholar",
        "openalex",
        "title_author_year",
    )


def _vocabulary_columns() -> list[tuple[str, str, str]]:
    """``(table, column, vocabulary_key)`` for every column guarded by a vocab CHECK."""
    found: list[tuple[str, str, str]] = []
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            name = getattr(constraint, "name", None)
            if name is None or getattr(constraint, "sqltext", None) is None:
                continue
            match = re.fullmatch(r"ck_(?P<column>\w+?)_(?P<vocab>[a-z]+)", str(name))
            if match is None or match.group("column") not in table.columns:
                continue
            key = next((k for k in vocab.all_keys() if k.lower() == match.group("vocab")), None)
            if key is not None:
                found.append((table.name, match.group("column"), key))
    return found


def test_model_defaults_are_valid_values_of_their_own_vocabulary() -> None:
    """A column default outside its own CHECK constraint would fail on first insert."""
    columns = _vocabulary_columns()
    assert columns, "no vocabulary-constrained columns found"
    for table_name, column_name, key in columns:
        column = Base.metadata.tables[table_name].columns[column_name]
        default = getattr(column.default, "arg", None)
        if isinstance(default, str):
            assert default in vocab.values(key), (
                f"{table_name}.{column_name} defaults to {default!r}, "
                f"which is not a valid '{key}' value"
            )


def test_shared_enums_file_is_valid_json_with_a_values_list_everywhere() -> None:
    document = json.loads(SHARED_ENUMS.read_text(encoding="utf-8"))
    for key, entry in document.items():
        if key.startswith("$"):
            continue
        assert isinstance(entry.get("values"), list), f"{key} has no values list"
