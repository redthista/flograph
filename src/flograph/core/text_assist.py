"""What an editor needs to help with a node's text box: the words its little
language has, how a column is spelled in it, and what is wrong with it.

A multiline param often holds a language of its own — Conditional Column's
`if => then` rules, Expression's assignments, a quality gate's checks, a
table's formatting rules. The pop-out editor completes words and marks
mistakes as you type, and for that it needs, per box, a vocabulary and a
lint. The lint reads the text the way the node will: it runs the node's own
parser line by line, so the editor and the run can never disagree about
what is wrong — and when the table coming in has been run, it tries the
text against the first rows of it. Qt-free; the editor side is ui/editor.
"""
from __future__ import annotations

import ast
import keyword
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

from .column_refs import as_typed, quote_bare_columns, split_assignment, unquote


@dataclass(frozen=True)
class Diagnostic:
    line: int                  # 1-based
    message: str
    severity: str = "error"    # "error" or "warning"


Lint = Callable[[str, Any], "list[Diagnostic]"]


@dataclass(frozen=True)
class TextAssist:
    """keywords: offered by completion and highlighted. quote: how a column
    name is typed into the box. lint(text, sample): sample is the first rows
    of the table coming in, or None when nothing upstream has run."""
    keywords: tuple = ()
    quote: Callable[[str], str] = as_typed
    lint: Optional[Lint] = None


_PREFIX = re.compile(r"^(?:rule line|rule|line)\s+\d+:\s*")


def _message(exc) -> str:
    text = exc if isinstance(exc, str) else str(exc)
    return _PREFIX.sub("", text).strip() or type(exc).__name__


def _lines(text: str) -> Iterator[tuple[int, str]]:
    for lineno, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.strip()
        if line and not line.startswith("#"):
            yield lineno, line


def _columns(sample) -> Optional[list[str]]:
    return None if sample is None else [str(c) for c in sample.columns]


def _missing(column: str) -> str:
    return f"no column {column!r} in the table coming in"


# ---------------------------------------------------------- Conditional Column

CONDITIONAL_KEYWORDS = ("and", "or", "contains", "starts with", "ends with",
                        "matches", "is empty", "is not empty")


def lint_conditional_column(text: str, sample=None) -> list[Diagnostic]:
    from flograph.nodes.transform import conditional_column as node

    columns = _columns(sample)
    out: list[Diagnostic] = []
    fallback_at = None
    for lineno, line in _lines(text):
        try:
            groups, result = node._parse_rule(lineno, line, columns or ())
        except ValueError as exc:
            out.append(Diagnostic(lineno, _message(exc)))
            continue
        if groups is None:
            if fallback_at is None:
                fallback_at = lineno
            continue
        if fallback_at is not None:
            out.append(Diagnostic(
                lineno, f"comes after the '=> …' fallback on line "
                        f"{fallback_at}, so it can never match"))
            continue
        if columns is None:
            continue
        problem = None
        for group in groups:
            for column, op, value, quoted in group:
                if column not in columns:
                    problem = Diagnostic(lineno, _missing(column), "warning")
                else:
                    try:
                        node._mask(sample, column, op, value, quoted)
                    except Exception as exc:  # a bad regex, say
                        problem = Diagnostic(lineno, _message(exc))
                if problem:
                    break
            if problem:
                break
        if problem is None and result.startswith("@"):
            ref = unquote(result[1:])
            if ref not in columns:
                problem = Diagnostic(lineno, _missing(ref), "warning")
        if problem:
            out.append(problem)
    return out


# ----------------------------------------------------------------- Expression

EXPRESSION_KEYWORDS = ("and", "or", "not", "abs", "sqrt", "log", "log10",
                       "exp", "sin", "cos", "tan")

_WORD_GAP = re.compile(r"\b(\w+)\s+(?=(\w+)\b)")


