"""Excel-style formula language: tokenizer, parser, evaluator, and
reference utilities.

Grammar (Excel-compatible precedence, loosest binding first):

    compare := concat (("="|"<>"|"<"|"<="|">"|">=") concat)*
    concat  := addsub ("&" addsub)*
    addsub  := muldiv (("+"|"-") muldiv)*
    muldiv  := power  (("*"|"/") power)*
    power   := signed ("^" signed)*          # left-associative; -2^2 == 4
    signed  := ("+"|"-")* postfix
    postfix := primary "%"*
    primary := NUMBER | STRING | TRUE | FALSE | error literal
             | REF (":" REF)? | NAME "(" [expr ("," expr)*] ")"
             | "(" expr ")"

References are A1-style and case-insensitive, with optional "$" pins
($B$2). Row 1 is the first data row — the header row is not addressable.
Ranges (A1:B3) are only meaningful as function arguments and are clamped
to the grid, so =SUM(A1:A999) sums however much of column A exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .functions import call_function
from .values import (ERR_DIV0, ERR_NAME, ERR_NUM, ERR_VALUE, FormulaError,
                     RangeValue, as_date, date_text, to_bool, to_number,
                     to_text)


class FormulaSyntaxError(ValueError):
    pass


# ------------------------------------------------------------- references

def col_index(letters: str) -> int:
    """Column letters to 0-based index: A -> 0, Z -> 25, AA -> 26."""
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def col_letters(index: int) -> str:
    """0-based column index to letters: 0 -> A, 25 -> Z, 26 -> AA."""
    index += 1
    out = ""
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def cell_name(row: int, col: int) -> str:
    """0-based (row, col) to an A1-style name: (2, 1) -> "B3"."""
    return f"{col_letters(col)}{row + 1}"


def ref_text(row: int, col: int, row_abs: bool = False,
             col_abs: bool = False) -> str:
    return (("$" if col_abs else "") + col_letters(col)
            + ("$" if row_abs else "") + str(row + 1))


# -------------------------------------------------------------- tokenizer

@dataclass
class Token:
    kind: str   # num str ident ref colref err op lp rp comma colon
    text: str   # the raw lexeme, used verbatim when re-serializing
    value: object = None   # parsed float / unescaped string / error code / column name
    row: int = 0
    col: int = 0
    row_abs: bool = False
    col_abs: bool = False
    this_row: bool = False   # colref only: [@name] vs [name]


_TWO_CHAR_OPS = ("<=", ">=", "<>")
_ONE_CHAR_OPS = "+-*/^&=<>%"
_SIMPLE = {"(": "lp", ")": "rp", ",": "comma", ";": "comma", ":": "colon"}


def tokenize(src: str) -> list[Token]:
    """Tokenize a formula body (the part after the leading "=")."""
    tokens: list[Token] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch.isspace():
            i += 1
            continue
        if src[i:i + 2] in _TWO_CHAR_OPS:
            tokens.append(Token("op", src[i:i + 2]))
            i += 2
            continue
        if ch in _ONE_CHAR_OPS:
            tokens.append(Token("op", ch))
            i += 1
            continue
        if ch in _SIMPLE:
            tokens.append(Token(_SIMPLE[ch], ch))
            i += 1
            continue
        if ch == "[":
            j = src.find("]", i)
            if j == -1:
                raise FormulaSyntaxError("unclosed [column] reference")
            inner = src[i + 1:j].strip()
            this_row = inner.startswith("@")
            name = inner[1:].strip() if this_row else inner
            if not name:
                raise FormulaSyntaxError("empty [column] reference")
            tokens.append(Token("colref", src[i:j + 1], value=name,
                                this_row=this_row))
            i = j + 1
            continue
        if ch == '"':
            j = i + 1
            parts: list[str] = []
            while True:
                if j >= n:
                    raise FormulaSyntaxError('unclosed text — close it with "')
                if src[j] == '"':
                    if j + 1 < n and src[j + 1] == '"':  # "" escapes a quote
                        parts.append('"')
                        j += 2
                        continue
                    break
                parts.append(src[j])
                j += 1
            tokens.append(Token("str", src[i:j + 1], value="".join(parts)))
            i = j + 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i
            while j < n and (src[j].isdigit() or src[j] == "."):
                j += 1
            if j < n and src[j] in "eE":
                k = j + 1
                if k < n and src[k] in "+-":
                    k += 1
                if k < n and src[k].isdigit():
                    j = k
                    while j < n and src[j].isdigit():
                        j += 1
            text = src[i:j]
            try:
                number = float(text)
            except ValueError:
                raise FormulaSyntaxError(f"bad number {text!r}") from None
            tokens.append(Token("num", text, value=number))
            i = j
            continue
        if ch == "#":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == "/"):
                j += 1
            if j < n and src[j] in "!?":
                code = src[i:j + 1].upper()
                tokens.append(Token("err", code, value=code))
                i = j + 1
                continue
            raise FormulaSyntaxError("unexpected character '#'")
        if ch == "$" or ch.isalpha() or ch == "_":
            j = i
            col_abs = src[j] == "$"
            if col_abs:
                j += 1
            letters_start = j
            while j < n and (src[j].isalpha() or src[j] == "_"):
                j += 1
            letters = src[letters_start:j]
            row_abs = j < n and src[j] == "$"
            digits_start = j + 1 if row_abs else j
            k = digits_start
            while k < n and src[k].isdigit():
                k += 1
            digits = src[digits_start:k]
            is_ref = (digits and letters and "_" not in letters
                      and len(letters) <= 3)
            if is_ref:
                row = int(digits) - 1
                if row < 0:
                    raise FormulaSyntaxError("row numbers start at 1")
                tokens.append(Token("ref", src[i:k], row=row,
                                    col=col_index(letters),
                                    row_abs=row_abs, col_abs=col_abs))
                i = k
                continue
            if col_abs or row_abs:
                raise FormulaSyntaxError(
                    f"bad cell reference {src[i:k] or ch!r}")
            if not letters:
                raise FormulaSyntaxError(f"unexpected character {ch!r}")
            # identifier — allow trailing digits (e.g. LOG10-style names)
            while j < n and src[j].isdigit():
                j += 1
            tokens.append(Token("ident", src[i:j]))
            i = j
            continue
        raise FormulaSyntaxError(f"unexpected character {ch!r}")
    return tokens


# ------------------------------------------------------------------- AST

@dataclass
class Num:
    value: float


@dataclass
class Str:
    value: str


@dataclass
class Bool:
    value: bool


@dataclass
class ErrLit:
    code: str
    detail: str = ""


@dataclass
class Ref:
    row: int
    col: int
    row_abs: bool = False
    col_abs: bool = False


@dataclass
class ColRef:
    """A structured reference: [@name] (this row) or [name] (whole column).
    Resolved against a concrete sheet by bind_column_refs."""
    name: str
    this_row: bool = False


@dataclass
class Range:
    start: Ref
    end: Ref


@dataclass
class Call:
    name: str
    args: list = field(default_factory=list)


@dataclass
class Bin:
    op: str
    left: object
    right: object


@dataclass
class Un:
    op: str   # "-", "+", or postfix "%"
    operand: object


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Optional[Token]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> Token:
        token = self.peek()
        if token is None:
            raise FormulaSyntaxError("formula ends unexpectedly")
        self.pos += 1
        return token

    def at_op(self, *ops: str) -> bool:
        token = self.peek()
        return token is not None and token.kind == "op" and token.text in ops

    def parse(self):
        node = self.compare()
        leftover = self.peek()
        if leftover is not None:
            raise FormulaSyntaxError(f"unexpected {leftover.text!r}")
        return node

    def compare(self):
        node = self.concat()
        while self.at_op("=", "<>", "<", "<=", ">", ">="):
            op = self.take().text
            node = Bin(op, node, self.concat())
        return node

    def concat(self):
        node = self.addsub()
        while self.at_op("&"):
            self.take()
            node = Bin("&", node, self.addsub())
        return node

    def addsub(self):
        node = self.muldiv()
        while self.at_op("+", "-"):
            op = self.take().text
            node = Bin(op, node, self.muldiv())
        return node

    def muldiv(self):
        node = self.power()
        while self.at_op("*", "/"):
            op = self.take().text
            node = Bin(op, node, self.power())
        return node

    def power(self):
        node = self.signed()
        while self.at_op("^"):
            self.take()
            node = Bin("^", node, self.signed())
        return node

    def signed(self):
        if self.at_op("-", "+"):
            op = self.take().text
            return Un(op, self.signed())
        return self.postfix()

    def postfix(self):
        node = self.primary()
        while self.at_op("%"):
            self.take()
            node = Un("%", node)
        return node

    def primary(self):
        token = self.take()
        if token.kind == "num":
            return Num(token.value)
        if token.kind == "str":
            return Str(token.value)
        if token.kind == "err":
            return ErrLit(token.value)
        if token.kind == "colref":
            return ColRef(token.value, token.this_row)
        if token.kind == "ref":
            start = Ref(token.row, token.col, token.row_abs, token.col_abs)
            nxt = self.peek()
            if nxt is not None and nxt.kind == "colon":
                self.take()
                end_token = self.take()
                if end_token.kind != "ref":
                    raise FormulaSyntaxError(
                        "a range needs a cell on both sides of ':'")
                end = Ref(end_token.row, end_token.col,
                          end_token.row_abs, end_token.col_abs)
                return Range(start, end)
            return start
        if token.kind == "ident":
            name = token.text.upper()
            nxt = self.peek()
            if nxt is not None and nxt.kind == "lp":
                self.take()
                args = []
                if self.peek() is not None and self.peek().kind != "rp":
                    args.append(self.compare())
                    while self.peek() is not None and self.peek().kind == "comma":
                        self.take()
                        args.append(self.compare())
                closing = self.take()
                if closing.kind != "rp":
                    raise FormulaSyntaxError(
                        f"expected ')' after {name} arguments")
                return Call(name, args)
            if name == "TRUE":
                return Bool(True)
            if name == "FALSE":
                return Bool(False)
            raise FormulaSyntaxError(
                f"{token.text!r} isn't a defined name — a function needs "
                f"parentheses, like {token.text.upper()}( )")
        if token.kind == "lp":
            node = self.compare()
            closing = self.take()
            if closing.kind != "rp":
                raise FormulaSyntaxError("expected ')'")
            return node
        raise FormulaSyntaxError(f"unexpected {token.text!r}")


def parse_formula(src: str):
    """Parse a formula source ("=A1+1" or "A1+1") into an AST."""
    body = src[1:] if src.startswith("=") else src
    tokens = tokenize(body)
    if not tokens:
        raise FormulaSyntaxError("empty formula")
    return _Parser(tokens).parse()


# formula text -> its AST, or the syntax error's message. A table's column
# of formulas is one text repeated down every row (=[@Units]*[@Price]), so
# a recalculation parses each text once. ASTs are never changed after
# parsing — binding and evaluating build new nodes or only read — so one
# can be shared by every cell that holds the text.
_parsed: dict = {}


def parse_formula_cached(src: str):
    hit = _parsed.get(src)
    if hit is None:
        try:
            hit = parse_formula(src)
        except FormulaSyntaxError as exc:
            hit = _SyntaxProblem(str(exc))
        if len(_parsed) >= 20_000:
            _parsed.clear()
        _parsed[src] = hit
    if isinstance(hit, _SyntaxProblem):
        raise FormulaSyntaxError(hit.message)
    return hit


class _SyntaxProblem:
    __slots__ = ("message",)

    def __init__(self, message: str) -> None:
        self.message = message


# -------------------------------------------------------------- evaluator

def _range_cells(rng: Range, bounds: tuple[int, int]):
    """0-based (row, col) pairs of a range, clamped to the grid."""
    n_rows, n_cols = bounds
    r1, r2 = sorted((rng.start.row, rng.end.row))
    c1, c2 = sorted((rng.start.col, rng.end.col))
    r1, r2 = max(r1, 0), min(r2, n_rows - 1)
    c1, c2 = max(c1, 0), min(c2, n_cols - 1)
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            yield r, c


def _compare(op: str, a, b):
    if isinstance(a, FormulaError):
        return a
    if isinstance(b, FormulaError):
        return b
    if isinstance(a, bool) and isinstance(b, bool):
        x, y = a, b
    elif isinstance(a, str) and isinstance(b, str):
        da, db = as_date(a), as_date(b)
        if da is not None and db is not None:
            x, y = da, db                   # 7/10/2026 = 2026-10-07
        else:
            x, y = a.casefold(), b.casefold()   # Excel compares text case-blind
    else:
        na, nb = to_number(a), to_number(b)
        if isinstance(na, FormulaError) or isinstance(nb, FormulaError):
            if op == "=":
                return False
            if op == "<>":
                return True
            return FormulaError(
                ERR_VALUE, "cannot order values of different types")
        x, y = na, nb
    if op == "=":
        return x == y
    if op == "<>":
        return x != y
    if op == "<":
        return x < y
    if op == "<=":
        return x <= y
    if op == ">":
        return x > y
    return x >= y


def _date_arithmetic(op: str, left, right):
    """Excel's date sums, for dates kept as text: a date plus or minus a
    number of days is a date, and a date minus a date is the days between.
    None when neither side is a date (the sum is ordinary arithmetic)."""
    from datetime import timedelta
    dl, dr = as_date(left), as_date(right)
    if dl is None and dr is None:
        return None
    if dl is not None and dr is not None:
        if op == "-":
            return (dl - dr).total_seconds() / 86400.0
        return FormulaError(ERR_VALUE, "two dates cannot be added")
    if dl is not None:
        days = to_number(right)
        if isinstance(days, FormulaError):
            return days
        moment = dl + timedelta(days=days if op == "+" else -days)
        return date_text(moment, keep_time=bool(days % 1) or bool(
            dl.hour or dl.minute or dl.second))
    if op == "-":
        return FormulaError(ERR_VALUE, "a number minus a date")
    days = to_number(left)
    if isinstance(days, FormulaError):
        return days
    moment = dr + timedelta(days=days)
    return date_text(moment, keep_time=bool(days % 1))


def evaluate(node, get_cell, bounds: tuple[int, int]):
    """Evaluate an AST. ``get_cell(row, col)`` supplies referenced cell
    values (and may itself return a FormulaError, e.g. #REF! outside the
    grid); ``bounds`` is (n_rows, n_cols) used to clamp ranges."""
    if isinstance(node, Num):
        return node.value
    if isinstance(node, Str):
        return node.value
    if isinstance(node, Bool):
        return node.value
    if isinstance(node, ErrLit):
        return FormulaError(node.code, node.detail)
    if isinstance(node, ColRef):   # only reachable when not bound to a sheet
        return FormulaError(
            ERR_NAME, "[column] references need a sheet to resolve against")
    if isinstance(node, Ref):
        return get_cell(node.row, node.col)
    if isinstance(node, Range):
        return FormulaError(
            ERR_VALUE, "a range needs a function like SUM around it")
    if isinstance(node, Un):
        value = to_number(evaluate(node.operand, get_cell, bounds))
        if isinstance(value, FormulaError):
            return value
        if node.op == "-":
            return -value
        if node.op == "%":
            return value / 100.0
        return value
    if isinstance(node, Bin):
        if node.op == "&":
            left = to_text(evaluate(node.left, get_cell, bounds))
            if isinstance(left, FormulaError):
                return left
            right = to_text(evaluate(node.right, get_cell, bounds))
            if isinstance(right, FormulaError):
                return right
            return left + right
        if node.op in ("=", "<>", "<", "<=", ">", ">="):
            left = evaluate(node.left, get_cell, bounds)
            right = evaluate(node.right, get_cell, bounds)
            return _compare(node.op, left, right)
        raw_left = evaluate(node.left, get_cell, bounds)
        raw_right = evaluate(node.right, get_cell, bounds)
        if node.op in ("+", "-"):
            dated = _date_arithmetic(node.op, raw_left, raw_right)
            if dated is not None:
                return dated
        left = to_number(raw_left)
        if isinstance(left, FormulaError):
            return left
        right = to_number(raw_right)
        if isinstance(right, FormulaError):
            return right
        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        if node.op == "/":
            if right == 0:
                return FormulaError(ERR_DIV0, "division by zero")
            return left / right
        if node.op == "^":
            try:
                result = left ** right
            except ZeroDivisionError:
                return FormulaError(ERR_DIV0, "zero to a negative power")
            except (OverflowError, ValueError):
                return FormulaError(ERR_NUM)
            if isinstance(result, complex):
                return FormulaError(
                    ERR_NUM, "negative base with a fractional exponent")
            return float(result)
        return FormulaError(ERR_VALUE, f"unknown operator {node.op!r}")
    if isinstance(node, Call):
        if node.name == "IF":   # lazy: only the taken branch is evaluated
            if not 2 <= len(node.args) <= 3:
                return FormulaError(
                    ERR_VALUE, "IF expects (condition, then, [else])")
            cond = to_bool(evaluate(node.args[0], get_cell, bounds))
            if isinstance(cond, FormulaError):
                return cond
            if cond:
                return evaluate(node.args[1], get_cell, bounds)
            if len(node.args) == 3:
                return evaluate(node.args[2], get_cell, bounds)
            return False
        args = []
        for arg in node.args:
            if isinstance(arg, Range):
                # a sheet hands out one shared value per range (engine.py)
                shared = getattr(get_cell, "range_value", None)
                if shared is not None:
                    args.append(shared(arg))
                    continue
                cells = list(_range_cells(arg, bounds))
                width = len({c for _r, c in cells}) or 1
                args.append(RangeValue([get_cell(r, c) for r, c in cells],
                                       width))
            else:
                args.append(evaluate(arg, get_cell, bounds))
        try:
            return call_function(node.name, args)
        except Exception as exc:   # a function bug must not kill the app
            return FormulaError(ERR_VALUE, str(exc))
    return FormulaError(ERR_VALUE, f"cannot evaluate {type(node).__name__}")


def clamp_range(rng: "Range", bounds: tuple[int, int]):
    """A range as (r1, c1, r2, c2) inside the grid, or None if none of it
    is."""
    n_rows, n_cols = bounds
    r1, r2 = sorted((rng.start.row, rng.end.row))
    c1, c2 = sorted((rng.start.col, rng.end.col))
    r1, r2 = max(r1, 0), min(r2, n_rows - 1)
    c1, c2 = max(c1, 0), min(c2, n_cols - 1)
    if r1 > r2 or c1 > c2:
        return None
    return (r1, c1, r2, c2)


def refs_and_ranges(node, bounds: tuple[int, int]):
    """The single cells an AST reads, and its ranges (clamped, as
    :func:`clamp_range` gives them) — kept whole, so a whole-column range
    is one thing to depend on rather than a thousand cells."""
    cells: set[tuple[int, int]] = set()
    ranges: set[tuple[int, int, int, int]] = set()
    n_rows, n_cols = bounds

    def walk(item) -> None:
        if isinstance(item, Ref):
            if 0 <= item.row < n_rows and 0 <= item.col < n_cols:
                cells.add((item.row, item.col))
        elif isinstance(item, Range):
            box = clamp_range(item, bounds)
            if box is not None:
                ranges.add(box)
        elif isinstance(item, Call):
            for arg in item.args:
                walk(arg)
        elif isinstance(item, Bin):
            walk(item.left)
            walk(item.right)
        elif isinstance(item, Un):
            walk(item.operand)

    walk(node)
    return cells, ranges


def refs_of(node, bounds: tuple[int, int]) -> set[tuple[int, int]]:
    """All in-grid cells an AST reads (ranges expanded and clamped)."""
    refs: set[tuple[int, int]] = set()
    n_rows, n_cols = bounds

    def walk(item) -> None:
        if isinstance(item, Ref):
            if 0 <= item.row < n_rows and 0 <= item.col < n_cols:
                refs.add((item.row, item.col))
        elif isinstance(item, Range):
            refs.update(_range_cells(item, bounds))
        elif isinstance(item, Call):
            for arg in item.args:
                walk(arg)
        elif isinstance(item, Bin):
            walk(item.left)
            walk(item.right)
        elif isinstance(item, Un):
            walk(item.operand)

    walk(node)
    return refs


# --------------------------------------------------- column-ref binding

def bind_column_refs(node, row: int, columns: list[str], n_rows: int):
    """Resolve [@name]/[name] against a concrete sheet: [@name] becomes
    this row's cell in that column, [name] the column's whole data range.
    Matching is exact first, then case-insensitive; unknown names become
    #NAME? errors naming the column."""
    def resolve(name: str):
        for idx, col_name in enumerate(columns):
            if col_name == name:
                return idx
        lowered = name.casefold()
        for idx, col_name in enumerate(columns):
            if col_name.casefold() == lowered:
                return idx
        return None

    def rebuild(item):
        if isinstance(item, ColRef):
            idx = resolve(item.name)
            if idx is None:
                return ErrLit(ERR_NAME, f"no column named {item.name!r}")
            if item.this_row:
                return Ref(row, idx, row_abs=False, col_abs=True)
            return Range(Ref(0, idx, True, True),
                         Ref(max(n_rows - 1, 0), idx, True, True))
        if isinstance(item, Call):
            return Call(item.name, [rebuild(arg) for arg in item.args])
        if isinstance(item, Bin):
            return Bin(item.op, rebuild(item.left), rebuild(item.right))
        if isinstance(item, Un):
            return Un(item.op, rebuild(item.operand))
        return item

    return rebuild(node)


