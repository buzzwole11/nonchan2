"""Before you read, and Why it matters (spec section 8).

Section 8 ends both features with AI生成であることを明示する, and section 0 requires that
distinction to hold in the data model rather than only in the interface. So most of these
tests are about what is *not* produced: a provider that cannot ground a statement must
return nothing and say why, and nothing anywhere may present generated prose as the paper's.

The rest is the cache key. An explanation is written about a specific abstract by a specific
model under a specific prompt, and a cache that forgot any of those three would serve an
explanation of text that no longer exists, or one model's words under another's name.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import AbstractExplanation, Field, Paper
from papermatch_api.providers.anthropic_explanation import AnthropicExplanationProvider
from papermatch_api.providers.base import ProviderUnavailable
from papermatch_api.providers.derived_explanation import (
    MIN_TERMS,
    DerivedExplanationProvider,
)
from papermatch_api.providers.http import HttpResponse
from papermatch_api.services.explanations import (
    AUDIENCES,
    before_you_read,
    explanation_input,
    input_hash,
    why_it_matters,
)
from tests.conftest import requires_db

ABSTRACT = (
    "We study concentration inequalities for non-reversible Markov chains on Kagome "
    "lattices. Our gradient-descent estimator attains the optimal rate under a "
    "log-concave assumption. The analysis uses a spectral decomposition of the "
    "generator, and the resulting bound is dimension-free."
)


def _paper(session: Session, slug: str = "x", abstract: str = ABSTRACT) -> Paper:
    row = Paper(
        canonical_id=f"test:explain-{slug}",
        title="Concentration for Non-Reversible Measures",
        normalized_title="concentration for non reversible measures",
        abstract=abstract,
        authors=[{"name": "K. Novak"}],
        year=2026,
        source_provider="mock",
        source_url="https://example.invalid/abs/1",
        acquired_at=datetime.now(tz=UTC),
    )
    session.add(row)
    session.flush()
    return row


# ------------------------------------------------------------------ the derived provider


def test_terms_come_from_the_abstract_itself() -> None:
    # Not a gloss. A phrase the paper actually used, with the sentence it used it in — that
    # cannot be wrong, which is the point of it being the default provider.
    answer = DerivedExplanationProvider().explain("before_you_read", {"abstract": ABSTRACT})

    terms = [item for item in answer["items"] if item["kind"] == "term"]
    assert len(terms) >= MIN_TERMS
    for item in terms:
        assert item["source"] == "abstract"
        assert item["title"] in ABSTRACT
        assert item["detail"] in ABSTRACT


def test_generic_abstract_vocabulary_is_not_offered_as_terminology() -> None:
    # A "technical terms" list containing `method` and `results` teaches nothing and costs
    # the reader the time it takes to notice that.
    answer = DerivedExplanationProvider().explain(
        "before_you_read",
        {"abstract": "The results of this study. Our method and model. The data analysis."},
    )

    assert [item for item in answer["items"] if item["kind"] == "term"] == []
    assert answer["unavailableReason"] is not None


def test_the_field_is_offered_as_background_without_a_description() -> None:
    # The field a paper belongs to is a fact from the taxonomy. A sentence describing that
    # field would not be, so there is none.
    answer = DerivedExplanationProvider().explain(
        "before_you_read",
        {"abstract": ABSTRACT, "fieldLabel": "Probability", "fieldId": "math.PR"},
    )

    background = [item for item in answer["items"] if item["kind"] == "background"]
    assert [item["title"] for item in background] == ["Probability"]
    assert background[0]["detail"] is None
    assert background[0]["source"] == "taxonomy"


def test_why_it_matters_produces_nothing_and_says_so() -> None:
    """The refusal this provider exists to make.

    Section 8's four readings are each a claim about what a paper means to somebody. None
    follows from a title, a year and a category. A template would give every paper in a
    field the same significance, which reads as insight and is not.
    """
    answer = DerivedExplanationProvider().explain(
        "why_it_matters", {"abstract": ABSTRACT, "audience": "beginner"}
    )

    assert answer["items"] == []
    assert "メタデータからは導けません" in answer["unavailableReason"]


def test_an_unknown_kind_is_refused_rather_than_guessed() -> None:
    answer = DerivedExplanationProvider().explain("something_else", {"abstract": ABSTRACT})

    assert answer["items"] == []
    assert answer["unavailableReason"] is not None


# ------------------------------------------------------------------ the model provider


class _RecordedTransport:
    """One recorded reply, and a note of what was sent."""

    def __init__(self, body: str, status_code: int = 200) -> None:
        self._body = body
        self._status = status_code
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, json_body: Any, headers: Any) -> HttpResponse:
        self.calls.append({"url": url, "body": dict(json_body), "headers": dict(headers)})
        return HttpResponse(status_code=self._status, text=self._body)


def _reply(payload: dict[str, Any]) -> str:
    return json.dumps({"content": [{"type": "text", "text": json.dumps(payload)}]})


def _provider(transport: _RecordedTransport) -> AnthropicExplanationProvider:
    from papermatch_api.providers.http import RateLimiter

    return AnthropicExplanationProvider(
        api_key="test-key", transport=transport, rate_limiter=RateLimiter(0.0)
    )


def test_a_missing_key_is_refused_at_construction() -> None:
    # A provider that exists but cannot work turns a configuration mistake into a runtime
    # one, and the runtime one surfaces as a reader seeing an empty panel.
    with pytest.raises(ValueError, match="API key"):
        AnthropicExplanationProvider(api_key="")


def test_only_the_named_paper_fields_reach_the_wire() -> None:
    """Spec section 25 asks for 送信内容の最小化.

    Asserted by putting something reader-shaped into the payload and checking it does not
    come out the other side: the prompt builder reads named fields, so anything a future
    caller adds to the payload stays on this side of the boundary by construction rather
    than by everyone remembering.
    """
    transport = _RecordedTransport(_reply({"items": []}))
    _provider(transport).explain(
        "before_you_read",
        {
            "title": "T",
            "abstract": ABSTRACT,
            "fieldLabel": "Probability",
            "userId": "SECRET-READER-ID",
            "savedPapers": ["SECRET-LIBRARY"],
        },
    )

    sent = json.dumps(transport.calls[0]["body"], ensure_ascii=False)
    assert ABSTRACT in sent
    assert "SECRET-READER-ID" not in sent
    assert "SECRET-LIBRARY" not in sent
    # And nothing beyond the API's own envelope.
    assert set(transport.calls[0]["body"]) == {"model", "max_tokens", "system", "messages"}


def test_the_key_travels_in_the_header_and_nowhere_else() -> None:
    transport = _RecordedTransport(_reply({"items": []}))
    _provider(transport).explain("before_you_read", {"abstract": ABSTRACT})

    call = transport.calls[0]
    assert call["headers"]["x-api-key"] == "test-key"
    assert "test-key" not in json.dumps(call["body"])


def test_the_key_is_not_in_the_health_report() -> None:
    # `GET /health` is a public-ish surface, and a provider that reported its own
    # configuration would put the key one curl away.
    health = _provider(_RecordedTransport(_reply({"items": []}))).health()

    assert "test-key" not in json.dumps({"name": health.name, "detail": health.detail})


def test_an_answer_is_parsed_into_labelled_items() -> None:
    transport = _RecordedTransport(
        _reply(
            {
                "items": [
                    {"kind": "term", "title": "log-concave", "detail": "密度の対数が凹であること"},
                    {
                        "kind": "background",
                        "title": "マルコフ連鎖",
                        "detail": "状態が確率的に遷移する",
                    },
                ]
            }
        )
    )

    answer = _provider(transport).explain("before_you_read", {"abstract": ABSTRACT})

    assert [item["title"] for item in answer["items"]] == ["log-concave", "マルコフ連鎖"]
    # Every item says it came from a model, so the interface never has to infer it.
    assert {item["source"] for item in answer["items"]} == {"model"}


def test_a_fenced_reply_is_still_read() -> None:
    # The instruction not to add prose is followed far more often than the instruction not
    # to wrap the JSON in a code fence.
    fenced = "```json\n" + json.dumps({"items": [{"kind": "why", "title": "新しい上界"}]}) + "\n```"
    transport = _RecordedTransport(json.dumps({"content": [{"type": "text", "text": fenced}]}))

    answer = _provider(transport).explain(
        "why_it_matters", {"abstract": ABSTRACT, "audience": "researcher"}
    )

    assert [item["title"] for item in answer["items"]] == ["新しい上界"]


def test_an_unreadable_reply_is_an_empty_answer_rather_than_an_error() -> None:
    # Section 8's material is 強制表示しない, so the paper is fully readable without it. A
    # 500 on a card the reader was only curious about is the wrong trade.
    transport = _RecordedTransport(json.dumps({"content": [{"type": "text", "text": "sorry!"}]}))

    answer = _provider(transport).explain("before_you_read", {"abstract": ABSTRACT})

    assert answer["items"] == []
    assert answer["unavailableReason"] is not None


def test_an_item_of_an_unknown_kind_is_dropped() -> None:
    # The interface groups by kind, so an unrecognised one would be invisible — which looks
    # like the model having said less than it did.
    transport = _RecordedTransport(
        _reply(
            {"items": [{"kind": "speculation", "title": "たぶん"}, {"kind": "term", "title": "x"}]}
        )
    )

    answer = _provider(transport).explain("before_you_read", {"abstract": ABSTRACT})

    assert [item["title"] for item in answer["items"]] == ["x"]


def test_an_empty_list_from_the_model_is_treated_as_a_deliberate_refusal() -> None:
    # The prompt tells the model that an empty list is a correct answer, so this is very
    # likely it doing as asked rather than failing.
    transport = _RecordedTransport(_reply({"items": []}))

    answer = _provider(transport).explain(
        "why_it_matters", {"abstract": ABSTRACT, "audience": "field_history"}
    )

    assert answer["items"] == []
    assert "根拠のある説明を出せない" in answer["unavailableReason"]


def test_a_client_error_does_not_open_the_breaker() -> None:
    # Our own bad request will not fix itself by being retried, and opening the breaker
    # would take the provider down for every other paper too.
    transport = _RecordedTransport("{}", status_code=400)
    provider = _provider(transport)

    for _ in range(6):
        with pytest.raises(ProviderUnavailable):
            provider.explain("before_you_read", {"abstract": ABSTRACT})

    assert provider.breaker.is_open is False


def test_rate_limiting_and_the_breaker_react_to_the_service_struggling() -> None:
    transport = _RecordedTransport("{}", status_code=503)
    provider = _provider(transport)

    for _ in range(4):
        with pytest.raises(ProviderUnavailable):
            provider.explain("before_you_read", {"abstract": ABSTRACT})

    assert provider.breaker.is_open is True
    assert provider.health().healthy is False


# ------------------------------------------------------------------ storing and caching

pytestmark_db = [pytest.mark.integration, requires_db]


@pytest.mark.integration
@requires_db
def test_an_explanation_is_stored_as_ai_generated_with_its_provenance(
    db_session: Session,
) -> None:
    paper = _paper(db_session, "stored")

    result = before_you_read(db_session, DerivedExplanationProvider(), paper)

    row = db_session.execute(
        select(AbstractExplanation).where(AbstractExplanation.paper_id == paper.id)
    ).scalar_one()
    # Section 0: the distinction has to survive in the data model, not only in the UI.
    assert row.provenance_kind == "ai_explanation"
    assert row.generation_provider == "derived"
    assert row.prompt_version
    assert row.input_hash
    assert result.provenance_kind == "ai_explanation"


@pytest.mark.integration
@requires_db
def test_asking_twice_does_not_call_the_provider_twice(db_session: Session) -> None:
    paper = _paper(db_session, "cached")

    class _Counting(DerivedExplanationProvider):
        calls = 0

        def explain(self, prompt_kind: str, payload: dict[str, Any]) -> dict[str, Any]:
            type(self).calls += 1
            return super().explain(prompt_kind, payload)

    provider = _Counting()
    before_you_read(db_session, provider, paper)
    before_you_read(db_session, provider, paper)

    assert _Counting.calls == 1


@pytest.mark.integration
@requires_db
def test_a_corrected_abstract_is_not_explained_by_the_old_text(db_session: Session) -> None:
    """The reason the cache key is the input rather than the paper id.

    An abstract that is corrected after ingestion would otherwise keep an explanation
    written about text that no longer exists — and nothing in the interface would say so.
    """
    paper = _paper(db_session, "corrected")
    first = before_you_read(db_session, DerivedExplanationProvider(), paper)

    paper.abstract = "An entirely different abstract about Kloosterman sums and heights."
    db_session.flush()
    second = before_you_read(db_session, DerivedExplanationProvider(), paper)

    assert [item["title"] for item in first.items] != [item["title"] for item in second.items]


def test_the_cache_key_separates_two_models_explaining_the_same_paper() -> None:
    # One model's words served under another's name is exactly what the label is for.
    payload = {"title": "T", "abstract": ABSTRACT}
    a = input_hash(payload, provider="anthropic", model="model-a", prompt_version="v1")
    b = input_hash(payload, provider="anthropic", model="model-b", prompt_version="v1")
    c = input_hash(payload, provider="anthropic", model="model-a", prompt_version="v2")

    assert len({a, b, c}) == 3


@pytest.mark.integration
@requires_db
def test_nothing_about_the_reader_enters_the_cache_key(db_session: Session) -> None:
    paper = _paper(db_session, "input")

    payload = explanation_input(db_session, paper)

    assert set(payload) == {
        "title",
        "abstract",
        "fieldId",
        "fieldLabel",
        "parentFieldId",
        "parentFieldLabel",
        "audience",
    }


@pytest.mark.integration
@requires_db
def test_the_parent_field_is_offered_as_well_as_the_field(db_session: Session) -> None:
    # "High Energy Physics — Theory" is not a useful thing to be told you should already
    # know; "Physics" is the level a reader outside the area actually needs.
    db_session.add(Field(id="physics", label_en="Physics", label_ja="物理学"))
    db_session.add(
        Field(id="hep-th", parent_id="physics", label_en="HEP — Theory", label_ja="高エネ")
    )
    paper = _paper(db_session, "parent")
    paper.primary_field_id = "hep-th"
    db_session.flush()

    payload = explanation_input(db_session, paper)

    assert payload["fieldLabel"] == "HEP — Theory"
    assert payload["parentFieldLabel"] == "Physics"


@pytest.mark.integration
@requires_db
def test_all_four_readings_are_asked_for_separately(db_session: Session) -> None:
    """One empty answer must not suppress the others.

    A paper can genuinely have nothing to say to a practitioner while having a great deal
    to say to a researcher, and collapsing that into "no explanation" loses the true half.
    """
    paper = _paper(db_session, "four")

    results = why_it_matters(db_session, DerivedExplanationProvider(), paper)

    assert [result.audience for result in results] == list(AUDIENCES)


@pytest.mark.integration
@requires_db
def test_a_provider_that_is_down_is_not_written_into_the_cache(db_session: Session) -> None:
    """Otherwise the reader keeps being told it is unavailable long after it recovers."""
    paper = _paper(db_session, "down")

    class _Down(DerivedExplanationProvider):
        def explain(self, prompt_kind: str, payload: dict[str, Any]) -> dict[str, Any]:
            raise ProviderUnavailable("connection refused")

    result = before_you_read(db_session, _Down(), paper)

    assert result.items == []
    assert "接続できませんでした" in (result.unavailable_reason or "")
    assert (
        db_session.execute(
            select(AbstractExplanation).where(AbstractExplanation.paper_id == paper.id)
        ).scalar_one_or_none()
        is None
    )


# ------------------------------------------------------------------ through the API


@pytest.mark.integration
@requires_db
def test_the_endpoint_labels_everything_it_returns(client, seeded_db: Session) -> None:  # type: ignore[no-untyped-def]
    paper = seeded_db.execute(select(Paper)).scalars().first()
    assert paper is not None

    auth = client.post("/auth/guest", json={"locale": "ja-JP", "timezone": "Asia/Tokyo"})
    headers = {"Authorization": f"Bearer {auth.json()['accessToken']}"}
    response = client.get(f"/papers/{paper.id}/explanation", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["beforeYouRead"]["provenanceKind"] == "ai_explanation"
    assert len(body["whyItMatters"]) == len(AUDIENCES)
    for section in body["whyItMatters"]:
        assert section["provenanceKind"] == "ai_explanation"
        # The derived provider refuses this one, and the refusal has to reach the reader as
        # a reason rather than as an empty panel.
        assert section["unavailableReason"]


@pytest.mark.integration
@requires_db
def test_an_unknown_paper_is_a_404_rather_than_an_empty_explanation(client) -> None:  # type: ignore[no-untyped-def]
    import uuid as _uuid

    auth = client.post("/auth/guest", json={"locale": "ja-JP", "timezone": "Asia/Tokyo"})
    headers = {"Authorization": f"Bearer {auth.json()['accessToken']}"}

    assert client.get(f"/papers/{_uuid.uuid4()}/explanation", headers=headers).status_code == 404
    # And without a token it is a 401, like every other paper endpoint.
    assert client.get(f"/papers/{_uuid.uuid4()}/explanation").status_code == 401
