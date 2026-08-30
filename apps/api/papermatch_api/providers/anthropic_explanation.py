"""Explanations from a language model (spec sections 8, 21, 25).

`DerivedExplanationProvider` answers what can be derived and refuses the rest by name. This
is the provider that answers the rest — section 8's 学部レベルの短い説明 and the four
readings of 「なぜ重要か」, none of which follow from metadata.

**The key is read from the server's environment and never leaves it.** Spec section 25 is
explicit: API キーをクライアントに置かない. This module is the only place in the codebase that
holds one, the mobile app calls our endpoint rather than the model's, and the key is not
echoed in health output, errors or the audit log.

**The paper's own text goes up; nothing about the reader does.** The request carries the
title, abstract and field — public metadata we are already permitted to hold. It does not
carry the user id, their library, or what they saved, because none of that is needed to
explain a paper and section 25 asks for 送信内容の最小化.

**Everything that comes back is labelled AI-generated and stored as such.** The caller
writes it to `abstract_explanations` with provider, model and prompt version, so a reader
sees the label and a maintainer can find every explanation a given prompt produced.

**A refusal to answer is a valid answer.** The prompt tells the model to return an empty
list for anything it cannot ground in the abstract, and a response it cannot parse is
treated the same way. That is what keeps this provider's failure mode the same as the
derived one's — an absent section with a reason — rather than confident prose nobody checked.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from papermatch_api.providers.base import ProviderHealth, ProviderUnavailable
from papermatch_api.providers.http import CircuitBreaker, HttpResponse, RateLimiter

__all__ = ["PROMPT_VERSION", "AnthropicExplanationProvider", "PostTransport"]

#: Bumped whenever the prompt changes. Explanations are keyed on it, so a new version adds
#: rows rather than rewriting ones a reader may already have been shown.
PROMPT_VERSION = "anthropic-v1"

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

#: Small and cheap. This is short, structured, well-specified work over text we supply — the
#: places where a larger model earns its cost are not these.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

MAX_TOKENS = 1400

_SYSTEM = """You explain academic paper abstracts to readers in Japanese.

Rules you must follow:
1. Ground every statement in the abstract, title, and field you are given. If you cannot
   ground a statement, omit the item. An empty list is a correct answer.
2. Never state a result the abstract does not state. Never name a person, dataset,
   institution, or prior paper that is not in the text you were given.
3. Write in Japanese, plainly, for someone who is not in this subfield.
4. Reply with JSON only, matching the schema in the user message. No prose around it.
"""

# Filled with `_fill` rather than `str.format`: these prompts contain JSON schemas, and
# every `{` in them would have to be doubled for `format` — a rule that is obeyed until
# somebody edits the prompt and gets a `KeyError` at request time instead of at import.
_BEFORE_YOU_READ = """Produce "Before you read" material for this paper.

Return JSON: {"items": [...]} where each item is
  {"kind": "background" | "term", "title": "...", "detail": "..."}

* At most 3 items with kind "background": something a reader should already know to follow
  this abstract. `detail` is one or two sentences at undergraduate level.
* 3 to 5 items with kind "term": a technical term that appears in the abstract, with
  `detail` explaining what it means here.
* Omit any item you cannot ground in the text below. Fewer items is correct; invented ones
  are not.

Title: <<TITLE>>
Field: <<FIELD>>
Abstract: <<ABSTRACT>>
"""

_WHY_IT_MATTERS = """Explain why this paper matters, for one specific audience.

Audience: <<AUDIENCE>>

Return JSON: {"items": [{"kind": "why", "title": "...", "detail": "..."}]}
with at most 2 items. `title` is a short phrase; `detail` is two or three sentences.

If the abstract does not support a statement for this audience, return {"items": []}.
That is a correct answer and is preferred over a general remark that would be true of any
paper in the field.

