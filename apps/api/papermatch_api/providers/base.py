"""Provider interfaces (spec section 22).

Everything the product depends on from outside — paper metadata, translation, embeddings,
AI explanation, maths verification, full text — sits behind one of these protocols. The
rest of the codebase never imports a concrete provider; it asks the registry for the
interface. That is what makes arXiv swappable for OpenAlex, and a mock swappable for
either, without touching a route handler.

Two rules apply to every provider:

* Failure is expected, not exceptional. Each provider reports its health, and callers
  degrade to cache rather than surfacing an error (spec section 25).
* Nothing is returned without provenance. A record with no licence information is
  returned with ``license_id=None`` and ``abstract_redistributable=False`` so downstream
  code can refuse to reuse its text (spec section 21).
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "EmbeddingProvider",
    "ExplanationProvider",
    "FullTextProvider",
    "MathVerifier",
    "PaperProvider",
    "PaperQuery",
    "ProviderError",
    "ProviderHealth",
    "ProviderUnavailable",
    "TranslationProvider",
    "TranslationRequest",
    "TranslationResult",
    "VerificationOutcome",
]


class ProviderError(RuntimeError):
    """Base class for provider failures."""


class ProviderUnavailable(ProviderError):
    """The provider could not be reached, or refused the request.

    Callers catch this and serve cached content (spec section 25: 外部API失敗時もキャッシュ
    済みフィードを表示).
    """


@dataclass(frozen=True)
class ProviderHealth:
    name: str
    healthy: bool
    detail: str | None = None
    checked_at: datetime | None = None


@dataclass(frozen=True)
class PaperQuery:
    """A request for candidate papers.

    ``exclude_canonical_ids`` carries the papers this user has already been shown, so
    deduplication happens before the network call where the provider supports it
    (spec section 16: 一度表示した論文は原則再表示しない).
    """

    field_ids: tuple[str, ...] = ()
    limit: int = 20
    cursor: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    exclude_canonical_ids: frozenset[str] = frozenset()
    include_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class PaperRecord:
    """Provider-neutral paper metadata.

    Field names mirror ``packages/shared-types``' ``Paper`` so the mapping to the API
    response stays mechanical.
    """

    canonical_id: str
    title: str
    abstract: str
    authors: tuple[dict[str, Any], ...]
    year: int
    identifiers: tuple[dict[str, str], ...]
    source_provider: str
    source_url: str
    acquired_at: datetime
    license_id: str | None
    license_url: str | None
    abstract_redistributable: bool
    venue: str | None = None
    primary_field_id: str | None = None
    field_weights: dict[str, float] = field(default_factory=dict)
    paper_types: tuple[str, ...] = ()
    open_access: str = "unknown"
    retraction_status: str = "none"
    version: str | None = None
    pdf_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class PaperProvider(Protocol):
    """Source of paper metadata (arXiv, OpenAlex, Semantic Scholar, Crossref, mock)."""

    name: str

    @abstractmethod
    def search(self, query: PaperQuery) -> tuple[list[PaperRecord], str | None]:
        """Return a page of records and the cursor for the next page (``None`` at end)."""

    @abstractmethod
    def get_by_canonical_id(self, canonical_id: str) -> PaperRecord | None:
        """Fetch a single record, or ``None`` when this provider does not have it."""

    @abstractmethod
    def health(self) -> ProviderHealth:
        """Cheap liveness check; must not raise."""


@dataclass(frozen=True)
class TranslationRequest:
    """A partial translation request (spec section 7).

    ``text`` is the user's selection only — never a whole abstract. The product
    deliberately does not offer full-text translation, and the API enforces a length
    limit so it cannot become one by accident.
    """

    text: str
    source_lang: str
    target_lang: str
    style: str
    stage: str
    #: Surrounding sentences, sent as context but not translated.
    context_before: str = ""
    context_after: str = ""
    field_id: str | None = None


@dataclass(frozen=True)
class TranslationResult:
    translated_text: str
    provider: str
    model: str
    prompt_version: str
    #: Present when the provider could not preserve every masked formula; the caller
    #: falls back to the original text (spec section 7).
    dropped_math_tokens: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@runtime_checkable
class TranslationProvider(Protocol):
    """Translation of a selected span.

    Implementations receive text in which maths has already been masked by
    ``text.math_placeholders`` and must return the tokens untouched.
    """

    name: str

    @abstractmethod
    def translate(self, request: TranslationRequest) -> TranslationResult: ...

    @abstractmethod
    def health(self) -> ProviderHealth: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Semantic vectors for canvas placement and similarity (spec sections 13, 16)."""

    name: str
    model: str
    dimensions: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    def health(self) -> ProviderHealth: ...


@runtime_checkable
class ExplanationProvider(Protocol):
    """AI explanation of an abstract or formula.

    Output is always labelled as AI-generated and never presented as verified
    (spec sections 8, 11, 12).
    """

    name: str

    @abstractmethod
    def explain(self, prompt_kind: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def health(self) -> ProviderHealth: ...


@dataclass(frozen=True)
class VerificationOutcome:
    """Result of checking a derivation step (spec section 12).

    ``status`` is one of the ``verificationStatus`` vocabulary values. Anything that is
    not verified stays hidden by default — an unverified step is worse than no step.
    """

    status: str
    detail: str | None = None
    checks_run: tuple[str, ...] = ()


@runtime_checkable
class MathVerifier(Protocol):
    """Symbolic / numeric / dimensional checking of a proposed transformation."""

    name: str

    @abstractmethod
    def verify_step(
        self, from_latex: str, to_latex: str, context: dict[str, Any]
    ) -> VerificationOutcome: ...

    @abstractmethod
    def health(self) -> ProviderHealth: ...


@runtime_checkable
class FullTextProvider(Protocol):
    """Full text or LaTeX source, only for papers whose terms permit it.

    Spec section 12 restricts the maths pipeline to documents whose licence has been
    checked; spec section 21 forbids scraping publisher sites. Implementations must
    return ``None`` rather than guessing when the terms are unknown.
    """

    name: str

    @abstractmethod
    def fetch_source(self, canonical_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def health(self) -> ProviderHealth: ...
