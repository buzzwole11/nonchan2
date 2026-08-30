"""Routes through a paper (spec section 17).

Section 17's example route walks through a paper's body — Figure 1, the introduction's first
paragraphs, Eq. 7 — and we have never seen any of that. So the tests that matter are the ones
that check the route does not pretend otherwise.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from papermatch_api.models import AbstractSegment, Equation, Paper
from papermatch_api.services.reading_path import (
    READING_PURPOSES,
    build_route,
    routes_for,
)
from tests.conftest import requires_db

ABSTRACT = (
    "Concentration inequalities bound deviations. "
    "The constant is unknown for this family. "
    "We combine a spectral argument with a coupling. "
    "We prove a bound with no log factor. "
    "This settles a case left open since 2011."
)


def _paper(**overrides: object) -> Paper:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "canonical_id": "test:route",
        "title": "A Paper",
        "normalized_title": "a paper",
        "abstract": ABSTRACT,
        "authors": [],
        "year": 2026,
        "venue": "Annals of Probability",
        "version": "v2",
        "license_id": "CC-BY-4.0",
        "open_access": "gold",
        "retraction_status": "none",
        "source_provider": "openalex",
        "source_url": "https://example.invalid/abs/1",
        "acquired_at": datetime.now(tz=UTC),
    }
    defaults.update(overrides)
    return Paper(**defaults)


def _segments(paper: Paper) -> list[AbstractSegment]:
    roles = ["background", "problem", "method", "result", "significance"]
    start = 0
    rows = []
    for role, sentence in zip(roles, ABSTRACT.split(". "), strict=False):
        end = start + len(sentence) + 2
        rows.append(
            AbstractSegment(
                paper_id=paper.id,
                start_offset=start,
                end_offset=end,
                section=role,
                detected_by="heuristic",
                confidence=0.7,
            )
        )
        start = end
    return rows


def _equation(paper: Paper, number: str | None) -> Equation:
    return Equation(
        id=uuid.uuid4(),
        paper_id=paper.id,
        latex=r"t_{\mathrm{mix}} = \frac{1}{2\lambda}\log n",
        equation_number=number,
        section="3",
        display=True,
    )


# ------------------------------------------------------------------ what is never invented


def test_no_step_points_at_a_part_of_the_paper_we_have_never_seen() -> None:
    # Section 17's example names Figure 1 and the introduction's paragraphs. We hold neither.
    # A step naming them would send the reader scrolling a PDF for something that may not be
    # there, after trusting us enough to open it.
    paper = _paper()
    for purpose in READING_PURPOSES:
        route = build_route(purpose, paper, _segments(paper), [_equation(paper, "7")])
        for step in route.steps:
            assert step.kind in {"abstract_segment", "equation", "metadata", "external"}
            if step.kind != "external":
                assert step.held is True


def test_the_only_unheld_step_is_the_link_to_the_paper_itself() -> None:
    paper = _paper()
    route = build_route("overview", paper, _segments(paper), [])

    unheld = [step for step in route.steps if not step.held]
    assert len(unheld) == 1
    assert unheld[0].kind == "external"
    assert unheld[0].detail == "https://example.invalid/abs/1"


def test_every_route_says_the_body_is_not_covered() -> None:
    # Stated rather than implied by the presence of a link. The reader should know the route
    # stops at the abstract, not discover it.
    paper = _paper()
    for purpose in READING_PURPOSES:
        route = build_route(purpose, paper, _segments(paper), [])
        assert "full_text" in route.missing


def test_a_paper_with_nothing_detected_yields_a_short_route_not_a_padded_one() -> None:
    # Generic advice would make every paper's route identical and none of them true.
    paper = _paper()
    route = build_route("overview", paper, [], [])

    assert [step.kind for step in route.steps] == ["external"]
    assert "abstract_segments" in route.missing


def test_an_equation_the_source_did_not_number_is_not_given_one() -> None:
    paper = _paper()
    route = build_route("follow_math", paper, [], [_equation(paper, None)])

    equations = [step for step in route.steps if step.kind == "equation"]
    assert equations[0].equation_number is None


# ------------------------------------------------------------------ what each purpose reads


def test_the_overview_route_walks_the_abstract_in_order() -> None:
    paper = _paper()
    route = build_route("overview", paper, _segments(paper), [])

    assert [step.section for step in route.steps if step.kind == "abstract_segment"] == [
        "background",
        "problem",
        "method",
        "result",
        "significance",
    ]


def test_the_results_route_skips_how_they_got_there() -> None:
    paper = _paper()
    route = build_route("results_only", paper, _segments(paper), [])

    sections = [step.section for step in route.steps if step.kind == "abstract_segment"]
    assert sections == ["result", "significance"]


def test_the_maths_route_includes_the_equations() -> None:
    paper = _paper()
    route = build_route("follow_math", paper, _segments(paper), [_equation(paper, "7")])

    numbers = [step.equation_number for step in route.steps if step.kind == "equation"]
    assert numbers == ["7"]


def test_the_maths_route_says_so_when_a_paper_has_no_equations() -> None:
    # An empty maths route and a paper with no maths look identical otherwise, and the
    # reader concludes the feature is broken rather than that the paper has no formulas.
    paper = _paper()
    route = build_route("follow_math", paper, _segments(paper), [])

    assert "equations" in route.missing


def test_the_citation_route_carries_the_facts_a_citation_needs() -> None:
    paper = _paper()
    route = build_route("citation_check", paper, _segments(paper), [])

    details = {step.label_key: step.detail for step in route.steps if step.kind == "metadata"}
    assert details["readingPath.venue"] == "Annals of Probability"
    assert details["readingPath.version"] == "v2"
    assert details["readingPath.license"] == "CC-BY-4.0"
    assert details["readingPath.openAccess"] == "gold"


def test_an_unknown_licence_is_shown_as_unknown_rather_than_omitted() -> None:
    # Section 21: not knowing the terms is the answer that should stop someone reusing the
    # text. Dropping the row would make it look like the question was never asked.
    paper = _paper(license_id=None)
    route = build_route("citation_check", paper, [], [])

    licences = [s for s in route.steps if s.label_key == "readingPath.license"]
    assert len(licences) == 1
    assert licences[0].detail is None


def test_a_retraction_is_surfaced_and_a_clean_record_is_not() -> None:
    # A "not retracted" badge on every paper trains the reader to ignore the one that matters.
    clean = build_route("citation_check", _paper(), [], [])
    retracted = build_route("citation_check", _paper(retraction_status="retracted"), [], [])

    assert not any(s.label_key == "readingPath.retraction" for s in clean.steps)
    assert any(s.label_key == "readingPath.retraction" for s in retracted.steps)


def test_labels_are_i18n_keys_rather_than_prose() -> None:
    # Section 25 puts UI strings on the client; a server shipping Japanese sentences would
    # make the API the place translations live.
    paper = _paper()
    route = build_route("overview", paper, _segments(paper), [])

    for step in route.steps:
        assert " " not in step.label_key
        assert "." in step.label_key


def test_an_unknown_purpose_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(ValueError, match="unknown reading purpose"):
        build_route("skim_it", _paper(), [], [])


# ------------------------------------------------------------------ against the database


@pytest.mark.integration
@requires_db
def test_all_four_routes_come_back_for_a_stored_paper(db_session: Session) -> None:
    paper = _paper(canonical_id=f"test:route-{uuid.uuid4()}")
    db_session.add(paper)
    db_session.flush()
    for segment in _segments(paper):
        db_session.add(segment)
    db_session.add(_equation(paper, "7"))
    db_session.flush()

    routes = routes_for(db_session, paper)

    assert [route.purpose for route in routes] == list(READING_PURPOSES)
    maths = next(route for route in routes if route.purpose == "follow_math")
    assert any(step.kind == "equation" for step in maths.steps)


@pytest.mark.integration
@requires_db
def test_the_endpoint_offers_every_purpose(client: TestClient, db_session: Session) -> None:
    response = client.post("/auth/guest", json={"locale": "ja-JP", "timezone": "Asia/Tokyo"})
    headers = {"Authorization": f"Bearer {response.json()['accessToken']}"}

    paper = _paper(canonical_id=f"test:route-http-{uuid.uuid4()}")
    db_session.add(paper)
    db_session.flush()
    for segment in _segments(paper):
        db_session.add(segment)
    db_session.commit()

    body = client.get(f"/papers/{paper.id}/reading-path", headers=headers).json()

    assert [route["purpose"] for route in body["routes"]] == list(READING_PURPOSES)
    overview = body["routes"][0]
    assert overview["steps"][0]["labelKey"] == "section.background"
    assert overview["steps"][-1]["held"] is False


@pytest.mark.integration
@requires_db
def test_an_unknown_paper_has_no_reading_path(client: TestClient) -> None:
    response = client.post("/auth/guest", json={"locale": "ja-JP", "timezone": "Asia/Tokyo"})
    headers = {"Authorization": f"Bearer {response.json()['accessToken']}"}

    missing = "11111111-1111-4111-8111-111111111111"
    assert client.get(f"/papers/{missing}/reading-path", headers=headers).status_code == 404