Title: <<TITLE>>
Field: <<FIELD>>
Abstract: <<ABSTRACT>>
"""

#: Section 8's four readings, as instructions rather than as labels. Passing the label alone
#: ("応用上の意味") gets four rewordings of the same paragraph; naming the question gets four
#: different answers, which is what the section is asking for.
AUDIENCE_PROMPTS: dict[str, str] = {
    "beginner": (
        "Someone new to this field. What problem does this help with, and why was it hard?"
    ),
    "researcher": (
        "A researcher in a nearby subfield. What is new here relative to what was already"
        " known, as far as the abstract states it?"
    ),
    "application": (
        "A practitioner. What could this be used for, and what would still be needed first?"
        " Do not promise applications the abstract does not claim."
    ),
    "field_history": (
        "Someone asking where this sits in the field's development. Only answer if the"
        " abstract itself positions the work; otherwise return no items."
    ),
}


class PostTransport(Protocol):
    """A JSON POST, so tests can supply a recorded response.

    Separate from `providers.http.Transport`, which is GET-only and shared by the paper
    providers. Widening that protocol would mean every existing test double had to grow a
    method none of them need.
    """

    def post(
        self, url: str, *, json_body: Mapping[str, Any], headers: Mapping[str, str]
    ) -> HttpResponse: ...


class HttpxPostTransport:
    """The real thing."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout = timeout_seconds

    def post(
        self, url: str, *, json_body: Mapping[str, Any], headers: Mapping[str, str]
    ) -> HttpResponse:
        import httpx

        try:
            response = httpx.post(
                url, json=dict(json_body), headers=dict(headers), timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{type(exc).__name__}: {exc}") from exc
        return HttpResponse(
            status_code=response.status_code,
            text=response.text,
            headers=dict(response.headers),
        )


class AnthropicExplanationProvider:
    """Section 8's explanations, from a model, labelled as such."""

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        transport: PostTransport | None = None,
        rate_limiter: RateLimiter | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        if not api_key:
            # Refused at construction rather than at the first request: a provider that
            # exists but cannot work turns a configuration mistake into a runtime one, and
            # the runtime one surfaces as a reader seeing an empty panel.
            raise ValueError("an Anthropic API key is required; set PAPERMATCH_ANTHROPIC_API_KEY")
        self._api_key = api_key
        self.model = model
        self._transport = transport or HttpxPostTransport()
        # Spec section 27 lists 同一ソースへの過剰APIアクセス as a guardrail, and this is the
        # one provider whose calls cost money as well as capacity.
        self._rate_limiter = rate_limiter or RateLimiter(0.5)
        self._breaker = breaker or CircuitBreaker(failure_threshold=4, cooldown_seconds=120.0)

    @property
    def breaker(self) -> CircuitBreaker:
        return self._breaker

    # ------------------------------------------------------------------ the request

    def explain(self, prompt_kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        prompt = self._prompt(prompt_kind, payload)
        if prompt is None:
            return _empty(f"未対応の説明種別（{prompt_kind}）")

        self._breaker.before_call()
        self._rate_limiter.wait()
        try:
            response = self._transport.post(
                API_URL,
                json_body={
                    "model": self.model,
                    "max_tokens": MAX_TOKENS,
                    "system": _SYSTEM,
                    "messages": [{"role": "user", "content": prompt}],
                },
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": API_VERSION,
                    "content-type": "application/json",
                },
            )
        except ProviderUnavailable:
            self._breaker.record_failure()
            raise

        if not response.ok:
            # 429 and 5xx mean the service is struggling; a 4xx of ours means our request is
            # wrong and repeating it will not help, so it must not open the breaker and take
            # the provider down for everyone else. Same rule as `providers/http.py`.
            if response.status_code == 429 or response.status_code >= 500:
                self._breaker.record_failure()
            raise ProviderUnavailable(f"Anthropic returned {response.status_code}")

        self._breaker.record_success()
        return {
            **self._parse(response.text),
            "promptVersion": PROMPT_VERSION,
            "model": self.model,
        }

    def _prompt(self, prompt_kind: str, payload: dict[str, Any]) -> str | None:
        title = str(payload.get("title") or "")
        abstract = str(payload.get("abstract") or "")
        field = str(payload.get("fieldLabel") or payload.get("parentFieldLabel") or "unknown")

        if prompt_kind == "before_you_read":
            return _fill(_BEFORE_YOU_READ, title=title, field=field, abstract=abstract)
        if prompt_kind == "why_it_matters":
            audience = str(payload.get("audience") or "")
            instruction = AUDIENCE_PROMPTS.get(audience)
            if instruction is None:
                return None
            return _fill(
                _WHY_IT_MATTERS,
                title=title,
                field=field,
                abstract=abstract,
                audience=instruction,
            )
        return None

    # ------------------------------------------------------------------ the response

    def _parse(self, body: str) -> dict[str, Any]:
        """Items from the reply, or an empty list with the reason.

        **A response we cannot read is an empty answer, not an exception.** The alternative
        is a 500 on a card the reader was only curious about, and section 8 says this
        material is 強制表示しない — the paper is still perfectly readable without it.
        """
        try:
            document = json.loads(body)
            blocks = document["content"]
            text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            return _empty("説明モデルの応答を読み取れませんでした")

        parsed = _json_object(text)
        if parsed is None:
            return _empty("説明モデルが JSON を返しませんでした")

        items = parsed.get("items")
        if not isinstance(items, list):
            return _empty("説明モデルの応答に items がありませんでした")

        clean = [item for item in (_clean_item(raw) for raw in items) if item is not None]
        if not clean:
            # The model was told an empty list is a correct answer, so this is very likely
            # it doing as it was asked rather than failing.
            return _empty(
                "説明モデルが、この Abstract からは根拠のある説明を出せないと判断しました"
            )
        return {"items": clean, "unavailableReason": None}

    def health(self) -> ProviderHealth:
        # No request is made: a health check that costs a model call would run on every
        # `GET /health`. What is reportable without one is whether the breaker is open.
        open_breaker = self._breaker.is_open
        return ProviderHealth(
            name=self.name,
            healthy=not open_breaker,
            detail=("circuit breaker is open" if open_breaker else f"model {self.model}"),
            checked_at=datetime.now(tz=UTC),
        )


def _fill(template: str, **values: str) -> str:
    """Substitute `<<NAME>>` placeholders.

    Not `str.format`: the prompts above contain JSON schemas, and every brace in them would
    have to be doubled — a rule that holds until somebody edits a prompt, at which point it
    fails at request time rather than at import.
    """
    filled = template
    for name, value in values.items():
        filled = filled.replace(f"<<{name.upper()}>>", value)
    return filled


def _empty(reason: str) -> dict[str, Any]:
    return {"items": [], "unavailableReason": reason}


def _json_object(text: str) -> dict[str, Any] | None:
    """The JSON object in a reply, tolerating a fenced code block around it."""
    candidate = text.strip()
    if candidate.startswith("```"):
        # ```json … ``` — strip the fence rather than failing, because the instruction not
        # to add prose is followed far more often than the instruction not to fence.
        candidate = candidate.split("\n", 1)[-1]
        if candidate.rstrip().endswith("```"):
            candidate = candidate.rstrip()[: -len("```")]
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


#: The only kinds this pipeline stores. An item claiming to be anything else is dropped
#: rather than passed through: the UI groups by kind, and an unknown one would be invisible.
_KINDS = frozenset({"background", "term", "why"})


def _clean_item(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip()
    title = str(raw.get("title") or "").strip()
    detail = raw.get("detail")
    if kind not in _KINDS or not title:
        return None
    return {
        "kind": kind,
        "title": title[:200],
        "detail": str(detail).strip()[:1200]
        if isinstance(detail, str) and detail.strip()
        else None,
        "source": "model",
    }
