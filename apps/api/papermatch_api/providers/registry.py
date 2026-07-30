"""Provider selection.

Concrete providers are chosen from configuration, never imported directly by routes.
Phase 1 registers ``arxiv`` and ``openalex`` here and everything upstream keeps working.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import TypeVar

from papermatch_api.config import Settings, get_settings
from papermatch_api.providers.base import PaperProvider, ProviderHealth, TranslationProvider
from papermatch_api.providers.mock_paper import MockPaperProvider
from papermatch_api.providers.mock_translation import MockTranslationProvider

PaperProviderFactory = Callable[[Settings], PaperProvider]
TranslationProviderFactory = Callable[[Settings], TranslationProvider]

PAPER_PROVIDERS: dict[str, PaperProviderFactory] = {
    "mock": lambda settings: MockPaperProvider(settings.fixtures_dir),
}

TRANSLATION_PROVIDERS: dict[str, TranslationProviderFactory] = {
    "mock": lambda _settings: MockTranslationProvider(),
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


def reset_providers() -> None:
    """Drop cached instances. Used by tests that change configuration."""
    get_paper_provider.cache_clear()
    get_translation_provider.cache_clear()


def health_snapshot() -> dict[str, ProviderHealth]:
    """Health of every active provider, for ``GET /health`` (spec section 24)."""
    snapshot: dict[str, ProviderHealth] = {}
    for label, provider in (
        ("paper", get_paper_provider()),
        ("translation", get_translation_provider()),
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
