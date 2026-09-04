"""Table conditional formatting — the rule model and its evaluation.

Qt-free on purpose. The **Table Style** node turns its parameters (a
structured quick-rule plus a free-text rule box) into a list of :class:`Rule`
dicts and emits them on its ``style`` port; :class:`~flograph.ui.inspector.
pandas_model.PandasModel` and the cell delegate turn the evaluated
:class:`CellStyle` into ``QColor`` / ``QFont`` / a painted bar / an icon
glyph.

Nothing here imports pandas at module load — the evaluators take a Series /
DataFrame and import pandas locally, matching the node-script rule.

The text DSL, one rule per line (blank lines skipped, ``#`` starts a
comment — a whole line, or trailing after a rule)::

    revenue              scale green                # 2- or 3-colour gradient
    margin               scale red-yellow-green
    units                bar blue                   # in-cell data bar
    score   >= 90        => bg green, bold          # highlight a cell
    status  contains fail => bg red
    status  = closed     => row grey                # highlight the whole row
    health               icons traffic              # 3-tier icon set
    amount               format $,.0f               # per-column number format

A ``scale`` / ``bar`` / ``icons`` rule can take its deciding value **from
another column** with a trailing ``by`` (or ``from``) clause, and a
highlight can **test another column** with an ``if`` (or ``when``) clause —
the style still lands in the column(s) named on the left::

    product   scale green by revenue               # shade Product by revenue
    product   bar blue    by units
    product   icons traffic by score
    product   if revenue < 0 => bg red             # flag Product when revenue < 0
    product   if status = closed => row grey        # whole row, tested on status

A column name is matched exactly, unless it contains a glob metacharacter
(``*``, ``?``, ``[``) — then it selects every matching column, so
``20* scale green`` heatmaps every year column and ``*_qty bar blue`` every
quantity column. (Case-sensitive; quote a pattern that contains a space.)

Later lines win where two rules touch the same cell; a ``row``-scope style
sits under a ``cell``-scope one.
"""
from __future__ import annotations

import dataclasses
import fnmatch
import math
from dataclasses import dataclass, field
from typing import Any, Optional

# --------------------------------------------------------------- presets

# Solid dark-theme fills — chosen to read against the grid (#2a2c33) without
# a translucent-alpha composite the delegate would have to special-case.
_FILL_PRESETS = {
    "red": "#5c2b2b", "amber": "#5c4a24", "orange": "#5c4a24",
    "green": "#2e4d33", "blue": "#26415c", "grey": "#3a3d44",
    "gray": "#3a3d44", "purple": "#3f2e57",
}

# (low, mid, high); mid None ⇒ a 2-colour gradient.
_SCALE_PRESETS = {
    "green": ("#23252b", None, "#2e7d46"),
    "blue": ("#23252b", None, "#2f6f9f"),
    "red": ("#23252b", None, "#a4373a"),
    "white-red": ("#23252b", None, "#a4373a"),
    "red-green": ("#a4373a", None, "#2e7d46"),
    "red-yellow-green": ("#a4373a", "#b0902f", "#2e7d46"),
    "green-yellow-red": ("#2e7d46", "#b0902f", "#a4373a"),
    "diverging": ("#2f6f9f", "#3a3d44", "#a4373a"),
}

_BAR_PRESETS = {
    "blue": "#3b6299", "green": "#2e7d46", "orange": "#b9722e",
    "purple": "#7d5aa8", "red": "#a4373a", "grey": "#5b5f68",
}
_BAR_NEGATIVE = "#a4373a"

# (glyph, colour) low -> high. Plain Unicode, not emoji — a colour-emoji
# font is not a given, but ● ▲ ▼ ✓ ✗ are in every default sans.
_ICON_SETS = {
    "traffic": [("●", "#d9534f"), ("●", "#e0a83d"),
                ("●", "#5cb85c")],                        # ● ● ●
    "arrows": [("▼", "#d9534f"), ("▬", "#9aa0a6"),
               ("▲", "#5cb85c")],                         # ▼ ▬ ▲
    "check": [("✗", "#d9534f"), ("–", "#9aa0a6"),
              ("✓", "#5cb85c")],                          # ✗ – ✓
}
_ICON_LABELS = {
    "traffic lights": "traffic", "traffic": "traffic", "arrows": "arrows",
    "check / cross": "check", "check": "check", "cross": "check",
}

_MODES = {"color_scale", "data_bar", "highlight", "icons", "icon_map",
          "number_format"}


def scale_token(low, mid, high) -> str:
    """The DSL name for a (low, mid, high) triple, or its raw ``low..high``
    when it matches no preset."""
    for name, triple in _SCALE_PRESETS.items():
        if triple == (low, mid, high):
            return name
    return "green"


