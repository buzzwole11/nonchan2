"""A local, deterministic embedding provider (spec sections 16, 22).

Phase 3 needs vectors to measure "how similar is this to the last twenty cards". The usual
answer is a hosted embedding model, which this environment cannot reach (DECISIONS.md
D-016) — and which would also mean that a reader on a train gets no recommendations.

So this is a real implementation, not a stand-in: hashed bag-of-words with sublinear term
weighting, L2-normalised. It is genuinely weaker than a sentence encoder at *paraphrase* —
"we prove a bound" and "an upper limit is established" share no tokens and will look
unrelated. What it is good at is exactly what section 16 asks similarity for: noticing that
the next card is about the same thing as the last one, which in practice shows up as shared
technical vocabulary rather than shared phrasing.

Being deterministic matters more here than it looks. A recommendation that changes because
the model was re-run is one nobody can debug, and `embeddings` is keyed on model and
version precisely so a re-embedding cannot silently mix vector spaces (DECISIONS.md D-006).
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter

__all__ = ["DIMENSIONS", "MODEL_NAME", "MODEL_VERSION", "LocalEmbeddingProvider", "cosine"]

MODEL_NAME = "papermatch-hashed-bow"
MODEL_VERSION = "1"

#: Enough to keep collisions rare across a corpus of technical vocabulary, small enough
#: that a vector is cheap to store as JSON until a pgvector column exists.
DIMENSIONS = 512

#: Words that carry no topic. Deliberately short: an aggressive list would strip the very
#: hedging vocabulary ("we conjecture", "it remains open") that distinguishes a paper's
#: stance, and section 16 wants topical similarity, not keyword extraction.
STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "we",
        "our",
        "us",
        "their",
        "they",
        "which",
        "with",
        "was",
        "were",
        "will",
        "been",
        "can",
        "could",
        "may",
        "might",
        "must",
        "should",
        "these",
        "those",
        "than",
        "then",
        "there",
        "here",
        "also",
        "such",
        "more",
        "most",
        "some",
        "any",
        "all",
        "both",
        "each",
        "other",
    ]
)

_TOKEN_RE = re.compile(r"[a-z][a-z0-9\-]*")

#: Maths is masked before tokenising. A formula's tokens are notation, not topic, and a
#: paper packed with `\alpha` would otherwise look like every other paper packed with it.
_MATH_RE = re.compile(r"\$[^$]*\$|\\\[[^\]]*\\\]|\\begin\{[a-z*]+\}.*?\\end\{[a-z*]+\}", re.S)


def _tokens(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKC", _MATH_RE.sub(" ", text)).lower()
    return [t for t in _TOKEN_RE.findall(folded) if t not in STOP_WORDS and len(t) > 2]


def _bucket(token: str) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % DIMENSIONS


def embed(text: str) -> list[float]:
    """One L2-normalised vector.

    Counts are damped with ``1 + log(count)`` rather than used raw: a term repeated twenty
    times in an abstract is more important than one used once, but not twenty times more,
    and without the damping a single repeated word dominates the whole vector.
    """
    counts = Counter(_tokens(text))
    if not counts:
        return [0.0] * DIMENSIONS

    vector = [0.0] * DIMENSIONS
    for token, count in counts.items():
        vector[_bucket(token)] += 1.0 + math.log(count)

    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return vector
    return [v / norm for v in vector]


def cosine(a: list[float], b: list[float]) -> float:
    """Similarity of two vectors from this provider.

    Both are already unit length, so this is a dot product — but it is written to cope with
    vectors that are not, because an embedding read back from storage may have come from a
    different model, and silently returning a number larger than 1 would corrupt every
    score it feeds.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


class LocalEmbeddingProvider:
    """Implements `EmbeddingProvider` without leaving the process."""

    name = MODEL_NAME
    model = MODEL_NAME
    version = MODEL_VERSION
    dimensions = DIMENSIONS

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [embed(text) for text in texts]

    def embed_text(self, text: str) -> list[float]:
        return embed(text)
