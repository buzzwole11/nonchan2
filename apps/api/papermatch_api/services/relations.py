"""Classifying how two papers are related (spec section 17).

Section 17 asks for four roles around a saved paper — Related, Contrasting, Foundational,
Follow-up — and then states the constraint that this module exists to enforce:

    単なる類似度だけで関係ラベルを断定しない。引用方向、公開日、本文中の言及、
    モデル分類の根拠を保持する。

**Similarity can produce exactly one label, and it is the weak one.** Two abstracts that
read alike are, on that evidence, *related*. They are not foundational, they are not a
follow-up, and they are certainly not contrasting — every one of those is a claim about
something similarity cannot see. A pipeline that assigned them anyway would be telling the
reader that one paper builds on another when all it knows is that both mention Markov
chains. So each label declares what it requires, and a label whose evidence is absent is
simply not produced; there is no "best guess" path.

**Direction is not decoration.** `foundational` and `follow_up` are the same citation edge
read from opposite ends, and which one it is depends entirely on who cites whom. Getting
that backwards would point a reader at the wrong end of a literature, so the citation
evidence carries the direction explicitly rather than being inferred from publication dates.
Dates *corroborate* a citation; they never stand in for one — a preprint can cite a paper
published later, and citation lists are the only thing that knows.

**Contrast needs someone to have said so.** There is no way to detect "different conclusion"
from metadata. What can be detected is one paper's text *saying* it, so `contrasting`
requires a mention snippet containing a contrastive cue. That makes it the narrowest label
here, and it should be: wrongly telling a reader that two papers disagree sends them looking
for an argument that is not there.

**Every relation keeps its evidence**, in the shape section 17 lists: citation direction,
publication order, the mention snippet, and which model produced the similarity. The reader
sees why, and a relation whose evidence later turns out to be wrong can be found.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session, selectinload

from papermatch_api.models import Paper, PaperRelation, SavedPaper
from papermatch_api.providers.local_embedding import MODEL_NAME, cosine
from papermatch_api.services.embeddings import embeddings_for, nearest_papers

__all__ = [
    "CONTRAST_CUES",
    "POOL_LIMIT",
    "RELATED_SIMILARITY",
    "Candidate",
    "ClassifiedRelation",
    "Mention",
    "candidate_pool",
    "candidates_for",
    "cited_openalex_ids",
    "classify",
    "classify_all",
    "refresh_relations",
    "relations_for",
]


@dataclass(frozen=True)
class Mention:
    """One paper's text referring to another, with the sentence it was said in.

    The snippet is kept because it is the evidence. A boolean "was mentioned" would let the
    contrast rule fire without anything a reader could check.
    """

    #: Which paper's text the sentence comes from.
    source: str
    snippet: str


@dataclass
class Candidate:
    """Everything known about one pair, and nothing assumed about the rest.

    Absent evidence is `None` or empty — never a default that reads as a finding. A missing
    citation list means "we do not know who cites whom", which is not the same as "neither
    cites the other", and the rules below treat it as the former.
    """

    paper_id: str
    year: int | None = None
    #: Cosine similarity of the two abstracts, when both have a vector from the same model.
    similarity: float | None = None
    similarity_model: str | None = None
    #: True when the *anchor* paper's reference list contains this candidate.
    anchor_cites_candidate: bool = False
    #: True when this candidate's reference list contains the anchor.
    candidate_cites_anchor: bool = False
    mentions: tuple[Mention, ...] = ()
    extra_evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClassifiedRelation:
    relation_type: str
    confidence: float
    evidence: dict[str, Any]


#: Cosine above which two abstracts are alike enough to call the pair `related`.
#:
#: Deliberately high. This is the one label similarity can produce on its own, so the cost of
#: setting it low is a list of "related work" that is mostly noise — which teaches the reader
#: to stop reading the list, and takes the three well-evidenced labels down with it.
RELATED_SIMILARITY = 0.62

#: Below this a citation edge is reported without similarity backing it up; above it the
#: similarity is recorded as corroboration. Citations are never overruled by a low score —
#: a paper genuinely can build on something in a different area.
CORROBORATING_SIMILARITY = 0.40

#: Phrases that mark a sentence as drawing a contrast rather than merely citing.
#:
#: Matched as whole phrases with word boundaries. An earlier draft matched bare "however"
#: anywhere in the snippet, which fired on "however large n becomes" — a sentence about
#: asymptotics, not about disagreeing with anybody.
CONTRAST_CUES: tuple[str, ...] = (
    "in contrast",
    "by contrast",
    "unlike",
    "contrary to",
    "disagree",
    "we disagree with",
    "differs from",
    "fails to account",
    "cannot be reconciled",
    "contradicts",
    "challenges the",
    "call into question",
    "とは対照的に",
    "とは異なり",
    "に反して",
    "矛盾",
)

_CUE_PATTERNS = tuple(
    # Latin-script cues get word boundaries; Japanese has no spaces, so those match directly.
    re.compile(rf"\b{re.escape(cue)}\b" if cue.isascii() else re.escape(cue), re.IGNORECASE)
    for cue in CONTRAST_CUES
)


def _contrast_cue(snippet: str) -> str | None:
    """The first contrastive phrase in the snippet, or None."""
    for cue, pattern in zip(CONTRAST_CUES, _CUE_PATTERNS, strict=True):
        if pattern.search(snippet):
            return cue
    return None


def _similarity_evidence(candidate: Candidate) -> dict[str, Any]:
    """What the similarity contributed, named so it cannot masquerade as more than it is."""
    if candidate.similarity is None:
        return {"similarity": None, "similarityModel": None}
    return {
        "similarity": round(candidate.similarity, 4),
        "similarityModel": candidate.similarity_model,
    }


def _publication_order(anchor_year: int | None, candidate: Candidate) -> str | None:
    """`before`, `after`, `same_year`, or None when either year is unknown."""
    if anchor_year is None or candidate.year is None:
        return None
    if candidate.year < anchor_year:
        return "before"
    if candidate.year > anchor_year:
        return "after"
    return "same_year"


def classify(anchor_year: int | None, candidate: Candidate) -> ClassifiedRelation | None:
    """The strongest label the evidence supports, or None when it supports none.

    Order matters: the labels are tried strongest-evidence first, so a pair that both cites
    and contrasts is reported as contrasting — the more specific and more useful statement.
    """
    order = _publication_order(anchor_year, candidate)
    similarity = _similarity_evidence(candidate)
    base: dict[str, Any] = {
        "publicationOrder": order,
        "anchorYear": anchor_year,
        "candidateYear": candidate.year,
        **similarity,
        **candidate.extra_evidence,
    }

    # ---- contrasting: someone had to have said so, in a sentence we can show.
    for mention in candidate.mentions:
        cue = _contrast_cue(mention.snippet)
        if cue is not None:
            return ClassifiedRelation(
                relation_type="contrasting",
                # Text is the strongest evidence available for this label and also the
                # easiest to over-read, so it does not go above 0.8 on a cue alone.
                confidence=0.8 if candidate.similarity is None else 0.85,
                evidence={
                    **base,
                    "mention": {"source": mention.source, "snippet": mention.snippet},
                    "contrastCue": cue,
                    "basis": "mention",
                },
            )

    # ---- foundational / follow_up: a citation edge, read in its own direction.
    cites = candidate.anchor_cites_candidate
    cited_by = candidate.candidate_cites_anchor
    if cites or cited_by:
        # Both directions is not an error — two papers can cite each other across versions.
        # It is reported as the direction that the publication order supports, and when the
        # order is unknown it stays `related`, because we cannot say which came first.
        if cites and cited_by:
            if order == "before":
                relation, direction = "foundational", "anchor_cites_candidate"
            elif order == "after":
                relation, direction = "follow_up", "candidate_cites_anchor"
            else:
                return ClassifiedRelation(
                    relation_type="related",
                    confidence=0.6,
                    evidence={**base, "citation": "mutual", "basis": "citation"},
                )
        elif cites:
            relation, direction = "foundational", "anchor_cites_candidate"
        else:
            relation, direction = "follow_up", "candidate_cites_anchor"

        # The publication order either corroborates the citation or contradicts it. A
        # contradiction is kept and reported rather than being allowed to flip the label:
        # citation lists know who built on whom; dates only know what was announced when.
        expected = "before" if relation == "foundational" else "after"
        corroborated = order == expected
        confidence = 0.9 if corroborated else 0.7
        if candidate.similarity is not None and candidate.similarity >= CORROBORATING_SIMILARITY:
            confidence = min(0.95, confidence + 0.05)

        return ClassifiedRelation(
            relation_type=relation,
            confidence=confidence,
            evidence={
                **base,
                "citation": direction,
                "publicationOrderAgrees": corroborated if order is not None else None,
                "basis": "citation",
            },
        )

    # ---- related: the only thing similarity is allowed to conclude on its own.
    if candidate.similarity is not None and candidate.similarity >= RELATED_SIMILARITY:
        return ClassifiedRelation(
            relation_type="related",
            # Capped well below the citation-backed labels. It is a weaker claim and the
            # number should say so, because it is what the UI sorts and filters on.
            confidence=round(min(0.6, candidate.similarity * 0.75), 4),
            evidence={**base, "basis": "similarity"},
        )

    # A mention with no contrastive cue is still a real connection, and a weaker one than
    # similarity would be. It is reported as `related` with the sentence attached so the
    # reader can see what the connection actually was.
    if candidate.mentions:
        mention = candidate.mentions[0]
        return ClassifiedRelation(
            relation_type="related",
            confidence=0.5,
            evidence={
                **base,
                "mention": {"source": mention.source, "snippet": mention.snippet},
                "basis": "mention",
            },
        )

    return None


def classify_all(
    anchor_year: int | None, candidates: list[Candidate]
) -> list[tuple[str, ClassifiedRelation]]:
    """Classify a batch, dropping the pairs no label fits.

    Sorted by confidence so the caller can take the top n and get the best-evidenced
    relations rather than an arbitrary slice.
    """
    results = [
        (candidate.paper_id, relation)
        for candidate in candidates
        if (relation := classify(anchor_year, candidate)) is not None
    ]
    results.sort(key=lambda pair: pair[1].confidence, reverse=True)
    return results


# ------------------------------------------------------------------ from the database
#
# Everything above is pure and knows nothing about storage. What follows gathers the
# evidence the rules ask for out of what has actually been ingested, and is careful to pass
# absence through as absence: a provider that did not give us a reference list must not look
# like a provider that gave us an empty one.


#: How many papers are considered as candidates for one anchor.
#:
#: Bounded because this is an interactive request, and because a relation list longer than a
#: screen is not a list anyone reads. The pool is ordered so the most likely candidates —
#: the reader's own library first — are the ones inside the bound.
POOL_LIMIT = 60


def cited_openalex_ids(paper: Paper) -> set[str]:
    """OpenAlex ids in this paper's own provider record, as bare `W…` values.

    Read from `raw_metadata` rather than a column of our own: it is exactly what the
    provider said, and re-parsing it never needs a re-fetch. An absent `referenced_works`
    yields an empty set, and the caller must not read that as "cites nothing" — see
    `candidates_for`, which only sets a citation flag when at least one side actually
    published a reference list.
    """
    raw = paper.raw_metadata or {}
    referenced = raw.get("referenced_works")
    if not isinstance(referenced, list):
        return set()
    return {
        value.rsplit("/", 1)[-1] for value in referenced if isinstance(value, str) and value.strip()
    }


def _has_reference_list(paper: Paper) -> bool:
    """Whether the provider told us anything at all about what this paper cites."""
    raw = paper.raw_metadata or {}
    return isinstance(raw.get("referenced_works"), list)


def candidate_pool(session: Session, anchor: Paper, user_id: uuid.UUID) -> list[Paper]:
    """Papers worth considering as relations of `anchor`.

    The reader's own saved library first — section 17 is about organising 保存論文の周辺 —
    then the anchor's nearest neighbours by embedding, through the ANN index (migration
    0009).

    **Neighbours replaced "any paper in the same primary field".** That was a proxy chosen
    when there was no index, and it was wrong in both directions: it admitted every
    unrelated paper that happened to share a category, and missed every close one that did
    not. Being a candidate is not a relation — `classify` still decides, and similarity on
    its own still yields at most `related`.
    """
    saved_ids = set(
        session.execute(select(SavedPaper.paper_id).where(SavedPaper.user_id == user_id)).scalars()
    )
    saved_ids.discard(anchor.id)

    anchor_vector = embeddings_for(session, [anchor.id]).get(anchor.id)
    neighbour_ids = (
        [
            paper_id
            for paper_id, _ in nearest_papers(
                session, anchor_vector, limit=POOL_LIMIT, exclude=anchor.id
            )
        ]
        if anchor_vector is not None
        else []
    )

    conditions: list[ColumnElement[bool]] = []
    if saved_ids:
        conditions.append(Paper.id.in_(saved_ids))
    if neighbour_ids:
        conditions.append(Paper.id.in_(neighbour_ids))
    else:
        # No neighbours to be had — the anchor has no vector, or nothing else does. The
        # field is the only remaining way to reach past the reader's own library, so it
        # comes back as the fallback it always was.
        #
        # Applied whenever the neighbours are missing, not only when nothing is saved: an
        # earlier version made it conditional on an empty library, which meant a reader who
        # had saved anything lost the reach entirely.
        conditions.append(Paper.primary_field_id == anchor.primary_field_id)

    rows = list(
        session.execute(
            select(Paper)
            .options(selectinload(Paper.identifiers))
            .where(Paper.id != anchor.id, or_(*conditions))
            .limit(POOL_LIMIT * 2)
        ).scalars()
    )
    # Saved first, then nearest first, so the bound below keeps the useful end.
    order = {paper_id: index for index, paper_id in enumerate(neighbour_ids)}
    rows.sort(key=lambda p: (p.id not in saved_ids, order.get(p.id, len(order)), -p.year))
    return rows[:POOL_LIMIT]


def candidates_for(
    session: Session,
    anchor: Paper,
    pool: list[Paper],
    mentions: dict[uuid.UUID, tuple[Mention, ...]] | None = None,
) -> list[Candidate]:
    """Assemble the evidence for each pair.

    Similarity comes from the stored vectors and is only computed when *both* papers have
    one from the same model — `embeddings_for` already refuses to mix models, and a pair
    where one side is missing is reported as "no similarity information" rather than as a
    low score.
    """
    vectors = embeddings_for(session, [anchor.id, *(p.id for p in pool)])
    anchor_vector = vectors.get(anchor.id)

    anchor_references = cited_openalex_ids(anchor)
    anchor_publishes_references = _has_reference_list(anchor)
    anchor_openalex = {i.value for i in anchor.identifiers if i.kind == "openalex"}

    candidates: list[Candidate] = []
    for paper in pool:
        vector = vectors.get(paper.id)
        similarity = (
            cosine(anchor_vector, vector)
            if anchor_vector is not None and vector is not None
            else None
        )
        candidate_openalex = {i.value for i in paper.identifiers if i.kind == "openalex"}

        candidates.append(
            Candidate(
                paper_id=str(paper.id),
                year=paper.year,
                similarity=similarity,
                similarity_model=MODEL_NAME if similarity is not None else None,
                anchor_cites_candidate=(
                    anchor_publishes_references and bool(anchor_references & candidate_openalex)
                ),
                candidate_cites_anchor=(
                    _has_reference_list(paper) and bool(cited_openalex_ids(paper) & anchor_openalex)
                ),
                mentions=(mentions or {}).get(paper.id, ()),
            )
        )
    return candidates


def refresh_relations(
    session: Session,
    anchor: Paper,
    classified: list[tuple[str, ClassifiedRelation]],
) -> list[PaperRelation]:
    """Write the classifications down, replacing what was there for this anchor.

    Replacing rather than appending: a relation is a *current* reading of the evidence, and
    re-running after an embedding model changes should leave one answer per pair rather than
    a pile of them. Rows for pairs that no longer classify are removed, because a relation
    the evidence no longer supports must stop being shown.
    """
    existing = {
        (row.target_paper_id, row.relation_type): row
        for row in session.execute(
            select(PaperRelation).where(PaperRelation.source_paper_id == anchor.id)
        ).scalars()
    }

    kept: list[PaperRelation] = []
    seen: set[tuple[uuid.UUID, str]] = set()
    for target_id, relation in classified:
        key = (uuid.UUID(target_id), relation.relation_type)
        seen.add(key)
        row = existing.get(key)
        if row is None:
            row = PaperRelation(
                source_paper_id=anchor.id,
                target_paper_id=key[0],
                relation_type=relation.relation_type,
            )
            session.add(row)
        row.confidence = relation.confidence
        row.evidence = relation.evidence
        kept.append(row)

    for key, row in existing.items():
        if key not in seen:
            session.delete(row)

    return kept


def relations_for(
    session: Session, anchor: Paper, user_id: uuid.UUID
) -> list[tuple[Paper, PaperRelation]]:
    """Classify, store, and return this paper's relations with the papers they point at.

    Computed on request rather than served from whatever was stored earlier. The evidence
    changes as the library grows, and a reader looking at a paper today should see what is
    true today; the stored rows are the audit record of what was concluded and why.
    """
    pool = candidate_pool(session, anchor, user_id)
    classified = classify_all(anchor.year, candidates_for(session, anchor, pool))
    rows = refresh_relations(session, anchor, classified)

    by_id = {paper.id: paper for paper in pool}
    return [(by_id[row.target_paper_id], row) for row in rows if row.target_paper_id in by_id]