def preset_name(colour, presets) -> str:
    for name, value in presets.items():
        if value == colour:
            return name
    return colour or ""


def bar_token(colour) -> str:
    return preset_name(colour, _BAR_PRESETS)


def fill_token(colour) -> str:
    return preset_name(colour, _FILL_PRESETS)
_OPS = {">", ">=", "<", "<=", "=", "!=", "between",
        "contains", "starts", "ends", "matches", "empty", "notempty"}


# --------------------------------------------------------------- shapes

@dataclass
class Rule:
    mode: str
    columns: list[str] = field(default_factory=list)
    scope: str = "cell"                       # cell | row
    # color_scale
    low: Optional[str] = None
    mid: Optional[str] = None
    high: Optional[str] = None
    low_value: Optional[float] = None
    high_value: Optional[float] = None
    # data_bar
    color: Optional[str] = None
    negative_color: Optional[str] = None
    origin: Optional[float] = None
    # highlight
    op: Optional[str] = None
    value: Any = None                         # scalar, or [a, b] for between
    bg: Optional[str] = None
    fg: Optional[str] = None
    bold: bool = False
    # icons
    icon_set: Optional[str] = None
    thresholds: Optional[list] = None
    reverse: bool = False
    # icon_map, and any rule that reads a different column than the one it
    # draws in: `scale`/`bar`/`icons` with a `by <col>` clause, and a
    # `highlight` with an `if <col> …` clause (the tested column).
    source: Optional[str] = None              # column whose value decides it
    mapping: Optional[dict] = None            # exact value -> [glyph, colour]
    # number_format
    number_spec: Optional[str] = None

    def to_dict(self) -> dict:
        out = {}
        for f in dataclasses.fields(self):
            v = getattr(self, f.name)
            # keep 0 / 0.0 (a real threshold or origin); drop only genuine
            # absence — None, False, an empty list
            if v is None or v is False or (isinstance(v, list) and not v):
                continue
            out[f.name] = v
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class CellStyle:
    bg: Optional[str] = None
    fg: Optional[str] = None
    bold: bool = False
    bar: Optional[float] = None               # signed, -1..1
    bar_color: Optional[str] = None
    bar_mode: str = "left"                    # left | center (column has < 0)
    icon: Optional[str] = None
    icon_color: Optional[str] = None
    text: Optional[str] = None                # DisplayRole override

    def over(self, base: Optional["CellStyle"]) -> "CellStyle":
        """`self` laid on top of `base` — self's set fields win."""
        if base is None:
            return self
        return CellStyle(
            bg=self.bg or base.bg,
            fg=self.fg or base.fg,
            bold=self.bold or base.bold,
            bar=base.bar if self.bar is None else self.bar,
            bar_color=self.bar_color or base.bar_color,
            bar_mode=self.bar_mode if self.bar is not None else base.bar_mode,
            icon=self.icon or base.icon,
            icon_color=self.icon_color or base.icon_color,
            text=self.text or base.text,
        )

    def is_empty(self) -> bool:
        return (self.bg is None and self.fg is None and not self.bold
                and self.bar is None and self.icon is None
                and self.text is None)


@dataclass
class ColumnStats:
    min: Optional[float] = None
    max: Optional[float] = None
    mean: Optional[float] = None
    tertiles: Optional[tuple] = None          # (t1, t2)


# --------------------------------------------------------------- colour maths

