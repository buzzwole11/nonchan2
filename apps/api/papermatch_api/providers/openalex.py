"""OpenAlex metadata provider (spec section 21).

Reads the OpenAlex works API: https://developers.openalex.org/api-reference/introduction

Two things about OpenAlex shape this module:

* **Abstracts arrive as an inverted index**, not as text. ``abstract_inverted_index`` maps
  each word to the positions it occupies, and the abstract has to be rebuilt from it. The
  reconstruction is lossy in one specific way — the original whitespace and any markup are
  gone — so what comes back is a faithful *word sequence* rather than a byte-exact copy of
  the publisher's abstract. That matters here because spec section 7 anchors translations
  to character offsets, and those offsets are into our reconstruction, not into anything
  we could compare against a publisher's page.
* **Licence varies per work.** Unlike arXiv, OpenAlex reports the open-access licence of
  each work, so that is used when present. The OpenAlex *dataset* is CC0, which is what
  lets us store the metadata at all; the per-work licence is what the reader is told.
  A work with no licence we can name is stored with ``license_id=None`` and
  ``abstract_redistributable=False``, which makes ingestion skip it (spec section 21).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from papermatch_api.providers.base import (
    PaperProvider,
    PaperQuery,
    PaperRecord,
    ProviderHealth,
    ProviderUnavailable,
)
from papermatch_api.providers.http import (
    DEFAULT_USER_AGENT,
    CircuitBreaker,
    HttpProviderClient,
    HttpxTransport,
    RateLimiter,
    Transport,
)
from papermatch_api.text.normalize import normalize_arxiv_id, normalize_doi

API_URL = "https://api.openalex.org/works"

#: OpenAlex allows 10 requests/second in the polite pool; one every 200ms is well inside
#: it and keeps us off their radar (spec section 27: 同一ソースへの過剰APIアクセス).
MIN_REQUEST_INTERVAL_SECONDS = 0.2

SOURCE_TERMS_URL = "https://docs.openalex.org/additional-help/faq"

#: The dataset licence, which is what permits storing the metadata. Per-work licences
#: override this for what the reader is shown.
DATASET_LICENSE = "CC0-1.0"

#: OpenAlex concept / topic ids are not stable enough to map directly, so the mapping goes
#: through the primary topic's field name, which is.
FIELD_NAME_MAP: dict[str, str] = {
    "particle and high energy physics": "hep-th",
    "nuclear and high energy physics": "hep-th",
    "condensed matter physics": "cond-mat",
    "materials science": "cond-mat",
    "atomic and molecular physics, and optics": "quant-ph",
    "quantum information": "quant-ph",
    "astronomy and astrophysics": "astro-ph",
    "space and planetary science": "astro-ph",
    "analysis": "math.AP",
    "applied mathematics": "math.AP",
    "discrete mathematics and combinatorics": "math.CO",
    "algebra and number theory": "math.NT",
    "statistics and probability": "math.PR",
    "artificial intelligence": "cs.LG",
    "machine learning": "cs.LG",
    "computational theory and mathematics": "cs.DS",
    "theoretical computer science": "cs.DS",
    "computational linguistics": "cs.CL",
    "language and linguistics": "cs.CL",
    "computer security and cryptography": "cs.CR",
    "safety, risk, reliability and quality": "cs.CR",
}

PARENT_OF: dict[str, str] = {
    "hep-th": "physics",
    "cond-mat": "physics",
    "quant-ph": "physics",
    "astro-ph": "physics",
    "math.AP": "math",
    "math.CO": "math",
    "math.NT": "math",
    "math.PR": "math",
    "cs.LG": "cs",
    "cs.DS": "cs",
    "cs.CL": "cs",
    "cs.CR": "cs",
}

#: OpenAlex `open_access.oa_status` values map straight onto ours.
OA_STATUS_MAP = {
    "gold": "gold",
    "green": "green",
    "hybrid": "hybrid",
    "bronze": "bronze",
    "closed": "closed",
    "diamond": "gold",
}

#: Licences we are willing to name. Anything else is recorded as unknown rather than
#: guessed at, which is what stops it being ingested (spec section 21).
KNOWN_LICENSES = {
    "cc0": "CC0-1.0",
    "cc-by": "CC-BY-4.0",
    "cc-by-sa": "CC-BY-SA-4.0",
    "cc-by-nc": "CC-BY-NC-4.0",
    "cc-by-nc-sa": "CC-BY-NC-SA-4.0",
    "cc-by-nc-nd": "CC-BY-NC-ND-4.0",
    "cc-by-nd": "CC-BY-ND-4.0",
    "public-domain": "CC0-1.0",
}


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    """Rebuild an abstract from OpenAlex's inverted index.

    The index maps a word to every position it appears at, so the abstract is recovered by
    placing each word at each of its positions and joining with single spaces. Gaps —
    positions no word claims — are dropped rather than filled with a placeholder: a hole
    in the middle of a sentence is better than an invented token, and it will be visible
    to a reader rather than silently plausible.
    """
    if not inverted_index:
        return ""

    positions: dict[int, str] = {}
    for word, indices in inverted_index.items():
        for index in indices:
            if isinstance(index, int) and index >= 0:
                positions[index] = word
    if not positions:
        return ""
    return " ".join(positions[index] for index in sorted(positions))


def _map_field(work: dict[str, Any]) -> str | None:
    topic = work.get("primary_topic") or {}
    field = (topic.get("field") or {}).get("display_name")
    if isinstance(field, str):
        mapped = FIELD_NAME_MAP.get(field.strip().lower())
        if mapped:
            return mapped
    subfield = (topic.get("subfield") or {}).get("display_name")
    if isinstance(subfield, str):
        return FIELD_NAME_MAP.get(subfield.strip().lower())
    return None


def _map_license(work: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return ``(license_id, license_url)`` for a work, or ``(None, None)``."""
    for location_key in ("best_oa_location", "primary_location"):
        location = work.get(location_key) or {}
        raw = location.get("license")
        if isinstance(raw, str) and raw.strip():
            mapped = KNOWN_LICENSES.get(raw.strip().lower())
            if mapped:
                return mapped, location.get("license_id") or None
            # A licence string we do not recognise is still information; record it as-is
            # so a human can decide, but do not claim it permits anything.
            return None, None
    return None, None