def rename_column_in_formulas(src: str, old: str, new: str) -> str:
    """Rewrite [old]/[@old] references when a column is renamed, so
    formulas follow the column. Non-formulas and unparseable formulas come
    back unchanged."""
    if not (isinstance(src, str) and src.startswith("=") and src != "="):
        return src
    try:
        tokens = tokenize(src[1:])
        _Parser(list(tokens)).parse()
    except FormulaSyntaxError:
        return src
    out, changed = [], False
    for token in tokens:
        if (token.kind == "colref"
                and token.value.casefold() == old.casefold()):
            out.append(("[@" if token.this_row else "[") + new + "]")
            changed = True
        else:
            out.append(token.text)
    return "=" + "".join(out) if changed else src


# ------------------------------------------------------------- translate

def translate(src: str, drow: int, dcol: int) -> str:
    """Shift relative references in a formula by (drow, dcol), respecting
    "$" pins — used by paste and fill-down. References pushed off the grid
    become literal #REF!. Non-formulas and unparseable formulas come back
    unchanged."""
    if not (isinstance(src, str) and src.startswith("=") and src != "="):
        return src
    if drow == 0 and dcol == 0:
        return src
    try:
        tokens = tokenize(src[1:])
        _Parser(list(tokens)).parse()   # only rewrite well-formed formulas
    except FormulaSyntaxError:
        return src
    out = []
    for token in tokens:
        if token.kind == "ref":
            row = token.row if token.row_abs else token.row + drow
            col = token.col if token.col_abs else token.col + dcol
            if row < 0 or col < 0:
                out.append("#REF!")
            else:
                out.append(ref_text(row, col, token.row_abs, token.col_abs))
        else:
            out.append(token.text)
    return "=" + "".join(out)


