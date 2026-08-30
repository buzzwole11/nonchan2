"""Unit tests for canonical identity and duplicate collapsing (spec sections 16, 30)."""

from __future__ import annotations

from typing import Any

from papermatch_api.text.dedup import compute_identity, dedupe_records, merge_group


def record(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "r1",
        "title": "Holographic Entanglement in Deformed Conformal Backgrounds",
        "authors": [{"name": "K. Aoki"}, {"name": "B. Novak"}],
        "year": 2024,
        "identifiers": [],
        "version": "v1",
        "paperTypes": ["preprint"],
        "provenance": {"sourceProvider": "arxiv", "acquiredAt": "2024-01-01T00:00:00Z"},
    }
    base.update(overrides)
    return base


def test_doi_wins_the_canonical_id() -> None:
    identity = compute_identity(
        record(
            identifiers=[
                {"kind": "arxiv", "value": "arXiv:2401.01234"},
                {"kind": "doi", "value": "https://doi.org/10.1103/PhysRevD.109.045002"},
                {"kind": "openalex", "value": "W123"},
            ]
        )
    )
    assert identity.canonical_id == "doi:10.1103/physrevd.109.045002"


def test_precedence_falls_through_to_title_author_year() -> None:
    assert compute_identity(record()).canonical_id.startswith("title_author_year:")


def test_all_keys_include_every_identifier_so_later_lookups_still_match() -> None:
    identity = compute_identity(
        record(
            identifiers=[
                {"kind": "doi", "value": "10.1103/x.1"},
                {"kind": "arxiv", "value": "2401.01234v2"},
            ]
        )
    )
    assert "doi:10.1103/x.1" in identity.all_keys
    assert "arxiv:2401.01234" in identity.all_keys
    assert any(k.startswith("title_author_year:") for k in identity.all_keys)


def test_same_doi_written_differently_is_one_paper() -> None:
    merged = dedupe_records(
        [
            record(id="a", identifiers=[{"kind": "doi", "value": "10.1103/PhysRevD.109.045002"}]),
            record(
                id="b",
                identifiers=[
                    {"kind": "doi", "value": "https://doi.org/10.1103/PHYSREVD.109.045002"}
                ],
            ),
        ]
    )
    assert len(merged) == 1


def test_arxiv_versions_collapse_and_the_later_version_wins() -> None:
    merged = dedupe_records(
        [
            record(id="v1", version="v1", identifiers=[{"kind": "arxiv", "value": "2401.01234v1"}]),
            record(id="v2", version="v2", identifiers=[{"kind": "arxiv", "value": "2401.01234v2"}]),
        ]
    )
    assert len(merged) == 1
    assert merged[0]["version"] == "v2"
    assert merged[0]["mergedFrom"][0]["version"] == "v1"


def test_published_version_supersedes_the_preprint() -> None:
    preprint = record(
        id="pre",
        identifiers=[{"kind": "arxiv", "value": "2401.01234"}],
        paperTypes=["preprint"],
    )
    published = record(
        id="pub",
        identifiers=[{"kind": "doi", "value": "10.1103/x.1"}],
        paperTypes=["published"],
        venue="Physical Review D",
    )
    merged = dedupe_records([preprint, published])
    assert len(merged) == 1, "preprint and published version share a title/author/year key"
    assert merged[0]["venue"] == "Physical Review D"
    assert merged[0]["canonicalId"] == "doi:10.1103/x.1"
    kinds = {i["kind"] for i in merged[0]["identifiers"]}
    assert {"doi", "arxiv"} <= kinds, "identifiers from both records must survive the merge"


def test_transitive_duplicates_collapse_into_one_group() -> None:
    """v1 and the published record share no key directly — only through v2."""
    a = record(id="a", version="v1", identifiers=[{"kind": "arxiv", "value": "2401.01234v1"}])
    b = record(
        id="b",
        version="v2",
        identifiers=[
            {"kind": "arxiv", "value": "2401.01234v2"},
            {"kind": "doi", "value": "10.1103/x.1"},
        ],
    )
    c = record(
        id="c",
        title="A Completely Different Title",
        authors=[{"name": "Z. Zubkov"}],
        identifiers=[{"kind": "doi", "value": "10.1103/x.1"}],
    )
    merged = dedupe_records([a, b, c])
    assert len(merged) == 1


def test_distinct_papers_are_not_merged() -> None:
    merged = dedupe_records(
        [
            record(id="a", identifiers=[{"kind": "doi", "value": "10.1103/a"}]),
            record(
                id="b",
                title="Something Else Entirely",
                authors=[{"name": "M. Xu"}],
                identifiers=[{"kind": "doi", "value": "10.1103/b"}],
            ),
        ]
    )
    assert len(merged) == 2


def test_dedupe_preserves_first_seen_order() -> None:
    records = [
        record(id="1", title="Alpha", identifiers=[{"kind": "doi", "value": "10.1/a"}]),
        record(id="2", title="Beta", identifiers=[{"kind": "doi", "value": "10.1/b"}]),
        record(id="3", title="Alpha", identifiers=[{"kind": "doi", "value": "10.1/a"}]),
    ]
    merged = dedupe_records(records)
    assert [m["title"] for m in merged] == ["Alpha", "Beta"]


def test_merge_group_keeps_the_superseded_provenance() -> None:
    merged = merge_group(
        [
            record(id="old", version="v1"),
            record(id="new", version="v2"),
        ]
    )
    assert merged["id"] == "new"
    assert [m["id"] for m in merged["mergedFrom"]] == ["old"]
    assert merged["mergedFrom"][0]["sourceProvider"] == "arxiv"


def test_records_with_no_identifier_at_all_are_still_kept() -> None:
    merged = dedupe_records([record(id="x", identifiers=[], title="Untitled Draft")])
    assert len(merged) == 1
    assert merged[0]["canonicalId"].startswith("title_author_year:")
