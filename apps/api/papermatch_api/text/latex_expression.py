"""Translating a narrow subset of LaTeX into an evaluable expression (spec section 12).

D-028 recorded a real hole: `mathcheck` evaluates a machine-readable form written *beside*
the formula, so the check can disagree with the LaTeX it claims to check. A step could be
marked verified while the formula on screen said something else. There is no way to close
that without reading the LaTeX itself, and this module is the beginning of reading it.

**It refuses far more than it accepts, and that is the design.** A translator that quietly
dropped `\\int` would turn an integral identity into an arithmetic one, sample it, and
report a pass — the formula would carry a verification badge earned by a different
statement. So every construct is either understood exactly or the whole expression is
refused. `None` is the common answer and a safe one: an unverified step is hidden, which
costs a reader nothing they had.

**What it accepts** is the arithmetic core: numbers, identifiers, `+ - * /`, powers,
`\\frac`, `\\sqrt`, parentheses, the functions `mathcheck` already allows, and Greek
letters as ordinary names. Subscripts become part of the name, so `t_{\\mathrm{mix}}` is
one variable called `t_mix` rather than a product.

**What it refuses**, deliberately and by name: integrals, sums, products, limits, matrices,
derivatives, relations other than a single `=`, and any command not on the list. Silence
about an unknown command is the one thing that would make this dangerous.
"""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass

__all__ = [
    "FUNCTION_COMMANDS",
    "REFUSED_COMMANDS",
    "TranslatedEquation",
    "translate_equation",
    "translate_expression",
]

#: Commands that map to a function `mathcheck.evaluate` already allows.
FUNCTION_COMMANDS: dict[str, str] = {
    "sqrt": "sqrt",
    "exp": "exp",
    "log": "log",
    "ln": "log",
    "sin": "sin",
    "cos": "cos",
    "tan": "tan",
    "sinh": "sinh",
    "cosh": "cosh",
    "tanh": "tanh",
    "arcsin": "asin",
    "arccos": "acos",
    "arctan": "atan",
}

#: Named so a refusal can say which construct stopped it. A maintainer reading
#: "refused: \\int" learns something; "could not parse" does not.
REFUSED_COMMANDS: frozenset[str] = frozenset(
    {
        "int",
        "iint",
        "iiint",
        "oint",
        "sum",
        "prod",
        "lim",
        "limsup",
        "liminf",
        "partial",
        "nabla",
        "det",
        "begin",
        "end",
        "binom",
        "choose",
        "infty",
        "to",
        "mapsto",
    }
)

#: Greek letters and similar, which are variable names rather than operators.
_LETTER_COMMANDS = {
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta", "theta",
    "vartheta", "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "rho", "varrho",
    "sigma", "varsigma", "tau", "upsilon", "phi", "varphi", "chi", "psi", "omega",
    "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Upsilon", "Phi", "Psi",
    "Omega",
}  # fmt: skip

#: `\pi` is a constant, not a free variable, and `mathcheck` knows the name.
_CONSTANT_COMMANDS = {"pi": "pi"}

#: Commands that only change how something is drawn. Their argument passes through.
#:
#: `\left` and `\right` are deliberately NOT here. They are delimiters rather than
#: wrappers, and having them in this set let `_term` consume a `\right` as a juxtaposed
#: factor, which refused every `\left( ... \right)` expression.
_STYLE_COMMANDS = {"mathrm", "mathit", "text", "textrm", "mathbf", "operatorname"}

#: Multiplication and spacing that carry no value.
_IGNORED = {",", ";", ":", "!", "quad", "qquad", "displaystyle", "limits", "nolimits"}

_MULTIPLY_COMMANDS = {"cdot", "times"}

#: What counts as a bare variable name in the produced expression language.
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_TOKEN_RE = re.compile(
    r"""
    (?P<command>\\[A-Za-z]+|\\[,;:!])
  | (?P<number>\d+(?:\.\d+)?)
  | (?P<name>[A-Za-z])
  | (?P<open>[({\[])
  | (?P<close>[)}\]])
  | (?P<op>[+\-*/^_=])
  | (?P<space>\s+)
    """,
    re.VERBOSE,
)


