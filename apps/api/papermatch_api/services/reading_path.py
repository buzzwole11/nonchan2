"""Routes through a paper, by what the reader came for (spec section 17).

Section 17 asks for four of them — 全体を知る / 数式を追う / 結果だけ見る / 引用に使えるか確認 —
and gives an example: Abstract → Figure 1 → Introduction 1～3段落 → Eq. 7 → Conclusion.

**That example is the trap.** We do not hold the paper's body. Nothing here has ever seen
whether the paper has a Figure 1, how many paragraphs its introduction runs to, or whether
Eq. 7 exists. A route that said "read Figure 1" would be inventing structure, and the reader
would find out by scrolling a PDF looking for something that is not there — after trusting
us enough to open it. So **every step points at something we actually have**, and the steps
that necessarily live in the original say so and hand over a link.

That is what `held` is for. A held step has its content in the app: an abstract sentence we
segmented, an equation we extracted, a fact from the metadata. An unheld step is an
instruction to look at the paper itself, and it is never dressed up as more than that.

**A purpose is a filter, not a rewrite.** Each route selects from the same material in the
same order the paper presents it. Reordering by "importance" would be a second opinion about
the paper on top of the reader's own reason for opening it.

**A route can come back short, and that is the honest outcome.** A paper with no detected
segments and no extracted equations yields the metadata steps and the link, because that is
genuinely all we know about it. Padding the list to a respectable length with generic advice
("skim the introduction") would make every paper's route identical and none of them true.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import AbstractSegment, Equation, Paper

__all__ = [
    "READING_PURPOSES",
    "ReadingRoute",
    "RouteStep",
    "build_route",
    "route_for",
    "routes_for",
]

#: The four in section 17, in the order that section lists them.
READING_PURPOSES: tuple[str, ...] = (
    "overview",
    "follow_math",
    "results_only",
    "citation_check",
)

#: Which abstract roles each purpose reads, in the paper's own order.
#:
#: `citation_check` takes `significance` alone: deciding whether a paper is citable is about
#: what it claims and whether the claim is usable, not about how it got there.
_SECTIONS: dict[str, tuple[str, ...]] = {
    "overview": ("background", "problem", "method", "result", "significance"),
    "follow_math": ("problem", "method"),
    "results_only": ("result", "significance"),
    "citation_check": ("significance",),
}

#: Section 8's order, used to sort roles when the offsets tie.
_SECTION_ORDER = ("background", "problem", "method", "result", "significance")


@dataclass(frozen=True)
class RouteStep:
    """One stop on a route.

    `label_key` is an i18n key, never prose: section 25 puts UI strings on the client, and a
    server that shipped Japanese sentences would make the API the place translations live.
    `detail` carries factual values only — a DOI, a licence id — which are the same in every
    language.
    """

    kind: str
    label_key: str
    #: True when the app holds the content; False when the step is "go and look at the paper".
    held: bool
    section: str | None = None
    start: int | None = None
    end: int | None = None
    equation_id: uuid.UUID | None = None
    equation_number: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class ReadingRoute:
    purpose: str
    steps: list[RouteStep] = field(default_factory=list)
    #: What the route could not cover because we do not hold the paper's body.
    missing: list[str] = field(default_factory=list)


def _segment_steps(segments: list[AbstractSegment], wanted: tuple[str, ...]) -> list[RouteStep]:
    """Abstract sentences with the wanted roles, in the order they appear in the text."""
    chosen = [segment for segment in segments if segment.section in wanted]
    chosen.sort(
        key=lambda s: (
            s.start_offset,
            _SECTION_ORDER.index(s.section) if s.section in _SECTION_ORDER else len(_SECTION_ORDER),
        )
    )
    return [
        RouteStep(
            kind="abstract_segment",
            label_key=f"section.{segment.section}",
            held=True,
            section=segment.section,
            start=segment.start_offset,
            end=segment.end_offset,
        )
        for segment in chosen
    ]


def _equation_steps(equations: list[Equation]) -> list[RouteStep]:
    """Every extracted equation, display ones first within their source order.

    Numbered equations keep their number, because "Eq. 7" is how the reader will find it in
    the original. An equation the source did not number is shown without one rather than
    being given a position we made up.
    """
    return [
        RouteStep(
            kind="equation",
            label_key="readingPath.equation",
            held=True,
            equation_id=equation.id,
            equation_number=equation.equation_number,
            detail=equation.section,
        )
        for equation in equations
    ]


def _citation_steps(paper: Paper) -> list[RouteStep]:
    """The facts someone needs to decide whether they can cite this.

    Each one is a real column. A missing licence appears as a step saying it is unknown
    rather than being left out, because "we do not know the terms" is exactly the answer that
    should stop someone reusing the text (section 21).
    """
    steps = [
        RouteStep(
            kind="metadata",
            label_key="readingPath.venue",
            held=True,
            detail=paper.venue or None,
        ),
        RouteStep(
            kind="metadata",
            label_key="readingPath.version",
            held=True,
            detail=paper.version or None,
        ),
        RouteStep(
            kind="metadata",
            label_key="readingPath.license",
            held=True,
            detail=paper.license_id,
        ),
        RouteStep(
            kind="metadata",
            label_key="readingPath.openAccess",
            held=True,
            detail=paper.open_access,
        ),
    ]
    # Only when there is something to say. A "not retracted" badge on every paper trains the
    # reader to ignore the one that matters.
    if paper.retraction_status != "none":
        steps.append(
            RouteStep(
                kind="metadata",
                label_key="readingPath.retraction",
                held=True,
                detail=paper.retraction_status,
            )
        )
    return steps


def build_route(
    purpose: str,
    paper: Paper,
    segments: list[AbstractSegment],
    equations: list[Equation],
) -> ReadingRoute:
    """Assemble one route from what is actually held about this paper."""
    if purpose not in READING_PURPOSES:
        raise ValueError(f"unknown reading purpose: {purpose}")

    steps: list[RouteStep] = []
    missing: list[str] = []

    if purpose == "citation_check":
        steps.extend(_citation_steps(paper))

    steps.extend(_segment_steps(segments, _SECTIONS[purpose]))

    if purpose == "follow_math":
        steps.extend(_equation_steps(equations))
        if not equations:
            # Named, because an empty maths route and a paper with no maths look identical
            # otherwise, and the reader concludes the feature is broken.
            missing.append("equations")

    if not segments:
        missing.append("abstract_segments")

    # The last step of every route, and the only one that is not held: the parts of a paper
    # we have never seen — its figures, its introduction, its conclusion — live here.
    steps.append(
        RouteStep(
            kind="external",
            label_key=f"readingPath.open.{purpose}",
            held=False,
            detail=paper.source_url,
        )
    )
    # Stated rather than implied by the link. Section 17's example route walks through the
    # body; we can point at the door but not describe the rooms.
    missing.append("full_text")

    return ReadingRoute(purpose=purpose, steps=steps, missing=missing)


def _material(session: Session, paper: Paper) -> tuple[list[AbstractSegment], list[Equation]]:
    segments = list(
        session.execute(
            select(AbstractSegment)
            .where(AbstractSegment.paper_id == paper.id)
            .order_by(AbstractSegment.start_offset)
        ).scalars()
    )
    equations = list(
        session.execute(
            select(Equation)
            .where(Equation.paper_id == paper.id)
            .order_by(Equation.display.desc(), Equation.created_at, Equation.id)
        ).scalars()
    )
    return segments, equations


def route_for(session: Session, paper: Paper, purpose: str) -> ReadingRoute:
    segments, equations = _material(session, paper)
    return build_route(purpose, paper, segments, equations)


def routes_for(session: Session, paper: Paper) -> list[ReadingRoute]:
    """All four, so the client can offer the choice without a request per purpose.

    One read of the material for all of them: the four routes are four selections from the
    same segments and equations, and fetching them per purpose would be four times the
    queries for identical rows.
    """
    segments, equations = _material(session, paper)
    return [build_route(purpose, paper, segments, equations) for purpose in READING_PURPOSES]
