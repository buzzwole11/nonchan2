"""Abstract structure detection (spec section 8).

Splits an abstract into Background / Problem / Method / Result / Significance spans.

**This is a rule-based classifier, and it says so.** Spec section 8 requires the label to
carry how it was produced (AI分類の場合は自動検出ラベルを付け、原文を変更しない), so the
output is stamped ``heuristic`` rather than ``ai``. Calling cue-phrase matching "AI" would
overstate what a reader should trust it for, and the vocabulary now has a value for
exactly this (DECISIONS.md D-022).

Why a heuristic at all, rather than waiting for a model: the structure is what lets the
card show role labels and what Phase 2's "Before you read" needs to find the method and
result sentences. A cue-phrase pass gets most academic abstracts right because the genre
is highly conventional, it costs nothing, it runs offline, and — most importantly — it
gives the eventual model a labelled baseline to be measured against. The fixture corpus
carries ``detected_by='source'`` ground truth for precisely that comparison.

The original text is never modified. Only offsets are stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from papermatch_api.text.math_placeholders import mask_math

#: Cue phrases per section, lower-cased. Ordered by how strongly they signal the role.
#: Drawn from the conventional shape of an academic abstract rather than from any corpus,
#: which is why the confidence they produce is capped well below 1.
CUES: dict[str, tuple[tuple[str, float], ...]] = {
    "background": (
        ("is a fundamental", 0.6),
        ("has long been", 0.6),
        ("are widely used", 0.55),
        ("classify", 0.4),
        ("describes", 0.4),
        ("relates", 0.4),
        ("organise", 0.4),
        ("organize", 0.4),
        ("measures", 0.4),
        ("plays a", 0.5),
        ("recent years", 0.55),
        ("it is well known", 0.7),
        ("let ", 0.35),
    ),
    "problem": (
        ("however", 0.7),
        ("remains open", 0.8),
        ("remains poorly", 0.8),
        ("remains unclear", 0.8),
        ("it is unclear", 0.8),
        ("it is not known", 0.8),
        ("has not been", 0.7),
        ("no ", 0.3),
        ("cannot", 0.6),
        ("fail", 0.6),
        ("break down", 0.7),
        ("is unknown", 0.75),
        ("resisted", 0.7),
        ("existing", 0.55),
        ("current ", 0.5),
        ("limited", 0.5),
        ("open question", 0.8),
        ("difficult", 0.5),
    ),
    "method": (
        ("we propose", 0.85),
        ("we present", 0.85),
        ("we introduce", 0.85),
        ("we develop", 0.8),
        ("we construct", 0.8),
        ("we derive", 0.8),
        ("we evaluate", 0.75),
        ("we combine", 0.75),
        ("we use", 0.7),
        ("we apply", 0.7),
        ("we analyse", 0.7),
        ("we analyze", 0.7),
        ("we perform", 0.75),
        ("we run", 0.7),
        ("we compare", 0.7),
        ("we build", 0.7),
        ("we model", 0.7),
        ("we prove", 0.6),
        ("here we", 0.7),
        ("in this paper", 0.6),
        ("our approach", 0.7),
        ("using ", 0.35),
        ("based on", 0.35),
    ),
    "result": (
        ("we find", 0.85),
        ("we show", 0.8),
        ("we obtain", 0.85),
        ("we prove that", 0.8),
        ("we establish", 0.8),
        ("we achieve", 0.8),
        ("we improve", 0.8),
        ("results show", 0.85),
        ("we report", 0.75),
        ("yields", 0.6),
        ("the result", 0.5),
        ("converges", 0.5),
        ("improves", 0.6),
        ("reduces", 0.55),
        ("diverges", 0.55),
        ("scales as", 0.6),
        ("closes at", 0.6),
        ("outperform", 0.8),
    ),
    "significance": (
        ("this suggests", 0.8),
        ("these results suggest", 0.85),
        ("our findings", 0.8),
        ("this identifies", 0.75),
        ("this opens", 0.75),
        ("this settles", 0.75),
        ("this narrows", 0.7),
        ("this closes", 0.7),
        ("this confirms", 0.7),
        ("implications", 0.75),
        ("paves the way", 0.85),
        ("more broadly", 0.75),
        ("should transfer", 0.7),
        ("applies to", 0.55),
        ("can be used", 0.6),
        ("makes it possible", 0.7),
        ("argues for", 0.65),
        ("is necessary before", 0.6),
    ),
}

#: The order the roles appear in, which is itself a strong prior for this genre.
ORDER = ("background", "problem", "method", "result", "significance")


@dataclass(frozen=True)
class DetectedSegment:
    start: int
    end: int
    section: str
    confidence: float
    detected_by: str = "heuristic"


def _sentence_spans(abstract: str) -> list[tuple[int, int]]:
    """Sentence boundaries, skipping periods that live inside maths.

    Reuses the maths masker so ``$n = 1.5$`` and ``$\\rho(T)$.`` behave, rather than
    re-deriving the rules here and letting the two drift apart.
    """
    masked = mask_math(abstract)
    # Work on the masked text so a period inside LaTeX cannot end a sentence, then map
    # the boundaries back by walking the same spans.
    spans: list[tuple[int, int]] = []
    start = 0
    text = masked.masked_text

    # Offsets differ between masked and original, so rebuild an index map.
    index_map: list[int] = []
    cursor = 0
    for span in masked.spans:
        index_map.extend(range(cursor, span.start))
        # Every character of the token maps to the start of the original formula.
        index_map.extend([span.start] * len(span.token))
        cursor = span.end
    index_map.extend(range(cursor, len(abstract)))
    index_map.append(len(abstract))

    for i, char in enumerate(text):
        if char not in ".?!":
            continue
        nxt = text[i + 1] if i + 1 < len(text) else None
        if char == "." and nxt is not None and nxt.isdigit():
            continue
        if nxt is not None and not nxt.isspace():
            continue
        if re.search(
            r"\b(e\.g|i\.e|cf|et al|etc|vs|Fig|Eq|Eqs|Ref|Refs|Sec|approx)\.$", text[: i + 1]
        ):
            continue
        spans.append((start, i + 1))
        start = i + 1
    if start < len(text):
        spans.append((start, len(text)))

    out: list[tuple[int, int]] = []
    for s, e in spans:
        original_start = index_map[min(s, len(index_map) - 1)]
        original_end = index_map[min(e, len(index_map) - 1)]
        # Trim leading whitespace so the offsets point at the sentence, not the gap.
        while original_start < original_end and abstract[original_start].isspace():
            original_start += 1
        if original_end > original_start:
            out.append((original_start, original_end))
    return out


def _score_sentence(text: str) -> dict[str, float]:
    lowered = text.lower()
    scores = dict.fromkeys(ORDER, 0.0)
    for section, cues in CUES.items():
        for cue, weight in cues:
            if cue in lowered:
                scores[section] = max(scores[section], weight)
    return scores


def classify(abstract: str) -> list[DetectedSegment]:
    """Label every sentence of an abstract with its structural role.

    Two signals are combined: cue phrases, and position. Position matters a lot in this
    genre — an abstract almost always moves background → problem → method → result →
    significance — so a sentence with no cue at all is still labelled by where it sits,
    and a cue that would move the sequence backwards is discounted rather than obeyed.
    """
    spans = _sentence_spans(abstract)
    if not spans:
        return []

    detected: list[DetectedSegment] = []
    previous_index = 0

    for position, (start, end) in enumerate(spans):
        sentence = abstract[start:end]
        cue_scores = _score_sentence(sentence)

        # Positional prior: where a sentence at this relative position usually sits.
        relative = position / max(1, len(spans) - 1)
        expected_index = min(len(ORDER) - 1, round(relative * (len(ORDER) - 1)))

        best_section = ORDER[expected_index]
        best_score = 0.0
        for index, section in enumerate(ORDER):
            score = cue_scores[section]
            if score == 0.0:
                continue
            # Going backwards through the sequence is unusual; discount it rather than
            # forbidding it, because "however" genuinely can reopen a problem late on.
            if index < previous_index:
                score *= 0.5
            # A cue that agrees with the position is worth more than one that fights it.
            score *= 1.0 - 0.12 * abs(index - expected_index)
            if score > best_score:
                best_score = score
                best_section = section

        chosen_index = ORDER.index(best_section)
        # Never move backwards more than one role: abstracts do not usually loop.
        if chosen_index < previous_index - 1:
            best_section = ORDER[previous_index]
            chosen_index = previous_index
            best_score = min(best_score, 0.3)

        previous_index = max(previous_index, chosen_index)

        confidence = round(
            # A cue-supported label is worth more than a position-only one, and neither is
            # ever presented as certain — this is a heuristic and the number says so.
            min(0.85, 0.35 + best_score * 0.5) if best_score > 0 else 0.3,
            3,
        )
        detected.append(
            DetectedSegment(start=start, end=end, section=best_section, confidence=confidence)
        )

    return detected


def agreement(predicted: list[DetectedSegment], truth: list[tuple[int, int, str]]) -> float:
    """Fraction of ground-truth spans whose label the classifier reproduces.

    Used by the tests to hold the classifier to a floor against the fixture corpus, which
    carries ``detected_by='source'`` labels. When a real model replaces this, the same
    measurement decides whether it is actually better.
    """
    if not truth:
        return 1.0
    by_start = {segment.start: segment.section for segment in predicted}
    hits = sum(1 for start, _end, section in truth if by_start.get(start) == section)
    return hits / len(truth)
