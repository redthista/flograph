"""Table conditional formatting — the rule model and its evaluation.

Qt-free on purpose. The **Table Style** node turns its parameters (a
structured quick-rule plus a free-text rule box) into a list of :class:`Rule`
dicts and emits them on its ``style`` port; :class:`~flograph.ui.inspector.
pandas_model.PandasModel` and the cell delegate turn the evaluated
:class:`CellStyle` into ``QColor`` / ``QFont`` / a painted bar / an icon
glyph.

Nothing here imports pandas at module load — the evaluators take a Series /
DataFrame and import pandas locally, matching the node-script rule.

The text DSL, one rule per line (``#`` comments and blank lines skipped)::

    revenue              scale green                # 2- or 3-colour gradient
    margin               scale red-yellow-green
    units                bar blue                   # in-cell data bar
    score   >= 90        => bg green, bold          # highlight a cell
    status  contains fail => bg red
    status  = closed     => row grey                # highlight the whole row
    health               icons traffic              # 3-tier icon set
    amount               format $,.0f               # per-column number format

Later lines win where two rules touch the same cell; a ``row``-scope style
sits under a ``cell``-scope one.
"""
from __future__ import annotations

import dataclasses
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

# Structured-param labels → DSL preset keys.
_SCALE_LABELS = {
    "green": "green", "red to green": "red-green",
    "white to red": "white-red", "blue": "blue", "diverging": "diverging",
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

_MODES = {"color_scale", "data_bar", "highlight", "icons", "number_format"}
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


def _column_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [c.strip() for c in str(value).split(",") if c.strip()]


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


_KEYWORDS = ("scale", "bar", "icons", "icon", "format")


def _parse_token_line(lineno: int, line: str) -> Rule:
    tokens = line.split()
    kw_idx = next((i for i in range(len(tokens) - 1, -1, -1)
                   if tokens[i].lower() in _KEYWORDS), None)
    if kw_idx is None or kw_idx == 0:
        raise ValueError(
            f"line {lineno}: expected 'column scale|bar|icons|format ...' "
            f"or 'condition => style', got {line!r}")
    columns = _column_list(" ".join(tokens[:kw_idx]))
    keyword = tokens[kw_idx].lower()
    arg = " ".join(tokens[kw_idx + 1:]).strip()

    if keyword == "scale":
        preset = _SCALE_PRESETS.get(arg.lower().replace(" ", "-")
                                    or "red-yellow-green")
        if preset is None:
            raise ValueError(f"line {lineno}: unknown scale {arg!r} "
                             f"(try {', '.join(sorted(_SCALE_PRESETS))})")
        return Rule("color_scale", columns,
                    low=preset[0], mid=preset[1], high=preset[2])
    if keyword == "bar":
        return Rule("data_bar", columns,
                    color=_BAR_PRESETS.get(arg.lower(), arg or _BAR_PRESETS["blue"]),
                    negative_color=_BAR_NEGATIVE)
    if keyword in ("icons", "icon"):
        key = _ICON_LABELS.get(arg.lower(), arg.lower() or "traffic")
        if key not in _ICON_SETS:
            raise ValueError(f"line {lineno}: unknown icon set {arg!r} "
                             f"(traffic, arrows, check)")
        return Rule("icons", columns, icon_set=key)
    # format
    if not arg:
        raise ValueError(f"line {lineno}: 'format' needs a spec like ',.0f'")
    return Rule("number_format", columns, number_spec=arg)


def _resolve_color(token: str) -> str:
    token = token.strip()
    return _FILL_PRESETS.get(token.lower(), token)


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
    # split "column op value": the column is everything up to the operator
    op, value, column = _split_condition(cond)
    if not column:
        raise ValueError(f"line {lineno}: no column in condition {cond!r}")
    return Rule("highlight", _column_list(column), scope=style["scope"],
                op=op, value=value, bg=style.get("bg"), fg=style.get("fg"),
                bold=bool(style.get("bold")))


def _split_condition(cond: str) -> tuple:
    """`"score >= 90"` → (op, value, column)."""
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


def parse_rules(text: str) -> list[Rule]:
    rules: list[Rule] = []
    for lineno, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=>" in line:
            rules.append(_parse_condition_line(lineno, line))
        else:
            rules.append(_parse_token_line(lineno, line))
    return rules


def rules_from_params(params: dict) -> list[Rule]:
    """The Table Style node's structured quick-rule, then the text box."""
    rules: list[Rule] = []
    mode = str(params.get("cf_mode", "off") or "off")
    columns = _column_list(params.get("cf_columns"))
    if mode == "colour scale":
        key = _SCALE_LABELS.get(str(params.get("cf_scale", "green")), "green")
        lo, md, hi = _SCALE_PRESETS[key]
        rules.append(Rule("color_scale", columns, low=lo, mid=md, high=hi))
    elif mode == "data bars":
        rules.append(Rule(
            "data_bar", columns,
            color=_BAR_PRESETS.get(str(params.get("cf_bar_color", "blue")),
                                   _BAR_PRESETS["blue"]),
            negative_color=_BAR_NEGATIVE))
    elif mode == "highlight":
        op, value = parse_op_value(params.get("cf_test", ""))
        scope = "row" if params.get("cf_scope") == "whole row" else "cell"
        rules.append(Rule("highlight", columns, scope=scope, op=op, value=value,
                          bg=_FILL_PRESETS.get(str(params.get("cf_fill", "red")),
                                               "#5c2b2b")))
    elif mode == "icons":
        key = _ICON_LABELS.get(str(params.get("cf_icons", "traffic lights")),
                               "traffic")
        rules.append(Rule("icons", columns, icon_set=key))
    rules.extend(parse_rules(params.get("format_rules", "")))
    return rules


def rules_from_style(style_obj: Any) -> list[Rule]:
    """Rehydrate the ``style`` port payload. Tolerant of anything — a bad
    payload yields no rules rather than an exception, because this runs in
    the render path where a raise would blank the card."""
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


def evaluate_column(series, rules, stats: ColumnStats) -> list:
    """One ``CellStyle | None`` per row of `series`, in its current order."""
    import pandas as pd

    n = len(series)
    acc: list = [None] * n
    values = list(series)

    for rule in rules:
        contrib: list = [None] * n

        if rule.mode == "color_scale":
            lo = stats.min if rule.low_value is None else rule.low_value
            hi = stats.max if rule.high_value is None else rule.high_value
            if lo is None or hi is None or hi == lo:
                span = None
            else:
                span = hi - lo
            num = pd.to_numeric(series, errors="coerce")
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
            origin = 0.0 if rule.origin is None else rule.origin
            top = max(abs((stats.max or 0) - origin),
                      abs((stats.min or 0) - origin)) or 1.0
            mode = "center" if (stats.min is not None
                                and stats.min < origin) else "left"
            num = pd.to_numeric(series, errors="coerce")
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
            try:
                mask = _condition_mask(series, rule.op, rule.value)
            except Exception:
                mask = pd.Series(False, index=series.index)
            style = CellStyle(bg=rule.bg,
                              fg=rule.fg or (readable_fg(rule.bg) if rule.bg else None),
                              bold=rule.bold)
            for i, hit in enumerate(mask.tolist()):
                if hit:
                    contrib[i] = style

        elif rule.mode == "icons":
            glyphs = _ICON_SETS.get(rule.icon_set or "traffic",
                                    _ICON_SETS["traffic"])
            if rule.reverse:
                glyphs = list(reversed(glyphs))
            t1, t2 = (rule.thresholds if rule.thresholds
                      else (stats.tertiles or (None, None)))
            num = pd.to_numeric(series, errors="coerce")
            for i, v in enumerate(num):
                if _is_missing(v) or t1 is None:
                    continue
                tier = 0 if v < t1 else (1 if v < t2 else 2)
                glyph, color = glyphs[tier]
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
    for rule in row_rules:
        cols = rule.columns or list(df.columns)
        col = next((c for c in cols if c in df.columns), None)
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
    """(column rules, whole-row rules)."""
    row = [r for r in rules if r.mode == "highlight" and r.scope == "row"]
    col = [r for r in rules if not (r.mode == "highlight" and r.scope == "row")]
    return col, row
