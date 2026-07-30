"""Maths cards over HTTP (spec sections 10, 11, 12, 24).

The unit tests decide what a status means; these decide what a client can see. The two
things worth pinning down at this boundary are that an unverified step never arrives
unasked, and that a formula the renderer must refuse still arrives — as source, flagged —
rather than vanishing.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import DerivationStep, Equation, MathCard
from papermatch_api.services.math_content import load_math_cards
from tests.conftest import FIXTURES_DIR, requires_db


def _loaded(db: Session) -> Session:
    load_math_cards(db, FIXTURES_DIR)
    db.flush()
    return db


def _first_card(db: Session) -> MathCard:
    card = db.execute(select(MathCard)).scalars().first()
    assert card is not None
    return card


@requires_db
def test_the_card_list_comes_back(client: TestClient, seeded_db: Session) -> None:
    _loaded(seeded_db)
    response = client.get("/math-cards")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 5
    assert {c["cardType"] for c in body["cards"]} >= {"derivation", "consistency_check"}


@requires_db
def test_the_list_can_be_filtered_by_card_type(client: TestClient, seeded_db: Session) -> None:
    """Spec section 10 lists seven card types; a reader looking for a derivation should
    not have to page past definitions."""
    _loaded(seeded_db)
    body = client.get("/math-cards", params={"cardType": "derivation"}).json()
    assert body["cards"]
    assert {c["cardType"] for c in body["cards"]} == {"derivation"}


@requires_db
def test_a_card_arrives_with_everything_focus_mode_needs(
    client: TestClient, seeded_db: Session
) -> None:
    """Section 10's tabs are views onto one fetched card, not four requests."""
    _loaded(seeded_db)
    card = (
        seeded_db.execute(select(MathCard).where(MathCard.card_type == "derivation"))
        .scalars()
        .first()
    )
    assert card is not None

    body = client.get(f"/math-cards/{card.id}").json()
    assert body["card"]["title"]
    assert len(body["equations"]) >= 2
    assert body["steps"], "a derivation card with no steps is not a derivation"
    # 記号 tab.
    assert any(e["symbols"] for e in body["equations"])
    symbol = next(s for e in body["equations"] for s in e["symbols"])
    assert symbol["localMeaning"]
    assert symbol["scope"] in {"equation", "section", "paper", "field"}


@requires_db
def test_every_step_says_how_it_was_checked(client: TestClient, seeded_db: Session) -> None:
    """A status the client cannot explain to the reader is just a badge."""
    _loaded(seeded_db)
    card = (
        seeded_db.execute(select(MathCard).where(MathCard.card_type == "derivation"))
        .scalars()
        .first()
    )
    assert card is not None

    for step in client.get(f"/math-cards/{card.id}").json()["steps"]:
        assert step["verificationStatus"] != "unverified"
        assert step["evidence"] is not None
        assert step["evidence"]["status"] == step["verificationStatus"]
        assert step["rationale"], "section 10 puts a Why? behind every operation"


@requires_db
def test_an_unverified_step_is_withheld_and_counted(client: TestClient, seeded_db: Session) -> None:
    """Spec section 12: 未検証の変形は既定で非表示.

    Counted rather than silently dropped — a derivation that is missing a step without
    saying so looks complete and is not.
    """
    _loaded(seeded_db)
    step = (
        seeded_db.execute(
            select(DerivationStep).where(DerivationStep.verification_status == "unverified")
        )
        .scalars()
        .first()
    )
    assert step is not None
    card = _card_owning(seeded_db, step)

    default = client.get(f"/math-cards/{card.id}").json()
    assert default["steps"] == []
    assert default["hiddenStepCount"] == 1

    asked = client.get(f"/math-cards/{card.id}", params={"includeUnverified": True}).json()
    assert len(asked["steps"]) == 1
    assert asked["steps"][0]["verificationStatus"] == "unverified"
    assert asked["hiddenStepCount"] == 0


