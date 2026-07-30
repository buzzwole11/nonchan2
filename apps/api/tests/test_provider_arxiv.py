"""arXiv provider (spec sections 16, 21, 30).

Driven entirely by the recorded Atom feed in ``tests/fixtures``. The environment this was
written in cannot reach arXiv (DECISIONS.md D-016), so the live check is a separate,
opt-in test at the bottom of this file.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from papermatch_api.providers.arxiv import (
    METADATA_LICENSE,
    ArxivPaperProvider,
    build_search_query,
    map_category,
    parse_feed,
)
from papermatch_api.providers.base import PaperProvider, PaperQuery, ProviderUnavailable
from papermatch_api.providers.http import HttpResponse

FEED = (Path(__file__).parent / "fixtures" / "arxiv_feed.xml").read_text(encoding="utf-8")


class StubTransport:
    def __init__(self, response: HttpResponse | Exception) -> None:
        self._response = response
        self.calls: list[dict] = []

    def get(self, url: str, *, params, headers) -> HttpResponse:  # type: ignore[no-untyped-def]
        self.calls.append({"url": url, "params": dict(params)})
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def provider(response: HttpResponse | Exception = HttpResponse(200, FEED)) -> ArxivPaperProvider:
    return ArxivPaperProvider(transport=StubTransport(response), min_interval_seconds=0.0)


# ------------------------------------------------------------------- category mapping


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("hep-th", "hep-th"),
        ("hep-ph", "hep-th"),
        ("cond-mat.str-el", "cond-mat"),
        ("cond-mat.mes-hall", "cond-mat"),
        ("astro-ph.CO", "astro-ph"),
        ("math.AP", "math.AP"),
        ("cs.LG", "cs.LG"),
        ("stat.ML", "cs.LG"),
        ("quant-ph", "quant-ph"),
    ],
)
def test_sub_archives_collapse_onto_the_field_the_reader_chose(term: str, expected: str) -> None:
    """Onboarding offers twelve fields, not arXiv's full category list (spec section 18)."""
    assert map_category(term) == expected


def test_an_unmapped_category_returns_none_rather_than_guessing() -> None:
    assert map_category("q-bio.NC") is None
    assert map_category("") is None


def test_the_search_query_wildcards_archive_level_categories() -> None:
    """`cat:cond-mat` does not match `cond-mat.str-el`, where the field actually lives."""
    query = build_search_query(("cond-mat",))
    assert query == "cat:cond-mat*"

    query = build_search_query(("math.AP",))
    assert query == "cat:math.ap"


def test_a_field_with_no_arxiv_category_falls_back_to_everything() -> None:
    assert build_search_query(("not-a-field",)) == "all:*"
    assert build_search_query(()) == "all:*"


# ------------------------------------------------------------------------- parsing


def test_the_feed_parses_into_records_and_a_total() -> None:
    records, total = parse_feed(FEED)
    assert total == 1428
    # The third entry has no abstract and is dropped rather than losing the whole page.
    assert len(records) == 2


def test_a_published_doi_outranks_the_preprint_id() -> None:
    """Spec section 16: DOI first."""
    records, _ = parse_feed(FEED)
    first = records[0]
    assert first.canonical_id == "doi:10.1103/physrevd.113.086012"
    kinds = {i["kind"] for i in first.identifiers}
    assert kinds == {"doi", "arxiv"}


def test_a_preprint_without_a_doi_is_keyed_on_its_arxiv_id() -> None:
    records, _ = parse_feed(FEED)
    assert records[1].canonical_id == "arxiv:2601.19883"


def test_the_version_is_kept_but_the_identifier_is_version_free() -> None:
    """The version drives "there is a newer version" (section 9); deduplication keys on the
    version-free id (section 16). Both are needed, and they are not the same value."""
    records, _ = parse_feed(FEED)
    assert records[0].version == "v2"
    arxiv_id = next(i["value"] for i in records[0].identifiers if i["kind"] == "arxiv")
    assert arxiv_id == "2602.04517"


def test_multi_line_titles_and_abstracts_are_collapsed() -> None:
    records, _ = parse_feed(FEED)
    assert records[0].title == "Holographic Entanglement in Deformed Conformal Backgrounds"
    assert "\n" not in records[0].abstract
    assert records[0].abstract.startswith("Gauge/gravity duality")


def test_latex_in_the_abstract_survives_untouched() -> None:
    """The abstract is the original; nothing may rewrite its maths (spec section 7)."""
    records, _ = parse_feed(FEED)
    assert r"$S_{\mathrm{EE}} = \frac{c}{3}\log\frac{\ell}{\epsilon}$" in records[0].abstract


def test_authors_are_parsed_in_order() -> None:
    records, _ = parse_feed(FEED)
    assert [a["name"] for a in records[0].authors] == ["A. Fujimoto", "R. Chatterjee"]


def test_the_primary_category_dominates_the_field_weights() -> None:
    records, _ = parse_feed(FEED)
    weights = records[0].field_weights
    assert weights["hep-th"] == 0.7
    assert weights["physics"] == 0.2


def test_a_journal_reference_marks_the_paper_as_published() -> None:
    records, _ = parse_feed(FEED)
    assert "published" in records[0].paper_types
    assert records[0].venue == "Phys. Rev. D 113, 086012 (2026)"
    # And a bare preprint is not.
    assert "published" not in records[1].paper_types
    assert records[1].venue == "arXiv"


