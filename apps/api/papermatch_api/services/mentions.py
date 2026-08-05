"""Turning stored bodies into the mentions `relations.classify` asks for (spec section 17).

Section 17 lists 本文中の言及 as one of the four kinds of evidence a relation may rest on, and
it is the only one that can produce `contrasting`. `text/citations` knows how to find a
mention in a LaTeX body and `services/fulltext` knows which bodies we are allowed to keep;
this joins the two to the papers actually under consideration.

**Both directions count, and which one it was is recorded.** "This paper says it disagrees
with that one" and "that paper says it disagrees with this one" are different statements
about the literature, so `Mention.source` names whose text the sentence came from and the UI
can attribute it. Collapsing them would let the app put words in an author's mouth.

**A missing body is silence, not absence of a connection.** Most papers have no stored body
— either the licence refused it (`services/fulltext`) or nothing has been fetched — and the
resulting empty mention list must not be read as "these papers do not refer to each other".
`classify` already treats absent evidence as absent rather than as a negative finding, which
is what makes it safe to run this over a corpus where most bodies are missing.

**Only LaTeX is scanned.** `text/citations` strips LaTeX markup to reach the prose; handing
it JATS XML would leave tags in the sentences and put element names into the snippets shown
to readers. A JATS body is stored and simply not scanned until there is an extractor for it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import Paper, PaperFullText
from papermatch_api.services.relations import Mention
from papermatch_api.text.citations import PaperKey, find_mentions

__all__ = [
    "SCAN_LIMIT",
    "mentions_for",
    "paper_key",
]

#: How many candidate bodies are read to look for mentions of the anchor.
#:
#: Bounded because bodies are whole manuscripts and this runs inside an interactive request:
#: the anchor's own body is one row, but the reverse direction would otherwise load every
#: body in the pool. The pool arrives ordered — the reader's own library first, then nearest
#: by embedding — so the bound keeps the end most likely to be worth reading.
SCAN_LIMIT = 20


def _surnames(paper: Paper) -> tuple[str, ...]:
    """Author surnames, lower-cased, for the `Almeida (2024)` form.

    The last whitespace-separated token of the display name. Wrong for some names — particles
    and multi-word family names among them — but a surname rule only ever *adds* a match, and
    `citations` requires the year alongside it before any of them counts.
    """
    found: list[str] = []
    for author in paper.authors or []:
        name = str(author.get("name") or "").strip() if isinstance(author, dict) else ""
        if name:
            found.append(name.split()[-1].lower())
    return tuple(dict.fromkeys(found))


def paper_key(paper: Paper) -> PaperKey:
    """What a sentence would have to contain to be referring to this paper."""
    return PaperKey(
        paper_id=str(paper.id),
        title=paper.title,
        year=paper.year,
        surnames=_surnames(paper),
        identifiers=tuple(
            identifier.value.lower()
            for identifier in paper.identifiers
            if identifier.kind in {"arxiv", "doi"}
        ),
    )


def _latex_bodies(session: Session, paper_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not paper_ids:
        return {}
    rows = (
        session.execute(
            select(PaperFullText.paper_id, PaperFullText.body).where(
                PaperFullText.paper_id.in_(paper_ids),
                PaperFullText.body_format == "latex",
            )
        )
        .tuples()
        .all()
    )
    return dict(rows)


def mentions_for(
    session: Session, anchor: Paper, pool: list[Paper]
) -> dict[uuid.UUID, tuple[Mention, ...]]:
    """Sentences connecting `anchor` to each paper in `pool`, keyed by the *other* paper.

    Keyed by the candidate whichever way the sentence runs, because that is what the caller
    is deciding about: `candidates_for` builds one `Candidate` per pool paper and needs every
    sentence that bears on that pair, no matter which of the two wrote it.
    """
    by_id = {paper.id: paper for paper in pool}
    found: dict[uuid.UUID, list[Mention]] = {}

    anchor_body = _latex_bodies(session, [anchor.id]).get(anchor.id)
    if anchor_body is not None and pool:
        anchor_source = str(anchor.id)
        for mention in find_mentions(anchor_body, [paper_key(paper) for paper in pool]):
            target = uuid.UUID(mention.paper_id)
            if target in by_id:
                found.setdefault(target, []).append(
                    Mention(source=anchor_source, snippet=mention.sentence)
                )

    scanned = [paper.id for paper in pool[:SCAN_LIMIT]]
    anchor_key = [paper_key(anchor)]
    for paper_id, body in _latex_bodies(session, scanned).items():
        source = str(paper_id)
        for mention in find_mentions(body, anchor_key):
            found.setdefault(paper_id, []).append(Mention(source=source, snippet=mention.sentence))

    return {paper_id: tuple(items) for paper_id, items in found.items()}
