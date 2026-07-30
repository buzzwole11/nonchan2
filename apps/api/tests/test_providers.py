"""Provider interface conformance and mock behaviour (spec sections 22, 30)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from papermatch_api.providers.base import (
    PaperProvider,
    PaperQuery,
    ProviderUnavailable,
    TranslationProvider,
    TranslationRequest,
)
from papermatch_api.providers.mock_paper import MockPaperProvider
from papermatch_api.providers.mock_translation import MockTranslationProvider
from papermatch_api.providers.registry import (
    PAPER_PROVIDERS,
    TRANSLATION_PROVIDERS,
    health_snapshot,
)
from papermatch_api.text.math_placeholders import mask_math, restore_math, unmasked_tokens

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures"


@pytest.fixture
def provider() -> MockPaperProvider:
    return MockPaperProvider(FIXTURES_DIR)


# -- interface conformance -------------------------------------------------------


def test_mock_paper_provider_satisfies_the_interface(provider: MockPaperProvider) -> None:
    assert isinstance(provider, PaperProvider)


def test_mock_translation_provider_satisfies_the_interface() -> None:
    assert isinstance(MockTranslationProvider(), TranslationProvider)


def test_every_registered_provider_is_constructible() -> None:
    from papermatch_api.config import get_settings

    settings = get_settings()
    for factory in PAPER_PROVIDERS.values():
        assert isinstance(factory(settings), PaperProvider)
    for factory in TRANSLATION_PROVIDERS.values():
        assert isinstance(factory(settings), TranslationProvider)


def test_health_snapshot_covers_every_active_provider() -> None:
    snapshot = health_snapshot()
    assert set(snapshot) == {"paper", "translation"}
    assert all(h.healthy for h in snapshot.values())


# -- fixture corpus --------------------------------------------------------------


def test_the_corpus_has_at_least_the_fifty_records_the_spec_asks_for(
    provider: MockPaperProvider,
) -> None:
    records, _ = provider.search(PaperQuery(limit=100))
    assert len(records) >= 50


def test_the_corpus_is_declared_synthetic_and_openly_licensed() -> None:
    """Spec section 31 item 4: no real abstract text ships in the repository."""
    document = json.loads((FIXTURES_DIR / "papers.sample.json").read_text(encoding="utf-8"))
    assert document["$meta"]["license"] == "CC0-1.0"
    assert "synthetic" in document["$meta"]["note"].lower()
    for paper in document["papers"]:
        assert paper["provenance"]["synthetic"] is True


def test_every_record_carries_provenance(provider: MockPaperProvider) -> None:
    records, _ = provider.search(PaperQuery(limit=100))
    for record in records:
        assert record.source_provider
        assert record.source_url.startswith("http")
        assert record.acquired_at is not None
        # A missing licence is representable, but then the text may not be reused.
        if record.license_id is None:
            assert record.abstract_redistributable is False


def test_records_without_a_licence_exist_so_the_pipeline_is_exercised(
    provider: MockPaperProvider,
) -> None:
    records, _ = provider.search(PaperQuery(limit=100))
    assert any(r.license_id is None for r in records)
    assert any(r.license_id is not None for r in records)


def test_canonical_ids_are_unique_across_the_corpus(provider: MockPaperProvider) -> None:
    records, _ = provider.search(PaperQuery(limit=100))
    ids = [r.canonical_id for r in records]
    assert len(set(ids)) == len(ids)


def test_duplicate_variants_are_only_served_when_asked_for() -> None:
    plain, _ = MockPaperProvider(FIXTURES_DIR).search(PaperQuery(limit=100))
    with_dupes, _ = MockPaperProvider(FIXTURES_DIR, include_duplicate_variants=True).search(
        PaperQuery(limit=100)
    )
    assert len(with_dupes) > len(plain)


# -- query semantics -------------------------------------------------------------


def test_field_filter_selects_only_matching_papers(provider: MockPaperProvider) -> None:
    records, _ = provider.search(PaperQuery(field_ids=("cs.LG",), limit=100))
    assert records
    for record in records:
        assert "cs.LG" in set(record.field_weights) | {record.primary_field_id}


def test_exclusions_are_honoured_so_a_seen_card_does_not_return(
    provider: MockPaperProvider,
) -> None:
    first_page, _ = provider.search(PaperQuery(limit=5))
    seen = frozenset(r.canonical_id for r in first_page)
    next_page, _ = provider.search(PaperQuery(limit=5, exclude_canonical_ids=seen))
    assert seen.isdisjoint({r.canonical_id for r in next_page})


def test_cursor_paging_covers_every_record_exactly_once(provider: MockPaperProvider) -> None:
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(20):
        page, cursor = provider.search(PaperQuery(limit=7, cursor=cursor))
        seen.extend(r.canonical_id for r in page)
        if cursor is None:
            break
    assert len(seen) == len(set(seen))
    total, _ = provider.search(PaperQuery(limit=100))
    assert len(seen) == len(total)


def test_year_filters_are_applied(provider: MockPaperProvider) -> None:
    records, _ = provider.search(PaperQuery(limit=100, year_from=2024, year_to=2025))
    assert records
    assert all(2024 <= r.year <= 2025 for r in records)


def test_lookup_by_canonical_id_round_trips(provider: MockPaperProvider) -> None:
    records, _ = provider.search(PaperQuery(limit=3))
    for record in records:
        assert provider.get_by_canonical_id(record.canonical_id) is not None
    assert provider.get_by_canonical_id("doi:10.0000/does-not-exist") is None


def test_a_missing_fixture_file_degrades_instead_of_raising(tmp_path: Path) -> None:
    """Spec section 25: a provider failure is reported, not thrown at the user."""
    broken = MockPaperProvider(tmp_path)
    records, cursor = broken.search(PaperQuery(limit=10))
    assert records == []
    assert cursor is None
    health = broken.health()
    assert health.healthy is False
    assert "could not read" in (health.detail or "")


# -- translation -----------------------------------------------------------------


def _request(text: str, stage: str = "natural") -> TranslationRequest:
    return TranslationRequest(
        text=text, source_lang="en", target_lang="ja", style="natural", stage=stage
    )


@pytest.mark.parametrize(
    "stage",
    ["hard_words", "sentence_skeleton", "phrase_structure", "literal", "natural", "domain_meaning"],
)
def test_every_hint_stage_returns_output(stage: str) -> None:
    result = MockTranslationProvider().translate(_request("The coupling is strong.", stage))
    assert result.translated_text.strip()
    assert result.model and result.prompt_version


@pytest.mark.parametrize(
    "stage",
    ["sentence_skeleton", "phrase_structure", "literal", "natural", "domain_meaning"],
)
def test_formulas_survive_the_full_round_trip(stage: str) -> None:
    original = r"The gap closes at $\theta_c = 1.09^{\circ}$ with $\Delta \approx 1.8$."
    masked = mask_math(original)
    result = MockTranslationProvider().translate(_request(masked.masked_text, stage))
    assert result.dropped_math_tokens == ()
    restored = restore_math(result.translated_text, masked.spans)
    assert r"\theta_c = 1.09^{\circ}" in restored
    assert r"\Delta \approx 1.8" in restored
    assert unmasked_tokens(result.translated_text, masked.spans) == []


def test_the_glossary_stage_is_not_expected_to_echo_formulas() -> None:
    masked = mask_math(r"The coupling $\lambda$ is strong.")
    result = MockTranslationProvider().translate(_request(masked.masked_text, "hard_words"))
    assert result.dropped_math_tokens == ()


def test_a_failing_provider_raises_provider_unavailable() -> None:
    with pytest.raises(ProviderUnavailable):
        MockTranslationProvider(fail=True).translate(_request("anything"))
    assert MockTranslationProvider(fail=True).health().healthy is False


def test_mock_output_is_deterministic() -> None:
    request = _request("Entanglement entropy grows linearly.", "literal")
    first = MockTranslationProvider().translate(request)
    second = MockTranslationProvider().translate(request)
    assert first.translated_text == second.translated_text
