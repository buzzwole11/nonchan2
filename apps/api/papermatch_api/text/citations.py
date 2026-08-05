"""Finding where one paper's text refers to another (spec section 17).

`services/relations.classify` accepts a `Mention` — a sentence in one paper that refers to
another — and it is the only evidence that can produce the `contrasting` label. This is what
produces those mentions from a stored LaTeX body.

**A wrong match here becomes a wrong claim about mathematics.** Telling a reader that two
papers disagree, on the strength of a sentence that was not actually about the other paper,
sends them looking for an argument that does not exist. So the matching rules are narrow on
purpose and every uncertain case yields nothing:

* **An identifier is a match.** An arXiv id or a DOI written in the text names exactly one
  paper. Nothing else in this module is as reliable.
* **Surname *and* year together are a match.** `Almeida et al. (2024)` matches a 2024 paper
  by Almeida. Either half alone is not: surnames repeat across a field, and a bare year is
  not a reference to anything.
* **A title match must be nearly the whole title.** A paper called "On Concentration" would
  otherwise match every sentence containing that word.

**Sentences, not paragraphs.** The evidence shown to a reader has to be checkable at a
glance, and a paragraph containing a contrastive phrase somewhere and a citation somewhere
else is not evidence that the two are connected.

**Only the sentence that carries the reference.** A contrastive cue in the *next* sentence is
not this paper's disagreement with that one — it may be about a third thing entirely.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from papermatch_api.text.latex_document import body_of, strip_comments

__all__ = [
    "MIN_TITLE_WORDS",
    "PaperKey",
    "TextMention",
    "find_mentions",
    "sentences_of",
]

#: A title has to contribute at least this many distinctive words before a title match is
#: allowed at all. Below it, the "title" is a phrase that shows up everywhere.
MIN_TITLE_WORDS = 4

#: Words that carry no identifying weight in a title.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "for",
        "on",
        "in",
        "to",
        "and",
        "or",
        "with",
        "without",
        "via",
        "using",
        "by",
        "from",
        "at",
        "as",
        "is",
        "are",
        "be",
        "new",
        "novel",
        "towards",
        "toward",
        "some",
        "its",
        "their",
        "our",
        "this",
        "that",
        "these",
        "those",
    ]
)

_COMMANDS = re.compile(r"\\(?:cite[a-z]*|ref|eqref|label|tag)\*?\{[^}]*\}")
#: Structural commands whose argument is not prose. Keeping the argument put the citing
#: paper's own title and author into its first sentence — which is how a paper ends up
#: "mentioning" an unrelated one whose author shares a surname with its own.
_STRUCTURE = re.compile(
    r"\\(?:title|author|date|thanks|documentclass|usepackage|newtheorem|maketitle"
    r"|section|subsection|subsubsection|chapter|paragraph|caption)\*?"
    r"(?:\[[^\]]*\])?(?:\{[^{}]*\})*"
)
_ENVIRONMENT = re.compile(r"\\(?:begin|end)\*?\{[^}]*\}")
_MATH = re.compile(r"\$[^$]*\$")
_MARKUP = re.compile(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{([^{}]*)\})?")
_WHITESPACE = re.compile(r"\s+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\\$])")

_ARXIV = re.compile(r"\b(?:arXiv:)?(\d{4}\.\d{4,5})(?:v\d+)?\b", re.IGNORECASE)
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s,;)\]]+)", re.IGNORECASE)
_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


@dataclass(frozen=True)
class PaperKey:
    """What is known about a paper that a sentence might be referring to."""

    paper_id: str
    title: str
    year: int | None = None
    #: Surnames, lower-cased. Enough for the "Almeida et al. (2024)" form.
    surnames: tuple[str, ...] = ()
    #: Normalised arXiv ids and DOIs, lower-cased.
    identifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class TextMention:
    paper_id: str
    sentence: str
    #: `identifier`, `author_year`, or `title` — which rule matched, kept as evidence.
    basis: str


def _plain(text: str) -> str:
    """LaTeX → readable prose, with markup removed rather than rendered.

    Citation and cross-reference commands go first and entirely: `\\cite{almeida2024}` is a
    key, not a name, and leaving `almeida2024` in the prose would let a surname rule fire on
    a string the author never wrote as a sentence.
    """
    text = _STRUCTURE.sub(" ", text)
    text = _ENVIRONMENT.sub(" ", text)
    text = _COMMANDS.sub(" ", text)
    text = _MATH.sub(" ", text)
    text = _MARKUP.sub(lambda m: m.group(1) or " ", text)
    text = text.replace("~", " ")
    return _WHITESPACE.sub(" ", text).strip()


def sentences_of(source: str) -> list[str]:
    """Prose sentences from a LaTeX body, in document order.

    Environments are not stripped: a sentence inside a theorem is still a sentence, and the
    interesting comparisons are often made there.
    """
    # The body only. A preamble is declarations, not prose, and its `\\author` is the
    # citing paper's own name — exactly the string that must not be matchable as a
    # reference to somebody else.
    prose = _plain(body_of(strip_comments(source)))
    return [part.strip() for part in _SENTENCE_SPLIT.split(prose) if part.strip()]


def _title_words(title: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z]+", title.lower())
        if len(word) > 2 and word not in _STOPWORDS
    }


def _matches(sentence: str, key: PaperKey) -> str | None:
    """Which rule, if any, says this sentence refers to `key`."""
    lowered = sentence.lower()

    for identifier in key.identifiers:
        if identifier and identifier.lower() in lowered:
            return "identifier"
    # Written out rather than only as a stored identifier: a paper's own text writes
    # `arXiv:2601.00001`, and the stored form may be the bare number.
    for pattern in (_ARXIV, _DOI):
        for found in pattern.findall(sentence):
            if any(found.lower() in identifier.lower() for identifier in key.identifiers):
                return "identifier"

    # Surname *and* year in the same sentence. Either half alone is not a reference:
    # surnames repeat across a field and a bare year names nothing.
    if key.year is not None and str(key.year) in _YEAR.findall(sentence):
        for surname in key.surnames:
            if surname and re.search(rf"\b{re.escape(surname)}\b", lowered):
                return "author_year"

    # Nearly the whole title. A short title contributes too few distinctive words to be
    # distinguishable from ordinary prose, so it is not allowed to match at all.
    words = _title_words(key.title)
    if len(words) >= MIN_TITLE_WORDS:
        present = {word for word in words if re.search(rf"\b{re.escape(word)}\b", lowered)}
        if len(present) >= len(words) - 1:
            return "title"

    return None


def find_mentions(source: str, keys: list[PaperKey]) -> list[TextMention]:
    """Every sentence in `source` that refers to one of `keys`.

    A sentence can mention more than one paper and is reported once per paper. It is not
    deduplicated across papers, because "this sentence is about both" is often exactly the
    comparison worth showing.
    """
    found: list[TextMention] = []
    for sentence in sentences_of(source):
        for key in keys:
            basis = _matches(sentence, key)
            if basis is not None:
                found.append(TextMention(paper_id=key.paper_id, sentence=sentence, basis=basis))
    return found
