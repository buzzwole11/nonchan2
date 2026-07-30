"""Maths protection for translation (spec section 7: 数式保護).

A translation model must never be given the chance to "improve" a formula. Before text
goes to a provider every maths span is replaced by an opaque token; after the provider
returns, the original LaTeX is put back byte for byte. If any token failed to survive the
round trip we say so rather than shipping a mangled formula.

Selections are made by hand on a rendered abstract, so a user can easily select from the
middle of one formula to the middle of another. That produces unbalanced delimiters,
which we detect and report instead of masking a span that was never a formula.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "MaskResult",
    "MathSpan",
    "mask_math",
    "restore_math",
    "selection_splits_math",
    "unmasked_tokens",
]

# Deliberately non-ASCII bracket characters: translation models leave them alone far more
# reliably than square brackets, which they happily reflow or translate around.
_TOKEN_OPEN = "\u27e6"  # ⟦
_TOKEN_CLOSE = "\u27e7"  # ⟧

# Tolerant on the way back in: providers sometimes insert spaces inside the brackets.
_TOKEN_RE = re.compile(rf"{_TOKEN_OPEN}\s*MATH[\s_]*(\d+)\s*{_TOKEN_CLOSE}")

_DISPLAY_ENVIRONMENTS = (
    "equation",
    "equation*",
    "align",
    "align*",
    "gather",
    "gather*",
    "multline",
    "multline*",
    "eqnarray",
    "eqnarray*",
)

_ENV_RE = re.compile(
    r"\\begin\{(" + "|".join(re.escape(e) for e in _DISPLAY_ENVIRONMENTS) + r")\}"
    r"(.*?)"
    r"\\end\{\1\}",
    re.DOTALL,
)


@dataclass(frozen=True)
class MathSpan:
    """One masked formula."""

    token: str
    latex: str
    display: bool
    start: int
    end: int


@dataclass(frozen=True)
class MaskResult:
    masked_text: str
    spans: tuple[MathSpan, ...]
    #: True when a maths delimiter was opened but never closed inside the selection.
    #: The caller should widen the selection or warn rather than translate blindly.
    unbalanced: bool


def _token(index: int) -> str:
    return f"{_TOKEN_OPEN}MATH_{index}{_TOKEN_CLOSE}"


def _scan_delimited(text: str) -> tuple[list[tuple[int, int, bool]], bool]:
    """Find maths spans delimited by ``$``/``$$``/``\\(..\\)``/``\\[..\\]``.

    Returns the spans as ``(start, end, is_display)`` plus a flag saying whether an
    opening delimiter was left unclosed.
    """
    spans: list[tuple[int, int, bool]] = []
    i = 0
    length = len(text)
    unbalanced = False

    while i < length:
        char = text[i]

        # Escaped dollar/paren/bracket is literal text, not a delimiter.
        if char == "\\" and i + 1 < length and text[i + 1] in "$()[]":
            nxt = text[i + 1]
            if nxt == "$":
                i += 2
                continue
            if nxt == "(":
                close = text.find("\\)", i + 2)
                if close == -1:
                    unbalanced = True
                    break
                spans.append((i, close + 2, False))
                i = close + 2
                continue
            if nxt == "[":
                close = text.find("\\]", i + 2)
                if close == -1:
                    unbalanced = True
                    break
                spans.append((i, close + 2, True))
                i = close + 2
                continue
            # A stray \) or \] without its opener.
            unbalanced = True
            i += 2
            continue

        if char == "$":
            display = text.startswith("$$", i)
            delim = "$$" if display else "$"
            close = text.find(delim, i + len(delim))
            if close == -1:
                unbalanced = True
                break
            spans.append((i, close + len(delim), display))
            i = close + len(delim)
            continue

        i += 1

    return spans, unbalanced


def mask_math(text: str) -> MaskResult:
    """Replace every maths span in ``text`` with an opaque token.

    Display environments (``\\begin{equation} … \\end{equation}``) are masked first, then
    the remaining ``$``-style delimiters, so a ``$`` inside an environment body is not
    mistaken for an inline delimiter.
    """
    protected: list[tuple[int, int, bool]] = []
    for match in _ENV_RE.finditer(text):
        protected.append((match.start(), match.end(), True))

    remainder_spans, unbalanced = _scan_delimited(text)
    for start, end, display in remainder_spans:
        # Skip anything already covered by a display environment.
        if any(p_start <= start and end <= p_end for p_start, p_end, _ in protected):
            continue
        protected.append((start, end, display))

    protected.sort(key=lambda s: s[0])

    pieces: list[str] = []
    spans: list[MathSpan] = []
    cursor = 0
    for index, (start, end, display) in enumerate(protected, start=1):
        if start < cursor:
            # Overlapping spans should not happen; if they do, keep the original text
            # rather than producing something that cannot be restored.
            continue
        pieces.append(text[cursor:start])
        token = _token(index)
        pieces.append(token)
        spans.append(
            MathSpan(token=token, latex=text[start:end], display=display, start=start, end=end)
        )
        cursor = end
    pieces.append(text[cursor:])

    return MaskResult(masked_text="".join(pieces), spans=tuple(spans), unbalanced=unbalanced)


def selection_splits_math(full_text: str, start: int, end: int) -> bool:
    """True when ``full_text[start:end]`` cuts through a formula.

    Looking at the selection alone cannot answer this: ``"$ in the regime where $"`` is
    lexically valid inline maths, so a span dragged from the middle of one formula to the
    middle of the next masks cleanly and produces nonsense. Masking the *whole* text and
    checking whether either boundary lands strictly inside a span settles it, which is why
    the caller passes the full abstract rather than just the highlighted characters.
    """
    if start >= end:
        return False
    for span in mask_math(full_text).spans:
        if span.start < start < span.end or span.start < end < span.end:
            return True
    return False


def restore_math(translated_text: str, spans: tuple[MathSpan, ...] | list[MathSpan]) -> str:
    """Put the original LaTeX back into a translated string.

    Matching is tolerant of whitespace the provider may have introduced inside a token,
    but the LaTeX itself is restored verbatim — it is never re-rendered or re-escaped.
    """
    by_index = {
        int(span.token.strip(_TOKEN_OPEN + _TOKEN_CLOSE).split("_")[1]): span for span in spans
    }

    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        span = by_index.get(index)
        return span.latex if span is not None else match.group(0)

    return _TOKEN_RE.sub(replace, translated_text)


def unmasked_tokens(
    translated_text: str, spans: tuple[MathSpan, ...] | list[MathSpan]
) -> list[str]:
    """Tokens that the provider dropped or mangled.

    A non-empty result means the translation must not be shown as-is: a formula would be
    missing. Callers fall back to showing the original sentence instead.
    """
    present = {int(m.group(1)) for m in _TOKEN_RE.finditer(translated_text)}
    missing = []
    for span in spans:
        index = int(span.token.strip(_TOKEN_OPEN + _TOKEN_CLOSE).split("_")[1])
        if index not in present:
            missing.append(span.token)
    return missing
