"""Real translation for the six-stage bottom sheet (spec sections 7, 25).

The mock provider gave the sheet its shape; this gives it real Japanese. The rules it works
under are the mock's rules, restated for something that can actually get them wrong:

**Formula tokens are inviolable.** The text arrives with maths already masked to
``⟦MATH_n⟧`` tokens (spec section 7: 数式や式番号を翻訳モデルに改変させない). The prompt
orders the model to copy them through verbatim, and the caller re-checks anyway: a result
that lost or altered a token is reported with ``dropped_math_tokens`` set and the router
falls back to the original text. The check is not this module's trust in the model — it is
the router's distrust of every provider equally.

**The selection is what is translated; the context is only context.** Section 7's product is
partial translation, and ``context_before``/``context_after`` are sent clearly fenced so the
model can resolve pronouns without translating a paragraph nobody selected.

**Stages are different tasks, not different lengths.** 段階1 is a glossary, 段階2 is a
structure sketch, 段階6 is a field-aware translation. Each stage has its own instruction;
one prompt with a "stage" dial would produce six phrasings of the same translation, which
defeats the sheet's purpose of letting the reader climb.

**The key lives on the server** (spec section 25: API キーをクライアントに置かない), same as
the explanation provider — one env var, never in health output or errors.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from papermatch_api.providers.anthropic_explanation import (
    API_URL,
    API_VERSION,
    HttpxPostTransport,
    PostTransport,
)
from papermatch_api.providers.base import (
    ProviderHealth,
    ProviderUnavailable,
    TranslationRequest,
    TranslationResult,
)
from papermatch_api.providers.http import CircuitBreaker, RateLimiter

__all__ = ["PROMPT_VERSION", "AnthropicTranslationProvider"]

PROMPT_VERSION = "anthropic-translate-v1"

#: Small and cheap, as for explanations: short structured work over supplied text.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

MAX_TOKENS = 1500

_TOKEN_RE = re.compile(r"⟦MATH_\d+⟧")

_SYSTEM = """You help Japanese readers of English academic abstracts, one selected span at
a time.

Rules you must follow:
1. Any token of the form ⟦MATH_n⟧ is a protected formula. Copy each one through to your
   output exactly as written, in its place. Never translate, drop, renumber or reformat one.
2. Translate or analyse ONLY the text inside <selection>. Text inside <context> exists so
   you can resolve references; never include its translation in your answer.
3. Do not add information the selection does not contain. An honest, plain rendering beats
   an eloquent one.
