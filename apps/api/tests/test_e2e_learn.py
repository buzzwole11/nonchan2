"""End-to-end learning flow (spec sections 7, 8, 9, 30).

Reading an abstract → saving an expression from it → meeting it again days later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import ExpressionCard
from tests.conftest import requires_db

pytestmark = [pytest.mark.e2e, requires_db]


def _auth(client: TestClient) -> dict[str, str]:
    response = client.post("/auth/guest", json={"locale": "ja-JP", "timezone": "Asia/Tokyo"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def _a_paper(client: TestClient) -> dict:
    return client.get("/papers", params={"limit": 1}).json()["papers"][0]


# ----------------------------------------------------------------------- structure


def test_abstracts_carry_their_structure_and_say_how_it_was_found(
    client: TestClient, seeded_db: Session
) -> None:
    """Spec section 8: 自動検出ラベルを付け、原文を変更しない."""
    paper_id = _a_paper(client)["id"]
    body = client.get(f"/papers/{paper_id}").json()

    segments = body["abstractSegments"]
    assert segments
    for segment in segments:
        assert segment["section"] in {
            "background",
            "problem",
            "method",
            "result",
            "significance",
        }
        assert segment["detectedBy"] in {"source", "heuristic", "ai", "human"}
        # Offsets must point into the untouched original.
        assert body["abstract"][segment["start"] : segment["end"]].strip()


# ---------------------------------------------------------------------- expressions


def test_saving_an_expression_from_a_paper_keeps_its_context(
    client: TestClient, seeded_db: Session
) -> None:
    headers = _auth(client)
    paper = _a_paper(client)
    sentence = paper["abstract"].split(". ")[0] + "."

    response = client.post(
        "/expressions",
        headers=headers,
        json={
            "phrase": "break down",
            "meaning": "成り立たなくなる",
            "context": sentence,
            "sourcePaperId": paper["id"],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created"] is True
    assert body["expression"]["kind"] == "collocation"
    assert body["expression"]["context"] == sentence
    assert body["expression"]["nextReviewAt"] is not None


def test_saving_the_same_phrase_again_reports_that_it_already_existed(
    client: TestClient, seeded_db: Session
) -> None:
    headers = _auth(client)
    client.post("/expressions", headers=headers, json={"phrase": "break down", "meaning": "—"})
    second = client.post(
        "/expressions",
        headers=headers,
        json={"phrase": "break down", "meaning": "—", "example": "another use"},
    )
    assert second.status_code == 201
    assert second.json()["created"] is False
    assert second.json()["expression"]["examples"] == ["another use"]


def test_expressions_list_filters_by_kind(client: TestClient, seeded_db: Session) -> None:
    headers = _auth(client)
    client.post(
        "/expressions", headers=headers, json={"phrase": "renormalisation", "meaning": "繰り込み"}
    )
    client.post("/expressions", headers=headers, json={"phrase": "break down", "meaning": "—"})

    everything = client.get("/expressions", headers=headers).json()
    assert everything["total"] == 2
    assert everything["dueCount"] == 0

    words = client.get("/expressions", headers=headers, params={"kind": "word"}).json()
    assert words["total"] == 1
    assert words["expressions"][0]["phrase"] == "renormalisation"


def test_an_unknown_kind_is_rejected(client: TestClient, seeded_db: Session) -> None:
    headers = _auth(client)
    response = client.post(
        "/expressions", headers=headers, json={"phrase": "x y", "meaning": "—", "kind": "idiom"}
    )
    assert response.status_code == 422


def test_an_empty_phrase_is_rejected(client: TestClient, seeded_db: Session) -> None:
    headers = _auth(client)
    assert (
        client.post(
            "/expressions", headers=headers, json={"phrase": "", "meaning": "—"}
        ).status_code
        == 422
    )


def test_expressions_require_authentication(client: TestClient, seeded_db: Session) -> None:
    assert client.get("/expressions").status_code == 401
    assert client.post("/expressions", json={"phrase": "x", "meaning": "y"}).status_code == 401


def test_an_expression_can_be_deleted(client: TestClient, seeded_db: Session) -> None:
    headers = _auth(client)
    created = client.post(
        "/expressions", headers=headers, json={"phrase": "break down", "meaning": "—"}
    ).json()["expression"]

    assert client.delete(f"/expressions/{created['id']}", headers=headers).status_code == 204
    assert client.get("/expressions", headers=headers).json()["total"] == 0
    assert client.delete(f"/expressions/{created['id']}", headers=headers).status_code == 404


# --------------------------------------------------------------------------- review


def test_nothing_is_due_the_moment_it_is_saved(client: TestClient, seeded_db: Session) -> None:
    headers = _auth(client)
    client.post("/expressions", headers=headers, json={"phrase": "break down", "meaning": "—"})

    queue = client.get("/learn/review", headers=headers).json()
    assert queue["due"] == []
    assert queue["totalDue"] == 0


def test_an_expression_comes_back_after_a_few_days(client: TestClient, seeded_db: Session) -> None:
    """Spec section 9: 数日後に保存論文の表現を1件提示 — the point of saving at all."""
    headers = _auth(client)
    created = client.post(
        "/expressions",
        headers=headers,
        json={"phrase": "break down", "meaning": "成り立たなくなる"},
    ).json()["expression"]

    # Wind the clock forward by moving the due date back, which is what elapsed time does.
    row = seeded_db.execute(
        select(ExpressionCard).where(ExpressionCard.id == created["id"])
    ).scalar_one()
    row.next_review_at = datetime.now(tz=UTC) - timedelta(hours=1)
    seeded_db.flush()

    queue = client.get("/learn/review", headers=headers).json()
    assert queue["totalDue"] == 1
    assert queue["due"][0]["phrase"] == "break down"
    assert queue["due"][0]["meaning"] == "成り立たなくなる"


def test_answering_got_it_pushes_the_next_showing_further_out(
    client: TestClient, seeded_db: Session
) -> None:
    headers = _auth(client)
    created = client.post(
        "/expressions", headers=headers, json={"phrase": "break down", "meaning": "—"}
    ).json()["expression"]
    first_due = created["nextReviewAt"]

    response = client.post(
        f"/learn/review/{created['id']}", headers=headers, json={"outcome": "got_it"}
    )
    assert response.status_code == 200, response.text
    reviewed = response.json()["expression"]
    assert reviewed["reviewCount"] == 1
    assert reviewed["nextReviewAt"] > first_due
    assert reviewed["lastReviewedAt"] is not None


def test_answering_again_keeps_the_entry_but_does_not_punish(
    client: TestClient, seeded_db: Session
) -> None:
    headers = _auth(client)
    created = client.post(
        "/expressions", headers=headers, json={"phrase": "break down", "meaning": "—"}
    ).json()["expression"]

    for _ in range(2):
        client.post(f"/learn/review/{created['id']}", headers=headers, json={"outcome": "got_it"})
    after_again = client.post(
        f"/learn/review/{created['id']}", headers=headers, json={"outcome": "again"}
    ).json()["expression"]

    assert after_again["reviewCount"] == 1, "one miss should cost one rung, not everything"


def test_an_unknown_outcome_is_rejected(client: TestClient, seeded_db: Session) -> None:
    headers = _auth(client)
    created = client.post(
        "/expressions", headers=headers, json={"phrase": "break down", "meaning": "—"}
    ).json()["expression"]
    response = client.post(
        f"/learn/review/{created['id']}", headers=headers, json={"outcome": "perfect"}
    )
    assert response.status_code == 422


def test_reviewing_another_users_expression_is_a_404(
    client: TestClient, seeded_db: Session
) -> None:
    owner = _auth(client)
    created = client.post(
        "/expressions", headers=owner, json={"phrase": "break down", "meaning": "—"}
    ).json()["expression"]

    intruder = _auth(client)
    response = client.post(
        f"/learn/review/{created['id']}", headers=intruder, json={"outcome": "got_it"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "expression_not_found"


def test_the_review_queue_stays_small_by_default(client: TestClient, seeded_db: Session) -> None:
    """Spec section 9 asks for a nudge, not a backlog."""
    headers = _auth(client)
    past = datetime.now(tz=UTC) - timedelta(days=1)
    for index in range(8):
        created = client.post(
            "/expressions", headers=headers, json={"phrase": f"term {index}", "meaning": "—"}
        ).json()["expression"]
        row = seeded_db.execute(
            select(ExpressionCard).where(ExpressionCard.id == created["id"])
        ).scalar_one()
        row.next_review_at = past
    seeded_db.flush()

    queue = client.get("/learn/review", headers=headers).json()
    assert len(queue["due"]) == 5, "the default page is a handful"
    assert queue["totalDue"] == 8, "but the count is honest about the backlog"
