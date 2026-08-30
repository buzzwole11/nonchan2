"""Numeric and dimensional checking of a claimed transformation (spec section 12).

Section 12 step 8 asks for 数式処理、数値代入、次元解析、極限, and step 9 for keeping what came
from the source separate from what we added. Section 11's `verificationStatus` vocabulary
is the result of that: a derivation step carries the name of the check that passed, and
section 12 hides anything that passed none.

**What this does and does not do.** There is no computer-algebra system here, and this
module does not parse LaTeX. It evaluates a *machine-readable form supplied alongside* the
formula: the author of a card writes the two sides of the claimed identity as ordinary
expressions, names the variables and their ranges, and this samples them. That is a real
check — a wrong algebraic step will disagree at almost every sample point — but it is
weaker than symbolic proof in one specific way: an identity that holds on the sampled
region and fails outside it will pass. Ranges are therefore part of the recorded claim.

Writing the check by hand also means the check can disagree with the LaTeX it is attached
to. That is a genuine hole and there is no way to close it without parsing the LaTeX;
what it buys, until then, is that a step marked verified has had *something* mechanical
happen to it, rather than someone having typed the word.

**The expression language is deliberately tiny.** These strings come from fixture files
and, later, from a pipeline; they are input. Evaluation walks the AST and admits only
arithmetic, comparisons and a fixed list of functions from `math`. No attribute access, no
names outside the declared variables, no calls to anything not on the list. `eval` with a
blanked `__builtins__` is not enough on its own — attribute traversal from a literal is
the standard way out of that — so the guard is the walk, not the environment.
"""

from __future__ import annotations

import ast
import math
from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = [
    "ALLOWED_FUNCTIONS",
    "BASE_DIMENSIONS",
    "CheckOutcome",
    "DimensionCheck",
    "ExpressionError",
    "NumericCheck",
    "combined_status",
    "dimension_check",
    "evaluate",
    "spot_check",
]

#: Everything an identity in these fixtures needs, and nothing that touches the process.
ALLOWED_FUNCTIONS: dict[str, object] = {
    "sqrt": math.sqrt,
    "exp": math.exp,
    "log": math.log,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "erf": math.erf,
    "gamma": math.gamma,
    "lgamma": math.lgamma,
    "fabs": math.fabs,
    "abs": abs,
    "floor": math.floor,
    "ceil": math.ceil,
    "pow": pow,
    "min": min,
    "max": max,
    "pi": math.pi,
    "e": math.e,
    "inf": math.inf,
}

#: SI base dimensions, plus the two that show up constantly in the fields this app covers.
BASE_DIMENSIONS = ("L", "M", "T", "I", "K", "N", "J")

_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Call,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.FloorDiv,
    ast.USub,
    ast.UAdd,
    ast.Compare,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Eq,
    ast.NotEq,
    ast.IfExp,
)


class ExpressionError(ValueError):
    """A check expression that will not be evaluated, and why."""


def _validate(tree: ast.AST, allowed_names: frozenset[str]) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(f"{type(node).__name__} is not allowed in a check expression")
        if isinstance(node, ast.Name) and node.id not in allowed_names:
            raise ExpressionError(f"unknown name {node.id!r}")
        if isinstance(node, ast.Call):
            # Only a bare name may be called: `f(x)`, never `obj.f(x)` or `(expr)(x)`.
            if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCTIONS:
                raise ExpressionError("only the listed mathematical functions may be called")
            if node.keywords:
                raise ExpressionError("keyword arguments are not allowed")


