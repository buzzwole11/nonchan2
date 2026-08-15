"""An explanation provider that invents nothing (spec sections 8, 21).

Section 8 asks for background knowledge, technical terms, and four readings of why a paper
matters. Three of those four readings are judgements about a literature, and there is no way
to produce them from metadata. **So this provider does not produce them.**

That is the whole design. A provider that filled the gap with plausible sentences would be
the worst failure this codebase can have: a reader has no way to tell an invented
"位置づけ in the field" from a real one, and section 0's requirement that AI explanation be
distinguishable from verified content is meaningless if the AI content is fabricated in the
first place. So each answer here is either derived from something we actually hold — the
paper's own sentences, the field taxonomy, the structure classifier's output — or it is
absent, with a reason recorded saying why.

**What it can do, it does from the paper's own text.** A technical term is a phrase the
abstract actually contains, shown with the sentence it appeared in. That is not an
explanation, and it is not labelled as one: it is a pointer back into the original, which is
useful before reading and cannot be wrong.

**What it cannot do, it says.** `unavailable_reason` travels with the empty result, so the
interface can say "this needs a language model that is not configured" rather than showing
an empty panel that looks like a bug.

`AnthropicExplanationProvider` is the one that answers the rest. This is the default because
it needs no key, no network and no trust.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from papermatch_api.providers.base import ProviderHealth

__all__ = ["PROMPT_VERSION", "DerivedExplanationProvider"]

#: Bumped when the derivation changes in a way that would produce different output. Rows are
#: keyed on it, so old explanations stay readable rather than being silently rewritten.
PROMPT_VERSION = "derived-v1"

#: Words that look technical but are the vocabulary of every abstract. A "technical term"
#: list containing `method` and `results` teaches nothing and costs the reader the time it
#: takes to notice that.
_GENERIC = frozenset(
    {
        "abstract",
        "analysis",
        "approach",
        "conclusion",
        "data",
        "effect",
        "experiment",
        "framework",
        "method",
        "methods",
        "model",
        "models",
        "paper",
        "problem",
        "result",
        "results",
        "study",
        "system",
        "technique",
        "theory",
        "work",
    }
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
#: Capitalised multi-word phrases and hyphenated compounds — the shape a named method,
#: model or object takes in an abstract. Deliberately narrow: a looser pattern returns
#: sentence-initial ordinary words, which is noise dressed as terminology.
_TERM = re.compile(
    r"\b(?:[A-Z][a-z]+(?:[- ][A-Z][a-z]+)+"  # Kagome Lattices, Non-Reversible Measures
    r"|[a-z]+(?:-[a-z]+){1,3}"  # non-reversible, gradient-descent
    r"|[A-Z]{2,6}\d*)\b"  # AdS, CFT, SU2
)

#: How many terms section 8 asks for. Fewer is allowed and common; more is noise.
MIN_TERMS, MAX_TERMS = 3, 5


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]


class DerivedExplanationProvider:
    """Answers only from the paper and the taxonomy; refuses the rest by name."""

    name = "derived"
    model = "rule-based"

    def explain(self, prompt_kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if prompt_kind == "before_you_read":
            return self._before_you_read(payload)
        if prompt_kind == "why_it_matters":
            return self._why_it_matters(payload)
        return {
            "items": [],
            "unavailableReason": f"未対応の説明種別（{prompt_kind}）",
            "promptVersion": PROMPT_VERSION,
        }

    # ------------------------------------------------------------------ before you read

    def _before_you_read(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Terms from the abstract, and the field this paper sits in.

        Both are things we hold. Neither is an explanation — section 8's 学部レベルの短い説明
        is exactly the part a rule cannot write, and it is left to the model provider.
        """
        abstract = str(payload.get("abstract") or "")
        items: list[dict[str, Any]] = []

        for label, field_id in (
            ("parentFieldLabel", "parentFieldId"),
            ("fieldLabel", "fieldId"),
        ):
            name = payload.get(label)
            if isinstance(name, str) and name.strip():
                items.append(
                    {
                        "kind": "background",
                        "title": name.strip(),
                        # No prose. The field a paper belongs to is a fact from the
                        # taxonomy; a sentence describing that field would not be.
                        "detail": None,
                        "source": "taxonomy",
                        "fieldId": payload.get(field_id),
                    }
                )

        for term, context in self._terms(abstract):
            items.append(
                {
                    "kind": "term",
                    "title": term,
                    # The sentence the term appeared in, verbatim. A pointer back into the
                    # original rather than a gloss — it cannot be wrong, and the reader can
                    # see for themselves what the paper does with the word.
                    "detail": context,
                    "source": "abstract",
                }
            )

        terms = sum(1 for item in items if item["kind"] == "term")
        reason = None
        if terms < MIN_TERMS:
            reason = (
                "この Abstract から確実に取り出せる専門用語が "
                f"{terms} 件しかありません（説明モデルが未設定）"
            )
        return {
            "items": items,
            "unavailableReason": reason,
            "promptVersion": PROMPT_VERSION,
        }

    def _terms(self, abstract: str) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        seen: set[str] = set()
        for sentence in _sentences(abstract):
            for match in _TERM.finditer(sentence):
                term = match.group(0)
                key = term.lower()
                if key in seen or key in _GENERIC or len(key) < 4:
                    continue
                # A single generic word joined by a hyphen is still generic.
                if all(part in _GENERIC for part in re.split(r"[- ]", key) if part):
                    continue
                seen.add(key)
                found.append((term, sentence))
                if len(found) == MAX_TERMS:
                    return found
        return found

    # ------------------------------------------------------------------ why it matters

    def _why_it_matters(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Nothing. Deliberately, and with the reason attached.

        Section 8's four audiences — 初学者 / 研究者 / 応用 / 分野史 — are each a claim about
        what a paper means to somebody. None of them follows from a title, a year and a
        category. Producing them from a template would give every paper in a field the same
        significance, which reads as insight and is not.
        """
        return {
            "items": [],
            "unavailableReason": (
                "「なぜ重要か」は論文の位置づけについての判断で、メタデータからは導けません。"
                "説明モデル（PAPERMATCH_EXPLANATION_PROVIDER=anthropic）が要ります"
            ),
            "promptVersion": PROMPT_VERSION,
        }

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            healthy=True,
            detail="規則ベース。生成はせず、持っているものだけを返す",
            checked_at=datetime.now(tz=UTC),
        )