# ------------------------------------------------- structural ref shifting

def shift_for_structure(src: str, axis: str, at: int, count: int) -> str:
    """Rewrite A1 references after rows or columns were inserted or
    deleted, the way Excel keeps a formula pointing at the same cells.

    ``axis`` is "row" or "col". A positive ``count`` inserted that many at
    index ``at``: every reference at or past it moves along, "$" pins
    included — a pin fixes a reference against copying, not against the
    sheet changing shape under it. A negative ``count`` deleted
    ``-count`` starting at ``at``: references past the gap move back, a
    lone reference into the gap becomes #REF!, and a range loses the
    deleted part of itself (#REF! only when all of it went).

    Column-name references ([Price], [@Price]) need nothing: they name the
    column, not its position. Non-formulas and unparseable formulas come
    back unchanged."""
    if (count == 0 or not isinstance(src, str) or not src.startswith("=")
            or src == "="):
        return src
    try:
        tokens = tokenize(src[1:])
        _Parser(list(tokens)).parse()
    except FormulaSyntaxError:
        return src
    by_row = axis == "row"
    gone_end = at - count   # first index past a deletion

    def position(token: Token) -> int:
        return token.row if by_row else token.col

    def moved(token: Token, index: int) -> str:
        row, col = (index, token.col) if by_row else (token.row, index)
        return ref_text(row, col, token.row_abs, token.col_abs)

    def single(token: Token) -> Optional[int]:
        index = position(token)
        if count > 0:
            return index + count if index >= at else index
        if index < at:
            return index
        if index >= gone_end:
            return index + count
        return None   # the cell it named was deleted

    out: list[str] = []
    changed = False
    i = 0
    while i < len(tokens):
        token = tokens[i]
        is_range = (token.kind == "ref" and i + 2 < len(tokens)
                    and tokens[i + 1].kind == "colon"
                    and tokens[i + 2].kind == "ref")
        if is_range:
            first, last = token, tokens[i + 2]
            lo, hi = sorted((position(first), position(last)))
            if count > 0:
                new_lo = lo + count if lo >= at else lo
                new_hi = hi + count if hi >= at else hi
            else:
                new_lo = lo if lo < at else (
                    lo + count if lo >= gone_end else at)
                new_hi = hi if hi < at else (
                    hi + count if hi >= gone_end else at - 1)
            if new_hi < new_lo:
                out.append("#REF!")
            else:
                start_tok, end_tok = ((first, last)
                                      if position(first) <= position(last)
                                      else (last, first))
                out.append(moved(start_tok, new_lo) + ":"
                           + moved(end_tok, new_hi))
            changed = changed or (new_lo, new_hi) != (lo, hi)
            i += 3
            continue
        if token.kind == "ref":
            index = single(token)
            if index is None:
                out.append("#REF!")
                changed = True
            else:
                out.append(moved(token, index))
                changed = changed or index != position(token)
        else:
            out.append(token.text)
        i += 1
    return "=" + "".join(out) if changed else src
