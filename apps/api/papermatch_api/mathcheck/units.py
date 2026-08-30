"""Turning declared units into base dimensions (spec section 12: 次元解析).

`mathcheck.verify.dimension_check` compares two mappings of base-dimension exponents. This
is what produces those mappings from what a paper actually says: a symbol table entry with
`unit = "m/s^2"` becomes `{"L": 1, "T": -2}`, and an expression's dimension is computed from
its variables'.

**Refusing is the normal outcome and it costs nothing.** Most symbols in most papers have no
declared unit, and a dimensional verdict computed from a guessed unit is *worse than no
verdict*: it upgrades a step's `verificationStatus` on evidence that does not exist, and
`mechanically_verified` is a label a reader is entitled to trust. So every function here
returns `None` rather than a default whenever anything is unknown, and the pipeline simply
does not run a dimensional check for that step.

**Adding unlike dimensions is a failure, not a refusal.** `t + x` with `t` in seconds and `x`
in metres is not "we cannot tell" — it is wrong, and the difference matters: a refusal leaves
the step unverified, while a failure says the step does not hold. Both are reported, and the
caller distinguishes them.

**The unit vocabulary is deliberately small.** SI bases, a handful of derived units that
appear constantly in the fields this app covers, and nothing else. An unrecognised unit is
refused rather than parsed optimistically — `"arb. units"`, `"a.u."` and `"dimensionless (see
text)"` all appear in real papers and none of them mean what a permissive parser would decide.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping

from papermatch_api.mathcheck.verify import BASE_DIMENSIONS

__all__ = [
    "DERIVED_UNITS",
    "SI_BASE_UNITS",
    "Dimension",
    "DimensionError",
    "dimension_of_expression",
    "parse_dimensions",
    "parse_unit",
]

#: Exponents over `verify.BASE_DIMENSIONS`. Absent key means exponent zero.
Dimension = dict[str, int]


class DimensionError(ValueError):
    """The expression is dimensionally inconsistent — a finding, not a refusal."""


#: The SI bases, spelled the way symbol tables spell them.
SI_BASE_UNITS: dict[str, Dimension] = {
    "m": {"L": 1},
    "kg": {"M": 1},
    "g": {"M": 1},
    "s": {"T": 1},
    "A": {"I": 1},
    "K": {"K": 1},
    "mol": {"N": 1},
    "cd": {"J": 1},
}

#: Derived units common in physics and applied maths. Anything not here is refused.
DERIVED_UNITS: dict[str, Dimension] = {
    "N": {"M": 1, "L": 1, "T": -2},
    "J": {"M": 1, "L": 2, "T": -2},
    "W": {"M": 1, "L": 2, "T": -3},
    "Pa": {"M": 1, "L": -1, "T": -2},
    "Hz": {"T": -1},
    "C": {"I": 1, "T": 1},
    "V": {"M": 1, "L": 2, "T": -3, "I": -1},
    "T": {"M": 1, "T": -2, "I": -1},
    "eV": {"M": 1, "L": 2, "T": -2},
}

#: Ways a paper writes "this quantity has no dimensions".
_DIMENSIONLESS = frozenset({"1", "-", "—", "dimensionless", "無次元"})

_FACTOR = re.compile(r"^\s*([A-Za-zΩμ]+)\s*(?:\^\s*\(?\s*(-?\d+)\s*\)?)?\s*$")


def _lookup(symbol: str) -> Dimension | None:
    if symbol in DERIVED_UNITS:
        return dict(DERIVED_UNITS[symbol])
    if symbol in SI_BASE_UNITS:
        return dict(SI_BASE_UNITS[symbol])
    return None


def _combine(into: Dimension, other: Dimension, sign: int) -> None:
    for name, exponent in other.items():
        into[name] = into.get(name, 0) + sign * exponent


def _tidy(dimension: Dimension) -> Dimension:
    return {name: exponent for name, exponent in dimension.items() if exponent != 0}


def parse_unit(unit: str | None) -> Dimension | None:
    """`"m/s^2"` → `{"L": 1, "T": -2}`, or None when it cannot be read confidently.

    Handles products (`kg m/s^2` or `kg*m/s^2`) and a single solidus. Deliberately does not
    handle parenthesised groups, prefixes (`km`, `ms`) or units-with-commentary: each is a
    place where a wrong reading yields a confident wrong dimension, and refusing costs only
    a check that would not have run anyway.
    """
    if unit is None:
        return None
    text = unit.strip()
    if not text:
        return None
    if text.lower() in _DIMENSIONLESS or text in _DIMENSIONLESS:
        return {}

    if text.count("/") > 1:
        return None
    numerator, _, denominator = text.partition("/")

    result: Dimension = {}
    for part, sign in ((numerator, 1), (denominator, -1)):
        if not part.strip():
            if sign == -1:
                continue
            return None
        for factor in re.split(r"[\s*·⋅]+", part.strip()):
            if not factor:
                continue
            match = _FACTOR.match(factor)
            if match is None:
                return None
            base = _lookup(match.group(1))
            if base is None:
                return None
            exponent = int(match.group(2) or 1)
            _combine(result, {k: v * exponent for k, v in base.items()}, sign)

    return _tidy(result)


def parse_dimensions(text: str | None) -> Dimension | None:
    """`"M L / T"` → `{"M": 1, "L": 1, "T": -1}`, or None when it cannot be read.

    A **different notation** from `parse_unit`, and deliberately a different function.
    `"T"` means tesla as a unit and time as a base dimension; there is no way to tell from
    the string which was meant, so the caller — which knows what its own corpus writes —
    picks the parser. Auto-detecting would be the guess that silently turns a duration into
    a magnetic field.
    """
    if text is None:
        return None
    body = text.strip()
    if not body:
        return None
    if body.lower() in _DIMENSIONLESS or body in _DIMENSIONLESS:
        return {}

    if body.count("/") > 1:
        return None
    numerator, _, denominator = body.partition("/")

    result: Dimension = {}
    for part, sign in ((numerator, 1), (denominator, -1)):
        cleaned = part.strip().strip("()").strip()
        if not cleaned:
            if sign == -1:
                continue
            return None
        for factor in re.split(r"[\s*·⋅]+", cleaned):
            if not factor:
                continue
            # `1/L^2` is how a paper writes an inverse area. The `1` contributes nothing
            # rather than being an unreadable factor.
            if factor == "1":
                continue
            match = _FACTOR.match(factor)
            if match is None:
                return None
            base = match.group(1)
            if base not in BASE_DIMENSIONS:
                return None
            _combine(result, {base: int(match.group(2) or 1)}, sign)

    return _tidy(result)


def _is_zero(node: ast.AST) -> bool:
    """A literal zero, which is the one number that is dimension-neutral in a sum."""
    return (
        isinstance(node, ast.Constant) and isinstance(node.value, int | float) and node.value == 0
    )


def _dimension_of_node(node: ast.AST, units: Mapping[str, Dimension]) -> Dimension | None:
    """Recursive walk. None means "cannot tell"; DimensionError means "inconsistent"."""
    match node:
        case ast.Expression():
            return _dimension_of_node(node.body, units)

        case ast.Constant(value=value) if isinstance(value, int | float):
            # A bare number is dimensionless. That is a fact, not an assumption.
            return {}

        case ast.Name(id=name):
            # An undeclared variable is unknown, not dimensionless: assuming otherwise is
            # exactly the guess that produces a confident wrong verdict.
            return dict(units[name]) if name in units else None

        case ast.UnaryOp(op=ast.UAdd() | ast.USub(), operand=operand):
            return _dimension_of_node(operand, units)

        case ast.BinOp(op=ast.Add() | ast.Sub(), left=left, right=right):
            # A literal zero takes the dimension of whatever it is added to. `0 - E` is how
            # a difference is written and it is dimensionally fine; treating the `0` as
            # dimensionless like any other number reported the fixtures' own correct
            # expressions as inconsistent — a confident wrong verdict, which is the failure
            # this module exists to avoid.
            if _is_zero(left):
                return _dimension_of_node(right, units)
            if _is_zero(right):
                return _dimension_of_node(left, units)

            a = _dimension_of_node(left, units)
            b = _dimension_of_node(right, units)
            if a is None or b is None:
                return None
            if _tidy(a) != _tidy(b):
                raise DimensionError(
                    f"cannot add {_tidy(a) or 'dimensionless'} to {_tidy(b) or 'dimensionless'}"
                )
            return _tidy(a)

        case ast.BinOp(op=ast.Mult(), left=left, right=right):
            a = _dimension_of_node(left, units)
            b = _dimension_of_node(right, units)
            if a is None or b is None:
                return None
            merged = dict(a)
            _combine(merged, b, 1)
            return _tidy(merged)

        case ast.BinOp(op=ast.Div(), left=left, right=right):
            a = _dimension_of_node(left, units)
            b = _dimension_of_node(right, units)
            if a is None or b is None:
                return None
            merged = dict(a)
            _combine(merged, b, -1)
            return _tidy(merged)

        case ast.BinOp(op=ast.Pow(), left=left, right=right):
            # Only a literal integer exponent. `x**y` has no dimension unless `y` is a known
            # number, and a fractional power of a dimensional quantity is meaningful only
            # when the result divides evenly — refused rather than rounded.
            if not isinstance(right, ast.Constant) or not isinstance(right.value, int):
                return None
            a = _dimension_of_node(left, units)
            if a is None:
                return None
            return _tidy({name: exponent * right.value for name, exponent in a.items()})

        case ast.Call(func=ast.Name(id=function), args=args) if len(args) == 1:
            # sqrt is the one function with a dimensional rule that always works out.
            inner = _dimension_of_node(args[0], units)
            if inner is None:
                return None
            if function == "sqrt":
                if any(exponent % 2 for exponent in inner.values()):
                    raise DimensionError(f"cannot take the square root of {inner}")
                return _tidy({name: exponent // 2 for name, exponent in inner.items()})
            # exp, log, sin, … require a dimensionless argument. That is a real check.
            if _tidy(inner):
                raise DimensionError(f"{function} of a quantity with dimensions {_tidy(inner)}")
            return {}

        case _:
            return None


def dimension_of_expression(expression: str, units: Mapping[str, Dimension]) -> Dimension | None:
    """The dimension of `expression`, or None when any part of it is undeclared.

    Raises `DimensionError` when the expression is inconsistent — adding a length to a time,
    or taking the logarithm of something with dimensions. That is a finding about the
    mathematics and the caller reports it as a failed check, not as a missing one.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return None
    return _dimension_of_node(tree, units)
