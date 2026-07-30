"""OpenAlex provider (spec sections 16, 21, 30).

Driven by the recorded works response in ``tests/fixtures``; the live check at the bottom
is opt-in for the same reason as the arXiv one (DECISIONS.md D-016).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from papermatch_api.providers.base import PaperProvider, PaperQuery, ProviderUnavailable
from papermatch_api.providers.http import HttpResponse
from papermatch_api.providers.openalex import (
    OpenAlexPaperProvider,
    parse_work,
    reconstruct_abstract,
)

PAYLOAD_TEXT = (Path(__file__).parent / "fixtures" / "openalex_works.json").read_text(
    encoding="utf-8"
)
PAYLOAD = json.loads(PAYLOAD_TEXT)
WORKS = PAYLOAD["results"]


class StubTransport:
    def __init__(self, response: HttpResponse | Exception) -> None:
        self._response = response
        self.calls: list[dict] = []

    def get(self, url: str, *, params, headers) -> HttpResponse:  # type: ignore[no-untyped-def]
        self.calls.append({"url": url, "params": dict(params)})
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def provider(
    response: HttpResponse | Exception = HttpResponse(200, PAYLOAD_TEXT), **kwargs: object
) -> OpenAlexPaperProvider:
    return OpenAlexPaperProvider(
        transport=StubTransport(response),
        min_interval_seconds=0.0,
        **kwargs,  # type: ignore[arg-type]
    )


# ----------------------------------------------------------------- inverted index


def test_the_abstract_is_rebuilt_from_the_inverted_index() -> None:
    """OpenAlex ships abstracts as word → positions, not as text."""
    index = {"Hello": [0], "there": [1], "world": [2, 4], "small": [3]}
    assert reconstruct_abstract(index) == "Hello there world small world"


def test_a_missing_or_empty_index_yields_nothing() -> None:
    assert reconstruct_abstract(None) == ""
    assert reconstruct_abstract({}) == ""


def test_a_gap_in_the_index_is_left_as_a_gap_rather_than_invented() -> None:
    """A hole a reader can see beats a plausible-looking token that was never written."""
    assert reconstruct_abstract({"start": [0], "end": [5]}) == "start end"


def test_negative_and_non_integer_positions_are_ignored() -> None:
    assert reconstruct_abstract({"a": [0], "b": [-1]}) == "a"


def test_the_real_fixture_reconstructs_into_readable_prose() -> None:
    abstract = reconstruct_abstract(WORKS[0]["abstract_inverted_index"])
    assert abstract.startswith("Topological invariants classify insulating phases.")
    assert abstract.endswith("numerically.")


# --------------------------------------------------------------------------- parsing


def test_a_work_with_a_doi_is_keyed_on_it() -> None:
    record = parse_work(WORKS[0])
    assert record is not None
    assert record.canonical_id == "doi:10.1103/physrevb.109.045139"


def test_every_identifier_the_work_carries_is_kept() -> None:
    """Spec section 16: a later lookup by any of them has to resolve to the same paper."""
    record = parse_work(WORKS[0])
    assert record is not None
    kinds = {i["kind"]: i["value"] for i in record.identifiers}
    assert kinds["doi"] == "10.1103/physrevb.109.045139"
    assert kinds["openalex"] == "W4390211873"
    assert kinds["arxiv"] == "2511.08822"


def test_an_arxiv_id_is_recovered_from_a_landing_page_url() -> None:
    work = json.loads(json.dumps(WORKS[0]))
    del work["ids"]["arxiv"]
    record = parse_work(work)
    assert record is not None
    assert any(i["kind"] == "arxiv" and i["value"] == "2511.08822" for i in record.identifiers)


def test_a_work_without_a_doi_falls_back_to_its_openalex_id() -> None:
    record = parse_work(WORKS[1])
    assert record is not None
    assert record.canonical_id == "openalex:W4390299991"


def test_authors_keep_their_orcid_and_affiliation() -> None:
    record = parse_work(WORKS[0])
    assert record is not None
    assert record.authors[0]["name"] == "N. Quesada"
    assert record.authors[0]["externalId"] == "https://orcid.org/0000-0002-1825-0097"
    assert record.authors[0]["affiliation"] == "Institute for Theoretical Physics"
    # An author with no institution is still an author.
    assert record.authors[1]["affiliation"] is None


def test_the_topic_field_maps_onto_one_of_our_fields() -> None:
    record = parse_work(WORKS[0])
    assert record is not None
    assert record.primary_field_id == "cond-mat"
    assert record.field_weights == {"cond-mat": 0.7, "physics": 0.2}


def test_open_access_status_and_venue_are_carried_through() -> None:
    record = parse_work(WORKS[0])
    assert record is not None
    assert record.open_access == "green"
    assert record.venue == "Physical Review B"


def test_a_recognised_licence_permits_reuse() -> None:
    record = parse_work(WORKS[0])
    assert record is not None
    assert record.license_id == "CC-BY-4.0"
    assert record.abstract_redistributable is True


def test_an_unrecognised_licence_is_not_guessed_at() -> None:
    """Spec section 21: ライセンス不明の本文断片を扱わない.

    `abstract_redistributable=False` is what makes ingestion skip the record entirely
    rather than storing text nobody has cleared.
    """
    record = parse_work(WORKS[2])
    assert record is not None
    assert record.license_id is None
    assert record.abstract_redistributable is False


def test_a_work_with_no_abstract_is_not_a_card() -> None:
    """Spec section 6 makes the abstract the body of the card; a title alone is not one."""
    assert parse_work(WORKS[3]) is None


def test_a_retracted_work_is_marked_as_such() -> None:
    work = json.loads(json.dumps(WORKS[0]))
    work["is_retracted"] = True
    record = parse_work(work)
    assert record is not None
    assert record.retraction_status == "retracted"


def test_a_preprint_type_is_not_labelled_published() -> None:
    record = parse_work(WORKS[1])
    assert record is not None
    assert "preprint" in record.paper_types
    assert "published" not in record.paper_types


def test_the_reconstruction_is_flagged_so_it_is_never_taken_for_the_publishers_text() -> None:
    record = parse_work(WORKS[0])
    assert record is not None
    assert record.raw["abstractReconstructedFromInvertedIndex"] is True


def test_a_work_with_neither_title_nor_identifiers_is_skipped() -> None:
    assert parse_work({}) is None
    assert parse_work({"display_name": "   "}) is None


# ------------------------------------------------------------------------- searching


def test_the_provider_satisfies_the_interface() -> None:
    assert isinstance(provider(), PaperProvider)


def test_search_returns_only_the_usable_works() -> None:
    records, _ = provider().search(PaperQuery(limit=25))
    # Four works in the fixture: one has no abstract, so three survive parsing.
    assert len(records) == 3


def test_search_filters_to_the_requested_fields() -> None:
    records, _ = provider().search(PaperQuery(field_ids=("cond-mat",), limit=25))
    assert [r.primary_field_id for r in records] == ["cond-mat"]


def test_search_honours_exclusions() -> None:
    records, _ = provider().search(
        PaperQuery(limit=25, exclude_canonical_ids=frozenset({"doi:10.1103/physrevb.109.045139"}))
    )
    assert "doi:10.1103/physrevb.109.045139" not in {r.canonical_id for r in records}


def test_search_asks_only_for_works_that_have_an_abstract() -> None:
    transport = StubTransport(HttpResponse(200, PAYLOAD_TEXT))
    OpenAlexPaperProvider(transport=transport, min_interval_seconds=0.0).search(
        PaperQuery(limit=25)
    )
    assert "has_abstract:true" in transport.calls[0]["params"]["filter"]


def test_the_polite_pool_address_is_sent_when_configured() -> None:
    transport = StubTransport(HttpResponse(200, PAYLOAD_TEXT))
    OpenAlexPaperProvider(
        transport=transport, min_interval_seconds=0.0, mailto="ops@example.org"
    ).search(PaperQuery(limit=5))
    assert transport.calls[0]["params"]["mailto"] == "ops@example.org"


def test_paging_uses_the_opaque_cursor() -> None:
    _, cursor = provider().search(PaperQuery(limit=25))
    assert cursor == PAYLOAD["meta"]["next_cursor"]


def test_a_repeated_cursor_ends_paging_rather_than_looping() -> None:
    """OpenAlex repeats the last cursor at the end of a result set."""
    repeated = PAYLOAD["meta"]["next_cursor"]
    _, cursor = provider().search(PaperQuery(limit=25, cursor=repeated))
    assert cursor is None


def test_unparseable_json_is_reported_as_provider_unavailable() -> None:
    with pytest.raises(ProviderUnavailable, match="unparseable JSON"):
        provider(HttpResponse(200, "not json")).search(PaperQuery(limit=5))


def test_a_rejected_request_is_reported_by_its_status_not_as_bad_json() -> None:
    """A 4xx body is not a works response.

    The client returns 4xx without opening the breaker, so the provider has to check the
    status itself — otherwise "OpenAlex rejected the filter" is reported as "unparseable
    JSON", and whoever debugs it next opens the parser instead of the query.
    """
    with pytest.raises(ProviderUnavailable, match="HTTP 400"):
        provider(HttpResponse(400, "Invalid query parameters")).search(PaperQuery(limit=5))


def test_lookup_by_doi_uses_the_doi_url_form() -> None:
    single = json.dumps(WORKS[0])
    transport = StubTransport(HttpResponse(200, single))
    openalex = OpenAlexPaperProvider(transport=transport, min_interval_seconds=0.0)

    record = openalex.get_by_canonical_id("doi:10.1103/physrevb.109.045139")
    assert record is not None
    assert transport.calls[0]["url"].endswith("/https://doi.org/10.1103/physrevb.109.045139")


def test_lookup_by_an_arxiv_id_says_not_mine() -> None:
    assert provider().get_by_canonical_id("arxiv:2511.08822") is None


def test_a_lookup_that_finds_nothing_is_not_a_failure() -> None:
    """404 on a single-work lookup means "no such work", which is an answer."""
    assert provider(HttpResponse(404, "")).get_by_canonical_id("openalex:W1") is None


def test_a_lookup_rejected_for_any_other_reason_is_raised() -> None:
    with pytest.raises(ProviderUnavailable, match="HTTP 400"):
        provider(HttpResponse(400, "bad id")).get_by_canonical_id("openalex:W1")


# ---------------------------------------------------------------------------- health


def test_health_reports_an_open_circuit() -> None:
    openalex = provider(HttpResponse(500, ""))
    for _ in range(4):
        with pytest.raises(ProviderUnavailable):
            openalex.search(PaperQuery(limit=1))

    health = openalex.health()
    assert health.healthy is False
    assert "circuit open" in (health.detail or "")


# ------------------------------------------------------------------------ live check


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("PAPERMATCH_LIVE_PROVIDERS") != "1",
    reason="reaches the real OpenAlex API; set PAPERMATCH_LIVE_PROVIDERS=1 to run",
)
def test_live_openalex_returns_parseable_records() -> None:
    records, _ = OpenAlexPaperProvider(mailto=os.environ.get("PAPERMATCH_OPENALEX_MAILTO")).search(
        PaperQuery(limit=5)
    )
    assert records, "OpenAlex returned no usable records"
    for record in records:
        assert record.title and record.abstract
        assert record.canonical_id.startswith(("doi:", "arxiv:", "openalex:"))
