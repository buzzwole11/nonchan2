"""Ingestion of provider records into the database (spec sections 16, 21, 25).

Three properties this code has to hold, all of them checked by tests:

* **Idempotent.** Running ingestion twice must not create a second copy of anything
  (spec section 25: 冪等な取り込みとジョブ).
* **Deduplicating.** Records that resolve to the same canonical id are merged, and their
  identifiers are all kept so a later lookup by any of them still finds the one row
  (spec section 16).
* **Auditable.** Every run writes an ``audit_log`` entry, including how many records were
  merged and how many were rejected for missing licence terms (spec section 0).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import (
    AbstractSegment,
    AuditLog,
    Field,
    Paper,
    PaperField,
    PaperIdentifier,
)
from papermatch_api.providers.base import PaperProvider, PaperQuery, PaperRecord
from papermatch_api.services.embeddings import store_paper_embedding
from papermatch_api.services.structure import classify
from papermatch_api.text.dedup import compute_identity
from papermatch_api.text.normalize import normalize_title


@dataclass
class IngestionReport:
    inserted: int = 0
    updated: int = 0
    merged_duplicates: int = 0
    skipped_unlicensed: int = 0

    @property
    def total_seen(self) -> int:
        return self.inserted + self.updated + self.merged_duplicates + self.skipped_unlicensed


def load_fields(session: Session, fixtures_dir: Path) -> int:
    """Upsert the field taxonomy. Safe to run on every startup."""
    path = Path(fixtures_dir) / "fields.json"
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)

    count = 0
    # Parents first: `parent_id` is a self-referencing foreign key.
    entries = sorted(document["fields"], key=lambda f: (f.get("parentId") is not None, f["id"]))
    for entry in entries:
        existing = session.get(Field, entry["id"])
        if existing is None:
            session.add(
                Field(
                    id=entry["id"],
                    parent_id=entry.get("parentId"),
                    label_en=entry["label"]["en"],
                    label_ja=entry["label"]["ja"],
                    color=entry.get("color", "#667085"),
                )
            )
        else:
            existing.parent_id = entry.get("parentId")
            existing.label_en = entry["label"]["en"]
            existing.label_ja = entry["label"]["ja"]
            existing.color = entry.get("color", existing.color)
        count += 1
    session.flush()
    return count


def _identifier_owner(session: Session, kind: str, value: str) -> Paper | None:
    row = session.execute(
        select(PaperIdentifier).where(PaperIdentifier.kind == kind, PaperIdentifier.value == value)
    ).scalar_one_or_none()
    return session.get(Paper, row.paper_id) if row is not None else None


def _find_existing(session: Session, record: PaperRecord) -> Paper | None:
    """Locate an already-stored paper by canonical id or by any of its identifiers.

    Looking at every identifier — not just the canonical one — is what makes an arXiv
    preprint and its later published DOI collapse into a single row instead of two cards.
    """
    by_canonical = session.execute(
        select(Paper).where(Paper.canonical_id == record.canonical_id)
    ).scalar_one_or_none()
    if by_canonical is not None:
        return by_canonical

    identity = compute_identity(
        {
            "identifiers": [dict(i) for i in record.identifiers],
            "title": record.title,
            "authors": [dict(a) for a in record.authors],
            "year": record.year,
        }
    )
    for key in identity.all_keys:
        kind, _, value = key.partition(":")
        owner = _identifier_owner(session, kind, value)
        if owner is not None:
            return owner
    return None


def _apply_identifiers(session: Session, paper: Paper, record: PaperRecord) -> None:
    existing = {(i.kind, i.value) for i in paper.identifiers}
    identity = compute_identity(
        {
            "identifiers": [dict(i) for i in record.identifiers],
            "title": record.title,
            "authors": [dict(a) for a in record.authors],
            "year": record.year,
        }
    )
    for key in sorted(identity.all_keys):
        kind, _, value = key.partition(":")
        if (kind, value) in existing:
            continue
        # Another paper may already own this identifier if the source data is
        # contradictory; leave that alone and log rather than stealing it.
        if _identifier_owner(session, kind, value) is not None:
            continue
        session.add(PaperIdentifier(paper_id=paper.id, kind=kind, value=value))
        existing.add((kind, value))


def _apply_field_weights(session: Session, paper: Paper, record: PaperRecord) -> None:
    known = {row.id for row in session.execute(select(Field)).scalars()}
    current = {row.field_id: row for row in paper.field_weights}
    for field_id, weight in record.field_weights.items():
        if field_id not in known:
            continue
        if field_id in current:
            current[field_id].weight = float(weight)
        else:
            session.add(PaperField(paper_id=paper.id, field_id=field_id, weight=float(weight)))


def _apply_segments(session: Session, paper: Paper, raw: dict[str, Any]) -> None:
    """Store the abstract's structure, from the source when it has one.

    A provider that publishes structured abstracts (some journals do) is authoritative;
    everything else goes through the heuristic classifier, which labels its output
    ``heuristic`` so a reader can tell the difference (spec section 8).
    """
    existing = (
        session.execute(select(AbstractSegment).where(AbstractSegment.paper_id == paper.id))
        .scalars()
        .all()
    )
    if existing:
        return

    segments = raw.get("abstractSegments") or []
    if segments:
        for segment in segments:
            session.add(
                AbstractSegment(
                    paper_id=paper.id,
                    start_offset=int(segment["start"]),
                    end_offset=int(segment["end"]),
                    section=segment["section"],
                    detected_by=segment.get("detectedBy", "source"),
                    confidence=float(segment.get("confidence", 0.0)),
                )
            )
        return

    for detected in classify(paper.abstract):
        session.add(
            AbstractSegment(
                paper_id=paper.id,
                start_offset=detected.start,
                end_offset=detected.end,
                section=detected.section,
                detected_by=detected.detected_by,
                confidence=detected.confidence,
            )
        )


def upsert_record(session: Session, record: PaperRecord) -> tuple[Paper, str]:
    """Insert or update one record.

    Returns the row and one of ``"inserted"``, ``"updated"`` or ``"merged"``.
    """
    existing = _find_existing(session, record)
    outcome = "inserted"

    if existing is None:
        paper = Paper(
            canonical_id=record.canonical_id,
            title=record.title,
            normalized_title=normalize_title(record.title),
            abstract=record.abstract,
            authors=[dict(a) for a in record.authors],
            year=record.year,
            venue=record.venue,
            paper_types=list(record.paper_types),
            primary_field_id=record.primary_field_id,
            open_access=record.open_access,
            retraction_status=record.retraction_status,
            version=record.version,
            english_level=record.raw.get("englishLevel", "intermediate"),
            math_density=float(record.raw.get("mathDensity", 0.0)),
            equation_count=int(record.raw.get("equationCount", 0)),
            estimated_reading_minutes=float(record.raw.get("estimatedReadingMinutes", 1.0)),
            source_provider=record.source_provider,
            source_url=record.source_url,
            pdf_url=record.pdf_url,
            acquired_at=record.acquired_at,
            license_id=record.license_id,
            license_url=record.license_url,
            abstract_redistributable=record.abstract_redistributable,
            cache_policy="full_cache" if record.abstract_redistributable else "metadata_only",
            raw_metadata=record.raw,
        )
        session.add(paper)
        session.flush()
    else:
        paper = existing
        outcome = "updated" if paper.canonical_id == record.canonical_id else "merged"
        # A published record supersedes a preprint; a later arXiv version supersedes an
        # earlier one. Otherwise keep what is already stored rather than churning it.
        incoming_is_newer = (
            "published" in record.paper_types and "published" not in (paper.paper_types or [])
        ) or ((record.version or "") > (paper.version or ""))
        if incoming_is_newer:
            paper.canonical_id = record.canonical_id
            paper.title = record.title
            paper.normalized_title = normalize_title(record.title)
            paper.abstract = record.abstract
            paper.venue = record.venue
            paper.paper_types = list(record.paper_types)
            paper.open_access = record.open_access
            paper.version = record.version
            paper.source_url = record.source_url
            paper.pdf_url = record.pdf_url
        paper.retraction_status = record.retraction_status
        paper.acquired_at = record.acquired_at

    _apply_identifiers(session, paper, record)
    _apply_field_weights(session, paper, record)
    _apply_segments(session, paper, record.raw)
    session.flush()
    # After the flush, because the vector is keyed on the paper's id. Embedding at
    # ingestion rather than at feed time is what keeps the feed a read: computing 500
    # vectors while someone waits for their next card is not a trade worth making.
    store_paper_embedding(session, paper)
    session.flush()
    return paper, outcome


def ingest(
    session: Session,
    provider: PaperProvider,
    *,
    query: PaperQuery | None = None,
    max_records: int = 500,
) -> IngestionReport:
    """Pull records from a provider and store them.

    Records whose terms do not permit storing the abstract are counted and skipped rather
    than stored with the text stripped: a card with no abstract is not something the
    Discover feed can show, and keeping the row would only invite it to leak later
    (spec section 21).
    """
    report = IngestionReport()
    cursor: str | None = query.cursor if query else None
    base = query or PaperQuery(limit=50)
    seen = 0

    while seen < max_records:
        page_query = PaperQuery(
            field_ids=base.field_ids,
            limit=min(base.limit, max_records - seen),
            cursor=cursor,
            year_from=base.year_from,
            year_to=base.year_to,
            exclude_canonical_ids=base.exclude_canonical_ids,
            include_types=base.include_types,
        )
        records, cursor = provider.search(page_query)
        if not records:
            break
        for record in records:
            seen += 1
            if not record.abstract_redistributable:
                report.skipped_unlicensed += 1
                continue
            _, outcome = upsert_record(session, record)
            if outcome == "inserted":
                report.inserted += 1
            elif outcome == "updated":
                report.updated += 1
            else:
                report.merged_duplicates += 1
        if cursor is None:
            break

    session.add(
        AuditLog(
            kind="ingestion",
            actor=f"provider:{getattr(provider, 'name', 'unknown')}",
            entity_type="paper",
            entity_id=None,
            detail={
                "inserted": report.inserted,
                "updated": report.updated,
                "mergedDuplicates": report.merged_duplicates,
                "skippedUnlicensed": report.skipped_unlicensed,
                "ranAt": datetime.now(tz=UTC).isoformat(),
            },
        )
    )
    session.flush()
    return report
