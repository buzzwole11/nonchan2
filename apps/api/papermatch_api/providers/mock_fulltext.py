"""Fixture-backed :class:`FullTextProvider` (spec section 12).

The real source for this is arXiv's e-print endpoint, which this environment cannot reach
(D-024/D-016), so the pipeline is built against recorded-shape LaTeX exactly as the paper
providers were. The fixtures are synthetic; their structure follows public LaTeX
conventions and `fixtures/fulltext/README.md` says so.

**The manifest carries the body's licence, and one entry is deliberately refused.** A
provider that only ever returns permitted documents cannot demonstrate that the gate
works, and the gate is the part of this feature that matters legally rather than
technically.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from papermatch_api.providers.base import (
    FullTextRecord,
    ProviderHealth,
)


class MockFullTextProvider:
    """Serves ``fixtures/fulltext/`` and nothing else."""

    name = "mock_fulltext"

    def __init__(self, fixtures_dir: Path) -> None:
        self._dir = Path(fixtures_dir) / "fulltext"
        self._entries: dict[str, dict[str, Any]] = {}
        manifest = self._dir / "manifest.json"
        if manifest.exists():
            raw = json.loads(manifest.read_text(encoding="utf-8"))
            for entry in raw.get("documents", ()):
                canonical = entry.get("canonicalId")
                if canonical:
                    self._entries[canonical] = entry

    def fetch_source(self, canonical_id: str) -> FullTextRecord | None:
        entry = self._entries.get(canonical_id)
        if entry is None:
            return None
        path = self._dir / str(entry.get("file", ""))
        if not path.exists():
            return None
        return FullTextRecord(
            canonical_id=canonical_id,
            body_format=entry.get("bodyFormat", "latex"),
            body=path.read_text(encoding="utf-8"),
            # Straight from the manifest, including `null`. A provider that substituted a
            # default here would be inventing permission.
            license_id=entry.get("licenseId"),
            license_url=entry.get("licenseUrl"),
            source_url=entry.get("sourceUrl", ""),
            retrieved_at=datetime.now(tz=UTC),
            version=entry.get("version"),
            raw_metadata=dict(entry),
        )

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            healthy=self._dir.exists(),
            detail=None if self._dir.exists() else f"missing fixtures at {self._dir}",
            checked_at=datetime.now(tz=UTC),
        )