def _join_spaced_names(expression: str) -> str:
    """`unit price * qty` as `unit_price * qty`, for a syntax check with no
    table to say which names are columns: two words side by side can only
    be one name, unless one of them is a keyword like `and`."""
    def join(match):
        if keyword.iskeyword(match.group(1)) or keyword.iskeyword(match.group(2)):
            return match.group(0)
        return match.group(1) + "_"
    previous = None
    while previous != expression:
        previous, expression = expression, _WORD_GAP.sub(join, expression)
    return expression


def _expression_problem(expression: str, known) -> Optional[Diagnostic]:
    """What is wrong with an expression read without any values: its syntax,
    and — when `known` holds the column names (plus the names earlier lines
    made) — a name that is none of them. `known` None: no names on record,
    so syntax only. Returns a Diagnostic with line 0 for the caller to place."""
    held: dict[str, str] = {}

    def hold(match) -> str:
        key = f"__col{len(held)}"
        held[key] = match.group(0)[1:-1]
        return key

    if known is not None:
        expression = quote_bare_columns(expression, known)
    probe = re.sub(r"`[^`]*`", hold, expression)
    if known is None:
        probe = _join_spaced_names(probe)
    try:
        tree = ast.parse(probe, mode="eval")
    except SyntaxError as exc:
        return Diagnostic(0, f"not a valid expression ({exc.msg})")
    if known is None:
        return None
    called = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and id(node) not in called:
            name = held.get(node.id, node.id)
            if name not in known:
                return Diagnostic(0, _missing(name), "warning")
    return None


def lint_expression(text: str, sample=None) -> list[Diagnostic]:
    """With rows in the sample, each line is evaluated against them, so a
    wrong type or a bad function shows too. With only the column names (an
    empty sample), names are checked rather than evaluated: an empty column
    has no type to go wrong with, and guessing one would mark good lines."""
    columns = _columns(sample)
    work = sample.copy() if sample is not None and len(sample) else None
    known = set(columns) if columns is not None else None
    out: list[Diagnostic] = []
    for lineno, line in _lines(text):
        parts = split_assignment(line)
        if parts is None or not parts[0] or not parts[1]:
            out.append(Diagnostic(lineno, "expected 'new_column = expression'"))
            continue
        target, expression = parts
        if work is not None:
            try:
                work[target] = work.eval(
                    quote_bare_columns(expression, work.columns))
            except Exception as exc:
                out.append(Diagnostic(lineno, _message(exc) or type(exc).__name__))
            continue
        problem = _expression_problem(expression, known)
        if problem is not None:
            out.append(Diagnostic(lineno, problem.message, problem.severity))
        if known is not None:
            known.add(target)
    return out


# ---------------------------------------------------------- Data Quality Gate

GATE_CHECKS = ("not_null", "unique", "in", "between", "regex", "max_null_pct")
_GATE_COMPARATORS = (">", ">=", "<", "<=", "==", "!=")


def _number_problem(args) -> Optional[str]:
    if not args:
        return None
    try:
        float(args[0])
    except ValueError:
        return f"expected a number, got {args[0]!r}"
    return None


def _gate_problem(column: str, check: str, args: list) -> Optional[str]:
    if column == "@rows":
        if check not in _GATE_COMPARATORS:
            return f"@rows needs a comparator ({' '.join(_GATE_COMPARATORS)})"
        return _number_problem(args)
    if check in ("not_null", "unique"):
        return None
    if check == "in":
        values = [a for a in " ".join(args).split("|") if a.strip()]
        return None if values else "'in' needs values, e.g. 'status in open | closed'"
    if check == "between":
        bits = " ".join(args).replace(" and ", " ").split()
        if len(bits) != 2:
            return "'between' needs two bounds, e.g. 'amount between 0 and 100'"
        return _number_problem(bits[:1]) or _number_problem(bits[1:])
    if check == "regex":
        pattern = " ".join(args)
        if not pattern:
            return "'regex' needs a pattern"
        try:
            re.compile(pattern)
        except re.error as exc:
            return f"bad pattern ({exc})"
        return None
    if check == "max_null_pct" or check in _GATE_COMPARATORS:
        return _number_problem(args)
    return (f"unknown check {check!r} — not_null, unique, in, between, regex, "
            f"max_null_pct or a comparator")