def _identifiers(work: dict[str, Any]) -> list[dict[str, str]]:
    identifiers: list[dict[str, str]] = []
    doi = normalize_doi(work.get("doi"))
    if doi:
        identifiers.append({"kind": "doi", "value": doi})

    openalex_id = work.get("id")
    if isinstance(openalex_id, str) and openalex_id:
        identifiers.append({"kind": "openalex", "value": openalex_id.rsplit("/", 1)[-1]})

    ids = work.get("ids") or {}
    mag_or_arxiv = ids.get("arxiv") if isinstance(ids, dict) else None
    arxiv = normalize_arxiv_id(mag_or_arxiv) if isinstance(mag_or_arxiv, str) else None
    if arxiv is None:
        # OpenAlex often exposes the arXiv id only through a landing-page URL.
        for location_key in ("best_oa_location", "primary_location"):
            location = work.get(location_key) or {}
            url = location.get("landing_page_url") or location.get("pdf_url")
            if isinstance(url, str) and "arxiv.org" in url:
                arxiv = normalize_arxiv_id(url)
                if arxiv:
                    break
    if arxiv:
        identifiers.append({"kind": "arxiv", "value": arxiv})
    return identifiers


def _year(work: dict[str, Any]) -> int:
    value = work.get("publication_year")
    if isinstance(value, int) and 1600 <= value <= 2200:
        return value
    published = work.get("publication_date")
    if isinstance(published, str):
        try:
            return date.fromisoformat(published).year
        except ValueError:
            pass
    return datetime.now(tz=UTC).year


def _english_level(words: list[str]) -> str:
    """A crude proxy: the share of long words. Same rule as the arXiv provider uses.

    Phase 2 replaces this with the calibrated estimator (spec section 11); until then a
    single shared heuristic keeps the two sources comparable to each other.
    """
    if not words:
        return "intermediate"
    long_words = sum(1 for w in words if len(re.sub(r"[^A-Za-z]", "", w)) >= 11)
    ratio = long_words / len(words)
    if ratio > 0.14:
        return "advanced"
    if ratio > 0.09:
        return "intermediate"
    return "beginner"


