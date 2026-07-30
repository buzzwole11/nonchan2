"""Swappable providers for every external capability (spec section 22)."""

from papermatch_api.providers.base import (
    EmbeddingProvider,
    ExplanationProvider,
    FullTextProvider,
    MathVerifier,
    PaperProvider,
    PaperQuery,
    PaperRecord,
    ProviderError,
    ProviderHealth,
    ProviderUnavailable,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
    VerificationOutcome,
)

__all__ = [
    "EmbeddingProvider",
    "ExplanationProvider",
    "FullTextProvider",
    "MathVerifier",
    "PaperProvider",
    "PaperQuery",
    "PaperRecord",
    "ProviderError",
    "ProviderHealth",
    "ProviderUnavailable",
    "TranslationProvider",
    "TranslationRequest",
    "TranslationResult",
    "VerificationOutcome",
]
