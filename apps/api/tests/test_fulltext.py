"""The licence gate on the maths pipeline (spec sections 12, 21).

Section 21 states the rule flatly: ライセンス不明の本文断片を数式カード化しない. Almost
every test here is about a way of accidentally saying yes, because that is the failure
that is invisible afterwards — a card built from a body we had no right to parse looks
exactly like one built from a body we did.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from papermatch_api.providers.base import FullTextRecord
from papermatch_api.providers.mock_fulltext import MockFullTextProvider
from papermatch_api.services.fulltext import (
    PERMITTED_LICENSES,
    REFUSED_LICENSES,
    licence_decision,
    may_build_math_cards,
)
from tests.conftest import FIXTURES_DIR


def _record(**overrides: object) -> FullTextRecord:
    defaults: dict[str, object] = {
        "canonical_id": "arXiv:2601.00001",
        "body_format": "latex",
        "body": r"\begin{equation}E = mc^2\end{equation}",
        "license_id": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "source_url": "https://example.invalid/abs/2601.00001",
        "retrieved_at": datetime.now(tz=UTC),
    }
    defaults.update(overrides)
    return FullTextRecord(**defaults)  # type: ignore[arg-type]


# ------------------------------------------------------------------ what it permits


def test_a_permissive_licence_is_allowed() -> None:
    decision = licence_decision(_record())

    assert decision.permitted is True
    assert decision.license_id == "CC-BY-4.0"
    # The reason is kept even on a yes: it is what goes in the audit log, and "permitted"
    # alone is not checkable later.
    assert "CC-BY-4.0" in decision.reason


@pytest.mark.parametrize("licence", sorted(PERMITTED_LICENSES))
def test_every_licence_on_the_permitted_list_actually_passes(licence: str) -> None:
    assert may_build_math_cards(_record(license_id=licence)) is True


# ------------------------------------------------------------------ what it refuses


def test_an_unknown_licence_is_refused() -> None:
    """The rule section 21 states outright."""
    decision = licence_decision(_record(license_id=None))

    assert decision.permitted is False
    assert decision.code == "unknown_licence"


def test_an_empty_licence_string_is_unknown_and_not_permissive() -> None:
    assert licence_decision(_record(license_id="   ")).code == "unknown_licence"


def test_an_unrecognised_licence_is_refused_rather_than_guessed_at() -> None:
    # Deciding whether a licence permits this belongs to a person reading it once, not to
    # a runtime string comparison guessing.
    decision = licence_decision(_record(license_id="Elsevier-TDM-1.0"))

    assert decision.permitted is False
    assert decision.code == "unrecognised_licence"
    assert "Elsevier-TDM-1.0" in decision.reason


@pytest.mark.parametrize("licence", sorted(REFUSED_LICENSES))
def test_a_named_refusal_says_why(licence: str) -> None:
    decision = licence_decision(_record(license_id=licence))

    assert decision.permitted is False
    assert decision.code == "refused_licence"
    assert decision.reason == REFUSED_LICENSES[licence]


def test_the_arxiv_distribution_licence_is_refused() -> None:
    """The most common licence on arXiv, and the one most likely to be read as permission.

    arXiv's metadata is CC0; the manuscript is not. A pipeline that took the paper's
    `license_id` would see CC0 and let every arXiv paper through.
    """
    assert may_build_math_cards(_record(license_id="arXiv-1.0")) is False


def test_a_pdf_is_refused_even_under_a_permissive_licence() -> None:
    # Section 12's input is LaTeX or structured XML. A PDF has already lost the equation
    # markup, so extracting maths from it would be guessing.
    decision = licence_decision(_record(body_format="pdf"))

    assert decision.permitted is False
    assert decision.code == "unsupported_format"


def test_a_body_with_no_source_url_is_refused() -> None:
    # Section 21 requires 原文リンクを明示. A record we cannot link back to cannot satisfy
    # that, whatever its licence says.
    assert licence_decision(_record(source_url="")).code == "no_source_url"


def test_an_empty_body_is_refused() -> None:
    assert licence_decision(_record(body="   ")).code == "empty_body"


def test_no_record_at_all_is_refused() -> None:
    decision = licence_decision(None)

    assert decision.permitted is False
    assert decision.code == "no_source"


def test_the_two_lists_do_not_overlap() -> None:
    """A licence on both lists would be decided by whichever check ran first."""
    assert PERMITTED_LICENSES.isdisjoint(REFUSED_LICENSES)


# ------------------------------------------------------------------ the fixture provider


def test_the_fixture_provider_serves_the_permitted_document() -> None:
    provider = MockFullTextProvider(Path(FIXTURES_DIR))

    record = provider.fetch_source("arXiv:2601.00001")

    assert record is not None
    assert record.license_id == "CC-BY-4.0"
    assert r"\begin{equation}" in record.body
    assert may_build_math_cards(record) is True


def test_the_fixture_provider_carries_a_refused_document_too() -> None:
    """A provider that only returns permitted documents cannot show the gate works."""
    provider = MockFullTextProvider(Path(FIXTURES_DIR))

    record = provider.fetch_source("arXiv:2601.00002")

    assert record is not None
    assert may_build_math_cards(record) is False


def test_the_fixture_provider_passes_a_null_licence_through_unchanged() -> None:
    # A provider that substituted a default here would be inventing permission.
    provider = MockFullTextProvider(Path(FIXTURES_DIR))

    record = provider.fetch_source("arXiv:2601.00003")

    assert record is not None
    assert record.license_id is None


def test_an_unknown_paper_yields_nothing() -> None:
    provider = MockFullTextProvider(Path(FIXTURES_DIR))

    assert provider.fetch_source("arXiv:9999.99999") is None