def parse_work(work: dict[str, Any]) -> PaperRecord | None:
    """Turn one OpenAlex work into a record, or ``None`` if it is unusable."""
    title = work.get("display_name") or work.get("title")
    if not isinstance(title, str) or not title.strip():
        return None

    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    if not abstract:
        # No abstract means no card. Spec section 6 makes the abstract the body of the
        # card; a title-only entry is not something Discover can show.
        return None

    identifiers = _identifiers(work)
    if not identifiers:
        return None

    doi = next((i["value"] for i in identifiers if i["kind"] == "doi"), None)
    arxiv = next((i["value"] for i in identifiers if i["kind"] == "arxiv"), None)
    openalex = next((i["value"] for i in identifiers if i["kind"] == "openalex"), None)
    canonical = f"doi:{doi}" if doi else f"arxiv:{arxiv}" if arxiv else f"openalex:{openalex}"

    authors: list[dict[str, Any]] = []
    for authorship in work.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") or {}
        name = author.get("display_name")
        if not isinstance(name, str) or not name.strip():
            continue
        institutions = authorship.get("institutions") or []
        affiliation = None
        if institutions and isinstance(institutions[0], dict):
            affiliation = institutions[0].get("display_name")
        authors.append(
            {"name": name, "externalId": author.get("orcid"), "affiliation": affiliation}
        )

    license_id, license_url = _map_license(work)

    primary_field = _map_field(work)
    field_weights: dict[str, float] = {}
    if primary_field:
        field_weights[primary_field] = 0.7
        parent = PARENT_OF.get(primary_field)
        if parent:
            field_weights[parent] = 0.2

    open_access = "unknown"
    oa = work.get("open_access") or {}
    if isinstance(oa, dict):
        open_access = OA_STATUS_MAP.get(str(oa.get("oa_status", "")).lower(), "unknown")

    retracted = bool(work.get("is_retracted"))
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    venue = source.get("display_name") if isinstance(source, dict) else None

    year = _year(work)
    paper_types = ["published"]
    if str(work.get("type", "")).lower() == "preprint":
        paper_types = ["preprint"]
    if datetime.now(tz=UTC).year - year >= 8:
        paper_types.append("classic")
    elif datetime.now(tz=UTC).year - year <= 1:
        paper_types.append("recent")

    words = abstract.split()
    english_level = _english_level(words)

    return PaperRecord(
        canonical_id=canonical,
        title=title.strip(),
        abstract=abstract,
        authors=tuple(authors),
        year=year,
        identifiers=tuple(identifiers),
        source_provider="openalex",
        source_url=(
            location.get("landing_page_url")
            or (f"https://doi.org/{doi}" if doi else "")
            or str(work.get("id", ""))
        ),
        acquired_at=datetime.now(tz=UTC),
        license_id=license_id,
        license_url=license_url,
        # Only when the work names a licence we recognise. Unknown terms mean the record
        # is stored as metadata but its abstract is not reused (spec section 21).
        abstract_redistributable=license_id is not None,
        venue=venue,
        primary_field_id=primary_field,
        field_weights=field_weights,
        paper_types=tuple(paper_types),
        open_access=open_access,
        retraction_status="retracted" if retracted else "none",
        version=None,
        pdf_url=(work.get("best_oa_location") or {}).get("pdf_url"),
        raw={
            "englishLevel": english_level,
            "mathDensity": 0.0,
            "equationCount": 0,
            "estimatedReadingMinutes": max(1.0, round((len(words) / 130) * 10) / 10),
            "sourceTermsUrl": SOURCE_TERMS_URL,
            "datasetLicense": DATASET_LICENSE,
            # Recorded so it is never mistaken for the publisher's exact text.
            "abstractReconstructedFromInvertedIndex": True,
        },
    )


