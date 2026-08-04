"""Proposing and checking the steps between a paper's equations (spec section 12).

Steps 6–8 of section 12: classify the relation between consecutive equations, propose
intermediate transformations, and verify them.

**A candidate is a proposal, not a claim.** Every step this produces starts `unverified`,
which section 12 hides by default. A check may then raise it — and only a check may. The
prose the author wrote between two equations is *evidence about* the transformation, never
verification of it: "squaring both sides" is what the author says they did, and a step that
said `mechanically_verified` because a sentence sounded confident would be the worst kind
of wrong here.

**Nothing invents an intermediate equation.** D-028 explains why: with no computer-algebra
system, a formula we generated between two of the paper's own would be fabrication wearing
the paper's clothes. So the endpoints of every candidate are equations that appear in the
manuscript, and what is generated is the *link* between them — the operation, taken from
the author's sentence, and the verification attempt.

**The operation text is quoted, not paraphrased.** It is the author's connective sentence
with the LaTeX cleaned out. Paraphrasing would put words in a paper's mouth and there is
no way for a reader to tell which they are reading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from papermatch_api.mathcheck.verify import NumericCheck, combined_status, spot_check
from papermatch_api.text.latex_document import ExtractedEquation, LatexDocument
from papermatch_api.text.latex_expression import translate_equation

__all__ = [
    "DEFAULT_SAMPLE_RANGE",
    "RELATION_CUES",
    "StepCandidate",
    "candidates_for",
    "classify_relation",
]

#: Phrases papers use for the transformation they just performed, mapped to a label.
#: Read off the author's own sentence: this is evidence about what happened, and the label
#: is only ever a summary of that sentence, never a conclusion about correctness.
RELATION_CUES: tuple[tuple[str, str], ...] = (
    (r"\bsquar", "square_both_sides"),
    (r"\btak(?:e|ing) the (?:square )?root", "take_root"),
    (r"\bchang(?:e|ing)\b.*\bcoordinat", "change_of_variables"),
    (r"\bsubstitut", "substitution"),
    (r"\bintegrat", "integrate"),
    (r"\bdifferentiat", "differentiate"),
    (r"\bexpand", "expand"),
    # Verb forms only. `\bfactor` also matched "contributes a factor of 2\pi", which is a
    # noun and describes the result rather than the operation — a cue that fires on the
    # wrong sentence produces a confident, wrong label.
    (r"\bfactoris|\bfactoriz|\bfactored\b|\bfactor(?:s|ing)? out\b", "factorise"),
    (r"\brearrang", "rearrange"),
    (r"\bsimplif", "simplify"),
    (r"\btak(?:e|ing) the limit", "take_limit"),
    (r"\bapply(?:ing)?\b", "apply_identity"),
)

#: Where a free variable is sampled when the paper does not say.
#:
#: Strictly positive and away from 1, because that is where a wrong step is least likely
#: to agree by accident: 0 and 1 are fixed points of far too many operations, and negative
#: values put `log` and `sqrt` out of their domain and would be skipped anyway. The range
#: is part of the recorded claim (see `mathcheck`), so a pass means "on this interval".
DEFAULT_SAMPLE_RANGE: tuple[float, float] = (0.3, 2.7)


@dataclass(frozen=True)
class StepCandidate:
    """A proposed transformation between two equations the paper actually contains."""

    from_index: int
    to_index: int
    from_latex: str
    to_latex: str
    #: The author's connective sentence, cleaned of markup. Quoted, never paraphrased.
    operation: str
    #: A label from `RELATION_CUES`, or `None` when the sentence matched none of them.
    relation: str | None
    #: One of the `verificationStatus` values. `unverified` until a check passes.
    verification_status: str
    #: What was tried and what happened, so a reviewer can see why the status is what it is.
    detail: str
    #: Ranges the check sampled over, empty when no check ran. Part of the claim.
    sampled: dict[str, tuple[float, float]] | None = None

    @property
    def provenance_kind(self) -> str:
        """Always `original`.

        Both endpoints are the paper's equations and the operation text is the paper's
        sentence. Nothing here was generated, so labelling it `ai_explanation` would be
        as wrong as labelling a generated step `original`.
        """
        return "original"


def classify_relation(text: str) -> str | None:
    """The transformation the author's sentence describes, or ``None``.

    ``None`` is a normal answer. A sentence that matches no cue is a sentence we did not
    understand, and inventing a label for it would put a claim in the paper's mouth.
    """
    lowered = text.lower()
    for pattern, label in RELATION_CUES:
        if re.search(pattern, lowered):
            return label
    return None


def _connective(previous: ExtractedEquation, current: ExtractedEquation) -> str:
    """The prose between two equations.

    The text after the first and before the second describe the same gap from either side.
    They are usually the same paragraph; when they differ, both are kept, because dropping
    one loses the half of the explanation the author put there.
    """
    # The sentence *before the target* comes first: that is where papers state what they
    # just did ("Squaring (1) and renaming..."), while the text after the source equation
    # is usually its symbol definitions. Leading with the definitions made the operation
    # read as though the symbols were the transformation.
    parts = [current.context_before.strip(), previous.context_after.strip()]
    unique = [part for index, part in enumerate(parts) if part and part not in parts[:index]]
    return " ".join(unique)


def _substitute(expression: str, name: str, replacement: str) -> str:
    """Replace a whole identifier with a parenthesised expression.

    Safe as a text substitution because the expression language produced by
    `latex_expression` has no strings, no comments and no attribute access — an identifier
    can only ever be an identifier, so a word-boundary match cannot hit anything else.
    """
    return re.sub(rf"\b{re.escape(name)}\b", f"({replacement})", expression)


def _verify(
    previous: ExtractedEquation, current: ExtractedEquation
) -> tuple[str, str, dict[str, tuple[float, float]] | None]:
    """Try to check the step by substituting the first equation into the second.

    **A paper's equation is a definition, not an identity over a box.** `y = (a+b)/2`
    constrains `y`; sampling `a`, `b` and `y` independently means the constraint almost
    never holds, so a check built that way *can only fail* — and it fails loudest on
    correct mathematics. The first version here did exactly that.

    What works instead: take the variable the first equation solves for, sample the rest,
    compute that variable from the first equation, and ask whether the second equation
    holds at the point that produces. If the step is sound it does; if a line was
    mistranscribed, it does not.

    This checks *consistency*, not derivability. It cannot tell that the author's stated
    operation is the one that was performed — only that the two lines describe the same
    relation. That is a real check and a narrow one, and the status it can award says so.
    """
    before = translate_equation(previous.latex)
    after = translate_equation(current.latex)
    if before is None or after is None:
        which = "前" if before is None else "後"
        return (
            "unverified",
            f"{which}の式が対応範囲外の構文（積分・総和・極限など）のため機械的に確認できない",
            None,
        )

    defined = before.defines
    if defined is None:
        return (
            "unverified",
            "前の式が 1 つの変数について解かれていないため、代入して確かめられない",
            None,
        )

    if defined not in after.variables:
        # The second line does not mention what the first defined, so substituting says
        # nothing about it — the two are not a step in the sense this check can see.
        return "unverified", f"後の式に {defined} が現れないため、代入しても比較にならない", None

    free = sorted((before.rhs_variables | after.variables) - {defined})
    variables = dict.fromkeys(free, DEFAULT_SAMPLE_RANGE)

    outcome = spot_check(
        NumericCheck(
            lhs=_substitute(after.lhs, defined, before.rhs),
            rhs=_substitute(after.rhs, defined, before.rhs),
            variables=variables,
        )
    )
    if not outcome.passed:
        return "unverified", f"代入後に一致しなかった: {outcome.detail}", variables

    # `combined_status` with no dimensional check gives `numerically_spot_checked`, which
    # is the honest ceiling here: nothing dimensional was supplied and no symbolic
    # manipulation was performed, so `mechanically_verified` would overstate what ran.
    return (
        combined_status(outcome, None),
        f"{defined} を代入し、標本点 {outcome.evaluated} 点で一致",
        variables,
    )


def candidates_for(document: LatexDocument) -> list[StepCandidate]:
    """Propose a step between each consecutive pair of equations in ``document``.

    Consecutive rather than every pair: a paper's equations are written in the order the
    argument runs, and a link between equation 1 and equation 7 is a claim about structure
    that this stage has no evidence for.
    """
    candidates: list[StepCandidate] = []
    for index in range(len(document.equations) - 1):
        previous = document.equations[index]
        current = document.equations[index + 1]
        operation = _connective(previous, current)
        status, detail, sampled = _verify(previous, current)
        candidates.append(
            StepCandidate(
                from_index=index,
                to_index=index + 1,
                from_latex=previous.latex,
                to_latex=current.latex,
                operation=operation,
                relation=classify_relation(operation),
                verification_status=status,
                detail=detail,
                sampled=sampled,
            )
        )
    return candidates
