"""Finding where one paper's text refers to another (spec section 17).

A mention is the only evidence that can produce the `contrasting` label, so a wrong match
here becomes a wrong claim about mathematics — telling a reader that two papers disagree
sends them looking for an argument that does not exist. Most of these tests are refusals.
"""

from __future__ import annotations

from pathlib import Path

from papermatch_api.providers.mock_fulltext import MockFullTextProvider
from papermatch_api.text.citations import PaperKey, find_mentions, sentences_of
from tests.conftest import FIXTURES_DIR

GAUSS = PaperKey(
    paper_id="gauss",
    title="A Worked Gaussian Integral",
    year=2026,
    surnames=("nonymous",),
    identifiers=("2601.00001",),
)
CONCENTRATION = PaperKey(
    paper_id="concentration",
    title="Concentration for Non-Reversible Measures",
    year=2021,
    surnames=("jankowski",),
    identifiers=("2108.12603",),
)


def _citing_source() -> str:
    record = MockFullTextProvider(Path(FIXTURES_DIR)).fetch_source("arXiv:2601.00005")
    assert record is not None
    return record.body


# ------------------------------------------------------------------ reading the prose


def test_the_preamble_is_not_prose() -> None:
    # The citing paper's own `\author` in its first sentence is how a paper ends up
    # "mentioning" an unrelated one whose author shares a surname with its own. Found by
    # running the extractor on this fixture and reading the sentences it produced.
    first = sentences_of(_citing_source())[0]

    assert "Almeida" not in first
    assert "documentclass" not in first
    assert first.startswith("The evaluation")


def test_section_headings_do_not_become_sentences() -> None:
    for sentence in sentences_of(_citing_source()):
        assert sentence not in {"Introduction", "Discussion"}


# ------------------------------------------------------------------ what counts as a match


def test_an_identifier_in_the_text_is_a_match() -> None:
    found = find_mentions(_citing_source(), [GAUSS])

    identifier = [m for m in found if m.basis == "identifier"]
    assert len(identifier) == 1
    assert "arXiv:2601.00001" in identifier[0].sentence


def test_a_surname_with_a_year_is_a_match() -> None:
    found = [m for m in find_mentions(_citing_source(), [GAUSS]) if m.basis == "author_year"]

    assert len(found) == 1
    assert "Nonymous (2026)" in found[0].sentence


def test_a_nearly_complete_distinctive_title_is_a_match() -> None:
    found = [m for m in find_mentions(_citing_source(), [CONCENTRATION]) if m.basis == "title"]

    assert len(found) == 1
    assert "Non-Reversible Measures" in found[0].sentence


# ------------------------------------------------------------------ what is refused


def test_a_bare_year_matches_nothing() -> None:
    # "Earlier treatments from 2026 used a different normalisation." A year names nothing.
    sentences = [m.sentence for m in find_mentions(_citing_source(), [GAUSS])]

    assert not any("Earlier treatments" in s for s in sentences)


def test_a_bare_surname_matches_nothing() -> None:
    # "The argument of Nonymous is standard." Surnames repeat across a field.
    sentences = [m.sentence for m in find_mentions(_citing_source(), [GAUSS])]

    assert not any(s.startswith("The argument of") for s in sentences)


def test_a_contrastive_phrase_with_no_reference_attaches_to_nobody() -> None:
    # "Unlike the usual presentation, ..." is a contrast with nothing in particular. If this
    # attached to a paper, that paper would be labelled `contrasting` on a sentence that was
    # never about it.
    sentences = [m.sentence for m in find_mentions(_citing_source(), [GAUSS, CONCENTRATION])]

    assert not any(s.startswith("Unlike the usual") for s in sentences)


def test_a_title_too_short_to_be_distinctive_does_not_match() -> None:
    # "A Worked Gaussian Integral" contributes three usable words, and any sentence about
    # Gaussian integrals contains them.
    found = [m for m in find_mentions(_citing_source(), [GAUSS]) if m.basis == "title"]

    assert found == []


def test_an_unrelated_paper_is_not_mentioned_at_all() -> None:
    stranger = PaperKey(
        paper_id="stranger",
        title="Topological Edge Modes in Kagome Lattices",
        year=2024,
        surnames=("aoki",),
        identifiers=("10.1103/pm.2024.0001",),
    )

    assert find_mentions(_citing_source(), [stranger]) == []


def test_a_paper_that_refers_to_nothing_produces_no_mentions() -> None:
    # The other fixtures have no cross-references, which is why this one was written.
    record = MockFullTextProvider(Path(FIXTURES_DIR)).fetch_source("arXiv:2601.00004")
    assert record is not None

    assert find_mentions(record.body, [GAUSS, CONCENTRATION]) == []