def test_the_licence_position_is_recorded_and_checkable() -> None:
    """Spec section 21: 出典、識別子、ライセンス、取得元を追跡可能にする.

    The claim rests on arXiv's API Terms of Use; the URL travels with the record so it can
    be checked rather than taken on faith (DECISIONS.md D-025).
    """
    records, _ = parse_feed(FEED)
    for record in records:
        assert record.license_id == METADATA_LICENSE
        assert record.abstract_redistributable is True
        assert record.raw["sourceTermsUrl"].startswith("https://info.arxiv.org/")
        assert record.source_url.startswith("https://arxiv.org/abs/")


def test_derived_reading_metrics_are_present() -> None:
    records, _ = parse_feed(FEED)
    raw = records[0].raw
    assert raw["englishLevel"] in {"beginner", "intermediate", "advanced", "native_like"}
    assert raw["mathDensity"] > 0
    assert raw["equationCount"] >= 1
    assert raw["estimatedReadingMinutes"] >= 1.0


def test_unparseable_xml_is_reported_as_provider_unavailable() -> None:
    with pytest.raises(ProviderUnavailable, match="unparseable XML"):
        parse_feed("<feed><unclosed>")


def test_a_rejected_request_is_reported_by_its_status_not_as_bad_xml() -> None:
    """A 4xx body is not an Atom feed.

    The client returns 4xx without opening the breaker (one bad query must not disable
    the provider), so the provider checks the status itself. Without this, an HTML error
    page from arXiv — or from a proxy in front of it — is reported as "unparseable XML",
    which points the next person at the parser rather than at the request.
    """
    with pytest.raises(ProviderUnavailable, match="HTTP 403"):
        provider(HttpResponse(403, "<html>Forbidden</html>")).search(PaperQuery(limit=5))


def test_an_empty_feed_parses_to_nothing() -> None:
    records, total = parse_feed(
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    )
    assert records == [] and total == 0


# ------------------------------------------------------------------------- searching


def test_the_provider_satisfies_the_interface() -> None:
    assert isinstance(provider(), PaperProvider)


def test_search_asks_for_the_right_categories_and_ordering() -> None:
    transport = StubTransport(HttpResponse(200, FEED))
    arxiv = ArxivPaperProvider(transport=transport, min_interval_seconds=0.0)

    arxiv.search(PaperQuery(field_ids=("hep-th",), limit=25))
    params = transport.calls[0]["params"]
    assert "cat:hep-th" in params["search_query"]
    assert params["max_results"] == 25
    assert params["sortBy"] == "submittedDate"


def test_search_paginates_while_results_remain() -> None:
    _, cursor = provider().search(PaperQuery(limit=10))
    # 1428 total results, so page two exists.
    assert cursor == "10"


def test_search_stops_paginating_at_the_end() -> None:
    _, cursor = provider().search(PaperQuery(limit=10, cursor="1500"))
    assert cursor is None


def test_search_applies_exclusions_the_atom_api_cannot_express() -> None:
    records, _ = provider().search(
        PaperQuery(limit=10, exclude_canonical_ids=frozenset({"arxiv:2601.19883"}))
    )
    assert [r.canonical_id for r in records] == ["doi:10.1103/physrevd.113.086012"]


def test_search_applies_the_year_filters() -> None:
    records, _ = provider().search(PaperQuery(limit=10, year_from=2027))
    assert records == []


def test_lookup_by_arxiv_id_uses_the_id_list_parameter() -> None:
    transport = StubTransport(HttpResponse(200, FEED))
    arxiv = ArxivPaperProvider(transport=transport, min_interval_seconds=0.0)

    record = arxiv.get_by_canonical_id("arxiv:2602.04517")
    assert record is not None
    assert transport.calls[0]["params"]["id_list"] == "2602.04517"


def test_lookup_by_a_doi_says_not_mine_rather_than_guessing() -> None:
    assert provider().get_by_canonical_id("doi:10.1103/x") is None


# ---------------------------------------------------------------------------- health


def test_health_is_ready_before_any_failure() -> None:
    assert provider().health().healthy is True


def test_health_reports_an_open_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec section 24: the client is told *which* provider is down and why."""
    arxiv = ArxivPaperProvider(
        transport=StubTransport(HttpResponse(503, "")), min_interval_seconds=0.0
    )
    for _ in range(4):
        with pytest.raises(ProviderUnavailable):
            arxiv.search(PaperQuery(limit=1))

    health = arxiv.health()
    assert health.healthy is False
    assert "circuit open" in (health.detail or "")


# ------------------------------------------------------------------------ live check


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("PAPERMATCH_LIVE_PROVIDERS") != "1",
    reason="reaches the real arXiv API; set PAPERMATCH_LIVE_PROVIDERS=1 to run",
)
def test_live_arxiv_returns_parseable_records() -> None:
    """The one test that needs the network.

    Everything above proves the parser handles arXiv's documented shape. This proves the
    shape is still what the documentation says — run it manually, or in an environment
    with outbound access, before trusting an ingestion run.
    """
    records, _ = ArxivPaperProvider().search(PaperQuery(field_ids=("hep-th",), limit=5))
    assert records, "arXiv returned no usable records"
    for record in records:
        assert record.title and record.abstract
        assert record.canonical_id.startswith(("doi:", "arxiv:"))
        assert record.license_id == METADATA_LICENSE
