"""The real translation provider (spec sections 7, 25).

What can actually go wrong here, and therefore what is tested: a formula token silently
damaged, the reader's surroundings translated as though they were the selection, the key
somewhere other than the header, and the failure path not being the router's fallback path.
Everything runs against recorded response shapes — the live call needs a key this
environment does not have, and the commit message says so.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from papermatch_api.providers.anthropic_translation import (
    AnthropicTranslationProvider,
)
from papermatch_api.providers.base import (
    ProviderUnavailable,
    TranslationRequest,
)
from papermatch_api.providers.http import HttpResponse, RateLimiter


class _RecordedTransport:
    def __init__(self, body: str, status_code: int = 200) -> None:
        self._body = body
        self._status = status_code
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, json_body: Any, headers: Any) -> HttpResponse:
        self.calls.append({"url": url, "body": dict(json_body), "headers": dict(headers)})
        return HttpResponse(status_code=self._status, text=self._body)


def _reply(text: str) -> str:
    inner = json.dumps({"text": text}, ensure_ascii=False)
    return json.dumps({"content": [{"type": "text", "text": inner}]}, ensure_ascii=False)


def _provider(transport: _RecordedTransport) -> AnthropicTranslationProvider:
    return AnthropicTranslationProvider(
        api_key="test-key", transport=transport, rate_limiter=RateLimiter(0.0)
    )


def _request(**overrides: Any) -> TranslationRequest:
    defaults: dict[str, Any] = {
        "text": "The bound ⟦MATH_0⟧ holds for every ⟦MATH_1⟧.",
        "source_lang": "en",
        "target_lang": "ja",
        "style": "natural",
        "stage": "natural",
        "context_before": "We study concentration.",
        "context_after": "The proof is elementary.",
        "field_id": "math.PR",
    }
    defaults.update(overrides)
    return TranslationRequest(**defaults)


def test_a_missing_key_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="API key"):
        AnthropicTranslationProvider(api_key="")


def test_a_faithful_reply_reports_no_dropped_tokens() -> None:
    transport = _RecordedTransport(_reply("上界 ⟦MATH_0⟧ は任意の ⟦MATH_1⟧ に対して成り立つ。"))

    result = _provider(transport).translate(_request())

    assert result.dropped_math_tokens == ()
    assert "⟦MATH_0⟧" in result.translated_text
    assert result.provider == "anthropic"
    assert result.prompt_version


def test_a_lost_formula_token_is_reported_not_hidden() -> None:
    """The one property spec section 7 states without qualification.

    The provider does not repair or refuse the result itself — it reports exactly which
    tokens are missing, because the router's existing fallback (show the original text) is
    the same for every provider and must not depend on each one's private policy.
    """
    transport = _RecordedTransport(_reply("上界は任意の ⟦MATH_1⟧ に対して成り立つ。"))

    result = _provider(transport).translate(_request())

    assert result.dropped_math_tokens == ("⟦MATH_0⟧",)


def test_the_glossary_stage_is_not_expected_to_carry_formulas() -> None:
    # Stage 1 lists words; a word list legitimately contains no equations, and flagging
    # that as damage would force the fallback on every selection containing maths.
    transport = _RecordedTransport(_reply("bound … 上界\nconcentration … 集中"))

    result = _provider(transport).translate(_request(stage="hard_words"))

    assert result.dropped_math_tokens == ()


def test_each_stage_sends_its_own_instruction() -> None:
    # Six phrasings of one translation would defeat the sheet. The instructions must
    # actually differ on the wire, not only in a dict nobody reads.
    prompts: list[str] = []
    for stage in (
        "hard_words",
        "sentence_skeleton",
        "phrase_structure",
        "literal",
        "natural",
        "domain_meaning",
    ):
        transport = _RecordedTransport(_reply("x"))
        _provider(transport).translate(_request(stage=stage))
        prompts.append(transport.calls[0]["body"]["messages"][0]["content"])

    assert len(set(prompts)) == len(prompts)


def test_the_selection_is_fenced_apart_from_its_context() -> None:
    transport = _RecordedTransport(_reply("x"))
    _provider(transport).translate(_request())

    prompt = transport.calls[0]["body"]["messages"][0]["content"]
    assert "<selection>The bound ⟦MATH_0⟧ holds for every ⟦MATH_1⟧.</selection>" in prompt
    assert "<context>We study concentration.</context>" in prompt


def test_the_key_travels_in_the_header_and_nowhere_else() -> None:
    transport = _RecordedTransport(_reply("x"))
    _provider(transport).translate(_request())

    call = transport.calls[0]
    assert call["headers"]["x-api-key"] == "test-key"
    assert "test-key" not in json.dumps(call["body"])
    assert "test-key" not in json.dumps(
        {"detail": _provider(_RecordedTransport(_reply("x"))).health().detail}
    )


def test_an_unknown_stage_is_refused_rather_than_guessed() -> None:
    with pytest.raises(ProviderUnavailable, match="unknown translation stage"):
        _provider(_RecordedTransport(_reply("x"))).translate(_request(stage="stage_7"))


def test_an_unreadable_reply_fails_into_the_routers_fallback_path() -> None:
    # The router already catches ProviderUnavailable and serves the original text (spec
    # section 25). A reply we cannot parse must reach that same path, not invent an empty
    # translation that would render as a blank sheet.
    transport = _RecordedTransport(json.dumps({"content": [{"type": "text", "text": "ごめん"}]}))

    with pytest.raises(ProviderUnavailable):
        _provider(transport).translate(_request())


def test_a_client_error_does_not_open_the_breaker() -> None:
    transport = _RecordedTransport("{}", status_code=400)
    provider = _provider(transport)

    for _ in range(6):
        with pytest.raises(ProviderUnavailable):
            provider.translate(_request())

    assert provider.breaker.is_open is False


def test_service_failures_open_the_breaker_and_health_says_so() -> None:
    transport = _RecordedTransport("{}", status_code=503)
    provider = _provider(transport)

    for _ in range(4):
        with pytest.raises(ProviderUnavailable):
            provider.translate(_request())

    assert provider.breaker.is_open is True
    assert provider.health().healthy is False
