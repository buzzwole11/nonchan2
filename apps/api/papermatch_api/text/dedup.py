"""Canonical identity and duplicate collapsing (spec section 16).

The MVP completion criterion is blunt: 同一DOI/arXivの重複カードが出ない — the same work
must never appear twice in the feed. That is enforced here, by reducing every incoming
record to a canonical id and a set of alternate keys, then merging records that share any
key.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from papermatch_api.text.normalize import (
    normalize_arxiv_id,
    normalize_doi,
    title_author_year_key,
)

__all__ = ["IdentityKeys", "compute_identity", "dedupe_records", "merge_group"]


@dataclass(frozen=True)
class IdentityKeys:
    """All keys under which a record may be recognised.

    ``canonical_id`` is the single stable name for the work; ``all_keys`` is everything
    the record can be matched on, so a later record carrying only one of them still
    merges into the same group.
    """

    canonical_id: str
    doi: str | None = None
    arxiv_id: str | None = None
    semantic_scholar_id: str | None = None
    openalex_id: str | None = None
    fallback_key: str | None = None
    all_keys: frozenset[str] = field(default_factory=frozenset)


def _identifier_map(identifiers: Iterable[dict[str, str]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for entry in identifiers:
        kind = entry.get("kind")
        value = entry.get("value")
        if not kind or not value:
            continue
        grouped.setdefault(kind, []).append(value)
    return grouped


def compute_identity(record: dict[str, Any]) -> IdentityKeys:
    """Derive the canonical id for a paper record.

    Precedence is DOI → arXiv → Semantic Scholar → OpenAlex → normalised
    title+author+year, exactly as listed in spec section 16. A record with no usable
    identifier at all still gets the fallback key, because dropping it silently would
    lose a paper.
    """
    identifiers = record.get("identifiers") or []
    grouped = _identifier_map(identifiers)

    doi = next(
        (d for d in (normalize_doi(v) for v in grouped.get("doi", [])) if d is not None),
        None,
    )
    arxiv = next(
        (a for a in (normalize_arxiv_id(v) for v in grouped.get("arxiv", [])) if a is not None),
        None,
    )
    s2 = next((v.strip() for v in grouped.get("semantic_scholar", []) if v.strip()), None)
    openalex = next((v.strip() for v in grouped.get("openalex", []) if v.strip()), None)

    authors = record.get("authors") or []
    first_author: str | None = None
    if isinstance(authors, Sequence) and authors:
        head = authors[0]
        if isinstance(head, dict):
            name = head.get("name")
            first_author = name if isinstance(name, str) else None
        elif isinstance(head, str):
            first_author = head

    title = record.get("title")
    year = record.get("year")
    fallback = title_author_year_key(
        title if isinstance(title, str) else "",
        first_author,
        year if isinstance(year, int) else None,
    )

    keys: set[str] = set()
    # A record may carry a title_author_year key computed elsewhere — by our own storage,
    # or by a provider that already resolved it. Honour it in addition to the one derived
    # here, so a record whose title was reformatted still matches its earlier self.
    for supplied in grouped.get("title_author_year", []):
        cleaned = supplied.strip().lower()
        if cleaned:
            keys.add(f"title_author_year:{cleaned}")
    if doi:
        keys.add(f"doi:{doi}")
    if arxiv:
        keys.add(f"arxiv:{arxiv}")
    if s2:
        keys.add(f"semantic_scholar:{s2}")
    if openalex:
        keys.add(f"openalex:{openalex}")
    keys.add(f"title_author_year:{fallback}")

    if doi:
        canonical = f"doi:{doi}"
    elif arxiv:
        canonical = f"arxiv:{arxiv}"
    elif s2:
        canonical = f"semantic_scholar:{s2}"
    elif openalex:
        canonical = f"openalex:{openalex}"
    else:
        canonical = f"title_author_year:{fallback}"

    return IdentityKeys(
        canonical_id=canonical,
        doi=doi,
        arxiv_id=arxiv,
        semantic_scholar_id=s2,
        openalex_id=openalex,
        fallback_key=fallback,
        all_keys=frozenset(keys),
    )


def _version_sort_key(record: dict[str, Any]) -> tuple[int, str]:
    """Later arXiv versions and published records sort last, so they win a merge."""
    version = record.get("version")
    numeric = 0
    if isinstance(version, str) and version.lower().startswith("v") and version[1:].isdigit():
        numeric = int(version[1:])
    types = record.get("paperTypes") or []
    published_bonus = 100 if isinstance(types, list) and "published" in types else 0
    acquired = record.get("provenance")
    acquired_at = ""
    if isinstance(acquired, dict):
        value = acquired.get("acquiredAt")
        acquired_at = value if isinstance(value, str) else ""
    return (numeric + published_bonus, acquired_at)


def merge_group(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Merge duplicate records of one work into a single record.

    The most authoritative record wins the scalar fields (published beats preprint, a
    later arXiv version beats an earlier one), while identifiers from every member are
    unioned so future lookups by any of them still resolve. The provenance of the
    superseded records is retained under ``mergedFrom`` — the spec requires the source of
    every field to stay traceable (section 21), so a merge must not erase history.
    """
    if not records:
        raise ValueError("merge_group requires at least one record")

    ordered = sorted(records, key=_version_sort_key)
    winner = dict(ordered[-1])

    seen: set[tuple[str, str]] = set()
    merged_identifiers: list[dict[str, str]] = []
    for record in ordered:
        for entry in record.get("identifiers") or []:
            if not isinstance(entry, dict):
                continue
            kind, value = entry.get("kind"), entry.get("value")
            if not kind or not value:
                continue
            key = (kind, value)
            if key in seen:
                continue
            seen.add(key)
            merged_identifiers.append({"kind": kind, "value": value})
    winner["identifiers"] = merged_identifiers

    identity = compute_identity(winner)
    winner["canonicalId"] = identity.canonical_id

    superseded = [r for r in ordered if r is not ordered[-1]]
    if superseded:
        winner["mergedFrom"] = [
            {
                "id": r.get("id"),
                "canonicalId": r.get("canonicalId"),
                "version": r.get("version"),
                "sourceProvider": (r.get("provenance") or {}).get("sourceProvider")
                if isinstance(r.get("provenance"), dict)
                else None,
            }
            for r in superseded
        ]
    return winner


def dedupe_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicates across a batch, preserving first-seen order.

    Uses union-find over the identity keys so a chain — arXiv v1 shares an id with v2,
    and v2 shares a title key with the published version — collapses into one group even
    though v1 and the published record have no key in common.
    """
    materialised = list(records)
    parent: dict[int, int] = {i: i for i in range(len(materialised))}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    key_owner: dict[str, int] = {}
    identities = [compute_identity(record) for record in materialised]
    for index, identity in enumerate(identities):
        for key in identity.all_keys:
            if key in key_owner:
                union(key_owner[key], index)
            else:
                key_owner[key] = index

    groups: dict[int, list[dict[str, Any]]] = {}
    order: list[int] = []
    for index, record in enumerate(materialised):
        root = find(index)
        if root not in groups:
            groups[root] = []
            order.append(root)
        groups[root].append(record)

    return [merge_group(groups[root]) for root in order]
