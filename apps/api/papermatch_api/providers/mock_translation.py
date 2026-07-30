"""Deterministic :class:`TranslationProvider` for development and tests.

This mock does not attempt real translation. It produces structurally faithful output for
each of the six hint stages in spec section 7, so the bottom sheet can be built and tested
against realistic shapes, and it is deterministic so snapshot tests are stable.

The property that matters most — and the one the tests assert — is that every masked
formula token comes back untouched. A translation provider that damages a formula is
worse than no translation at all (spec section 7: 数式や式番号を翻訳モデルに改変させない).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from papermatch_api.providers.base import (
    ProviderHealth,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
)

MODEL_NAME = "mock-translation-v1"
PROMPT_VERSION = "mock/2026-07-30"

_TOKEN_RE = re.compile(r"⟦MATH_\d+⟧")

#: A small academic-English glossary. Enough to make the word-level stages look like the
#: real thing during UI work; replaced wholesale by a real provider in Phase 2.
GLOSSARY: dict[str, str] = {
    "abstract": "要旨",
    "algorithm": "アルゴリズム",
    "amplitude": "振幅",
    "approximation": "近似",
    "asymptotic": "漸近的な",
    "bound": "限界",
    "boundary": "境界",
    "coefficient": "係数",
    "compact": "コンパクトな",
    "conjecture": "予想",
    "constraint": "制約",
    "convergence": "収束",
    "correlation": "相関",
    "coupling": "結合",
    "criterion": "判定条件",
    "curvature": "曲率",
    "degenerate": "退化した",
    "dimension": "次元",
    "distribution": "分布",
    "duality": "双対性",
    "eigenvalue": "固有値",
    "entanglement": "量子もつれ",
    "entropy": "エントロピー",
    "equilibrium": "平衡",
    "estimate": "評価",
    "expansion": "展開",
    "generalisation": "一般化",
    "generalization": "一般化",
    "gradient": "勾配",
    "hypothesis": "仮説",
    "inequality": "不等式",
    "invariant": "不変量",
    "lattice": "格子",
    "manifold": "多様体",
    "minimiser": "最小化元",
    "monotonic": "単調な",
    "nonlinearity": "非線形性",
    "observable": "観測量",
    "operator": "作用素",
    "perturbative": "摂動論的な",
    "phase": "相",
    "posterior": "事後分布",
    "propagator": "伝播関数",
    "regime": "領域",
    "regularisation": "正則化",
    "regularization": "正則化",
    "renormalisation": "繰り込み",
    "renormalization": "繰り込み",
    "robustness": "頑健性",
    "scaling": "スケーリング",
    "singularity": "特異点",
    "spectrum": "スペクトル",
    "stationary": "定常な",
    "symmetry": "対称性",
    "threshold": "閾値",
    "topological": "位相的な",
    "trajectory": "軌道",
    "variance": "分散",
    "well-posedness": "適切性",
}

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "we",
        "with",
        "which",
        "not",
    }
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]+")


def _hard_words(text: str) -> list[tuple[str, str]]:
    """Stage 1: only the words a reader is likely to stumble on."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for match in _WORD_RE.finditer(text):
        word = match.group(0)
        lowered = word.lower()
        if lowered in _STOPWORDS or lowered in seen:
            continue
        seen.add(lowered)
        gloss = GLOSSARY.get(lowered)
        if gloss is None and len(lowered) >= 10:
            gloss = "（辞書未収録の専門語）"
        if gloss is not None:
            out.append((word, gloss))
    return out


def _skeleton(text: str) -> str:
    """Stage 2: a crude S / V / O / M split, enough to exercise the UI."""
    clause = text.strip().rstrip(".")
    words = clause.split()
    if len(words) < 3:
        return f"[S] {clause}"
    subject = " ".join(words[: max(1, len(words) // 4)])
    verb = words[max(1, len(words) // 4)]
    rest = " ".join(words[max(1, len(words) // 4) + 1 :])
    return f"[S] {subject} / [V] {verb} / [O·M] {rest}"


class MockTranslationProvider(TranslationProvider):
    """Stage-aware stub translation with guaranteed formula preservation."""

    name = "mock"

    def __init__(self, *, fail: bool = False) -> None:
        # ``fail=True`` lets tests drive the degraded path in spec section 25.
        self._fail = fail

    def translate(self, request: TranslationRequest) -> TranslationResult:
        if self._fail:
            from papermatch_api.providers.base import ProviderUnavailable

            raise ProviderUnavailable("mock translation provider configured to fail")

        text = request.text
        tokens = _TOKEN_RE.findall(text)
        stage = request.stage

        if stage == "hard_words":
            pairs = _hard_words(text)
            body = (
                "\n".join(f"{word} … {gloss}" for word, gloss in pairs)
                if pairs
                else "難しい語は見当たりません。"
            )
        elif stage == "sentence_skeleton":
            body = _skeleton(text)
        elif stage == "phrase_structure":
            body = re.sub(r",\s*", "] [", f"[{text.strip()}]")
        elif stage == "literal":
            parts: list[str] = []
            for chunk in text.split():
                token_match = _TOKEN_RE.fullmatch(chunk.strip(".,;:"))
                if token_match:
                    parts.append(chunk)
                    continue
                gloss = GLOSSARY.get(chunk.lower().strip(".,;:"))
                parts.append(f"{chunk}（{gloss}）" if gloss else chunk)
            body = " ".join(parts)
        elif stage == "domain_meaning":
            field = request.field_id or "この分野"
            body = f"［{field} の文脈］{text}"
        else:  # natural
            body = f"［{request.style} 訳・モック］{text}"

        # The word-list stage is a glossary, not a rendering of the sentence, so it is
        # not expected to contain the formulas. Every other stage reproduces the full
        # selection, and there any missing token is a defect we report rather than hide.
        if stage == "hard_words":
            dropped: tuple[str, ...] = ()
        else:
            remaining = set(_TOKEN_RE.findall(body))
            dropped = tuple(t for t in dict.fromkeys(tokens) if t not in remaining)

        return TranslationResult(
            translated_text=body,
            provider=self.name,
            model=MODEL_NAME,
            prompt_version=PROMPT_VERSION,
            dropped_math_tokens=dropped,
            notes=("This is mock output. No real translation was performed.",),
        )

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            healthy=not self._fail,
            detail="mock provider" if not self._fail else "configured to fail",
            checked_at=datetime.now(tz=UTC),
        )