@requires_db
def test_an_unverified_step_arrives_labelled_when_it_is_asked_for(
    client: TestClient, seeded_db: Session
) -> None:
    """Section 11: 色だけでなくアイコンと文字ラベル. The label has to be in the payload
    before the UI can show it."""
    _loaded(seeded_db)
    step = (
        seeded_db.execute(
            select(DerivationStep).where(DerivationStep.verification_status == "unverified")
        )
        .scalars()
        .first()
    )
    assert step is not None
    card = _card_owning(seeded_db, step)

    body = client.get(f"/math-cards/{card.id}", params={"includeUnverified": True}).json()
    returned = body["steps"][0]
    assert returned["provenanceKind"] == "ai_explanation"
    assert returned["verificationStatus"] == "unverified"


def _card_owning(db: Session, step: DerivationStep) -> MathCard:
    for card in db.execute(select(MathCard)).scalars():
        if str(step.from_equation_id) in card.source_equation_ids:
            return card
    raise AssertionError("no card owns that step")


@requires_db
def test_the_server_decides_what_may_be_rendered(client: TestClient, seeded_db: Session) -> None:
    """Spec section 25 keeps that decision on the server. The client is told; it does not
    work it out."""
    _loaded(seeded_db)
    card = _first_card(seeded_db)
    for equation in client.get(f"/math-cards/{card.id}").json()["equations"]:
        assert equation["renderable"] is True
        assert equation["refusalReasons"] == []
        assert equation["latex"]


@requires_db
def test_a_formula_the_renderer_must_refuse_still_arrives_as_source(
    client: TestClient, seeded_db: Session
) -> None:
    """Section 11's fallback is 整形済みLaTeXソースと原文リンク, not an empty space.

    Refusing to typeset is not the same as refusing to send, so the string is still in the
    payload with the reason attached.
    """
    _loaded(seeded_db)
    equation = seeded_db.execute(select(Equation)).scalars().first()
    assert equation is not None
    equation.latex = r"\href{javascript:alert(1)}{x}"
    seeded_db.flush()

    body = client.get(f"/papers/{equation.paper_id}/equations").json()
    found = next(e for e in body["equations"] if e["id"] == str(equation.id))
    assert found["renderable"] is False
    assert "forbidden_command" in found["refusalReasons"]
    assert found["latex"] == r"\href{javascript:alert(1)}{x}"


@requires_db
def test_equations_for_a_paper_are_listed(client: TestClient, seeded_db: Session) -> None:
    _loaded(seeded_db)
    equation = seeded_db.execute(select(Equation)).scalars().first()
    assert equation is not None
    body = client.get(f"/papers/{equation.paper_id}/equations").json()
    assert body["equations"]
    assert all(e["paperId"] == str(equation.paper_id) for e in body["equations"])


@requires_db
def test_an_unknown_paper_is_a_404_not_an_empty_list(
    client: TestClient, seeded_db: Session
) -> None:
    """An empty list would read as "this paper has no equations", which is a different
    statement from "there is no such paper"."""
    response = client.get("/papers/00000000-0000-0000-0000-000000000000/equations")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "paper_not_found"


@requires_db
def test_an_unknown_card_is_a_404(client: TestClient, seeded_db: Session) -> None:
    response = client.get("/math-cards/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "math_card_not_found"


@requires_db
def test_nothing_in_the_payload_claims_a_human_reviewed_it(
    client: TestClient, seeded_db: Session
) -> None:
    """No human has reviewed this corpus. The API must not imply otherwise."""
    _loaded(seeded_db)
    for summary in client.get("/math-cards").json()["cards"]:
        assert summary["reviewStatus"] == "draft"
        detail: dict[str, Any] = client.get(f"/math-cards/{summary['id']}").json()
        for equation in detail["equations"]:
            assert equation["verificationStatus"] != "human_reviewed"
            assert equation["provenanceKind"] != "human_reviewed"
        for step in detail["steps"]:
            assert step["verificationStatus"] != "human_reviewed"