4. Reply with JSON only: {"text": "..."}. No prose around it.
"""

#: One instruction per stage of spec section 7. Each is a different task, and the reader
#: climbs them in order — so producing the same translation six ways would defeat the sheet.
_STAGE_INSTRUCTIONS: dict[str, str] = {
    "hard_words": (
        "List only the words and phrases in the selection that a Japanese graduate student"
        " would likely stumble on, one per line, as `word … 日本語の語義`. Do not translate"
        " the sentence. Skip words any English reader knows. Formula tokens are not words;"
        " ignore them."
    ),
    "sentence_skeleton": (
        "Show the grammatical skeleton of the selection: mark the subject [S], main verb"
        " [V], object [O] and major modifiers [M], keeping the original English words and"
        " order, e.g. `[S] the estimator / [V] attains / [O] the optimal rate / [M] under"
        " ...`. Do not translate."
    ),
    "phrase_structure": (
        "Rewrite the selection with square brackets around each syntactic chunk (noun"
        " phrase, verb phrase, clause), keeping the original English words and order, so"
        " the reader can see where each phrase begins and ends. Do not translate."
    ),
    "literal": (
        "Translate the selection into Japanese literally, keeping the English clause order"
        " where grammatical, so the reader can map each phrase back to the original. Prefer"
        " transparency over naturalness."
    ),
    "natural": "Translate the selection into natural, precise Japanese.",
    "domain_meaning": (
        "Translate the selection into Japanese using the standard terminology of the given"
        " field, then — only if a term's field-specific sense differs from its everyday"
        " sense — append one short note in the form `※用語: この分野では…`."
    ),
}

#: Section 7's 翻訳設定, as instructions layered onto the stage.
_STYLE_INSTRUCTIONS: dict[str, str] = {
    "natural": "Aim for fluent Japanese a researcher would write.",
    "faithful": "Stay close to the source structure even at some cost to fluency.",
    "literal": "Stay as close to word-for-word as Japanese grammar allows.",
    "academic": "Use formal academic register (である調, standard technical terms).",
    "plain_japanese": "Use plain, simple Japanese; avoid jargon where an ordinary word exists.",
}


class AnthropicTranslationProvider:
    """Section 7's staged translation, from a model, with formulas kept intact."""

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
            # At construction, not at the first selection: a misconfigured provider must
            # fail where an operator sees it, not where a reader does.
            raise ValueError("an Anthropic API key is required; set PAPERMATCH_ANTHROPIC_API_KEY")
        self._api_key = api_key
        self.model = model
        self._transport = transport or HttpxPostTransport()
        self._rate_limiter = rate_limiter or RateLimiter(0.5)
        self._breaker = breaker or CircuitBreaker(failure_threshold=4, cooldown_seconds=120.0)

    @property
    def breaker(self) -> CircuitBreaker:
        return self._breaker

    def translate(self, request: TranslationRequest) -> TranslationResult:
        stage = _STAGE_INSTRUCTIONS.get(request.stage)
        if stage is None:
            raise ProviderUnavailable(f"unknown translation stage {request.stage!r}")

        self._breaker.before_call()
        self._rate_limiter.wait()
        try:
            response = self._transport.post(
                API_URL,
                json_body={
                    "model": self.model,
                    "max_tokens": MAX_TOKENS,
                    "system": _SYSTEM,
                    "messages": [{"role": "user", "content": self._prompt(request, stage)}],
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
            # Same split as everywhere else: 429/5xx is the service struggling and opens
            # the breaker; our own 4xx does not get to take translation down for everyone.
            if response.status_code == 429 or response.status_code >= 500:
                self._breaker.record_failure()
            raise ProviderUnavailable(f"Anthropic returned {response.status_code}")

        self._breaker.record_success()
        text = self._text_of(response.text)
        if text is None:
            # An unreadable reply is a failed translation, not an empty one: the router's
            # fallback path (show the original) is the right outcome, and it is reached
            # through ProviderUnavailable exactly as when the service is down.
            raise ProviderUnavailable("the model did not return readable JSON")

        # The glossary stage lists words, so it legitimately contains no formulas. Every
        # other stage must carry every token through; report what is missing and let the
        # router decide (it falls back to the original text).
        if request.stage == "hard_words":
            dropped: tuple[str, ...] = ()
        else:
            wanted = list(dict.fromkeys(_TOKEN_RE.findall(request.text)))
            present = set(_TOKEN_RE.findall(text))
            dropped = tuple(token for token in wanted if token not in present)

        return TranslationResult(
            translated_text=text,
            provider=self.name,
            model=self.model,
            prompt_version=PROMPT_VERSION,
            dropped_math_tokens=dropped,
            notes=(),
        )

    def _prompt(self, request: TranslationRequest, stage_instruction: str) -> str:
        style = _STYLE_INSTRUCTIONS.get(request.style, "")
        field = request.field_id or "unspecified"
        parts = [
            f"Task: {stage_instruction}",
            f"Style: {style}" if style else "",
            f"Field: {field}",
            f"Source language: {request.source_lang}; target language: {request.target_lang}.",
            "",
            # Fenced so the model can tell the selection from its surroundings. The tags
            # are ours, chosen to be unlikely in academic prose.
            f"<context>{request.context_before}</context>" if request.context_before else "",
            f"<selection>{request.text}</selection>",
            f"<context>{request.context_after}</context>" if request.context_after else "",
            "",
            'Reply with JSON only: {"text": "..."}',
        ]
        return "\n".join(part for part in parts if part)

    def _text_of(self, body: str) -> str | None:
        """The `text` field of the model's JSON reply, or None."""
        try:
            document = json.loads(body)
            joined = "".join(
                block.get("text", "")
                for block in document["content"]
                if block.get("type") == "text"
            )
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            return None

        candidate = joined.strip()
        if candidate.startswith("```"):
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
        text = parsed.get("text") if isinstance(parsed, dict) else None
        return text if isinstance(text, str) and text.strip() else None

    def health(self) -> ProviderHealth:
        # No request: a health check that costs a model call would run on every GET /health.
        open_breaker = self._breaker.is_open
        return ProviderHealth(
            name=self.name,
            healthy=not open_breaker,
            detail=("circuit breaker is open" if open_breaker else f"model {self.model}"),
            checked_at=datetime.now(tz=UTC),
        )
