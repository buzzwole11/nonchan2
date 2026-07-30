"""End-to-end swipe, undo and saved-library flow (spec sections 4, 6, 9, 29, 30).

Covers the MVP completion criteria from spec section 29 that concern the deck:
左右スワイプとボタン操作が同等に働く / Undoが機能する / 保存・削除・状態変更が永続化される.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import requires_db

pytestmark = [pytest.mark.e2e, requires_db]


def _auth(client: TestClient) -> dict[str, str]:
    response = client.post("/auth/guest", json={"locale": "ja-JP", "timezone": "Asia/Tokyo"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def _onboard(client: TestClient, headers: dict[str, str]) -> None:
    response = client.put(
        "/me/interests",
        headers=headers,
        json={
            "interests": [
                {"fieldId": "hep-th", "strength": 1.0, "mode": "main"},
                {"fieldId": "cond-mat", "strength": 0.8, "mode": "main"},
            ]
        },
    )
    assert response.status_code == 200, response.text


def _feed(client: TestClient, headers: dict[str, str], **params: object) -> dict:
    response = client.get("/feed", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------- the feed


def test_feed_requires_authentication(client: TestClient, seeded_db: Session) -> None:
    assert client.get("/feed").status_code == 401


def test_feed_cards_carry_a_reason_in_words(client: TestClient, seeded_db: Session) -> None:
    """Spec section 6: 推薦理由は短く説明可能であること。単一の不透明なスコアだけを見せない."""
    headers = _auth(client)
    _onboard(client, headers)
    body = _feed(client, headers, limit=10)

    assert len(body["items"]) == 10
    for item in body["items"]:
        assert item["reasons"], "a card with no stated reason"
        assert item["reasonText"].strip(), "the reason must be readable, not just a code"
        assert item["pool"] in {"matched", "adjacent", "exploration"}
        assert item["paper"]["sourceUrl"].startswith("http")
        assert item["paper"]["provenance"]["licenseId"]


def test_feed_reason_text_follows_the_user_locale(client: TestClient, seeded_db: Session) -> None:
    ja_headers = _auth(client)
    _onboard(client, ja_headers)
    ja = _feed(client, ja_headers, limit=1)["items"][0]["reasonText"]

    en_response = client.post("/auth/guest", json={"locale": "en-US", "timezone": "UTC"})
    en_headers = {"Authorization": f"Bearer {en_response.json()['accessToken']}"}
    _onboard(client, en_headers)
    en = _feed(client, en_headers, limit=1)["items"][0]["reasonText"]

    assert ja != en
    assert any(ord(ch) > 0x3000 for ch in ja), "the Japanese reason should be Japanese"


def test_feed_reports_whether_it_is_serving_cached_content(
    client: TestClient, seeded_db: Session
) -> None:
    headers = _auth(client)
    body = _feed(client, headers, limit=1)
    assert body["degraded"] is False


# ------------------------------------------------------------ impressions and repeats


def test_a_card_that_was_shown_does_not_come_back(client: TestClient, seeded_db: Session) -> None:
    """Spec section 29: 表示履歴により同じ正規論文が再表示されない."""
    headers = _auth(client)
    _onboard(client, headers)

    first = _feed(client, headers, limit=10)
    shown = [item["paper"]["id"] for item in first["items"]]
    response = client.post(
        "/impressions",
        headers=headers,
        json={
            "impressions": [
                {"paperId": paper_id, "position": index, "dwellMs": 2000}
                for index, paper_id in enumerate(shown)
            ]
        },
    )
    assert response.status_code == 201
    assert response.json()["recorded"] == 10

    second = _feed(client, headers, limit=10)
    assert not set(shown) & {item["paper"]["id"] for item in second["items"]}


def test_reposting_an_impression_updates_rather_than_duplicates(
    client: TestClient, seeded_db: Session
) -> None:
    headers = _auth(client)
    paper_id = _feed(client, headers, limit=1)["items"][0]["paper"]["id"]

    for dwell in (500, 7000):
        response = client.post(
            "/impressions",
            headers=headers,
            json={"impressions": [{"paperId": paper_id, "dwellMs": dwell}]},
        )
        assert response.status_code == 201
        assert response.json()["recorded"] == 1


def test_an_impression_for_an_unknown_paper_is_rejected(
    client: TestClient, seeded_db: Session
) -> None:
    headers = _auth(client)
    response = client.post(
        "/impressions",
        headers=headers,
        json={"impressions": [{"paperId": "00000000-0000-4000-8000-000000000000"}]},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "paper_not_found"


# ------------------------------------------------------------------- swipe and buttons


def test_right_swipe_saves_and_left_swipe_skips(client: TestClient, seeded_db: Session) -> None:
    headers = _auth(client)
    _onboard(client, headers)
    items = _feed(client, headers, limit=2)["items"]
    save_id, skip_id = items[0]["paper"]["id"], items[1]["paper"]["id"]

    save = client.post(
        "/actions",
        headers=headers,
        json={"type": "save", "paperId": save_id, "payload": {"reasons": ["read_later"]}},
    )
    assert save.status_code == 201, save.text
    assert save.json()["saved"]["reasons"] == ["read_later"]
    assert save.json()["saved"]["status"] == "unread"

    skip = client.post("/actions", headers=headers, json={"type": "skip", "paperId": skip_id})
    assert skip.status_code == 201
    assert skip.json()["saved"] is None

    saved_ids = {
        entry["savedPaper"]["paperId"]
        for entry in client.get("/saved", headers=headers).json()["saved"]
    }
    assert saved_ids == {save_id}


def test_the_button_path_and_the_swipe_path_agree(client: TestClient, seeded_db: Session) -> None:
    """Spec section 29: 左右スワイプとボタン操作が同等に働く.

    The deck swipe posts an action; the card's Save button posts to /saved. Both must end
    with the same saved row *and* the same undo history, or Undo would behave differently
    depending on how the user saved.
    """
    headers = _auth(client)
    _onboard(client, headers)
    items = _feed(client, headers, limit=2)["items"]
    via_swipe, via_button = items[0]["paper"]["id"], items[1]["paper"]["id"]

    client.post(
        "/actions",
        headers=headers,
        json={"type": "save", "paperId": via_swipe, "payload": {"reasons": ["math"]}},
    )
    button = client.post(f"/saved/{via_button}", headers=headers, json={"reasons": ["math"]})
    assert button.status_code == 201, button.text

    saved = {
        entry["savedPaper"]["paperId"]: entry["savedPaper"]
        for entry in client.get("/saved", headers=headers).json()["saved"]
    }
    assert set(saved) == {via_swipe, via_button}
    assert saved[via_swipe]["reasons"] == saved[via_button]["reasons"] == ["math"]

    # Both are undoable, and the most recent undoable action is the button save.
    undoable = client.get("/actions/undoable", headers=headers).json()
    assert undoable["action"]["type"] == "save"
    assert undoable["action"]["paperId"] == via_button


def test_saving_twice_merges_reasons_instead_of_failing(
    client: TestClient, seeded_db: Session
) -> None:
    headers = _auth(client)
    paper_id = _feed(client, headers, limit=1)["items"][0]["paper"]["id"]

    client.post(f"/saved/{paper_id}", headers=headers, json={"reasons": ["math"]})
    second = client.post(
        f"/saved/{paper_id}", headers=headers, json={"reasons": ["english_expression"]}
    )
    assert second.status_code == 201
    assert second.json()["savedPaper"]["reasons"] == ["math", "english_expression"]


def test_an_invalid_save_reason_is_rejected(client: TestClient, seeded_db: Session) -> None:
    headers = _auth(client)
    paper_id = _feed(client, headers, limit=1)["items"][0]["paper"]["id"]
    response = client.post(f"/saved/{paper_id}", headers=headers, json={"reasons": ["because"]})
    assert response.status_code == 422


# ------------------------------------------------------------------------------- undo


def test_undoing_a_skip_brings_the_card_back(client: TestClient, seeded_db: Session) -> None:
    """Spec section 29: Undoが機能する.

    "Works" has to mean the card actually returns to the deck — reversing the log alone
    would leave the user staring at a paper they just recovered but can never see.
    """
    headers = _auth(client)
    _onboard(client, headers)
    paper_id = _feed(client, headers, limit=1)["items"][0]["paper"]["id"]

    client.post("/impressions", headers=headers, json={"impressions": [{"paperId": paper_id}]})
    skip = client.post("/actions", headers=headers, json={"type": "skip", "paperId": paper_id})
    action_id = skip.json()["action"]["id"]

    gone = {item["paper"]["id"] for item in _feed(client, headers, limit=50)["items"]}
    assert paper_id not in gone

    undo = client.post(f"/actions/{action_id}/undo", headers=headers)
    assert undo.status_code == 201, undo.text
    assert undo.json()["restoredPaperId"] == paper_id
    assert undo.json()["undo"]["type"] == "undo"

    back = {item["paper"]["id"] for item in _feed(client, headers, limit=50)["items"]}
    assert paper_id in back


def test_undoing_a_save_removes_it_from_the_library(client: TestClient, seeded_db: Session) -> None:
    headers = _auth(client)
    _onboard(client, headers)
    paper_id = _feed(client, headers, limit=1)["items"][0]["paper"]["id"]

    save = client.post("/actions", headers=headers, json={"type": "save", "paperId": paper_id})
    action_id = save.json()["action"]["id"]
    assert client.get("/saved", headers=headers).json()["total"] == 1

    undo = client.post(f"/actions/{action_id}/undo", headers=headers)
    assert undo.status_code == 201
    assert client.get("/saved", headers=headers).json()["total"] == 0


def test_undoing_twice_is_refused_rather_than_reversing_the_previous_action(
    client: TestClient, seeded_db: Session
) -> None:
    headers = _auth(client)
    paper_id = _feed(client, headers, limit=1)["items"][0]["paper"]["id"]
    action_id = client.post(
        "/actions", headers=headers, json={"type": "skip", "paperId": paper_id}
    ).json()["action"]["id"]

    assert client.post(f"/actions/{action_id}/undo", headers=headers).status_code == 201
    second = client.post(f"/actions/{action_id}/undo", headers=headers)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "already_undone"


def test_an_undo_cannot_itself_be_undone(client: TestClient, seeded_db: Session) -> None:
    headers = _auth(client)
    paper_id = _feed(client, headers, limit=1)["items"][0]["paper"]["id"]
    action_id = client.post(
        "/actions", headers=headers, json={"type": "skip", "paperId": paper_id}
    ).json()["action"]["id"]
    undo_id = client.post(f"/actions/{action_id}/undo", headers=headers).json()["undo"]["id"]

    response = client.post(f"/actions/{undo_id}/undo", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "cannot_undo_undo"


def test_undo_cannot_reach_another_users_action(client: TestClient, seeded_db: Session) -> None:
    owner = _auth(client)
    paper_id = _feed(client, owner, limit=1)["items"][0]["paper"]["id"]
    action_id = client.post(
        "/actions", headers=owner, json={"type": "skip", "paperId": paper_id}
    ).json()["action"]["id"]

    intruder = _auth(client)
    response = client.post(f"/actions/{action_id}/undo", headers=intruder)
    assert response.status_code == 404


def test_no_undoable_action_returns_null(client: TestClient, seeded_db: Session) -> None:
    headers = _auth(client)
    assert client.get("/actions/undoable", headers=headers).json() is None


# ----------------------------------------------------------------------- saved library


def test_saved_status_changes_persist(client: TestClient, seeded_db: Session) -> None:
    """Spec section 29: 保存・削除・状態変更が永続化される."""
    headers = _auth(client)
    paper_id = _feed(client, headers, limit=1)["items"][0]["paper"]["id"]
    client.post(f"/saved/{paper_id}", headers=headers, json={})

    patched = client.patch(
        f"/saved/{paper_id}",
        headers=headers,
        json={"status": "abstract_done", "notes": "式(7)を後で追う", "priority": 3},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["savedPaper"]["status"] == "abstract_done"
    assert patched.json()["savedPaper"]["lastVisitedAt"] is not None

    entry = client.get("/saved", headers=headers).json()["saved"][0]["savedPaper"]
    assert entry["status"] == "abstract_done"
    assert entry["notes"] == "式(7)を後で追う"
    assert entry["priority"] == 3


def test_saved_can_be_removed(client: TestClient, seeded_db: Session) -> None:
    headers = _auth(client)
    paper_id = _feed(client, headers, limit=1)["items"][0]["paper"]["id"]
    client.post(f"/saved/{paper_id}", headers=headers, json={})

    assert client.delete(f"/saved/{paper_id}", headers=headers).status_code == 204
    assert client.get("/saved", headers=headers).json()["total"] == 0
    assert client.delete(f"/saved/{paper_id}", headers=headers).status_code == 404


def test_saved_list_filters_and_sorts(client: TestClient, seeded_db: Session) -> None:
    headers = _auth(client)
    _onboard(client, headers)
    items = _feed(client, headers, limit=4)["items"]
    ids = [item["paper"]["id"] for item in items]

    client.post(f"/saved/{ids[0]}", headers=headers, json={"reasons": ["math"]})
    client.post(f"/saved/{ids[1]}", headers=headers, json={"reasons": ["english_expression"]})
    client.post(f"/saved/{ids[2]}", headers=headers, json={"reasons": ["math", "read_later"]})
    client.patch(f"/saved/{ids[2]}", headers=headers, json={"status": "finished"})

    by_reason = client.get("/saved", headers=headers, params={"reason": "math"}).json()
    assert {e["savedPaper"]["paperId"] for e in by_reason["saved"]} == {ids[0], ids[2]}

    by_status = client.get("/saved", headers=headers, params={"status": "finished"}).json()
    assert [e["savedPaper"]["paperId"] for e in by_status["saved"]] == [ids[2]]

    by_year = client.get("/saved", headers=headers, params={"sort": "year"}).json()["saved"]
    years = [e["paper"]["year"] for e in by_year]
    assert years == sorted(years, reverse=True)


def test_an_unknown_sort_key_is_rejected(client: TestClient, seeded_db: Session) -> None:
    headers = _auth(client)
    response = client.get("/saved", headers=headers, params={"sort": "vibes"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_sort"


def test_saved_paging_covers_everything_once(client: TestClient, seeded_db: Session) -> None:
    headers = _auth(client)
    _onboard(client, headers)
    for item in _feed(client, headers, limit=7)["items"]:
        client.post(f"/saved/{item['paper']['id']}", headers=headers, json={})

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        params: dict[str, object] = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = client.get("/saved", headers=headers, params=params).json()
        seen.extend(e["savedPaper"]["paperId"] for e in body["saved"])
        cursor = body["nextCursor"]
        if cursor is None:
            break

    assert len(seen) == 7
    assert len(set(seen)) == 7


def test_one_users_library_is_invisible_to_another(client: TestClient, seeded_db: Session) -> None:
    owner = _auth(client)
    paper_id = _feed(client, owner, limit=1)["items"][0]["paper"]["id"]
    client.post(f"/saved/{paper_id}", headers=owner, json={})

    intruder = _auth(client)
    assert client.get("/saved", headers=intruder).json()["total"] == 0
    assert (
        client.patch(
            f"/saved/{paper_id}", headers=intruder, json={"status": "finished"}
        ).status_code
        == 404
    )


# --------------------------------------------------------------------------- feedback


def test_hiding_a_topic_from_a_card_uses_that_cards_field(
    client: TestClient, seeded_db: Session
) -> None:
    """Spec section 16: 否定的フィードバックを「嫌い」と決めつけない — it is a scoped, reversible
    "less of this", which is why it is an ordinary undoable action."""
    headers = _auth(client)
    _onboard(client, headers)
    card = _feed(client, headers, limit=1)["items"][0]
    field_id = card["paper"]["primaryFieldId"]

    response = client.post(
        "/actions", headers=headers, json={"type": "hide_topic", "paperId": card["paper"]["id"]}
    )
    assert response.status_code == 201
    assert response.json()["action"]["payload"]["fieldId"] == field_id

    following = _feed(client, headers, limit=30)["items"]
    assert all(item["paper"]["primaryFieldId"] != field_id for item in following)


def test_hide_topic_without_a_field_or_paper_is_rejected(
    client: TestClient, seeded_db: Session
) -> None:
    headers = _auth(client)
    response = client.post("/actions", headers=headers, json={"type": "hide_topic"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "field_required"


def test_undo_is_not_accepted_as_an_ordinary_action(client: TestClient, seeded_db: Session) -> None:
    headers = _auth(client)
    response = client.post("/actions", headers=headers, json={"type": "undo"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "use_undo_endpoint"
