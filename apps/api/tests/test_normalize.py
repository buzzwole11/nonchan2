"""Unit tests for identifier and title normalisation (spec section 30)."""

from __future__ import annotations

import pytest

from papermatch_api.text.normalize import (
    normalize_arxiv_id,
    normalize_author_key,
    normalize_doi,
    normalize_title,
    strip_latex_commands,
    title_author_year_key,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10.1103/PhysRevD.101.045002", "10.1103/physrevd.101.045002"),
        ("https://doi.org/10.1103/PhysRevD.101.045002", "10.1103/physrevd.101.045002"),
        ("HTTP://DX.DOI.ORG/10.1145/3372297", "10.1145/3372297"),
        ("doi:10.4171/JEMS/1234", "10.4171/jems/1234"),
        ("  10.1038/s41586-021-03819-2  ", "10.1038/s41586-021-03819-2"),
        ("10.1103/PhysRevD.101.045002.", "10.1103/physrevd.101.045002"),
    ],
)
def test_doi_variants_collapse_to_one_form(raw: str, expected: str) -> None:
    assert normalize_doi(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", None, "not-a-doi", "10.1103", "arXiv:2401.01234"])
def test_non_dois_are_rejected_rather_than_guessed(raw: str | None) -> None:
    assert normalize_doi(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2401.01234", "2401.01234"),
        ("arXiv:2401.01234", "2401.01234"),
        ("arXiv:2401.01234v3", "2401.01234"),
        ("https://arxiv.org/abs/2401.01234v2", "2401.01234"),
        ("https://arxiv.org/pdf/2401.01234.pdf", "2401.01234"),
        ("hep-th/9901001", "hep-th/9901001"),
        ("hep-th/9901001v2", "hep-th/9901001"),
        ("math.AP/0501001", "math.ap/0501001"),
    ],
)
def test_arxiv_variants_collapse_and_drop_the_version(raw: str, expected: str) -> None:
    assert normalize_arxiv_id(raw) == expected


def test_arxiv_version_can_be_kept_when_the_revision_matters() -> None:
    assert normalize_arxiv_id("arXiv:2401.01234v3", keep_version=True) == "2401.01234v3"


@pytest.mark.parametrize("raw", ["", None, "12345", "not an id", "10.1103/x"])
def test_invalid_arxiv_ids_are_rejected(raw: str | None) -> None:
    assert normalize_arxiv_id(raw) is None


def test_latex_markup_is_flattened() -> None:
    assert strip_latex_commands(r"\emph{Holographic} $S_{\mathrm{EE}}$").split() == [
        "Holographic",
        "S_",
        "EE",
    ]


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Topological Edge Modes", "topological  edge   modes"),
        ("Anomaly Inflow and Defects", "Anomaly Inflow & Defects"),
        ("Non-perturbative Corrections", "Non–perturbative Corrections"),  # en dash
        (r"Bounds on $\Lambda$-CDM", "Bounds on Lambda-CDM".replace("Lambda", "")),
        ("Ｇｌｏｂａｌ Well-Posedness", "Global Well Posedness"),  # full-width
    ],
)
def test_titles_that_differ_only_in_punctuation_or_markup_compare_equal(a: str, b: str) -> None:
    assert normalize_title(a) == normalize_title(b)


def test_titles_that_genuinely_differ_stay_distinct() -> None:
    assert normalize_title("Mixing Times for Interchange Chains") != normalize_title(
        "Mixing Times for Reinforced Chains"
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("J. Müller", "muller"),
        ("Jan Muller", "muller"),
        ("MULLER, J.", "muller"),
        ("Y. Yamashita", "yamashita"),
        ("Anne-Marie Delacroix", "delacroix"),
    ],
)
def test_author_keys_ignore_initials_and_diacritics(name: str, expected: str) -> None:
    assert normalize_author_key(name) == expected


def test_fallback_key_combines_title_author_and_year() -> None:
    key = title_author_year_key("Scaling Laws for Sparse Mixture Models", "K. Aoki", 2025)
    assert key == "scaling laws for sparse mixture models|aoki|2025"


def test_fallback_key_tolerates_missing_author_and_year() -> None:
    assert title_author_year_key("A Title", None, None) == "a title||"
