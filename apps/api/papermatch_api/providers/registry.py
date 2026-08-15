"""Provider selection.

Concrete providers are chosen from configuration, never imported directly by routes.
Phase 1 registers ``arxiv`` and ``openalex`` here and everything upstream keeps working.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import TypeVar

from papermatch_api.config import Settings, get_settings
from papermatch_api.providers.anthropic_explanation import AnthropicExplanationProvider
from papermatch_api.providers.arxiv import ArxivPaperProvider
from papermatch_api.providers.base import (
    ExplanationProvider,
    FullTextProvider,
    PaperProvider,
    ProviderHealth,
    TranslationProvider,
)
from papermatch_api.providers.derived_explanation import DerivedExplanationProvider
from papermatch_api.providers.mock_fulltext import MockFullTextProvider
from papermatch_api.providers.mock_paper import MockPaperProvider
from papermatch_api.providers.mock_translation import MockTranslationProvider
from papermatch_api.providers.openalex import OpenAlexPaperProvider

PaperProviderFactory = Callable[[Settings], PaperProvider]
TranslationProviderFactory = Callable[[Settings], TranslationProvider]
FullTextProviderFactory = Callable[[Settings], FullTextProvider]
ExplanationProviderFactory = Callable[[Settings], ExplanationProvider]

PAPER_PROVIDERS: dict[str, PaperProviderFactory] = {
    "mock": lambda settings: MockPaperProvider(settings.fixtures_dir),
    "arxiv": lambda settings: ArxivPaperProvider(user_agent=settings.provider_user_agent),
    "openalex": lambda settings: OpenAlexPaperProvider(
        user_agent=settings.provider_user_agent, mailto=settings.openalex_mailto
    ),
}

TRANSLATION_PROVIDERS: dict[str, TranslationProviderFactory] = {
    "mock": lambda _settings: MockTranslationProvider(),
}

# Only a fixture source so far. arXiv serves e-print sources, but section 21 forbids using
# them without checking the manuscript's own licence, and that check is per paper rather
# than per provider — so an `arxiv_fulltext` entry here would still go through the same
# gate in `services/fulltext.py`.
FULLTEXT_PROVIDERS: dict[str, FullTextProviderFactory] = {
    "mock": lambda settings: MockFullTextProvider(settings.fixtures_dir),
}

# `derived` is the default rather than `anthropic`, and not only because it needs no key.
# It answers what can be grounded in the paper and refuses the rest by name; the model
# provider answers more and has to be chosen deliberately, because everything it adds is
# generated text a reader will be shown (spec section 8).
EXPLANATION_PROVIDERS: dict[str, ExplanationProviderFactory] = {
    "derived": lambda _settings: DerivedExplanationProvider(),
    "anthropic": lambda settings: AnthropicExplanationProvider(
        api_key=settings.anthropic_api_key,
        model=settings.explanation_model,
    ),
}


T = TypeVar("T")


def _resolve(
    registry: dict[str, Callable[[Settings], T]], key: str, settings: Settings, kind: str
) -> T:
    factory = registry.get(key)
    if factory is None:
        available = ", ".join(sorted(registry))
        raise ValueError(f"Unknown {kind} provider {key!r}. Registered: {available}")
    return factory(settings)


@lru_cache(maxsize=1)
def get_paper_provider() -> PaperProvider:
    settings = get_settings()
    return _resolve(PAPER_PROVIDERS, settings.paper_provider, settings, "paper")


@lru_cache(maxsize=1)
def get_translation_provider() -> TranslationProvider:
    settings = get_settings()
    return _resolve(TRANSLATION_PROVIDERS, settings.translation_provider, settings, "translation")


@lru_cache(maxsize=1)
def get_fulltext_provider() -> FullTextProvider:
    settings = get_settings()
    return _resolve(FULLTEXT_PROVIDERS, settings.fulltext_provider, settings, "fulltext")


@lru_cache(maxsize=1)
def get_explanation_provider() -> ExplanationProvider:
    settings = get_settings()
    return _resolve(EXPLANATION_PROVIDERS, settings.explanation_provider, settings, "explanation")


def reset_providers() -> None:
    """Drop cached instances. Used by tests that change configuration."""
    get_paper_provider.cache_clear()
    get_translation_provider.cache_clear()
    get_fulltext_provider.cache_clear()
    get_explanation_provider.cache_clear()


def health_snapshot() -> dict[str, ProviderHealth]:
    """Health of every active provider, for ``GET /health`` (spec section 24)."""
    snapshot: dict[str, ProviderHealth] = {}
    for label, provider in (
        ("paper", get_paper_provider()),
        ("translation", get_translation_provider()),
        ("explanation", get_explanation_provider()),
    ):
        try:
            snapshot[label] = provider.health()
        except Exception as exc:
            snapshot[label] = ProviderHealth(
                name=getattr(provider, "name", label),
                healthy=False,
                detail=f"health check raised {type(exc).__name__}: {exc}",
            )
    return snapshot
