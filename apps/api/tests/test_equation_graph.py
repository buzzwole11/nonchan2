"""The formula knowledge graph (spec section 28, Phase 7).

An edge here says "this equation follows from that one". That is a mathematical claim, so
most of these tests are about edges the graph must *not* draw.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from papermatch_api.models import DerivationStep, Equation, EquationSymbol, Paper
from papermatch_api.services.equation_graph import build_graph, graph_for_paper
from tests.conftest import requires_db


def _equation(latex: str, number: str | None = None, **overrides: object) -> Equation:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "paper_id": uuid.uuid4(),
        "latex": latex,
        "equation_number": number,
        "section": "3",
        "display": True,
        "provenance_kind": "original",
        "verification_status": "source_exact",
    }
    defaults.update(overrides)
    return Equation(**defaults)


def _symbol(
    symbol: str, equation: Equation, defined_in: Equation | None, kind: str = "original"
) -> EquationSymbol:
    return EquationSymbol(
        id=uuid.uuid4(),
        equation_id=equation.id,
        symbol=symbol,
        local_meaning="the thing",
        defined_in_equation_id=None if defined_in is None else defined_in.id,
        provenance_kind=kind,
    )


def _step(
    source: Equation, target: Equation, operation: str, status: str = "mechanically_verified"
) -> DerivationStep:
    return DerivationStep(
        id=uuid.uuid4(),
        from_equation_id=source.id,
        to_equation_id=target.id,
        latex=target.latex,
        operation=operation,
        verification_status=status,
        provenance_kind="verified_step",
    )


# ------------------------------------------------------------------ what is never an edge


def test_two_equations_sharing_a_letter_are_not_connected() -> None:
    # `n` is the size of everything. An edge on that basis would claim a dependency the
    # paper never stated.
    first = _equation(r"a_n = n^2")
    second = _equation(r"b_n = 2n")

    graph = build_graph([first, second], [_symbol("n", second, None)], [])

    assert graph.edges == []
    assert set(graph.isolated) == {first.id, second.id}


def test_a_symbol_defined_elsewhere_creates_no_dangling_edge() -> None:
    # Defined in another paper's equation: real, and not part of this picture. Drawing it
    # would put a line to a node that is not on screen.
    outside = _equation(r"\lambda = 1")
    inside = _equation(r"t = 1/\lambda")

    graph = build_graph([inside], [_symbol(r"\lambda", inside, outside)], [])

    assert graph.edges == []


def test_a_symbol_defined_in_its_own_equation_is_not_a_self_loop() -> None:
    equation = _equation(r"\lambda := \inf \sigma(L)")

    graph = build_graph([equation], [_symbol(r"\lambda", equation, equation)], [])

    assert graph.edges == []


def test_a_paper_with_no_symbol_table_is_edgeless_rather_than_complete() -> None:
    first = _equation(r"a = 1")
    second = _equation(r"b = 2")

    graph = build_graph([first, second], [], [])

    assert graph.edges == []
    assert len(graph.nodes) == 2


# ------------------------------------------------------------------ the edges that exist


def test_a_defined_symbol_links_the_two_equations() -> None:
    definition = _equation(r"\lambda := \inf \sigma(L)", "3")
    use = _equation(r"t_{\mathrm{mix}} = 1/(2\lambda)", "7")

    graph = build_graph([definition, use], [_symbol(r"\lambda", use, definition)], [])

    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert edge.kind == "defines"
    assert edge.label == r"\lambda"
    assert edge.from_equation_id == definition.id
    assert edge.to_equation_id == use.id


def test_a_derivation_step_links_the_two_equations_with_its_operation() -> None:
    before = _equation(r"x = y + z")
    after = _equation(r"x - z = y")

    graph = build_graph([before, after], [], [_step(before, after, "subtract z")])

    assert len(graph.edges) == 1
    assert graph.edges[0].kind == "derives"
    assert graph.edges[0].label == "subtract z"


def test_an_unverified_step_is_kept_and_labelled_rather_than_dropped() -> None:
    # Dropping it leaves a gap the reader cannot see; labelling it leaves one they can judge
    # (section 12).
    before = _equation(r"x = y")
    after = _equation(r"x^2 = y^2")

    graph = build_graph([before, after], [], [_step(before, after, "square", "unverified")])

    assert len(graph.edges) == 1
    assert graph.edges[0].verification_status == "unverified"


def test_an_equation_with_no_edges_is_named_as_isolated() -> None:
    # So the client can say why it stands alone rather than leaving a stray dot.
    linked_from = _equation(r"a = 1")
    linked_to = _equation(r"b = a")
    alone = _equation(r"c = 3")

    graph = build_graph([linked_from, linked_to, alone], [_symbol("a", linked_to, linked_from)], [])

    assert graph.isolated == [alone.id]


def test_an_ai_authored_symbol_edge_is_not_marked_verified() -> None:
    definition = _equation(r"\lambda := 1")
    use = _equation(r"t = 1/\lambda")

    graph = build_graph(
        [definition, use], [_symbol(r"\lambda", use, definition, "ai_explanation")], []
    )

    assert graph.edges[0].verification_status == "unverified"
    assert graph.edges[0].provenance_kind == "ai_explanation"


# ------------------------------------------------------------------ against the database


@pytest.mark.integration
@requires_db
def test_the_graph_of_a_stored_paper(db_session: Session) -> None:
    from datetime import UTC, datetime

    paper = Paper(
        canonical_id=f"test:graph-{uuid.uuid4()}",
        title="A Paper",
        normalized_title="a paper",
        abstract="x",
        authors=[],
        year=2026,
        source_provider="mock",
        source_url="https://example.invalid/1",
        acquired_at=datetime.now(tz=UTC),
    )
    db_session.add(paper)
    db_session.flush()

    definition = _equation(r"\lambda := \inf \sigma(L)", "3", paper_id=paper.id)
    use = _equation(r"t = 1/(2\lambda)", "7", paper_id=paper.id)
    db_session.add_all([definition, use])
    db_session.flush()
    db_session.add(_symbol(r"\lambda", use, definition))
    db_session.add(_step(definition, use, "substitute"))
    db_session.flush()

    graph = graph_for_paper(db_session, paper.id)

    assert len(graph.nodes) == 2
    assert {edge.kind for edge in graph.edges} == {"defines", "derives"}


@pytest.mark.integration
@requires_db
def test_a_paper_with_no_equations_has_an_empty_graph(db_session: Session) -> None:
    assert graph_for_paper(db_session, uuid.uuid4()).nodes == []


@pytest.mark.integration
@requires_db
def test_the_endpoint_returns_nodes_and_edges(client: TestClient, db_session: Session) -> None:
    from datetime import UTC, datetime

    paper = Paper(
        canonical_id=f"test:graph-http-{uuid.uuid4()}",
        title="A Paper",
        normalized_title="a paper",
        abstract="x",
        authors=[],
        year=2026,
        source_provider="mock",
        source_url="https://example.invalid/1",
        acquired_at=datetime.now(tz=UTC),
    )
    db_session.add(paper)
    db_session.flush()
    definition = _equation(r"\lambda := 1", "3", paper_id=paper.id)
    use = _equation(r"t = 1/\lambda", "7", paper_id=paper.id)
    db_session.add_all([definition, use])
    db_session.flush()
    db_session.add(_symbol(r"\lambda", use, definition))
    db_session.commit()

    body = client.get(f"/papers/{paper.id}/equation-graph").json()

    assert len(body["nodes"]) == 2
    assert body["edges"][0]["kind"] == "defines"
    assert body["edges"][0]["label"] == r"\lambda"