def lint_quality_gate(text: str, sample=None) -> list[Diagnostic]:
    from flograph.nodes.transform import data_quality_gate as node

    columns = _columns(sample)
    out: list[Diagnostic] = []
    for lineno, line in _lines(text):
        try:
            (_, _, column, check, args), = node._parse_rules(line, columns or ())
        except ValueError as exc:
            out.append(Diagnostic(lineno, _message(exc)))
            continue
        problem = _gate_problem(column, check, args)
        if problem:
            out.append(Diagnostic(lineno, problem))
        elif columns is not None and column != "@rows" and column not in columns:
            out.append(Diagnostic(lineno, _missing(column), "warning"))
    return out


# ------------------------------------------------ Rename Columns, Replace Values

def _unbacktick(name: str) -> str:
    name = name.strip()
    return name[1:-1] if len(name) > 1 and name[0] == name[-1] == "`" else name


def lint_rename(text: str, sample=None) -> list[Diagnostic]:
    columns = _columns(sample)
    out: list[Diagnostic] = []
    new_names: dict[str, int] = {}
    for lineno, line in _lines(text):
        old, sep, new = line.partition("=")
        old, new = _unbacktick(old), _unbacktick(new)
        if not sep or not old or not new:
            out.append(Diagnostic(lineno, "expected 'old = new'"))
            continue
        if columns is not None and old not in columns:
            out.append(Diagnostic(lineno, _missing(old), "warning"))
        elif new in new_names:
            out.append(Diagnostic(
                lineno, f"{new!r} is already the new name on line "
                        f"{new_names[new]}", "warning"))
        new_names.setdefault(new, lineno)
    return out


def lint_replace_values(text: str, sample=None) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for lineno, line in _lines(text):
        find, sep, _ = line.partition("=")
        if not sep or not find.strip():
            out.append(Diagnostic(lineno, "expected 'find = replace'"))
    return out


# --------------------------------------------------------------- table rules

def _table_rule_keywords() -> tuple:
    from . import table_format as tf
    words = (tf._KEYWORDS + tf._LEADING_KEYWORDS
             + ("between", "contains", "starts", "ends", "matches", "empty",
                "notempty", "bg", "fg", "bold", "row", "only", "pill", "wrap",
                "left", "right", "above", "below", "center")
             + tuple(tf._SCALE_PRESETS) + tuple(tf._ICON_SETS)
             + tuple(tf._FILL_PRESETS))
    return tuple(dict.fromkeys(words))


def lint_table_rules(text: str, sample=None) -> list[Diagnostic]:
    from .table_format import parse_rule_lines

    return [Diagnostic(lineno, _message(error))
            for lineno, (_raw, _rule, error)
            in enumerate(parse_rule_lines(text), 1) if error]


def _table_quote(name: str) -> str:
    from .table_format import quote_column
    return quote_column(name)


# ------------------------------------------------------------------ registry

_ASSISTS = {
    ("flograph.transform.conditional_column", "rules"):
        TextAssist(CONDITIONAL_KEYWORDS, as_typed, lint_conditional_column),
    ("flograph.transform.expression", "expressions"):
        TextAssist(EXPRESSION_KEYWORDS, as_typed, lint_expression),
    ("flograph.transform.data_quality_gate", "rules"):
        TextAssist(GATE_CHECKS + ("@rows",), as_typed, lint_quality_gate),
    ("flograph.transform.rename_columns", "mapping"):
        TextAssist((), as_typed, lint_rename),
    ("flograph.transform.replace_values", "pairs"):
        TextAssist((), as_typed, lint_replace_values),
}


def assist_for(type_id: str, param: str, rule_wizard: bool = False) -> TextAssist:
    """The help a pop-out editor can give with this node's text param. A box
    that takes table formatting rules — the ones with a Rules… manager — gets
    the rules language wherever it is; an unknown box gets none (the upstream
    columns still complete)."""
    found = _ASSISTS.get((type_id, param))
    if found is not None:
        return found
    if rule_wizard:
        return TextAssist(_table_rule_keywords(), _table_quote, lint_table_rules)
    return TextAssist()
