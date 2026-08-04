"""Reading a manuscript into equations, context and symbols (spec section 12, steps 2–5).

The tests worth having here are about restraint. Extraction that guesses produces a symbol
table full of confident nonsense, and a reader cannot tell a guessed meaning from a read
one — which is exactly the distinction section 0 requires the data model to preserve. So
several of these assert that something is *absent*.
"""

from __future__ import annotations

from pathlib import Path

from papermatch_api.providers.mock_fulltext import MockFullTextProvider
from papermatch_api.text.latex_document import parse_document, strip_comments
from tests.conftest import FIXTURES_DIR


def _document():  # type: ignore[no-untyped-def]
    provider = MockFullTextProvider(Path(FIXTURES_DIR))
    record = provider.fetch_source("arXiv:2601.00001")
    assert record is not None
    return parse_document(record.body)


# ------------------------------------------------------------------ equations


def test_it_finds_every_display_equation() -> None:
    document = _document()

    # Four numbered plus the starred aside.
    assert len(document.equations) == 5


def test_it_keeps_the_latex_byte_for_byte() -> None:
    """Section 11: LaTeX is the record of truth. Extraction copies, it does not rewrite."""
    document = _document()

    assert document.equations[0].latex == r"I(a) = \int_{-\infty}^{\infty} e^{-a x^{2}}\,dx"


def test_it_strips_the_label_and_tag_out_of_the_stored_latex() -> None:
    # `\label` and `\tag` are bookkeeping, not part of the formula; leaving them in makes
    # KaTeX render them as text.
    document = _document()

    for equation in document.equations:
        assert r"\label" not in equation.latex
        assert r"\tag" not in equation.latex


def test_it_reports_the_authors_number_and_never_invents_one() -> None:
    """LaTeX assigns numbering at typesetting time and we are not typesetting.

    A number of our own would look exactly like the paper's and send a reader to the
    wrong line.
    """
    document = _document()

    assert [equation.equation_number for equation in document.equations] == [
        "1",
        "2",
        "3",
        "4",
        None,
    ]


def test_a_starred_environment_is_extracted_but_not_marked_numbered() -> None:
    document = _document()
    aside = document.equations[4]

    assert aside.numbered is False
    assert aside.equation_number is None
    assert r"\lim" in aside.latex


def test_it_records_the_section_each_equation_sits_in() -> None:
    document = _document()

    assert document.equations[0].section == "Setup"
    assert document.equations[1].section == "Evaluation"


def test_labels_resolve_to_the_equation_they_name() -> None:
    document = _document()

    assert document.labels["eq:definition"] == 0
    assert document.labels["eq:result"] == 3


# ------------------------------------------------------------------ context and references


def test_it_keeps_the_paragraph_on_each_side() -> None:
    """The blank line around a display equation used to swallow both.

    A display equation is conventionally surrounded by blank lines, so the segment
    immediately adjacent to it is empty — taking it silently emptied the symbol table and
    the reference list at once.
    """
    document = _document()
    first = document.equations[0]

    assert "we write" in first.context_before
    assert "inverse width" in first.context_after


def test_it_resolves_what_the_surrounding_text_refers_to() -> None:
    document = _document()

    assert document.equations[1].references == ("eq:definition",)
    assert "as:positive" in document.equations[0].references


def test_it_keeps_definition_and_assumption_bodies() -> None:
    document = _document()

    kinds = [kind for kind, _ in document.statements]
    assert "assumption" in kinds
    assert "strictly positive" in document.statements[0][1]


# ------------------------------------------------------------------ symbols


def test_it_reads_symbol_meanings_out_of_a_where_clause() -> None:
    document = _document()

    table = {mention.symbol: mention.local_meaning for mention in document.symbols}
    assert table["a"] == "the inverse width of the Gaussian"
    assert table["x"] == "the integration variable"


def test_every_symbol_points_at_the_equation_it_was_introduced_after() -> None:
    document = _document()

    assert all(mention.equation_index == 0 for mention in document.symbols)


def test_it_does_not_invent_a_meaning_for_every_symbol_it_sees() -> None:
    """`$2\\pi$` appears in the prose but is not a defined symbol.

    A "find every `$...$` and call it a definition" pass is easy and produces a symbol
    table nobody can trust.
    """
    document = _document()

    assert r"2\pi" not in {mention.symbol for mention in document.symbols}


def test_a_document_with_no_where_clause_yields_no_symbols() -> None:
    source = r"""
\begin{document}
Consider the identity
\begin{equation}
a^2 + b^2 = c^2
\end{equation}
which is well known.
\end{document}
"""

    assert parse_document(source).symbols == ()


# ------------------------------------------------------------------ robustness


def test_comments_never_reach_the_extracted_prose() -> None:
    document = _document()

    for equation in document.equations:
        assert "must not reach" not in equation.context_before
        assert "must not reach" not in equation.context_after


def test_an_escaped_percent_survives_comment_stripping() -> None:
    assert strip_comments(r"a 40\% gain % but not this") == r"a 40\% gain "


def test_a_fragment_without_a_preamble_is_read_whole() -> None:
    source = r"\begin{equation}x = 1\end{equation}"

    assert len(parse_document(source).equations) == 1


def test_bracket_display_maths_is_extracted() -> None:
    document = parse_document(r"Text \[ y = mx + b \] more text")

    assert len(document.equations) == 1
    assert document.equations[0].numbered is False
    assert document.equations[0].latex == "y = mx + b"


def test_an_empty_environment_is_dropped_rather_than_stored_blank() -> None:
    document = parse_document(r"\begin{equation}\label{eq:empty}\end{equation}")

    assert document.equations == ()


def test_a_document_with_no_maths_yields_nothing_rather_than_failing() -> None:
    document = parse_document("Just prose, with no formulas at all.")

    assert document.equations == ()
    assert document.symbols == ()
