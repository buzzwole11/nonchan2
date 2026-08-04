"""Reading a LaTeX manuscript into equations, context and symbols (spec section 12).

Steps 2–5 of section 12's pipeline: parse the source, pull out display maths with its
equation numbers and surrounding paragraphs, resolve what the text refers to, and build a
symbol table.

**This is a reader, not a TeX engine.** It does not expand macros, run packages or lay
anything out. It finds display environments, the prose around them, and the sentences that
introduce a symbol. Anything it cannot account for it leaves alone rather than guessing —
a wrong symbol meaning is worse than a missing one, because a reader has no way to tell it
is wrong.

**Nothing here is a claim about correctness.** Every equation it returns is
`source_exact`: copied out of the manuscript, byte for byte. The pipeline's later stages
propose transformations *between* these, and those start `unverified` until a check passes.
Keeping extraction and verification apart is what lets the UI say which is which.

**Equation numbers are the author's, never ours.** A `\\label` gives an anchor, and an
explicit `\\tag` gives a printed number, but LaTeX assigns the actual numbering at
typesetting time and we are not typesetting. So a numbered environment with no `\\tag` gets
`None`, not a counter of our own — a number we invented would look exactly like the paper's
and send a reader to the wrong line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "ExtractedEquation",
    "LatexDocument",
    "SymbolMention",
    "parse_document",
    "strip_comments",
]

#: The environments section 12 calls display math. `equation*` and friends are unnumbered
#: but are still display maths, so they are extracted with `numbered=False`.
DISPLAY_ENVIRONMENTS: tuple[str, ...] = (
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
    "displaymath",
)

_ENV_RE = re.compile(
    r"\\begin\{(?P<env>"
    + "|".join(re.escape(name) for name in DISPLAY_ENVIRONMENTS)
    + r")\}(?P<body>.*?)\\end\{(?P=env)\}",
    re.DOTALL,
)

#: `\[ ... \]` is display maths with no environment name.
_BRACKET_RE = re.compile(r"\\\[(?P<body>.*?)\\\]", re.DOTALL)

_SECTION_RE = re.compile(r"\\(?:sub)*section\*?\{(?P<title>[^}]*)\}")
_LABEL_RE = re.compile(r"\\label\{(?P<label>[^}]*)\}")
_TAG_RE = re.compile(r"\\tag\*?\{(?P<tag>[^}]*)\}")

#: `\begin{document}` when present; a fragment without a preamble is read whole.
_BEGIN_DOC_RE = re.compile(r"\\begin\{document\}")
_END_DOC_RE = re.compile(r"\\end\{document\}")

#: "where $x$ is the ..." — the shape almost every paper uses to introduce a symbol.
#: Deliberately narrow: a looser pattern turns any sentence containing maths into a
#: definition, and a confidently wrong symbol table is worse than an empty one.
_WHERE_RE = re.compile(
    r"\bwhere\b\s+(?P<rest>.{0,400}?)(?=(?:\.\s)|\Z)",
    re.DOTALL | re.IGNORECASE,
)
_INLINE_MATH_RE = re.compile(r"\$(?P<latex>[^$]+)\$")

#: `\newcommand`, `\usepackage` and friends are preamble noise even inside the body.
_COMMENT_RE = re.compile(r"(?<!\\)%.*?$", re.MULTILINE)

#: Assumption and definition environments, whose text is worth keeping attached to the
#: equations near it (section 12 step 4: 参照される式、定義、仮定を解決).
_STATEMENT_ENVIRONMENTS = ("definition", "assumption", "hypothesis", "theorem", "lemma")
_STATEMENT_RE = re.compile(
    r"\\begin\{(?P<env>"
    + "|".join(re.escape(name) for name in _STATEMENT_ENVIRONMENTS)
    + r")\*?\}(?P<body>.*?)\\end\{(?P=env)\*?\}",
    re.DOTALL,
)


@dataclass(frozen=True)
class SymbolMention:
    """A symbol and the sentence that introduced it."""

    symbol: str
    #: The clause the meaning was read out of, kept verbatim so a reviewer can check it.
    local_meaning: str
    #: Index into `LatexDocument.equations` of the equation the clause followed.
    equation_index: int


@dataclass(frozen=True)
class ExtractedEquation:
    """One display equation, exactly as the manuscript wrote it."""

    latex: str
    #: The author's printed number when `\tag` gave one; never a number we assigned.
    equation_number: str | None
    #: `\label{...}`, which is how the prose refers back to this equation.
    label: str | None
    #: Nearest preceding `\section`/`\subsection` title.
    section: str | None
    environment: str
    #: False for starred environments, which LaTeX does not number.
    numbered: bool
    #: The paragraph before and after, for the reader and for symbol extraction.
    context_before: str
    context_after: str
    #: Labels this equation's surrounding text refers to, via `\ref`/`\eqref`.
    references: tuple[str, ...] = ()
    #: Text of any definition/assumption environment this equation sits inside.
    statement: str | None = None


@dataclass(frozen=True)
class LatexDocument:
    equations: tuple[ExtractedEquation, ...] = ()
    symbols: tuple[SymbolMention, ...] = ()
    #: Definition/assumption/theorem bodies, in document order.
    statements: tuple[tuple[str, str], ...] = ()

    @property
    def labels(self) -> dict[str, int]:
        """Label to equation index, for resolving a `\\ref` to the equation it names."""
        return {
            equation.label: index
            for index, equation in enumerate(self.equations)
            if equation.label is not None
        }


def strip_comments(source: str) -> str:
    """Remove TeX comments, keeping `\\%` which is a literal percent sign."""
    return _COMMENT_RE.sub("", source)


def _body_of(source: str) -> str:
    """The document body, or the whole string when there is no `\\begin{document}`."""
    start = _BEGIN_DOC_RE.search(source)
    if start is None:
        return source
    end = _END_DOC_RE.search(source, start.end())
    return source[start.end() : end.start() if end else len(source)]


def _section_at(source: str, position: int) -> str | None:
    """The title of the last section heading before ``position``."""
    title: str | None = None
    for match in _SECTION_RE.finditer(source, 0, position):
        title = match.group("title").strip() or None
    return title


def _paragraphs(window: str) -> list[str]:
    """Split on blank lines, dropping the empties.

    Dropping them is the whole point. A display equation is conventionally preceded and
    followed by a blank line, so the segment immediately adjacent to it is always empty —
    taking it gave every equation an empty context, which silently emptied both the symbol
    table and the reference list.
    """
    return [part for part in (p.strip() for p in re.split(r"\n\s*\n", window)) if part]


def _paragraph_before(source: str, position: int, *, limit: int = 600) -> str:
    # Back to the nearest blank line: that is where the paragraph this equation belongs to
    # starts, and text from the previous one is about a different equation.
    parts = _paragraphs(source[max(0, position - limit) : position])
    return _clean_prose(parts[-1] if parts else "")


def _paragraph_after(source: str, position: int, *, limit: int = 600) -> str:
    parts = _paragraphs(source[position : position + limit])
    return _clean_prose(parts[0] if parts else "")


def _clean_prose(text: str) -> str:
    """Collapse whitespace and drop the commands that carry no reading value."""
    text = re.sub(r"\\(?:label|tag|nonumber|notag)\*?\{[^}]*\}", "", text)
    text = re.sub(r"\\(?:nonumber|notag)\b", "", text)
    text = re.sub(r"\\(?:emph|textit|textbf|text|mathrm)\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _references_in(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in re.finditer(r"\\(?:eq)?ref\{(?P<label>[^}]*)\}", text):
        label = match.group("label").strip()
        if label and label not in found:
            found.append(label)
    return tuple(found)


def _statement_spans(source: str) -> list[tuple[int, int, str, str]]:
    spans: list[tuple[int, int, str, str]] = []
    for match in _STATEMENT_RE.finditer(source):
        spans.append(
            (match.start(), match.end(), match.group("env"), _clean_prose(match.group("body")))
        )
    return spans


def _symbols_from(text: str, equation_index: int) -> list[SymbolMention]:
    """Symbols introduced by a "where ..." clause following an equation.

    Only that shape. A general "find every `$...$` and call it a definition" pass produces
    a symbol table full of confident nonsense, and a reader cannot tell a guessed meaning
    from a read one — which is the distinction section 0 requires the data model to keep.
    """
    mentions: list[SymbolMention] = []
    seen: set[str] = set()
    for clause in _WHERE_RE.finditer(text):
        rest = clause.group("rest")
        for piece in re.split(r",\s*and\s+|,\s*|\s+and\s+", rest):
            math = _INLINE_MATH_RE.search(piece)
            if math is None:
                continue
            symbol = math.group("latex").strip()
            meaning = _clean_prose(_INLINE_MATH_RE.sub("", piece)).lstrip("is ").strip(" .,")
            if not symbol or not meaning or symbol in seen:
                continue
            seen.add(symbol)
            mentions.append(
                SymbolMention(symbol=symbol, local_meaning=meaning, equation_index=equation_index)
            )
    return mentions


def parse_document(source: str) -> LatexDocument:
    """Read a LaTeX manuscript into equations, context and symbols."""
    body = _body_of(strip_comments(source))
    statements = _statement_spans(body)

    matches: list[tuple[int, int, str, str]] = []
    for match in _ENV_RE.finditer(body):
        matches.append((match.start(), match.end(), match.group("env"), match.group("body")))
    for match in _BRACKET_RE.finditer(body):
        matches.append((match.start(), match.end(), "displaymath", match.group("body")))
    matches.sort(key=lambda item: item[0])

    equations: list[ExtractedEquation] = []
    symbols: list[SymbolMention] = []

    for start, end, environment, raw in matches:
        label_match = _LABEL_RE.search(raw)
        tag_match = _TAG_RE.search(raw)
        latex = _LABEL_RE.sub("", raw)
        latex = _TAG_RE.sub("", latex).strip()
        if not latex:
            continue

        before = _paragraph_before(body, start)
        after = _paragraph_after(body, end)
        enclosing = next(
            (text for span_start, span_end, _, text in statements if span_start < start < span_end),
            None,
        )

        index = len(equations)
        equations.append(
            ExtractedEquation(
                latex=latex,
                equation_number=tag_match.group("tag").strip() if tag_match else None,
                label=label_match.group("label").strip() if label_match else None,
                section=_section_at(body, start),
                environment=environment,
                numbered=not environment.endswith("*") and environment != "displaymath",
                context_before=before,
                context_after=after,
                references=_references_in(f"{before} {after}"),
                statement=enclosing,
            )
        )
        symbols.extend(_symbols_from(after, index))

    return LatexDocument(
        equations=tuple(equations),
        symbols=tuple(symbols),
        statements=tuple((environment, text) for _, _, environment, text in statements),
    )
