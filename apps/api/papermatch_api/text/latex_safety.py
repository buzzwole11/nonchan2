"""LaTeX admission checks (spec sections 11, 25, 30).

Formulas are rendered by KaTeX inside a WebView. That WebView is a browser, so a formula
string is untrusted input that reaches a rendering engine with a DOM — spec section 30
asks for tests on 危険なLaTeX入力, and this is the module those tests point at.

**This validates; it does not rewrite.** Spec section 11 says 原式を勝手に変換しない, and a
sanitiser that silently strips part of a formula produces something that looks like the
paper's equation but is not it — the worst possible outcome for an app whose first
principle is that the original is the protagonist. So a formula is either admitted
verbatim or refused with a reason, and section 11's documented fallback takes over:
show the formatted LaTeX source and a link to the paper.

What is refused, and why each one matters:

* **Commands that reach outside the formula.** ``\\href`` and ``\\url`` carry a URL, and a
  ``javascript:`` or ``data:`` URL in one is script execution in the WebView. The
  ``\\html*`` family injects class names, ids and inline styles straight into the host
  document. None of them appear in a real equation.
* **Macro definitions.** ``\\def``/``\\newcommand`` and friends are how an expansion bomb
  is written: a handful of nested definitions expand to gigabytes and hang the renderer.
  KaTeX has ``maxExpand``, but relying on a renderer-side limit for input we could have
  refused is the wrong order.
* **File and I/O primitives.** ``\\input``, ``\\include``, ``\\write``, ``\\openout``,
  ``\\catcode`` and ``\\csname`` are meaningless to KaTeX but meaningful to a real TeX
  engine, and this text may one day be handed to one.
* **Layout bombs.** ``\\rule{1pt}{99999em}`` renders a box tall enough to freeze the view.
  Dimensions are capped rather than the command being banned, because ``\\rule`` and
  ``\\hspace`` have legitimate uses at sane sizes.
* **Size and nesting.** A long input or deeply nested groups cost quadratic work in the
  parser. Real display equations are far below these ceilings.

Unbalanced delimiters are refused too, but as a correctness matter rather than a security
one: a formula that does not parse will fail in the WebView anyway, and finding out here
means the fallback renders instead of an error frame.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "FORBIDDEN_COMMANDS",
    "MAX_DIMENSION_EM",
    "MAX_GROUP_DEPTH",
    "MAX_LENGTH",
    "LatexIssue",
    "LatexVerdict",
    "check_latex",
    "is_safe_latex",
]

#: Characters. A display equation in a physics paper is rarely past 600.
MAX_LENGTH = 4000

#: Brace nesting. Deeply nested groups are a parser-cost attack; \frac{\frac{...}} in real
#: mathematics bottoms out long before this.
MAX_GROUP_DEPTH = 32

#: Any explicit length past this is a layout bomb rather than typesetting.
MAX_DIMENSION_EM = 100.0

#: Rough em-equivalents, only used to compare against the ceiling above.
_UNIT_TO_EM = {
    "em": 1.0,
    "ex": 0.5,
    "pt": 0.1,
    "bp": 0.1,
    "px": 0.08,
    "mm": 0.28,
    "cm": 2.8,
    "in": 7.2,
    "pc": 1.2,
    "mu": 0.06,
}

#: Commands refused outright. Grouped by why, because the reason is the useful part when
#: one of these shows up in a real paper and someone has to decide what to do about it.
FORBIDDEN_COMMANDS: dict[str, str] = {
    # Escape into the host document.
    "href": "carries a URL into the rendering WebView",
    "url": "carries a URL into the rendering WebView",
    "htmlClass": "injects markup attributes into the host document",
    "htmlId": "injects markup attributes into the host document",
    "htmlStyle": "injects markup attributes into the host document",
    "htmlData": "injects markup attributes into the host document",
    "includegraphics": "loads an external resource",
    "special": "passes a directive to the output driver",
    # Macro definition: expansion bombs.
    "def": "defines a macro; expansion bombs are written with these",
    "gdef": "defines a macro; expansion bombs are written with these",
    "edef": "defines a macro; expansion bombs are written with these",
    "xdef": "defines a macro; expansion bombs are written with these",
    "let": "defines a macro; expansion bombs are written with these",
    "newcommand": "defines a macro; expansion bombs are written with these",
    "renewcommand": "defines a macro; expansion bombs are written with these",
    "providecommand": "defines a macro; expansion bombs are written with these",
    "newenvironment": "defines an environment",
    "csname": "constructs a command name at expansion time",
    "expandafter": "reorders expansion; used to build commands past a denylist",
    # File and engine primitives.
    "input": "reads a file",
    "include": "reads a file",
    "write": "writes a file",
    "openout": "writes a file",
    "read": "reads a stream",
    "catcode": "redefines how characters are parsed",
    "loop": "unbounded iteration",
    "repeat": "unbounded iteration",
}

#: Deliberately not clever about escaped backslashes: in ``a \\href`` the ``\\`` is a line
#: break and ``href`` is ordinary text, but the second backslash still reads as the start of
#: ``\href`` and the formula is refused. That direction is the safe one — a false positive
#: costs a formula rendered from its source instead of typeset, a false negative costs a
#: script running in the WebView. The usual spelling (``\\`` then a space) is unaffected.
_COMMAND_RE = re.compile(r"\\([a-zA-Z]+)")

#: `{1pt}`, `1pt`, `-3.5em` — the argument forms \rule and \hspace accept.
_DIMENSION_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(em|ex|pt|bp|px|mm|cm|in|pc|mu)\b")


@dataclass(frozen=True)
class LatexIssue:
    """One reason a formula was refused.

    ``code`` is stable and meant to be branched on; ``detail`` is for a human reading a
    log or a review queue.
    """

    code: str
    detail: str


@dataclass(frozen=True)
class LatexVerdict:
    safe: bool
    issues: tuple[LatexIssue, ...] = ()

    def __bool__(self) -> bool:
        return self.safe


def _group_depth_issue(latex: str) -> LatexIssue | None:
    """Deepest brace nesting, ignoring escaped braces.

    Also catches unbalanced braces, which is why it reports two different codes.
    """
    depth = 0
    deepest = 0
    index = 0
    length = len(latex)
    while index < length:
        char = latex[index]
        if char == "\\" and index + 1 < length:
            # An escaped character, including \{ and \}, is not a group delimiter.
            index += 2
            continue
        if char == "{":
            depth += 1
            deepest = max(deepest, depth)
        elif char == "}":
            depth -= 1
            if depth < 0:
                return LatexIssue("unbalanced_braces", "a closing brace has no opening brace")
        index += 1

    if depth != 0:
        return LatexIssue("unbalanced_braces", f"{depth} brace(s) left open")
    if deepest > MAX_GROUP_DEPTH:
        return LatexIssue(
            "nesting_too_deep", f"nested {deepest} deep; the limit is {MAX_GROUP_DEPTH}"
        )
    return None


def _delimiter_issue(latex: str) -> LatexIssue | None:
    r"""``\left`` and ``\right`` must pair up.

    KaTeX raises on an unpaired one, so catching it here is what lets the source fallback
    render instead of an error box.
    """
    opens = len(re.findall(r"\\left(?![a-zA-Z])", latex))
    closes = len(re.findall(r"\\right(?![a-zA-Z])", latex))
    if opens != closes:
        return LatexIssue(
            "unbalanced_delimiters", rf"\left appears {opens} time(s), \right {closes}"
        )
    return None


def _dimension_issue(latex: str) -> LatexIssue | None:
    for value, unit in _DIMENSION_RE.findall(latex):
        em = abs(float(value)) * _UNIT_TO_EM[unit]
        if em > MAX_DIMENSION_EM:
            return LatexIssue(
                "dimension_too_large",
                f"{value}{unit} is about {em:.0f}em; the limit is {MAX_DIMENSION_EM:.0f}em",
            )
    return None


def check_latex(latex: str) -> LatexVerdict:
    """Decide whether a formula may be handed to the renderer.

    Every reason is collected rather than returning on the first one: a formula that trips
    three different limits is a different thing from one that trips a single conservative
    limit, and a reviewer deciding whether to admit it needs to see all of them.
    """
    issues: list[LatexIssue] = []

    if not latex.strip():
        return LatexVerdict(False, (LatexIssue("empty", "no formula"),))

    if len(latex) > MAX_LENGTH:
        issues.append(LatexIssue("too_long", f"{len(latex)} characters; the limit is {MAX_LENGTH}"))

    if "\x00" in latex:
        issues.append(LatexIssue("control_character", "contains a NUL byte"))

    for name in _COMMAND_RE.findall(latex):
        reason = FORBIDDEN_COMMANDS.get(name)
        if reason is not None:
            issues.append(LatexIssue("forbidden_command", rf"\{name}: {reason}"))

    for issue in (_group_depth_issue(latex), _delimiter_issue(latex), _dimension_issue(latex)):
        if issue is not None:
            issues.append(issue)

    # Deduplicate while keeping order: the same banned command three times is one finding.
    seen: set[tuple[str, str]] = set()
    unique: list[LatexIssue] = []
    for issue in issues:
        key = (issue.code, issue.detail)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return LatexVerdict(not unique, tuple(unique))


def is_safe_latex(latex: str) -> bool:
    return check_latex(latex).safe