class _Refused(Exception):
    """Raised internally the moment something is not understood."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class TranslatedEquation:
    """A LaTeX equation split into two evaluable sides."""

    lhs: str
    rhs: str
    #: Per side, because a caller needs to know whether one side is a lone variable being
    #: defined by the other — which is what makes an equation checkable at all.
    lhs_variables: frozenset[str]
    rhs_variables: frozenset[str]

    @property
    def variables(self) -> frozenset[str]:
        return self.lhs_variables | self.rhs_variables

    @property
    def defines(self) -> str | None:
        """The variable this equation solves for, when it is of the form ``v = f(...)``.

        ``None`` when the left side is anything else. A paper's equation is usually a
        definition rather than an identity over a box, and knowing which variable it
        defines is what lets a check sample the others and compute this one.
        """
        name = self.lhs.strip()
        if not _IDENTIFIER_RE.fullmatch(name):
            return None
        return None if name in self.rhs_variables else name


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str


def _tokenise(latex: str) -> list[_Token]:
    tokens: list[_Token] = []
    position = 0
    while position < len(latex):
        match = _TOKEN_RE.match(latex, position)
        if match is None:
            raise _Refused(f"読めない文字 {latex[position]!r}")
        position = match.end()
        kind = match.lastgroup or ""
        if kind == "space":
            continue
        tokens.append(_Token(kind, match.group()))
    return tokens


class _Parser:
    """Recursive descent over the accepted subset."""

    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._index = 0
        self.variables: set[str] = set()
        #: Whether the most recent atom was a bare identifier, which is what makes a
        #: following `(` ambiguous — see `_term`.
        self._last_atom_was_name = False

    # -- token helpers --------------------------------------------------------------

    def _peek(self) -> _Token | None:
        return self._tokens[self._index] if self._index < len(self._tokens) else None

    def _next(self) -> _Token:
        token = self._peek()
        if token is None:
            raise _Refused("式が途中で終わっている")
        self._index += 1
        return token

    def _expect_group(self) -> str:
        """The next `{...}` group, or a single token used as an argument."""
        token = self._next()
        if token.kind == "open" and token.value == "{":
            inner = self._expression(stop_at_close=True)
            closing = self._next()
            if closing.kind != "close":
                raise _Refused("括弧が閉じていない")
            return inner
        # `\sqrt2` and `x^2` are legal LaTeX; a single token is the whole argument.
        return self._atom_from(token)

    # -- grammar --------------------------------------------------------------------

    def _expression(self, *, stop_at_close: bool = False) -> str:
        result = self._term()
        while True:
            token = self._peek()
            if token is None:
                break
            if token.kind == "close":
                if stop_at_close:
                    break
                raise _Refused("対応しない閉じ括弧")
            if token.kind == "op" and token.value in {"+", "-"}:
                self._next()
                result = f"({result} {token.value} {self._term()})"
                continue
            break
        return result

    def _term(self) -> str:
        result = self._factor()
        last_was_name = self._last_atom_was_name
        while True:
            token = self._peek()
            if token is None:
                break
            if token.kind == "op" and token.value in {"*", "/"}:
                self._next()
                result = f"({result} {token.value} {self._factor()})"
                continue
            if token.kind == "command" and token.value.lstrip("\\") in _MULTIPLY_COMMANDS:
                self._next()
                result = f"({result} * {self._factor()})"
                continue
            # `f(x)` is function application in a paper and a product in LaTeX's grammar,
            # and nothing in the markup says which. Reading it as a product would sample
            # `f * x` against the other side and report a verdict about a statement the
            # paper never made — so an identifier immediately followed by `(` is refused
            # rather than guessed. A *number* followed by `(` is unambiguous and stays.
            if last_was_name and token.kind == "open" and token.value == "(":
                raise _Refused("関数適用と積の区別がつかない（識別子の直後の括弧）")

            # Juxtaposition is multiplication: `2x`, `2(b+c)`, `x \sqrt{y}`.
            if token.kind in {"number", "name", "command"} or (
                token.kind == "open" and token.value in {"(", "{"}
            ):
                if token.kind == "command":
                    name = token.value.lstrip("\\")
                    if name in _IGNORED:
                        self._next()
                        continue
                    if name not in (
                        FUNCTION_COMMANDS.keys()
                        | _LETTER_COMMANDS
                        | _CONSTANT_COMMANDS.keys()
                        | _STYLE_COMMANDS
                        | {"frac"}
                    ):
                        break
                result = f"({result} * {self._factor()})"
                last_was_name = self._last_atom_was_name
                continue
            break
        return result

    def _factor(self) -> str:
        token = self._peek()
        if token is not None and token.kind == "op" and token.value == "-":
            self._next()
            return f"(-{self._factor()})"
        base = self._atom_from(self._next())
        token = self._peek()
        if token is not None and token.kind == "op" and token.value == "^":
            self._next()
            return f"({base} ** {self._expect_group()})"
        return base

    def _atom_from(self, token: _Token) -> str:
        self._last_atom_was_name = False

        if token.kind == "number":
            return token.value

        if token.kind == "name":
            self._last_atom_was_name = True
            return self._identifier(token.value)

        if token.kind == "open" and token.value in {"(", "{"}:
            inner = self._expression(stop_at_close=True)
            closing = self._next()
            if closing.kind != "close":
                raise _Refused("括弧が閉じていない")
            return f"({inner})"

        if token.kind == "command":
            return self._command(token.value.lstrip("\\"))

        raise _Refused(f"想定外のトークン {token.value!r}")

    def _identifier(self, head: str) -> str:
        """A name, absorbing any `_{...}` subscript into the name itself.

        `t_{\\mathrm{mix}}` is one variable, not `t` times something. Treating it as a
        product would sample two variables that do not exist and could agree by accident.
        """
        name = head
        token = self._peek()
        if token is not None and token.kind == "op" and token.value == "_":
            self._next()
            name = f"{name}_{self._subscript_text()}"
        # `\lambda` is one of the most common symbols in a paper and `lambda` is a Python
        # keyword, so the produced expression was a syntax error rather than a refusal —
        # the caller saw a crash where it expected a clean "cannot check this".
        if keyword.iskeyword(name) or keyword.issoftkeyword(name):
            name = f"{name}_"
        self.variables.add(name)
        return name

    def _subscript_text(self) -> str:
        token = self._next()
        if token.kind == "open" and token.value == "{":
            parts: list[str] = []
            depth = 1
            while True:
                inner = self._next()
                if inner.kind == "open" and inner.value == "{":
                    depth += 1
                    continue
                if inner.kind == "close":
                    depth -= 1
                    if depth == 0:
                        break
                    continue
                if inner.kind == "command":
                    name = inner.value.lstrip("\\")
                    if name in _STYLE_COMMANDS:
                        continue
                    if name in _LETTER_COMMANDS:
                        parts.append(name)
                        continue
                    raise _Refused(f"添字に使えない命令 \\{name}")
                parts.append(inner.value)
            text = "".join(parts)
        else:
            text = token.value.lstrip("\\")
        cleaned = re.sub(r"[^0-9A-Za-z_]", "", text)
        if not cleaned:
            raise _Refused("空の添字")
        return cleaned

    def _command(self, name: str) -> str:
        if name in REFUSED_COMMANDS:
            # By name, so the reason is actionable.
            raise _Refused(f"対応していない構造 \\{name}")

        if name == "frac":
            numerator = self._expect_group()
            denominator = self._expect_group()
            return f"(({numerator}) / ({denominator}))"

        if name == "sqrt":
            token = self._peek()
            if token is not None and token.kind == "open" and token.value == "[":
                self._next()
                degree = self._expression(stop_at_close=True)
                closing = self._next()
                if closing.kind != "close":
                    raise _Refused("根指数の括弧が閉じていない")
                return f"(({self._expect_group()}) ** (1 / ({degree})))"
            return f"sqrt({self._expect_group()})"

        if name in FUNCTION_COMMANDS:
            return f"{FUNCTION_COMMANDS[name]}({self._expect_group()})"

        if name in _CONSTANT_COMMANDS:
            return _CONSTANT_COMMANDS[name]

        if name in _LETTER_COMMANDS:
            self._last_atom_was_name = True
            return self._identifier(name)

        if name == "left":
            # `\left( ... \right)` is one group. Treating `\left` as a style command and
            # its `(` as an ordinary atom left the matching `\right` for `_term`, which
            # consumed it as a juxtaposed factor — refusing every such expression.
            opening = self._next()
            if opening.kind != "open":
                raise _Refused("\\left の後に開き括弧が無い")
            inner = self._expression(stop_at_close=True)
            delimiter = self._peek()
            if delimiter is not None and delimiter.kind == "close":
                self._next()
            elif (
                delimiter is not None
                and delimiter.kind == "command"
                and delimiter.value.lstrip("\\") == "right"
            ):
                self._next()
                following = self._peek()
                if following is not None and following.kind == "close":
                    self._next()
            else:
                raise _Refused("\\left に対応する閉じ括弧が無い")
            return f"({inner})"

        if name == "right":
            raise _Refused("\\right が対応する \\left なしに現れた")

        if name in _STYLE_COMMANDS:
            return self._expect_group()

        if name in _IGNORED:
            return self._atom_from(self._next())

        raise _Refused(f"未知の命令 \\{name}")


def translate_expression(latex: str) -> tuple[str, frozenset[str]] | None:
    """One side of an equation, or ``None`` when anything was not understood."""
    try:
        parser = _Parser(_tokenise(latex.strip()))
        expression = parser._expression()
        if parser._peek() is not None:
            raise _Refused("式の末尾に余りがある")
    except _Refused:
        return None
    except RecursionError:
        return None
    return expression, frozenset(parser.variables)


def translate_equation(latex: str) -> TranslatedEquation | None:
    """Split on a single ``=`` and translate both sides.

    Refuses anything with zero or more than one ``=``: a chain like ``a = b = c`` is two
    claims, and picking one of them silently would check something the paper did not say.
    """
    # Not `str.split("=")`: `\neq` and `\leq` contain no `=` after tokenising, but a
    # relation like `\le` would slip past a naive split as a single side.
    parts = latex.split("=")
    if len(parts) != 2:
        return None

    left = translate_expression(parts[0])
    right = translate_expression(parts[1])
    if left is None or right is None:
        return None

    return TranslatedEquation(
        lhs=left[0], rhs=right[0], lhs_variables=left[1], rhs_variables=right[1]
    )
