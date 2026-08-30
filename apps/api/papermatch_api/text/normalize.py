"""Identifier and title normalisation (spec section 16).

Two records describe the same work far more often than their raw fields suggest: DOIs
arrive with and without the ``https://doi.org/`` prefix and in either case, arXiv ids
carry version suffixes, and titles differ by punctuation, LaTeX markup and whitespace.
Everything here is deliberately pure and side-effect free so it can be unit tested
without a database.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = [
    "normalize_arxiv_id",
    "normalize_author_key",
    "normalize_doi",
    "normalize_title",
    "strip_latex_commands",
    "title_author_year_key",
]

_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
)

_ARXIV_PREFIXES = (
    "https://arxiv.org/abs/",
    "http://arxiv.org/abs/",
    "https://arxiv.org/pdf/",
    "arxiv:",
)

# Trailing "v3" on a new-style (1234.56789) or old-style (hep-th/9901001) identifier.
_ARXIV_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)

# \emph{...}, \mathcal{...}, \text{...} — keep the braced content, drop the command.
_LATEX_COMMAND_WITH_ARG_RE = re.compile(r"\\[a-zA-Z]+\s*\{([^{}]*)\}")
# Bare commands such as \alpha or \, with no braced argument.
_LATEX_BARE_COMMAND_RE = re.compile(r"\\[a-zA-Z]+|\\[^a-zA-Z\s]")

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_doi(raw: str | None) -> str | None:
    """Return the bare, lower-cased DOI, or ``None`` when the input is not a DOI.

    DOIs are case-insensitive for matching purposes, so the canonical form is folded to
    lower case. Registrant prefixes always start with ``10.``; anything else is rejected
    rather than guessed at.
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    lowered = value.lower()
    for prefix in _DOI_PREFIXES:
        if lowered.startswith(prefix):
            value = value[len(prefix) :]
            lowered = value.lower()
            break
    value = lowered.strip().rstrip(".,;")
    if not value.startswith("10."):
        return None
    if "/" not in value:
        return None
    return value


def normalize_arxiv_id(raw: str | None, *, keep_version: bool = False) -> str | None:
    """Return the bare arXiv identifier.

    By default the version suffix is dropped, because ``2401.01234v1`` and
    ``2401.01234v2`` are the same work at different revisions and must collapse to one
    card (spec section 16). Pass ``keep_version=True`` when the revision itself matters,
    for example when reporting that a saved paper has a newer version (spec section 9).
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    lowered = value.lower()
    for prefix in _ARXIV_PREFIXES:
        if lowered.startswith(prefix):
            value = value[len(prefix) :]
            break
    value = value.strip().lower()
    if value.endswith(".pdf"):
        value = value[: -len(".pdf")]
    if not value:
        return None
    if not keep_version:
        value = _ARXIV_VERSION_RE.sub("", value)
    # New style: 2401.01234 — old style: hep-th/9901001
    if re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", value):
        return value
    if re.fullmatch(r"[a-z-]+(\.[a-z]{2})?/\d{7}(v\d+)?", value):
        return value
    return None


def strip_latex_commands(text: str) -> str:
    """Flatten inline LaTeX so that titles differing only in markup compare equal."""
    previous = None
    current = text
    # Repeat so nested commands such as \emph{\mathbf{x}} unwrap fully.
    while previous != current:
        previous = current
        current = _LATEX_COMMAND_WITH_ARG_RE.sub(r"\1", current)
    current = _LATEX_BARE_COMMAND_RE.sub(" ", current)
    return current.replace("{", " ").replace("}", " ").replace("$", " ")


def normalize_title(title: str) -> str:
    """Canonical comparison form of a title.

    Applies Unicode NFKC folding (so ``–`` and ``-`` or full-width characters do not
    create false distinctions), removes LaTeX markup, lower-cases, and collapses
    everything that is not alphanumeric into single spaces.
    """
    folded = unicodedata.normalize("NFKC", title)
    # NFKC leaves en/em dashes alone; they are punctuation for our purposes.
    folded = folded.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    # Providers disagree on "&" vs "and" in the same title often enough that leaving them
    # distinct would split a work in two.
    folded = folded.replace("&", " and ")
    without_latex = strip_latex_commands(folded)
    lowered = without_latex.lower()
    collapsed = _NON_ALNUM_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", collapsed).strip()


def normalize_author_key(author_name: str) -> str:
    """Surname-based key for an author, tolerant of initials and diacritics.

    ``"J. Müller"``, ``"Jan Muller"`` and ``"MULLER, J."`` all reduce to ``muller``.
    """
    folded = unicodedata.normalize("NFKD", author_name)
    ascii_only = "".join(ch for ch in folded if not unicodedata.combining(ch))
    if "," in ascii_only:
        # "Surname, Given" ordering.
        surname = ascii_only.split(",", 1)[0]
    else:
        parts = [p for p in _NON_ALNUM_RE.sub(" ", ascii_only.lower()).split() if len(p) > 1]
        surname = parts[-1] if parts else ascii_only
    return _NON_ALNUM_RE.sub("", surname.lower())


def title_author_year_key(title: str, first_author: str | None, year: int | None) -> str:
    """Last-resort identity key when no DOI or arXiv id is available (spec section 16)."""
    author = normalize_author_key(first_author) if first_author else ""
    return f"{normalize_title(title)}|{author}|{year if year is not None else ''}"
