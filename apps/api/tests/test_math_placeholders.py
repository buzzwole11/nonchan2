"""Unit tests for formula protection during translation (spec sections 7, 29, 30).

The MVP criterion is 数式を含む選択でLaTeXが壊れない — a selection containing maths must
survive translation byte for byte.
"""

from __future__ import annotations

import pytest

from papermatch_api.text.math_placeholders import (
    mask_math,
    restore_math,
    selection_splits_math,
    unmasked_tokens,
)


def test_inline_math_is_masked_and_restored_exactly() -> None:
    text = r"The gap closes at $\theta_c = 1.09^{\circ}$ in this regime."
    masked = mask_math(text)
    assert len(masked.spans) == 1
    assert r"\theta_c" not in masked.masked_text
    assert restore_math(masked.masked_text, masked.spans) == text


def test_multiple_formulas_keep_their_order() -> None:
    text = r"With $a = 1$ and $b = 2$ we obtain $c = 3$."
    masked = mask_math(text)
    assert len(masked.spans) == 3
    assert [s.latex for s in masked.spans] == ["$a = 1$", "$b = 2$", "$c = 3$"]
    assert restore_math(masked.masked_text, masked.spans) == text


def test_display_math_is_marked_as_display() -> None:
    text = r"Therefore $$E = mc^2$$ holds."
    masked = mask_math(text)
    assert len(masked.spans) == 1
    assert masked.spans[0].display is True
    assert restore_math(masked.masked_text, masked.spans) == text


def test_paren_and_bracket_delimiters_are_handled() -> None:
    text = r"We write \(x + y\) and then \[\int_0^1 f(t)\,dt\]."
    masked = mask_math(text)
    assert len(masked.spans) == 2
    assert masked.spans[0].display is False
    assert masked.spans[1].display is True
    assert restore_math(masked.masked_text, masked.spans) == text


def test_equation_environments_are_masked_as_a_whole() -> None:
    text = r"See \begin{equation} S = \frac{c}{3}\log\frac{\ell}{\epsilon} \end{equation} above."
    masked = mask_math(text)
    assert len(masked.spans) == 1
    assert masked.spans[0].display is True
    assert restore_math(masked.masked_text, masked.spans) == text


def test_dollar_inside_an_equation_environment_is_not_a_delimiter() -> None:
    text = r"\begin{align} a &= b \\ c &= d \end{align} and separately $x$."
    masked = mask_math(text)
    assert len(masked.spans) == 2
    assert masked.spans[0].latex.startswith(r"\begin{align}")
    assert masked.spans[1].latex == "$x$"
    assert restore_math(masked.masked_text, masked.spans) == text


def test_escaped_dollar_is_literal_text_not_a_delimiter() -> None:
    text = r"The cost is \$5 per query and the bound is $O(n)$."
    masked = mask_math(text)
    assert len(masked.spans) == 1
    assert masked.spans[0].latex == "$O(n)$"
    assert masked.unbalanced is False
    assert restore_math(masked.masked_text, masked.spans) == text


def test_an_unclosed_delimiter_is_reported_as_unbalanced() -> None:
    masked = mask_math(r"The bound is $O(n \log n) for all inputs.")
    assert masked.unbalanced is True


def test_a_selection_cutting_through_a_formula_is_detected_against_the_full_text() -> None:
    """A user can drag a selection from the middle of one formula into the next.

    The excerpt on its own is lexically valid inline maths, so this can only be caught by
    checking the boundaries against the whole abstract.
    """
    full = r"The gap closes at $\theta_c = 1.09^{\circ}$ in the regime where $\lambda > 0$ holds."
    start = full.index(r"\theta_c")
    end = full.index(r"\lambda") + len(r"\lambda")
    assert full[start:end].count("$") == 2, "the excerpt alone looks like valid inline maths"
    assert mask_math(full[start:end]).unbalanced is False
    assert selection_splits_math(full, start, end) is True


def test_a_selection_that_contains_whole_formulas_is_allowed() -> None:
    full = r"The gap closes at $\theta_c = 1.09^{\circ}$ in the regime where $\lambda > 0$ holds."
    start = full.index("The")
    end = full.index(" holds")
    assert selection_splits_math(full, start, end) is False


def test_a_selection_that_avoids_formulas_entirely_is_allowed() -> None:
    full = r"Background text. The gap closes at $\theta_c$ later."
    assert selection_splits_math(full, 0, len("Background text.")) is False


def test_text_with_no_maths_is_unchanged() -> None:
    text = "Weak lensing measures the projected matter distribution."
    masked = mask_math(text)
    assert masked.spans == ()
    assert masked.masked_text == text
    assert masked.unbalanced is False


def test_restoration_tolerates_whitespace_a_provider_inserted_into_a_token() -> None:
    masked = mask_math(r"The value $x$ is fixed.")
    mangled = masked.masked_text.replace("⟦MATH_1⟧", "⟦ MATH_1 ⟧")
    assert restore_math(mangled, masked.spans) == "The value $x$ is fixed."


def test_a_dropped_token_is_detected_rather_than_silently_losing_a_formula() -> None:
    masked = mask_math(r"We obtain $a = 1$ and $b = 2$.")
    provider_output = masked.masked_text.replace("⟦MATH_2⟧", "")
    missing = unmasked_tokens(provider_output, masked.spans)
    assert missing == ["⟦MATH_2⟧"]


def test_no_tokens_are_reported_missing_when_the_provider_behaves() -> None:
    masked = mask_math(r"We obtain $a = 1$ and $b = 2$.")
    assert unmasked_tokens(masked.masked_text, masked.spans) == []


@pytest.mark.parametrize(
    "text",
    [
        r"$\alpha$",
        r"Start $\beta$ end.",
        r"$$\sum_{i=1}^{n} x_i$$",
        r"Mixed $a$ and \(b\) and \[c\].",
        r"\begin{equation*} x = y \end{equation*}",
        "No maths here at all.",
        r"Nested braces $f(\{x : x \in S\})$ survive.",
    ],
)
def test_mask_then_restore_is_the_identity(text: str) -> None:
    masked = mask_math(text)
    assert restore_math(masked.masked_text, masked.spans) == text
