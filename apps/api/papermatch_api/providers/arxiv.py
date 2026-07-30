"""arXiv metadata provider (spec section 21).

Reads the arXiv Atom API: https://info.arxiv.org/help/api/index.html

**Licence position, stated explicitly because spec section 21 requires it to be
traceable.** arXiv's API Terms of Use place the *metadata* returned by the API — which is
what an abstract is, for our purposes — under CC0 1.0. That is what this provider records
as `license_id`, together with the source URL so the claim can be checked rather than
taken on faith. It says nothing about the full text of a submission, which carries the
author's own licence and which this provider never fetches. Spec section 21 also requires
an individual review of terms before commercial use; DECISIONS.md D-025 records that this
has not been done.

**What is deliberately not here.** No scraping, no PDF fetching, no full text. The Atom
feed only.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from xml.etree import ElementTree

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

API_URL = "http://export.arxiv.org/api/query"

#: arXiv asks for at most one request every three seconds.
MIN_REQUEST_INTERVAL_SECONDS = 3.0

#: See the module docstring. Recorded on every abstract, with `SOURCE_TERMS_URL` alongside.
METADATA_LICENSE = "CC0-1.0"
METADATA_LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
SOURCE_TERMS_URL = "https://info.arxiv.org/help/api/tou.html"

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"

#: arXiv categories → our field ids. Anything unmapped falls back to the parent archive,
#: and then to nothing — a paper with no field we recognise is still a paper, and dropping
#: it would silently narrow the corpus.
CATEGORY_MAP: dict[str, str] = {
    "hep-th": "hep-th",
    "hep-ph": "hep-th",
    "gr-qc": "hep-th",
    "quant-ph": "quant-ph",
    "cond-mat": "cond-mat",
    "astro-ph": "astro-ph",
    "math.ap": "math.AP",
    "math.co": "math.CO",
    "math.nt": "math.NT",
    "math.pr": "math.PR",
    "cs.lg": "cs.LG",
    "cs.ai": "cs.LG",
    "cs.ne": "cs.LG",
    "cs.ds": "cs.DS",
    "cs.cc": "cs.DS",
    "cs.cl": "cs.CL",
    "cs.cr": "cs.CR",
    "stat.ml": "cs.LG",
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

_WHITESPACE = re.compile(r"\s+")
_VERSION_SUFFIX = re.compile(r"v(\d+)$")


def map_category(term: str) -> str | None:
    """Map an arXiv category to one of our field ids.

    Sub-archives collapse onto their parent: ``cond-mat.str-el`` is condensed matter as far
    as a reader choosing fields is concerned, and offering forty sub-categories in
    onboarding would be worse than offering twelve (spec section 18).
    """
    lowered = term.strip().lower()
    if lowered in CATEGORY_MAP:
        return CATEGORY_MAP[lowered]
    head = lowered.split(".", 1)[0]
    return CATEGORY_MAP.get(head)


def _text(element: ElementTree.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return _WHITESPACE.sub(" ", element.text).strip()


def _parse_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(tz=UTC)


def _estimate_reading_minutes(abstract: str) -> float:
    words = len(abstract.split())
    return max(1.0, round((words / 130) * 10) / 10)


def _english_level(abstract: str) -> str:
    """Same rule the fixture corpus uses, so the badge means one thing everywhere."""
    words = abstract.split()
    if not words:
        return "intermediate"
    long_words = sum(1 for w in words if len(re.sub(r"[^A-Za-z]", "", w)) >= 11)
    ratio = long_words / len(words)
    if ratio > 0.14:
        return "advanced"
    if ratio > 0.09:
        return "intermediate"
    return "beginner"


def _math_density(abstract: str) -> float:
    inline = len(re.findall(r"\$[^$]+\$", abstract))
    if not abstract:
        return 0.0
    return round(inline / (len(abstract) / 1000), 2)


def parse_feed(xml: str) -> tuple[list[PaperRecord], int]:
    """Parse an arXiv Atom feed into records, plus the total result count.

    Entries that cannot be turned into a usable record — no id, or no abstract — are
    skipped rather than raising: one malformed entry must not lose the whole page.
    """
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ProviderUnavailable(f"arXiv returned unparseable XML: {exc}") from exc

    total_element = root.find(f"{OPENSEARCH}totalResults")
    try:
        total = int(_text(total_element) or "0")
    except ValueError:
        total = 0

    records: list[PaperRecord] = []
    for entry in root.findall(f"{ATOM}entry"):
        record = _parse_entry(entry)
        if record is not None:
            records.append(record)
    return records, total


def _parse_entry(entry: ElementTree.Element) -> PaperRecord | None:
    raw_id = _text(entry.find(f"{ATOM}id"))
    abstract = _text(entry.find(f"{ATOM}summary"))
    title = _text(entry.find(f"{ATOM}title"))
    if not raw_id or not abstract or not title:
        return None

    # The id is a URL like http://arxiv.org/abs/2401.01234v2 — the version matters for
    # "there is a newer version of a paper you saved" (spec section 9), while the
    # version-free id is what deduplication keys on (spec section 16).
    tail = raw_id.rsplit("/abs/", 1)[-1]
    versioned = normalize_arxiv_id(tail, keep_version=True)
    bare = normalize_arxiv_id(tail)
    if bare is None:
        return None
    version_match = _VERSION_SUFFIX.search(versioned or "")
    version = f"v{version_match.group(1)}" if version_match else None

    authors = tuple(
        {"name": _text(node.find(f"{ATOM}name")), "externalId": None, "affiliation": None}
        for node in entry.findall(f"{ATOM}author")
        if _text(node.find(f"{ATOM}name"))
    )

    doi = normalize_doi(_text(entry.find(f"{ARXIV}doi")) or None)
    journal_ref = _text(entry.find(f"{ARXIV}journal_ref")) or None

    primary = entry.find(f"{ARXIV}primary_category")
    primary_term = primary.get("term", "") if primary is not None else ""
    primary_field = map_category(primary_term)

    field_weights: dict[str, float] = {}
    if primary_field:
        field_weights[primary_field] = 0.7
        parent = PARENT_OF.get(primary_field)
        if parent:
            field_weights[parent] = 0.2
    for category in entry.findall(f"{ATOM}category"):
        mapped = map_category(category.get("term", ""))
        if mapped and mapped != primary_field:
            field_weights.setdefault(mapped, 0.1)

    published = _parse_timestamp(_text(entry.find(f"{ATOM}published")))

    pdf_url = None
    for link in entry.findall(f"{ATOM}link"):
        if link.get("title") == "pdf" or link.get("type") == "application/pdf":
            pdf_url = link.get("href")

    identifiers: list[dict[str, str]] = [{"kind": "arxiv", "value": bare}]
    if doi:
        identifiers.append({"kind": "doi", "value": doi})

    # A published DOI outranks the preprint id (spec section 16).
    canonical = f"doi:{doi}" if doi else f"arxiv:{bare}"

    paper_types = ["preprint"]
    if journal_ref or doi:
        paper_types.append("published")
    if datetime.now(tz=UTC).year - published.year >= 8:
        paper_types.append("classic")
    elif datetime.now(tz=UTC).year - published.year <= 1:
        paper_types.append("recent")

    return PaperRecord(
        canonical_id=canonical,
        title=title,
        abstract=abstract,
        authors=authors,
        year=published.year,
        identifiers=tuple(identifiers),
        source_provider="arxiv",
        source_url=f"https://arxiv.org/abs/{bare}",
        acquired_at=datetime.now(tz=UTC),
        license_id=METADATA_LICENSE,
        license_url=METADATA_LICENSE_URL,
        # Metadata only. See the module docstring for what this claim rests on.
        abstract_redistributable=True,
        venue=journal_ref or "arXiv",
        primary_field_id=primary_field,
        field_weights=field_weights,
        paper_types=tuple(paper_types),
        # Everything reachable through the API is a freely readable preprint.
        open_access="green",
        retraction_status="none",
        version=version,
        pdf_url=pdf_url,
        raw={
            "englishLevel": _english_level(abstract),
            "mathDensity": _math_density(abstract),
            "equationCount": len(re.findall(r"\$[^$]+\$", abstract)),
            "estimatedReadingMinutes": _estimate_reading_minutes(abstract),
            "sourceTermsUrl": SOURCE_TERMS_URL,
            "primaryCategory": primary_term,
        },
    )


def build_search_query(field_ids: tuple[str, ...]) -> str:
    """Turn our field ids back into an arXiv category query.

    A field with no arXiv category behind it contributes nothing rather than breaking the
    query; if none of them map, the caller gets the recent-submissions firehose, which is
    a reasonable default for a discovery app.
    """
    wanted = set(field_ids)
    categories = {
        # An archive-level category needs a wildcard: `cat:cond-mat` does not match
        # `cond-mat.str-el`, which is where nearly all of condensed matter actually lives.
        arxiv_category if "." in arxiv_category else f"{arxiv_category}*"
        for arxiv_category, mapped in CATEGORY_MAP.items()
        if mapped in wanted
    }
    if not categories:
        return "all:*"
    return " OR ".join(f"cat:{category}" for category in sorted(categories))


class ArxivPaperProvider(PaperProvider):
    """Paper metadata from the arXiv Atom API."""

    name = "arxiv"

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        min_interval_seconds: float = MIN_REQUEST_INTERVAL_SECONDS,
        api_url: str = API_URL,
    ) -> None:
        self._api_url = api_url
        self._client = HttpProviderClient(
            transport=transport or HttpxTransport(),
            rate_limiter=RateLimiter(min_interval_seconds),
            breaker=CircuitBreaker(),
            user_agent=user_agent,
        )
        self._last_error: str | None = None

    def _fetch(self, params: dict[str, Any]) -> str:
        """One request, with the status checked before the body is trusted.

        The client deliberately returns 4xx rather than raising, so that a bad query of
        ours does not open the breaker for everyone. But a 4xx body is not an Atom feed,
        and handing it to the parser turns "arXiv rejected the query" into "unparseable
        XML" — which sends the next person debugging this to the wrong file.
        """
        try:
            response = self._client.get(self._api_url, params)
        except ProviderUnavailable as exc:
            self._last_error = str(exc)
            raise
        if not response.ok:
            self._last_error = f"HTTP {response.status_code}"
            raise ProviderUnavailable(
                f"arXiv returned HTTP {response.status_code}: {response.text[:200]}"
            )
        self._last_error = None
        return response.text

    def search(self, query: PaperQuery) -> tuple[list[PaperRecord], str | None]:
        start = 0
        if query.cursor:
            try:
                start = max(0, int(query.cursor))
            except ValueError:
                start = 0

        limit = max(1, min(query.limit, 100))
        params: dict[str, Any] = {
            "search_query": build_search_query(query.field_ids),
            "start": start,
            "max_results": limit,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        records, total = parse_feed(self._fetch(params))

        # Exclusions are applied here because the Atom API has no "not these ids" filter.
        if query.exclude_canonical_ids:
            records = [r for r in records if r.canonical_id not in query.exclude_canonical_ids]
        if query.year_from is not None:
            records = [r for r in records if r.year >= query.year_from]
        if query.year_to is not None:
            records = [r for r in records if r.year <= query.year_to]

        next_start = start + limit
        next_cursor = str(next_start) if next_start < total else None
        return records, next_cursor

    def get_by_canonical_id(self, canonical_id: str) -> PaperRecord | None:
        kind, _, value = canonical_id.partition(":")
        if kind != "arxiv":
            # A DOI-keyed paper may still be on arXiv, but resolving that needs a second
            # source; saying "not mine" is more honest than guessing.
            return None
        records, _ = parse_feed(self._fetch({"id_list": value, "max_results": 1}))
        return records[0] if records else None

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
            detail=self._last_error or f"ready (min {MIN_REQUEST_INTERVAL_SECONDS}s between calls)",
            checked_at=datetime.now(tz=UTC),
        )