def evaluate(expression: str, variables: Mapping[str, float]) -> float:
    """Evaluate one check expression at one point.

    Raises ``ExpressionError`` for anything the language does not admit. Arithmetic that
    genuinely does not have a value at this point — a division by zero, a log of a
    negative — raises the underlying ``ArithmeticError`` or ``ValueError``; the sampler
    treats those as "not defined here" rather than as a failed identity.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"could not parse {expression!r}: {exc}") from exc

    allowed = frozenset(ALLOWED_FUNCTIONS) | frozenset(variables)
    _validate(tree, allowed)

    environment: dict[str, object] = {**ALLOWED_FUNCTIONS, **variables}
    compiled = compile(tree, filename="<check>", mode="eval")
    result = eval(compiled, {"__builtins__": {}}, environment)
    if not isinstance(result, (int, float)):
        raise ExpressionError(f"{expression!r} produced {type(result).__name__}, not a number")
    return float(result)


@dataclass(frozen=True)
class NumericCheck:
    """A claimed identity, in a form that can be sampled.

    ``variables`` maps a name to the closed interval it is sampled over. The interval is
    part of the claim: an identity is asserted *on this region*, and recording it is what
    stops a later reader over-reading a pass.
    """

    lhs: str
    rhs: str
    variables: dict[str, tuple[float, float]] = field(default_factory=dict)
    samples: int = 25
    #: Relative, because these expressions span many orders of magnitude.
    tolerance: float = 1e-9


@dataclass(frozen=True)
class DimensionCheck:
    """Both sides reduced to exponents over the base dimensions.

    A dimensionless quantity is the empty mapping, not a missing one — the difference
    between "this side has no dimensions" and "nobody said" matters here.
    """

    lhs: dict[str, int]
    rhs: dict[str, int]


@dataclass(frozen=True)
class CheckOutcome:
    passed: bool
    detail: str
    #: How many sample points actually had a value on both sides.
    evaluated: int = 0


def _sample_points(check: NumericCheck) -> list[dict[str, float]]:
    """Deterministic points across the declared box.

    Deterministic on purpose: a fixture whose verification status changes between runs is
    worse than one that is never checked, because it looks stable and is not. The points
    are irrational multiples of each range so they avoid the symmetric values (0, 1, π)
    where a wrong step is most likely to agree by accident.
    """
    names = sorted(check.variables)
    if not names:
        return [{}]

    points: list[dict[str, float]] = []
    golden = (math.sqrt(5.0) - 1.0) / 2.0
    for index in range(check.samples):
        point: dict[str, float] = {}
        for offset, name in enumerate(names):
            low, high = check.variables[name]
            # A different irrational stride per variable, so the points do not lie on a
            # diagonal of the box.
            fraction = ((index + 1) * golden * (offset + 1) ** 0.5) % 1.0
            point[name] = low + fraction * (high - low)
        points.append(point)
    return points


def spot_check(check: NumericCheck) -> CheckOutcome:
    """Sample both sides and compare (section 12: 数値代入).

    A point where either side has no value is skipped rather than counted as a failure —
    `1/x` at zero says nothing about whether the identity is true. If too few points
    survive, the result is a failure with that as the reason, because a check that
    evaluated twice has not checked anything.
    """
    points = _sample_points(check)
    evaluated = 0
    for point in points:
        try:
            left = evaluate(check.lhs, point)
            right = evaluate(check.rhs, point)
        except ExpressionError:
            raise
        except (ArithmeticError, ValueError):
            continue

        if math.isnan(left) or math.isnan(right):
            continue
        if math.isinf(left) or math.isinf(right):
            if left != right:
                return CheckOutcome(False, f"diverges differently at {point}", evaluated)
            evaluated += 1
            continue

        scale = max(abs(left), abs(right), 1.0)
        if abs(left - right) > check.tolerance * scale:
            return CheckOutcome(
                False,
                f"differs at {point}: {left!r} vs {right!r}",
                evaluated,
            )
        evaluated += 1

    # A quarter of the points that *exist*, not of `samples`: an identity between
    # constants has exactly one point, and evaluating it is a complete check rather than a
    # nearly-empty one.
    minimum = max(1, len(points) // 4)
    if evaluated < minimum:
        return CheckOutcome(
            False,
            f"only {evaluated} of {len(points)} points had a value on both sides",
            evaluated,
        )
    return CheckOutcome(True, f"agreed at {evaluated} sample points", evaluated)


def dimension_check(check: DimensionCheck) -> CheckOutcome:
    """Compare base-dimension exponents (section 12: 次元解析)."""
    unknown = {d for d in (*check.lhs, *check.rhs) if d not in BASE_DIMENSIONS}
    if unknown:
        return CheckOutcome(False, f"unknown base dimension(s): {sorted(unknown)}")

    left = {d: e for d, e in check.lhs.items() if e != 0}
    right = {d: e for d, e in check.rhs.items() if e != 0}
    if left != right:
        return CheckOutcome(False, f"{left or 'dimensionless'} vs {right or 'dimensionless'}")
    return CheckOutcome(True, f"both sides are {left or 'dimensionless'}")


def combined_status(numeric: CheckOutcome | None, dimensional: CheckOutcome | None) -> str:
    """The `verificationStatus` a step has earned.

    Two *independent* checks agreeing is a stronger claim than either alone — a wrong step
    has to survive both sampling and dimensional bookkeeping — so that combination is what
    `mechanically_verified` means here. Anything that passed no check is `unverified`,
    which section 12 hides by default. Nothing in this function can return
    `source_exact` or `human_reviewed`: those describe where a formula came from and who
    looked at it, and no amount of arithmetic establishes either.
    """
    numeric_ok = numeric is not None and numeric.passed
    dimensional_ok = dimensional is not None and dimensional.passed

    if numeric_ok and dimensional_ok:
        return "mechanically_verified"
    if numeric_ok:
        return "numerically_spot_checked"
    if dimensional_ok:
        return "dimensionally_checked"
    return "unverified"
