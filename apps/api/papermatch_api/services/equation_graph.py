"""The formula knowledge graph (spec section 28, Phase 7).

Nodes are equations. Edges are the two ways one equation actually depends on another in the
data we hold:

* **`defines`** — a symbol used in equation B is defined in equation A. This comes from
  `EquationSymbol.defined_in_equation_id`, which is recorded when the symbol table is built,
  not guessed here.
* **`derives`** — a `DerivationStep` transforms A into B, with the operation it performed.

**No edge is inferred from two equations looking alike.** The same rule as section 17's
relations, for the same reason: an edge saying "this follows from that" is a mathematical
claim, and sharing a `\\lambda` is not evidence for it. Every edge here traces to a row
somebody or something wrote down deliberately.

**Every edge carries its verification status.** A derivation step that was never verified is
still part of the graph — hiding it would leave a gap the reader cannot see — but it is
labelled, so nothing in the picture implies more confidence than the step earned (section
12). The client draws the two differently.

**Symbols shared without a definition are not edges.** Two equations both using `n` are not
connected by that; `n` is the size of everything. Only a recorded definition creates the
link, which is why the graph of a paper with no symbol table is edgeless rather than
complete.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import DerivationStep, Equation, EquationSymbol

__all__ = [
    "EquationEdge",
    "EquationGraph",
    "EquationNode",
    "build_graph",
    "graph_for_paper",
]


@dataclass(frozen=True)
class EquationNode:
    equation_id: uuid.UUID
    latex: str
    equation_number: str | None
    section: str | None
    provenance_kind: str
    verification_status: str


@dataclass(frozen=True)
class EquationEdge:
    from_equation_id: uuid.UUID
    to_equation_id: uuid.UUID
    #: `defines` or `derives`.
    kind: str
    #: The symbol, for a `defines` edge; the operation, for a `derives` one.
    label: str
    verification_status: str
    provenance_kind: str


@dataclass(frozen=True)
class EquationGraph:
    nodes: list[EquationNode] = field(default_factory=list)
    edges: list[EquationEdge] = field(default_factory=list)
    #: Nodes with no edge at all, named so the client can say why they float alone.
    isolated: list[uuid.UUID] = field(default_factory=list)


def build_graph(
    equations: list[Equation],
    symbols: list[EquationSymbol],
    steps: list[DerivationStep],
) -> EquationGraph:
    """Assemble the graph from rows that were written down, never from resemblance."""
    known = {equation.id for equation in equations}
    nodes = [
        EquationNode(
            equation_id=equation.id,
            latex=equation.latex,
            equation_number=equation.equation_number,
            section=equation.section,
            provenance_kind=equation.provenance_kind,
            verification_status=equation.verification_status,
        )
        for equation in equations
    ]

    edges: list[EquationEdge] = []

    for symbol in symbols:
        source = symbol.defined_in_equation_id
        # An edge to an equation outside this graph would draw a line to nothing. A symbol
        # defined in another paper is real, and it is not part of this picture.
        if source is None or source not in known or symbol.equation_id not in known:
            continue
        # A symbol defined in the same equation it appears in is a definition, not a
        # dependency; a self-loop here would clutter the picture and say nothing.
        if source == symbol.equation_id:
            continue
        edges.append(
            EquationEdge(
                from_equation_id=source,
                to_equation_id=symbol.equation_id,
                kind="defines",
                label=symbol.symbol,
                # A symbol table entry is as verified as the equation it was read from; it
                # carries no verification of its own, so this states the honest default.
                verification_status="source_exact"
                if symbol.provenance_kind == "original"
                else "unverified",
                provenance_kind=symbol.provenance_kind,
            )
        )

    for step in steps:
        if step.from_equation_id not in known or step.to_equation_id not in known:
            continue
        edges.append(
            EquationEdge(
                from_equation_id=step.from_equation_id,
                to_equation_id=step.to_equation_id,
                kind="derives",
                label=step.operation,
                # Carried, not filtered on. A gap where an unverified step was is a gap the
                # reader cannot see; a labelled edge is one they can judge (section 12).
                verification_status=step.verification_status,
                provenance_kind=step.provenance_kind,
            )
        )

    touched = {edge.from_equation_id for edge in edges} | {edge.to_equation_id for edge in edges}
    isolated = [node.equation_id for node in nodes if node.equation_id not in touched]

    return EquationGraph(nodes=nodes, edges=edges, isolated=isolated)


def graph_for_paper(session: Session, paper_id: uuid.UUID) -> EquationGraph:
    equations = list(
        session.execute(
            select(Equation)
            .where(Equation.paper_id == paper_id)
            .order_by(Equation.created_at, Equation.id)
        ).scalars()
    )
    if not equations:
        return EquationGraph()

    ids = [equation.id for equation in equations]
    symbols = list(
        session.execute(select(EquationSymbol).where(EquationSymbol.equation_id.in_(ids))).scalars()
    )
    steps = list(
        session.execute(
            select(DerivationStep).where(DerivationStep.from_equation_id.in_(ids))
        ).scalars()
    )
    return build_graph(equations, symbols, steps)