class OpenAlexPaperProvider(PaperProvider):
    """Paper metadata from the OpenAlex works API."""

    name = "openalex"

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        mailto: str | None = None,
        min_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
        api_url: str = API_URL,
    ) -> None:
        self._api_url = api_url
        # OpenAlex asks callers to identify themselves for the faster "polite pool".
        self._mailto = mailto
        self._client = HttpProviderClient(
            transport=transport or HttpxTransport(),
            rate_limiter=RateLimiter(min_interval_seconds),
            breaker=CircuitBreaker(),
            user_agent=user_agent,
        )
        self._last_error: str | None = None

    def _params(self, extra: dict[str, Any]) -> dict[str, Any]:
        params = dict(extra)
        if self._mailto:
            params["mailto"] = self._mailto
        return params

    def _fetch(self, url: str, params: dict[str, Any], *, missing_is_none: bool = False) -> Any:
        """One request, with the status checked before the body is parsed.

        The client returns 4xx rather than raising, so that a malformed query of ours does
        not open the breaker for everyone. But a 4xx body is not a works response, and
        parsing it anyway reports "unparseable JSON" for what is really "OpenAlex rejected
        the request" — the wrong file to go and read.

        ``missing_is_none`` covers the lookup case, where a 404 is a legitimate answer
        ("no such work") rather than a failure.
        """
        try:
            response = self._client.get(url, params)
        except ProviderUnavailable as exc:
            self._last_error = str(exc)
            raise
        if missing_is_none and response.status_code == 404:
            self._last_error = None
            return None
        if not response.ok:
            self._last_error = f"HTTP {response.status_code}"
            raise ProviderUnavailable(
                f"OpenAlex returned HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            self._last_error = str(exc)
            raise ProviderUnavailable(f"OpenAlex returned unparseable JSON: {exc}") from exc
        self._last_error = None
        return payload

    def search(self, query: PaperQuery) -> tuple[list[PaperRecord], str | None]:
        filters = ["has_abstract:true"]
        if query.year_from is not None and query.year_to is not None:
            filters.append(f"publication_year:{query.year_from}-{query.year_to}")
        elif query.year_from is not None:
            filters.append(f"from_publication_date:{query.year_from}-01-01")
        elif query.year_to is not None:
            filters.append(f"to_publication_date:{query.year_to}-12-31")

        params = self._params(
            {
                "filter": ",".join(filters),
                "per-page": max(1, min(query.limit, 200)),
                "cursor": query.cursor or "*",
                "sort": "publication_date:desc",
            }
        )

        payload = self._fetch(self._api_url, params)

        records = []
        for work in (payload.get("results") if isinstance(payload, dict) else None) or []:
            if not isinstance(work, dict):
                continue
            record = parse_work(work)
            if record is None:
                continue
            if record.canonical_id in query.exclude_canonical_ids:
                continue
            if query.field_ids and record.primary_field_id not in query.field_ids:
                continue
            records.append(record)

        meta = (payload.get("meta") if isinstance(payload, dict) else None) or {}
        # OpenAlex paginates with an opaque cursor and repeats the last one at the end;
        # treating that as "more" would loop forever.
        next_cursor = meta.get("next_cursor")
        if not isinstance(next_cursor, str) or next_cursor == query.cursor or not records:
            next_cursor = None
        return records, next_cursor

    def get_by_canonical_id(self, canonical_id: str) -> PaperRecord | None:
        kind, _, value = canonical_id.partition(":")
        if kind == "doi":
            url = f"{self._api_url}/https://doi.org/{value}"
        elif kind == "openalex":
            url = f"{self._api_url}/{value}"
        else:
            return None

        work = self._fetch(url, self._params({}), missing_is_none=True)
        return parse_work(work) if isinstance(work, dict) else None

    def health(self) -> ProviderHealth:
        breaker = self._client.breaker
        if breaker.is_open:
            return ProviderHealth(
                name=self.name,
                healthy=False,
                detail=f"circuit open after {breaker.consecutive_failures} failures",
                checked_at=datetime.now(tz=UTC),
            )
        return ProviderHealth(
            name=self.name,
            healthy=True,
            detail=self._last_error or "ready",
            checked_at=datetime.now(tz=UTC),
        )
