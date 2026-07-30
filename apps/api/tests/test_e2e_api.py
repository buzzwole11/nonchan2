"""End-to-end flow across HTTP and the database (spec section 30, E2E).

Walks the Phase 0 slice of the onboarding path in spec section 4: guest sign-in, settings,
field selection, browsing papers, and translating one selected span. The mobile E2E suite
(Maestro) drives the same endpoints through the UI in Phase 1 — see TASKS.md.
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


def test_health_reports_providers_and_database(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] in {"ok", "degraded"}
    assert set(body["providers"]) == {"paper", "translation"}
    assert body["database"]["connected"] is True


def test_guest_signin_returns_a_usable_token_and_default_settings(client: TestClient) -> None:
    response = client.post("/auth/guest", json={})
    assert response.status_code == 201
    body = response.json()

    assert body["tokenType"] == "bearer"
    assert body["expiresIn"] > 0
    assert body["user"]["isGuest"] is True
    settings = body["user"]["settings"]
    assert settings["canvasStyle"] == "mosaic"
    assert settings["reduceMotion"] is False
    # Spec section 25: the model-improvement opt-in defaults to off.
    assert settings["allowSelectionsForModelImprovement"] is False

    me = client.get("/me", headers={"Authorization": f"Bearer {body['accessToken']}"})
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]


def test_protected_routes_reject_missing_and_invalid_tokens(client: TestClient) -> None:
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_onboarding_flow_persists_interests_and_settings(
    client: TestClient, seeded_db: Session
) -> None:
    headers = _auth(client)

    fields = client.get("/fields").json()["fields"]
    assert len(fields) >= 15
    roots = [f for f in fields if f["parentId"] is None]
    assert {f["id"] for f in roots} == {"physics", "math", "cs"}
    assert any(f["paperCount"] > 0 for f in fields)

    # Onboarding step 1: research fields, with per-field strength (spec section 18).
    response = client.put(
        "/me/interests",
        headers=headers,
        json={
            "interests": [
                {"fieldId": "hep-th", "strength": 1.0, "mode": "main"},
                {"fieldId": "math.AP", "strength": 0.6, "mode": "occasional"},
                {"fieldId": "cs.LG", "strength": 0.3, "mode": "serendipity"},
            ]
        },
    )
    assert response.status_code == 200, response.text
    assert {i["fieldId"] for i in response.json()["interests"]} == {"hep-th", "math.AP", "cs.LG"}

    # Onboarding steps 3-5: English level, maths level, exploration.
    response = client.patch(
        "/me/settings",
        headers=headers,
        json={
            "englishLevel": "intermediate",
            "mathLevel": "level_3",
            "exploration": "adventurous",
            "reduceMotion": True,
            "colorScheme": "dark",
        },
    )
    assert response.status_code == 200
    settings = response.json()["settings"]
    assert settings["mathLevel"] == "level_3"
    assert settings["reduceMotion"] is True
    assert settings["colorScheme"] == "dark"
    # Untouched fields keep their defaults: PATCH is not a replace.
    assert settings["canvasStyle"] == "mosaic"

    assert client.get("/me", headers=headers).json()["settings"]["mathLevel"] == "level_3"


def test_interests_reject_unknown_fields_instead_of_dropping_them(
    client: TestClient, seeded_db: Session
) -> None:
    headers = _auth(client)
    response = client.put(
        "/me/interests",
        headers=headers,
        json={"interests": [{"fieldId": "not-a-field", "strength": 1.0, "mode": "main"}]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_field_ids"


def test_settings_reject_values_outside_the_shared_vocabulary(client: TestClient) -> None:
    headers = _auth(client)
    response = client.patch("/me/settings", headers=headers, json={"mathLevel": "level_9"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_paper_listing_is_paged_deduplicated_and_carries_provenance(
    client: TestClient, seeded_db: Session
) -> None:
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params = {"limit": 10}
        if cursor:
            params["cursor"] = cursor
        body = client.get("/papers", params=params).json()
        for paper in body["papers"]:
            seen.append(paper["canonicalId"])
            assert paper["provenance"]["sourceProvider"]
            assert paper["provenance"]["sourceUrl"].startswith("http")
            # Spec section 29: 原文リンクと出典が表示される.
            assert paper["sourceUrl"].startswith("http")
        cursor = body["nextCursor"]
        if cursor is None:
            break

    assert len(seen) >= 40
    assert len(set(seen)) == len(seen), "the same canonical paper was listed twice"


def test_paper_detail_includes_abstract_structure(client: TestClient, seeded_db: Session) -> None:
    paper_id = client.get("/papers", params={"limit": 1}).json()["papers"][0]["id"]
    body = client.get(f"/papers/{paper_id}").json()

    assert body["abstract"]
    sections = [s["section"] for s in body["abstractSegments"]]
    assert sections == ["background", "problem", "method", "result", "significance"]
    for segment in body["abstractSegments"]:
        assert body["abstract"][segment["start"] : segment["end"]].strip()


def test_unknown_paper_returns_a_structured_404(client: TestClient, seeded_db: Session) -> None:
    response = client.get("/papers/00000000-0000-4000-8000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "paper_not_found"


def _paper_with_math(client: TestClient) -> dict:
    body = client.get("/papers", params={"limit": 100}).json()
    for summary in body["papers"]:
        if "$" in summary["abstract"]:
            return summary
    raise AssertionError("no fixture paper contains inline maths")


def test_selecting_a_span_translates_only_that_span(client: TestClient, seeded_db: Session) -> None:
    """Spec section 7: only the selection is translated, never the whole abstract."""
    headers = _auth(client)
    paper = _paper_with_math(client)
    abstract = paper["abstract"]

    # First sentence only.
    end = abstract.index(". ") + 1
    selection = abstract[:end]

    response = client.post(
        "/translations",
        headers=headers,
        json={
            "paperId": paper["id"],
            "selection": {"field": "abstract", "start": 0, "end": end, "exactText": selection},
            "style": "natural",
            "stage": "natural",
        },
    )
    assert response.status_code == 201, response.text
    translation = response.json()["translation"]

    assert translation["original"] == selection
    assert len(translation["original"]) < len(abstract)
    assert translation["fellBackToOriginal"] is False
    # Spec section 23: every AI artefact carries its generation provenance.
    generation = translation["generation"]
    assert generation["provider"] and generation["model"] and generation["promptVersion"]
    assert generation["inputHash"]


def test_formulas_survive_a_translation_request(client: TestClient, seeded_db: Session) -> None:
    """Spec section 29: 数式を含む選択でLaTeXが壊れない."""
    headers = _auth(client)
    paper = _paper_with_math(client)
    abstract = paper["abstract"]

    # A sentence that contains at least one formula, selected whole.
    sentences = []
    start = 0
    for index, char in enumerate(abstract):
        if char == "." and index + 1 < len(abstract) and abstract[index + 1] == " ":
            sentences.append((start, index + 1))
            start = index + 2
    target = next((s for s in sentences if "$" in abstract[s[0] : s[1]]), None)
    assert target is not None, "expected a fixture sentence containing maths"

    start, end = target
    selection = abstract[start:end]
    response = client.post(
        "/translations",
        headers=headers,
        json={
            "paperId": paper["id"],
            "selection": {
                "field": "abstract",
                "start": start,
                "end": end,
                "exactText": selection,
            },
            "style": "natural",
            "stage": "natural",
        },
    )
    assert response.status_code == 201, response.text
    translation = response.json()["translation"]

    assert translation["mathPlaceholders"], "the formula should have been masked"
    for placeholder in translation["mathPlaceholders"]:
        assert placeholder["latex"] in translation["translated"], (
            "the original LaTeX must be restored verbatim"
        )
        assert placeholder["token"] not in translation["translated"], (
            "no placeholder token may leak into the output"
        )
    assert translation["fellBackToOriginal"] is False


def test_a_selection_cutting_through_a_formula_is_refused(
    client: TestClient, seeded_db: Session
) -> None:
    headers = _auth(client)
    paper = _paper_with_math(client)
    abstract = paper["abstract"]

    dollar = abstract.index("$")
    start = dollar + 2  # inside the formula
    end = min(len(abstract), start + 40)
    response = client.post(
        "/translations",
        headers=headers,
        json={
            "paperId": paper["id"],
            "selection": {
                "field": "abstract",
                "start": start,
                "end": end,
                "exactText": abstract[start:end],
            },
            "style": "natural",
            "stage": "natural",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "selection_splits_formula"


def test_offsets_that_disagree_with_the_stored_text_are_refused(
    client: TestClient, seeded_db: Session
) -> None:
    """A re-ingested abstract must not silently re-anchor a stale selection."""
    headers = _auth(client)
    paper = _paper_with_math(client)
    response = client.post(
        "/translations",
        headers=headers,
        json={
            "paperId": paper["id"],
            "selection": {
                "field": "abstract",
                "start": 0,
                "end": 10,
                "exactText": "not what is stored",
            },
            "style": "natural",
            "stage": "natural",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "selection_text_mismatch"


def test_translation_requires_authentication(client: TestClient, seeded_db: Session) -> None:
    paper = _paper_with_math(client)
    response = client.post(
        "/translations",
        json={
            "paperId": paper["id"],
            "selection": {
                "field": "abstract",
                "start": 0,
                "end": 5,
                "exactText": paper["abstract"][:5],
            },
        },
    )
    assert response.status_code == 401