def _hex_rgb(value: str) -> Optional[tuple]:
    s = str(value or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def _rgb_hex(rgb: tuple) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _lerp(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def readable_fg(bg_hex: str) -> str:
    """A legible text colour for a given cell background."""
    rgb = _hex_rgb(bg_hex)
    if rgb is None:
        return "#e5e7eb"
    r, g, b = (c / 255 for c in rgb)
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#1b1c20" if luminance > 0.55 else "#e5e7eb"


def _scale_color(frac: float, low: str, mid: Optional[str], high: str) -> Optional[str]:
    lo, hi = _hex_rgb(low), _hex_rgb(high)
    if lo is None or hi is None:
        return None
    frac = 0.0 if frac < 0 else 1.0 if frac > 1 else frac
    md = _hex_rgb(mid) if mid else None
    if md is None:
        return _rgb_hex(_lerp(lo, hi, frac))
    if frac <= 0.5:
        return _rgb_hex(_lerp(lo, md, frac / 0.5))
    return _rgb_hex(_lerp(md, hi, (frac - 0.5) / 0.5))


# --------------------------------------------------------------- parsing

def _coerce(text: str) -> Any:
    t = str(text).strip()
    low = t.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        return t


def _unquote(name: str) -> str:
    name = str(name).strip()
    if len(name) >= 2 and name[0] == name[-1] and name[0] in "\"'":
        return name[1:-1]
    return name


def _split_top_commas(text: str) -> list[str]:
    """Split on commas that are not inside "quotes"; the quote chars are
    dropped."""
    parts: list[str] = []
    buf: list[str] = []
    quote = None
    for ch in str(text):
        if quote:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
        elif ch in "\"'":
            quote = ch
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _column_list(value: Any) -> list[str]:
    """A comma-separated column list, honouring "quotes" so a name may
    itself contain a comma or read like a keyword."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [_unquote(v) for v in value if str(v).strip()]
    return _split_top_commas(str(value))


def _is_glob(pattern: str) -> bool:
    return any(ch in str(pattern) for ch in "*?[")


def column_matches(patterns, name) -> bool:
    """True if `name` is selected by `patterns` — a plain entry matches by
    exact name, an entry with ``*`` / ``?`` / ``[`` is a case-sensitive
    glob. An empty `patterns` matches nothing (callers treat that as
    "every column" themselves)."""
    name = str(name)
    for p in patterns or ():
        p = str(p)
        if p == name or (_is_glob(p) and fnmatch.fnmatchcase(name, p)):
            return True
    return False


def expand_columns(patterns, columns) -> list[str]:
    """The concrete column names `patterns` selects, in `columns` order and
    de-duplicated. A plain name is kept even when absent (so a caller can
    still flag it missing); a glob contributes only the names it matches."""
    cols = [str(c) for c in columns]
    out: list[str] = []
    for p in patterns or ():
        p = str(p)
        if _is_glob(p):
            out.extend(c for c in cols if fnmatch.fnmatchcase(c, p))
        else:
            out.append(p)
    return _dedup(out)


def quote_column(name: str) -> str:
    """Wrap a column name in quotes for the DSL when it would otherwise be
    ambiguous — a space, a comma, or a bare keyword."""
    name = str(name)
    if (any(ch in name for ch in ', "\'')
            or name.lower() in _KEYWORDS or name.lower() == "hide"):
        return '"' + name.replace('"', "") + '"'
    return name


def parse_op_value(text: str) -> tuple:
    """`"> 90"` / `"contains fail"` / `"between 10 20"` → (op, value).

    Value is ``None`` for empty/notempty, a 2-list for between, else a
    coerced scalar. Raises ``ValueError`` on an unrecognised expression.
    """
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty condition")
    low = raw.lower()
    if low in ("is empty", "empty"):
        return ("empty", None)
    if low in ("is not empty", "not empty", "notempty"):
        return ("notempty", None)
    for token, canon in (("contains", "contains"), ("starts with", "starts"),
                         ("ends with", "ends"), ("starts", "starts"),
                         ("ends", "ends"), ("matches", "matches"),
                         ("between", "between")):
        if low.startswith(token + " "):
            rest = raw[len(token):].strip()
            if canon == "between":
                parts = rest.replace("..", " ").split()
                if len(parts) != 2:
                    raise ValueError(f"'between' needs two values, got {rest!r}")
                return ("between", [_coerce(parts[0]), _coerce(parts[1])])
            return (canon, rest)
    for op in ("!=", ">=", "<=", "=", ">", "<"):
        if raw.startswith(op):
            return (op, _coerce(raw[len(op):]))
    # a bare value means equals
    return ("=", _coerce(raw))


_KEYWORDS = ("scale", "bar", "icons", "icon", "iconmap", "format")


def _split_by_clause(arg: str) -> tuple:
    """Pull a trailing ``by <column>`` / ``from <column>`` off a keyword
    argument. Returns ``(remaining arg, source column | None)``.

    ``x scale green by revenue`` → ``("green", "revenue")``;
    ``x icons by score`` (no preset) → ``("", "score")``.
    """
    low = arg.lower()
    for sep in (" by ", " from "):
        idx = low.rfind(sep)
        if idx != -1:
            return arg[:idx].strip(), (_unquote(arg[idx + len(sep):].strip())
                                       or None)
    for sep in ("by ", "from "):
        if low.startswith(sep):
            return "", (_unquote(arg[len(sep):].strip()) or None)
    return arg, None


def _parse_icon_map(lineno: int, arg: str) -> tuple:
    """`"severity: high=▲ #d9534f, med=■ amber, low=▼ green"`
    → (source column, {value: [glyph, colour]})."""
    arg = arg.strip()
    if arg[:1] in "\"'":
        end = arg.find(arg[0], 1)
        after = arg[end + 1:].lstrip() if end != -1 else ""
        source = arg[1:end] if end != -1 else ""
        body = after[1:] if after.startswith(":") else ""
        sep = ":" if after.startswith(":") else ""
    else:
        source, sep, body = arg.partition(":")
        source = source.strip()
    if not sep or not source:
        raise ValueError(
            f"line {lineno}: 'iconmap' needs 'source-column: value=icon, …'")
    mapping: dict = {}
    for chunk in body.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, eq, spec = chunk.partition("=")
        if not eq or not key.strip() or not spec.strip():
            raise ValueError(
                f"line {lineno}: don't understand icon mapping {chunk!r} "
                f"(use 'value=icon colour')")
        parts = spec.split()
        glyph = parts[0]
        color = _resolve_glyph_color(parts[1]) if len(parts) > 1 else None
        mapping[key.strip()] = [glyph, color]
    if not mapping:
        raise ValueError(f"line {lineno}: 'iconmap' has no value=icon pairs")
    return source, mapping


def _parse_token_line(lineno: int, line: str) -> Rule:
    tokens = line.split()

    if tokens and tokens[0].lower() == "hide":
        cols = _column_list(" ".join(tokens[1:]))
        if not cols:
            raise ValueError(f"line {lineno}: 'hide' needs a column name")
        return Rule("hide", cols)

    kw_idx = next((i for i in range(len(tokens) - 1, -1, -1)
                   if tokens[i].lower() in _KEYWORDS), None)
    if kw_idx is None or kw_idx == 0:
        raise ValueError(
            f"line {lineno}: expected 'column scale|bar|icons|iconmap|format "
            f"…', 'hide column', or 'condition => style', got {line!r}")
    columns = _column_list(" ".join(tokens[:kw_idx]))
    keyword = tokens[kw_idx].lower()
    arg = " ".join(tokens[kw_idx + 1:]).strip()

    if keyword == "iconmap":
        source, mapping = _parse_icon_map(lineno, arg)
        return Rule("icon_map", columns, source=source, mapping=mapping)
    if keyword == "scale":
        arg, source = _split_by_clause(arg)
        preset = _SCALE_PRESETS.get(arg.lower().replace(" ", "-")
                                    or "red-yellow-green")
        if preset is None:
            raise ValueError(f"line {lineno}: unknown scale {arg!r} "
                             f"(try {', '.join(sorted(_SCALE_PRESETS))})")
        return Rule("color_scale", columns,
                    low=preset[0], mid=preset[1], high=preset[2], source=source)
    if keyword == "bar":
        arg, source = _split_by_clause(arg)
        return Rule("data_bar", columns,
                    color=_BAR_PRESETS.get(arg.lower(), arg or _BAR_PRESETS["blue"]),
                    negative_color=_BAR_NEGATIVE, source=source)
    if keyword in ("icons", "icon"):
        arg, source = _split_by_clause(arg)
        reverse = False
        low = arg.lower()
        if low.endswith(" reverse") or low == "reverse":
            reverse = True
            arg = arg[:len(arg) - len("reverse")].strip()
        key = _ICON_LABELS.get(arg.lower(), arg.lower() or "traffic")
        if key not in _ICON_SETS:
            raise ValueError(f"line {lineno}: unknown icon set {arg!r} "
                             f"(traffic, arrows, check)")
        return Rule("icons", columns, icon_set=key, reverse=reverse, source=source)
    # format
    if not arg:
        raise ValueError(f"line {lineno}: 'format' needs a spec like ',.0f'")
    return Rule("number_format", columns, number_spec=arg)


def _resolve_color(token: str) -> str:
    token = token.strip()
    return _FILL_PRESETS.get(token.lower(), token)


# vivid foreground colours for an icon glyph — the fill presets are dark
# backgrounds and would be invisible drawn as a glyph on the grid
_GLYPH_COLOURS = {
    "green": "#5cb85c", "amber": "#e0a83d", "orange": "#e0a83d",
    "red": "#d9534f", "blue": "#4a90d9", "grey": "#9aa0a6", "gray": "#9aa0a6",
}


def _resolve_glyph_color(token: str) -> str:
    token = token.strip()
    return _GLYPH_COLOURS.get(token.lower(), token)


def _parse_style_tokens(lineno: int, rhs: str) -> dict:
    out: dict = {"scope": "cell"}
    for chunk in rhs.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(None, 1)
        head = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""
        if head == "bold":
            out["bold"] = True
        elif head == "bg" and rest:
            out["bg"] = _resolve_color(rest)
        elif head == "fg" and rest:
            out["fg"] = _resolve_color(rest)
        elif head == "row":
            out["scope"] = "row"
            if rest:
                out["bg"] = _resolve_color(rest)
        else:
            raise ValueError(
                f"line {lineno}: don't understand style {chunk!r} "
                f"(use 'bg <colour>', 'fg <colour>', 'bold', 'row <colour>')")
    if "bg" not in out and "fg" not in out and not out.get("bold"):
        raise ValueError(f"line {lineno}: no style after '=>'")
    return out


def _parse_condition_line(lineno: int, line: str) -> Rule:
    cond, _, rhs = line.partition("=>")
    cond, rhs = cond.strip(), rhs.strip()
    style = _parse_style_tokens(lineno, rhs)
    # `paint-columns if <other column> op value` — style the columns on the
    # left, but test the column named after `if` / `when`.
    low = cond.lower()
    for sep in (" if ", " when "):
        idx = low.find(sep)
        if idx > 0:
            left, right = cond[:idx].strip(), cond[idx + len(sep):].strip()
            try:
                op, value, tested = _split_condition(right)
            except ValueError:
                continue
            if not left or not tested:
                break
            return Rule("highlight", _column_list(left), scope=style["scope"],
                        op=op, value=value, source=tested, bg=style.get("bg"),
                        fg=style.get("fg"), bold=bool(style.get("bold")))
    # split "column op value": the column is everything up to the operator
    op, value, column = _split_condition(cond)
    if not column:
        raise ValueError(f"line {lineno}: no column in condition {cond!r}")
    return Rule("highlight", _column_list(column), scope=style["scope"],
                op=op, value=value, bg=style.get("bg"), fg=style.get("fg"),
                bold=bool(style.get("bold")))


def _split_condition(cond: str) -> tuple:
    """`"score >= 90"` → (op, value, column)."""
    cond = cond.strip()
    # a "quoted column" takes everything up to its closing quote, then the
    # rest is a bare condition parse_op_value already understands
    if cond[:1] in "\"'":
        end = cond.find(cond[0], 1)
        if end != -1:
            op, value = parse_op_value(cond[end + 1:])
            return (op, value, cond[1:end])
    low = cond.lower()
    for token, canon in (("is not empty", "notempty"), ("is empty", "empty")):
        if low.endswith(" " + token) or low == token:
            return (canon, None, cond[:len(cond) - len(token)].strip())
    for token, canon in ((" contains ", "contains"), (" starts with ", "starts"),
                         (" ends with ", "ends"), (" matches ", "matches"),
                         (" between ", "between")):
        idx = low.find(token)
        if idx != -1:
            column = cond[:idx].strip()
            rest = cond[idx + len(token):].strip()
            if canon == "between":
                parts = rest.replace("..", " ").split()
                return ("between", [_coerce(parts[0]), _coerce(parts[1])]
                        if len(parts) == 2 else rest, column)
            return (canon, rest, column)
    for op in ("!=", ">=", "<=", "=", ">", "<"):
        idx = cond.find(op)
        if idx > 0:
            return (op, _coerce(cond[idx + len(op):]), cond[:idx].strip())
    raise ValueError(f"no operator in condition {cond!r}")


def _strip_inline_comment(line: str) -> str:
    """Drop a trailing ``# comment`` from a rule line. A ``#`` only starts a
    comment when it is outside "quotes" and followed by whitespace or the end
    of the line — so ``=> bg #2e7d46`` and ``ok=✓ #d9534f`` keep their hex."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i + 1 == len(line) or line[i + 1].isspace()):
            return line[:i].rstrip()
    return line


def _parse_one_line(lineno: int, line: str) -> Rule:
    line = _strip_inline_comment(line)
    if not line:
        raise ValueError(f"line {lineno}: nothing but a comment")
    return (_parse_condition_line(lineno, line) if "=>" in line
            else _parse_token_line(lineno, line))


def parse_rules(text: str) -> list[Rule]:
    """Parse the rule text, raising ``ValueError`` on the first bad line."""
    rules: list[Rule] = []
    for lineno, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.strip()
        if line and not line.startswith("#"):
            rules.append(_parse_one_line(lineno, line))
    return rules


def parse_rule_lines(text: str) -> list[tuple]:
    """Every line of the rules box as ``(raw line, Rule | None, error | None)``
    — comments and blanks come back as ``(raw, None, None)``. For the rule
    manager, which edits the box one line at a time and must not disturb the
    others."""
    out: list[tuple] = []
    for lineno, raw in enumerate(str(text or "").splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            out.append((raw, None, None))
            continue
        try:
            out.append((raw, _parse_one_line(lineno, stripped), None))
        except ValueError as exc:
            out.append((raw, None, str(exc)))
    return out


def _op_phrase(op: str, value: Any) -> str:
    words = {">": "> ", ">=": "≥ ", "<": "< ", "<=": "≤ ", "=": "= ",
             "!=": "≠ ", "contains": "contains ", "starts": "starts with ",
             "ends": "ends with ", "matches": "matches "}
    if op == "empty":
        return "is empty"
    if op == "notempty":
        return "is not empty"
    if op == "between" and isinstance(value, (list, tuple)):
        return f"between {value[0]}–{value[1]}"
    return words.get(op, f"{op} ") + str(value)


def rule_summary(rule: Rule) -> str:
    """A one-line human description of a rule, for the manager's list."""
    cols = ", ".join(rule.columns) or "every column"
    by = f" (by {rule.source})" if rule.source else ""
    if rule.mode == "color_scale":
        return f"{cols}  ·  colour scale{by}"
    if rule.mode == "data_bar":
        return f"{cols}  ·  data bar{by}"
    if rule.mode == "highlight":
        where = "row" if rule.scope == "row" else "cell"
        test = f"{rule.source} " if rule.source else ""
        return (f"{cols}  ·  highlight the {where} when {test}"
                f"{_op_phrase(rule.op, rule.value)}" if rule.source else
                f"{cols} {_op_phrase(rule.op, rule.value)}  ·  "
                f"highlight the {where}")
    if rule.mode == "icons":
        rev = ", reversed" if rule.reverse else ""
        return f"{cols}  ·  icons ({rule.icon_set or 'traffic'}{rev}){by}"
    if rule.mode == "icon_map":
        return f"{cols}  ·  icon from “{rule.source}”"
    if rule.mode == "number_format":
        return f"{cols}  ·  number format “{rule.number_spec}”"
    if rule.mode == "hide":
        return f"hide  {cols}"
    return rule.mode


def parse_rules_lenient(text: str) -> tuple[list[Rule], list[str]]:
    """Parse the rule text, skipping bad lines and collecting their
    messages — for the node paths where one typo must not lose the rest."""
    rules: list[Rule] = []
    errors: list[str] = []
    for lineno, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rules.append(_parse_one_line(lineno, line))
        except ValueError as exc:
            errors.append(str(exc))
    return rules, errors


def _dedup(seq) -> list:
    seen, out = set(), []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def style_payload(params: dict) -> dict:
    """Turn a node's params — a ``format_rules`` text box and an optional
    ``hide`` column list — into the payload carried on a ``style`` port.

    Never raises: a bad rule line is dropped and its message collected, to
    be reported wherever the style is *applied* (Show Table), not typed.
    """
    rules, errors = parse_rules_lenient(params.get("format_rules", ""))
    hide = [c for r in rules if r.mode == "hide" for c in r.columns]
    hide += _column_list(params.get("hide"))
    keep = [r for r in rules if r.mode != "hide"]
    return {"rules": [r.to_dict() for r in keep], "hide": _dedup(hide),
            "errors": errors}


def _style_parts(style_obj: Any) -> tuple:
    if isinstance(style_obj, dict):
        return (list(style_obj.get("rules") or []),
                list(style_obj.get("hide") or []),
                list(style_obj.get("errors") or []))
    if isinstance(style_obj, (list, tuple)):
        return (list(style_obj), [], [])
    return ([], [], [])


def merge_styles(base: Any, extra: Any) -> dict:
    """`extra` laid on top of `base`: rules concatenated (so a later rule
    wins), hide lists unioned, errors kept from both. Either side may be a
    payload dict, a bare rule list, or ``None``."""
    b_rules, b_hide, b_err = _style_parts(base)
    e_rules, e_hide, e_err = _style_parts(extra)
    return {"rules": b_rules + e_rules, "hide": _dedup(b_hide + e_hide),
            "errors": b_err + e_err}


def hidden_columns(style_obj: Any) -> list[str]:
    """Columns the style asks Show Table to keep out of view — helper
    columns a rule reads but the reader shouldn't see."""
    if isinstance(style_obj, dict):
        return [str(c) for c in (style_obj.get("hide") or [])]
    return []


def rules_from_style(style_obj: Any) -> list[Rule]:
    """Rehydrate the ``style`` port payload — a ``{"rules": [...]}`` dict or
    a bare list. Tolerant of anything: a bad payload yields no rules rather
    than an exception, because this runs in the render path where a raise
    would blank the card."""
    if isinstance(style_obj, dict):
        style_obj = style_obj.get("rules")
    if not isinstance(style_obj, (list, tuple)):
        return []
    out: list[Rule] = []
    for item in style_obj:
        try:
            if isinstance(item, Rule):
                out.append(item)
            elif isinstance(item, dict) and item.get("mode") in _MODES:
                out.append(Rule.from_dict(item))
        except (TypeError, ValueError):
            continue
    return out


def style_report(style_obj: Any, df=None) -> list[str]:
    """Everything wrong with a style, for Show Table to log: the parse
    errors the Table Style node carried, plus any column its rules name that
    this table does not have."""
    messages: list[str] = []
    if isinstance(style_obj, dict):
        messages.extend(str(m) for m in (style_obj.get("errors") or []))
    columns = getattr(df, "columns", None)
    if columns is not None:
        known = {str(c) for c in columns}
        named: set = set()
        patterns: set = set()
        entries = [c for rule in rules_from_style(style_obj) for c in rule.columns]
        entries += [r.source for r in rules_from_style(style_obj) if r.source]
        entries += hidden_columns(style_obj)
        for c in entries:
            (patterns if _is_glob(c) else named).add(str(c))
        missing = sorted(c for c in named if c not in known)
        if missing:
            messages.append("column(s) not in the table: " + ", ".join(missing))
        empty = sorted(p for p in patterns
                       if not any(fnmatch.fnmatchcase(k, p) for k in known))
        if empty:
            messages.append("pattern(s) matched no column: " + ", ".join(empty))
    return messages


# --------------------------------------------------------------- evaluation

def column_stats(series) -> ColumnStats:
    import pandas as pd

    num = pd.to_numeric(series, errors="coerce")
    num = num[num.notna()]
    if num.empty:
        return ColumnStats()
    lo, hi = float(num.min()), float(num.max())
    try:
        tertiles = (float(num.quantile(1 / 3)), float(num.quantile(2 / 3)))
    except Exception:
        tertiles = None
    return ColumnStats(lo, hi, float(num.mean()), tertiles)


def _is_missing(value: Any) -> bool:
    try:
        return value is None or (isinstance(value, float) and math.isnan(value))
    except Exception:
        return False


def _condition_mask(series, op: str, value: Any):
    import pandas as pd

    if op == "empty":
        return series.isna() | (series.astype("string").str.strip() == "")
    if op == "notempty":
        return ~(series.isna() | (series.astype("string").str.strip() == ""))
    if op in ("contains", "starts", "ends", "matches"):
        text = series.astype("string")
        if op == "contains":
            return text.str.contains(str(value), regex=False, na=False)
        if op == "starts":
            return text.str.startswith(str(value), na=False)
        if op == "ends":
            return text.str.endswith(str(value), na=False)
        return text.str.match(str(value), na=False)

    if op == "between" and isinstance(value, (list, tuple)) and len(value) == 2:
        num = pd.to_numeric(series, errors="coerce")
        lo, hi = sorted(float(v) for v in value)
        return num.between(lo, hi)

    target = value
    if isinstance(target, (int, float)) and not isinstance(target, bool):
        s = pd.to_numeric(series, errors="coerce")
    else:
        s = series.astype("string")
        target = str(value)
    return {
        "=": s == target, "!=": s != target,
        "<": s < target, "<=": s <= target,
        ">": s > target, ">=": s >= target,
    }.get(op, pd.Series(False, index=series.index))


def _format_value(value: Any, spec: str) -> Optional[str]:
    """Apply a Python format spec, with a leading currency symbol (`$`, `€`,
    `£`, `¥`) pulled off as a prefix so a d3-style `$,.0f` also works."""
    if _is_missing(value):
        return None
    spec = str(spec or "").strip()
    prefix = ""
    if spec[:1] in "$€£¥":
        prefix, spec = spec[0], spec[1:]
    number = value if not isinstance(value, str) else _coerce(value)
    try:
        return prefix + format(float(number), spec)
    except (ValueError, TypeError):
        return None


def evaluate_column(series, rules, stats: ColumnStats, frame=None) -> list:
    """One ``CellStyle | None`` per row of `series`, in its current order.

    `frame` is the whole (current-order) DataFrame — needed only by a rule
    that reads a *different* column than the one it draws in: ``iconmap``,
    and any ``scale`` / ``bar`` / ``icons`` / ``highlight`` rule carrying a
    ``by`` / ``if`` clause (its deciding column is ``rule.source``).
    """
    import pandas as pd

    n = len(series)
    acc: list = [None] * n
    values = list(series)

    def _decide(rule) -> tuple:
        """The series whose values drive `rule`, and stats for it — the
        drawn column, unless a ``by`` / ``if`` clause named another one."""
        if (rule.source and frame is not None
                and rule.source in getattr(frame, "columns", [])):
            other = frame[rule.source]
            return other, column_stats(other)
        return series, stats

    for rule in rules:
        contrib: list = [None] * n

        if rule.mode == "color_scale":
            decide, dstats = _decide(rule)
            lo = dstats.min if rule.low_value is None else rule.low_value
            hi = dstats.max if rule.high_value is None else rule.high_value
            if lo is None or hi is None or hi == lo:
                span = None
            else:
                span = hi - lo
            num = pd.to_numeric(decide, errors="coerce")
            for i, v in enumerate(num):
                if span is None or _is_missing(v):
                    continue
                color = _scale_color((float(v) - lo) / span,
                                     rule.low or "#23252b", rule.mid,
                                     rule.high or "#2e7d46")
                if color:
                    contrib[i] = CellStyle(bg=color, fg=readable_fg(color))

        elif rule.mode == "data_bar":
            # Excel-style: the axis sits at zero (or an explicit origin). A
            # column with negatives splits from the centre; an all-positive
            # column fills from the left.
            decide, dstats = _decide(rule)
            origin = 0.0 if rule.origin is None else rule.origin
            top = max(abs((dstats.max or 0) - origin),
                      abs((dstats.min or 0) - origin)) or 1.0
            mode = "center" if (dstats.min is not None
                                and dstats.min < origin) else "left"
            num = pd.to_numeric(decide, errors="coerce")
            for i, v in enumerate(num):
                if _is_missing(v):
                    continue
                frac = (float(v) - origin) / top
                negative = frac < 0
                contrib[i] = CellStyle(
                    bar=max(-1.0, min(1.0, frac)), bar_mode=mode,
                    bar_color=(rule.negative_color or _BAR_NEGATIVE) if negative
                    else (rule.color or _BAR_PRESETS["blue"]))

        elif rule.mode == "highlight" and rule.scope == "cell":
            decide, _ = _decide(rule)
            try:
                mask = _condition_mask(decide, rule.op, rule.value)
            except Exception:
                mask = pd.Series(False, index=decide.index)
            style = CellStyle(bg=rule.bg,
                              fg=rule.fg or (readable_fg(rule.bg) if rule.bg else None),
                              bold=rule.bold)
            for i, hit in enumerate(mask.tolist()):
                if hit:
                    contrib[i] = style

        elif rule.mode == "icons":
            decide, dstats = _decide(rule)
            glyphs = _ICON_SETS.get(rule.icon_set or "traffic",
                                    _ICON_SETS["traffic"])
            if rule.reverse:
                glyphs = list(reversed(glyphs))
            t1, t2 = (rule.thresholds if rule.thresholds
                      else (dstats.tertiles or (None, None)))
            num = pd.to_numeric(decide, errors="coerce")
            for i, v in enumerate(num):
                if _is_missing(v) or t1 is None:
                    continue
                tier = 0 if v < t1 else (1 if v < t2 else 2)
                glyph, color = glyphs[tier]
                contrib[i] = CellStyle(icon=glyph, icon_color=color)

        elif rule.mode == "icon_map":
            src = None
            if frame is not None and rule.source in getattr(frame, "columns", []):
                src = list(frame[rule.source])
            mapping = rule.mapping or {}
            if src is not None:
                for i, v in enumerate(src):
                    if _is_missing(v):
                        continue
                    pair = mapping.get(str(v).strip())
                    if pair:
                        glyph = pair[0] if len(pair) else None
                        color = pair[1] if len(pair) > 1 else None
                        if glyph:
                            contrib[i] = CellStyle(icon=glyph, icon_color=color)

        elif rule.mode == "number_format":
            for i, v in enumerate(values):
                text = _format_value(v, rule.number_spec or "")
                if text is not None:
                    contrib[i] = CellStyle(text=text)

        for i in range(n):
            if contrib[i] is not None:
                acc[i] = contrib[i].over(acc[i])

    return acc


def evaluate_rows(df, row_rules) -> list:
    """One ``CellStyle | None`` per row position of `df`."""
    import pandas as pd

    n = len(df)
    acc: list = [None] * n
    names = list(df.columns)
    for rule in row_rules:
        # an `if <column>` clause names the tested column in `source`;
        # otherwise the condition is tested on the rule's own column(s),
        # which may be a glob.
        if rule.source:
            col = rule.source if rule.source in df.columns else None
        else:
            patterns = rule.columns or names
            col = next((c for c in names if column_matches(patterns, c)), None)
        if col is None:
            continue
        try:
            mask = _condition_mask(df[col], rule.op, rule.value)
        except Exception:
            continue
        style = CellStyle(bg=rule.bg,
                          fg=rule.fg or (readable_fg(rule.bg) if rule.bg else None),
                          bold=rule.bold)
        for i, hit in enumerate(mask.tolist()):
            if hit:
                acc[i] = style.over(acc[i])
    return acc


def split_rules(rules) -> tuple:
    """(column rules, whole-row rules) — ``hide`` directives are neither."""
    row, col = [], []
    for r in rules:
        if r.mode == "hide":
            continue
        (row if r.mode == "highlight" and r.scope == "row" else col).append(r)
    return col, row
