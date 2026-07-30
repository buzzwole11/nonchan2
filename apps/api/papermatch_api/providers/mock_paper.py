"""Fixture-backed :class:`PaperProvider` (spec section 31, item 3).

Serves the synthetic corpus in ``fixtures/papers.sample.json``. This is not only a test
double: it is the offline fallback the app uses when the real providers are unreachable
(spec section 25), so it implements the same filtering and cursor semantics that the
arXiv and OpenAlex providers will in Phase 1.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from papermatch_api.providers.base import (
    PaperProvider,
    PaperQuery,
    PaperRecord,
    ProviderHealth,
)
from papermatch_api.text.dedup import compute_identity


def _parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=UTC)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(tz=UTC)


def _to_record(raw: dict[str, Any]) -> PaperRecord:
    provenance = raw.get("provenance") or {}
    identity = compute_identity(raw)
    return PaperRecord(
        canonical_id=identity.canonical_id,
        title=(raw.get("title") or "").strip(),
        abstract=raw.get("abstract") or "",
        authors=tuple(raw.get("authors") or ()),
        year=int(raw.get("year") or 0),
        identifiers=tuple(raw.get("identifiers") or ()),
        source_provider=provenance.get("sourceProvider", "mock"),
        source_url=provenance.get("sourceUrl") or raw.get("sourceUrl") or "",
        acquired_at=_parse_iso(provenance.get("acquiredAt")),
        license_id=provenance.get("licenseId"),
        license_url=provenance.get("licenseUrl"),
        abstract_redistributable=bool(provenance.get("abstractRedistributable", False)),
        venue=raw.get("venue"),
        primary_field_id=raw.get("primaryFieldId"),
        field_weights=dict(raw.get("fieldWeights") or {}),
        paper_types=tuple(raw.get("paperTypes") or ()),
        open_access=raw.get("openAccess") or "unknown",
        retraction_status=raw.get("retractionStatus") or "none",
        version=raw.get("version"),
        pdf_url=raw.get("pdfUrl"),
        raw=raw,
    )


class MockPaperProvider(PaperProvider):
    """Reads the committed sample corpus.

    ``include_duplicate_variants`` exists so tests can feed the deliberately duplicated
    records through the ingestion path and assert that they collapse. The feed never
    turns it on.
    """

    name = "mock"

    def __init__(
        self,
        fixtures_dir: Path,
        *,
        include_duplicate_variants: bool = False,
    ) -> None:
        self._fixtures_dir = Path(fixtures_dir)
        self._include_duplicate_variants = include_duplicate_variants
        self._records: list[PaperRecord] | None = None
        self._load_error: str | None = None

    # -- loading ---------------------------------------------------------------

    @property
    def _path(self) -> Path:
        return self._fixtures_dir / "papers.sample.json"

    def _load(self) -> list[PaperRecord]:
        if self._records is not None:
            return self._records
        try:
            with self._path.open(encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            self._load_error = f"{type(exc).__name__}: {exc}"
            self._records = []
            return self._records

        raw_records: list[dict[str, Any]] = list(document.get("papers") or [])
        if self._include_duplicate_variants:
            raw_records.extend(document.get("duplicateVariants") or [])

        self._records = [_to_record(raw) for raw in raw_records]
        self._load_error = None
        return self._records

    # -- PaperProvider ---------------------------------------------------------

    def search(self, query: PaperQuery) -> tuple[list[PaperRecord], str | None]:
        records = self._load()

        def matches(record: PaperRecord) -> bool:
            if record.canonical_id in query.exclude_canonical_ids:
                return False
            if query.field_ids:
                wanted = set(query.field_ids)
                present = set(record.field_weights) | (
                    {record.primary_field_id} if record.primary_field_id else set()
                )
                if not (wanted & present):
                    return False
            if query.year_from is not None and record.year < query.year_from:
                return False
            if query.year_to is not None and record.year > query.year_to:
                return False
            return not (
                query.include_types and not (set(query.include_types) & set(record.paper_types))
            )

        filtered = [r for r in records if matches(r)]

        offset = 0
        if query.cursor:
            try:
                offset = max(0, int(query.cursor))
            except ValueError:
                offset = 0

        limit = max(1, min(query.limit, 100))
        page = filtered[offset : offset + limit]
        next_cursor = str(offset + limit) if offset + limit < len(filtered) else None
        return page, next_cursor

    def get_by_canonical_id(self, canonical_id: str) -> PaperRecord | None:
        for record in self._load():
            if record.canonical_id == canonical_id:
                return record
        return None

    def health(self) -> ProviderHealth:
        records = self._load()
        if self._load_error is not None:
            return ProviderHealth(
                name=self.name,
                healthy=False,
                detail=f"could not read {self._path}: {self._load_error}",
                checked_at=datetime.now(tz=UTC),
            )
        return ProviderHealth(
            name=self.name,
            healthy=len(records) > 0,
            detail=f"{len(records)} fixture records",
            checked_at=datetime.now(tz=UTC),
        )
