"""Chart rules — a text language for styling a Plotly chart, and for the
extra series drawn over it.

Qt-free on purpose, and shared by Show Plotly, Chart per Value (Plotly) and
Plotly Style, so one line means the same thing on all three and a style
travels down a Plotly Style chain as text.

One rule per line; blank lines are skipped and ``#`` starts a comment (a
whole line, or trailing after a rule). A line that cannot be read is
reported and **skipped** — the chart still draws, the way a table's
conditional formatting does::

    title "Revenue by region" center
    axis y title "Units" format ,.0f grid off
    axis x hide title
    legend bottom horizontal
    series total line thick blue as "Total"
    series total from compare dashed grey as "Last year"
    line at 100 dashed red label "Target"
    note "Draft" top right

The verbs, each with its own line:

``series``
    An extra trace over the chart, with its own legend entry. What to plot
    comes first: a **column** of the table, or ``total`` / ``average`` /
    ``min`` / ``max`` / ``count``, worked out across the columns the chart
    already plots (``total of units, revenue`` to choose them). ``from
    compare`` reads the node's second table instead, matched on the chart's
    X column. Then how to draw it: ``line`` (the default), ``dashed``,
    ``dotted``, ``step``, ``area``, ``bars``, ``markers``, ``points``, with
    ``thick``, a colour, ``right`` to put it on a second Y axis, and ``as
    "Label"`` for the legend.

``axis``
    ``axis x|y|y2 …``: ``title "…"``, ``hide title``, ``hide``, ``show``,
    ``hide ticks``, ``format ,.0f``, ``range 0 100``, ``log``, ``grid
    on|off``, ``angle -45``, ``order category ascending``, ``slider``. Any
    number of them on the one line.

``legend``
    ``hide``/``show``, a position (``top``, ``bottom``, ``left``,
    ``right``, ``inside top left`` …), ``horizontal``/``vertical``,
    ``title "…"``, ``hide title``, ``size 12``, ``background #fff``,
    ``border #ccc 1``, ``order reversed``, ``clicks off|isolate``.

``title`` / ``subtitle``
    ``title "Sales" center``.

``line``
    A reference line: ``line at 100 on y dashed red label "Target"``.

``note``
    ``note "Draft" top right``.

``font`` / ``background`` / ``margin`` / ``hover`` / ``bars`` / ``colorbar``
    ``font Georgia 12 #333``, ``background plot #fff``, ``background paper
    transparent``, ``margin 40 20 30 50``, ``hover unified``, ``bars stack
    gap 0.2``, ``colorbar hide``.

``layout`` / ``traces`` / ``config``
    The escape hatches, a JSON object each, handed straight to
    ``update_layout``, ``update_traces`` and the render config — so
    anything plotly can do is reachable from this box, even where there is
    no word for it yet.

Rules run top to bottom, after the node's own settings, so a rule wins over
a setting and a later rule wins over an earlier one.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

#: Traffic-light and everyday colour names, matching the chart nodes' own
#: `Color from column`. Anything else (a CSS name, #hex, rgb()) is passed to
#: plotly as written.
BASIC_COLORS = {
    "red": "#ef4444", "amber": "#f59e0b", "orange": "#f97316",
    "yellow": "#eab308", "green": "#22c55e", "blue": "#3b82f6",
    "purple": "#a855f7", "pink": "#ec4899", "brown": "#92400e",
    "black": "#000000", "white": "#ffffff", "gray": "#6b7280",
    "grey": "#6b7280",
}

#: What `series total` can work out across the chart's own Y columns.
AGGREGATES = ("total", "sum", "average", "mean", "min", "max", "count",
              "median")

#: How a series is drawn -> (plotly mode, dash, fill).
SERIES_STYLES = {
    "line": ("lines", None, None),
    "dashed": ("lines", "dash", None),
    "dotted": ("lines", "dot", None),
    "step": ("lines", None, None),
    "area": ("lines", None, "tozeroy"),
    "markers": ("markers", None, None),
    "points": ("markers", None, None),
    "both": ("lines+markers", None, None),
    "bars": ("bars", None, None),
}

LEGEND_POSITIONS = {
    "right": {"x": 1.02, "y": 1.0, "xanchor": "left", "yanchor": "top"},
    "left": {"x": -0.15, "y": 1.0, "xanchor": "right", "yanchor": "top"},
    "top": {"x": 0.5, "y": 1.1, "xanchor": "center", "yanchor": "bottom",
            "orientation": "h"},
    "bottom": {"x": 0.5, "y": -0.2, "xanchor": "center", "yanchor": "top",
               "orientation": "h"},
    "inside top left": {"x": 0.02, "y": 0.98, "xanchor": "left",
                        "yanchor": "top"},
    "inside top right": {"x": 0.98, "y": 0.98, "xanchor": "right",
                         "yanchor": "top"},
    "inside bottom left": {"x": 0.02, "y": 0.02, "xanchor": "left",
                           "yanchor": "bottom"},
    "inside bottom right": {"x": 0.98, "y": 0.02, "xanchor": "right",
                            "yanchor": "bottom"},
}

_CORNERS = ("top left", "top right", "bottom left", "bottom right")

_CATEGORY_ORDERS = (
    "as plotted", "category ascending", "category descending",
    "total ascending", "total descending", "min ascending", "min descending",
    "max ascending", "max descending", "sum ascending", "sum descending",
)


@dataclass
class Rule:
    """One line of the box, read."""

    kind: str
    opts: dict[str, Any] = field(default_factory=dict)
    raw: str = ""
    lineno: int = 0


def colour(text: str) -> str:
    """A colour word as plotly should see it."""
    text = str(text or "").strip()
    return BASIC_COLORS.get(text.lower(), text)


def is_colour(token: str) -> bool:
    token = token.strip()
    return bool(token) and (
        token.lower() in BASIC_COLORS or token.startswith("#")
        or token.lower().startswith(("rgb(", "rgba(", "hsl("))
        or token.lower() in _CSS_COLORS)


#: Enough CSS names that a colour typed without a # is recognised as one
#: rather than read as the next word of the rule. Plotly knows the whole
#: list; this only has to decide "is this token a colour".
_CSS_COLORS = frozenset("""
crimson coral salmon tomato firebrick maroon gold khaki olive lime teal cyan
aqua navy indigo violet magenta fuchsia plum orchid tan beige ivory silver
slategray slategrey lightgray lightgrey darkgray darkgrey dimgray dimgrey
steelblue skyblue royalblue midnightblue seagreen forestgreen darkgreen
springgreen turquoise chocolate sienna peru wheat linen snow transparent
""".split())


def tokens(line: str) -> list[tuple[str, bool]]:
    """The line as (text, was quoted) pairs, quotes removed."""
    out: list[tuple[str, bool]] = []
    for match in re.finditer(r'"([^"]*)"|\'([^\']*)\'|(\S+)', line):
        if match.group(3) is None:
            out.append((match.group(1) if match.group(1) is not None
                        else match.group(2), True))
        else:
            out.append((match.group(3), False))
    return out


def strip_comment(line: str) -> str:
    """Drop a trailing `# comment`, leaving a # colour alone."""
    out = []
    quote = None
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "#":
            # a colour is #abc123 with no space before the digits, and it
            # never starts a word on its own
            following = line[index + 1:index + 2]
            if index and line[index - 1] not in " \t" or following.isalnum():
                pass
            else:
                break
        out.append(char)
    return "".join(out)


def parse_rule_lines(text: str) -> list[tuple[str, Optional[Rule],
                                              Optional[str]]]:
    """Every line as ``(raw, Rule | None, error | None)``.

    Blank lines and comments come back as ``(raw, None, None)``, so a
    wizard can edit one line without disturbing the others.
    """
    out = []
    for lineno, raw in enumerate(str(text or "").splitlines(), 1):
        body = strip_comment(raw).strip()
        if not body:
            out.append((raw, None, None))
            continue
        try:
            out.append((raw, _parse_line(body, lineno), None))
        except ValueError as exc:
            out.append((raw, None, str(exc)))
    return out


def parse(text: str) -> tuple[list[Rule], list[str]]:
    """The rules a box holds, and a message for each line that failed."""
    rules, problems = [], []
    for raw, rule, error in parse_rule_lines(text):
        if rule is not None:
            rules.append(rule)
        elif error:
            problems.append(error)
    return rules, problems


def _parse_line(body: str, lineno: int) -> Rule:
    parsed = tokens(body)
    verb = parsed[0][0].lower()
    parser = _PARSERS.get(verb)
    if parser is None:
        raise ValueError(
            f"line {lineno}: {verb!r} is not a chart rule — expected one of "
            f"{', '.join(sorted(_PARSERS))}")
    rule = parser(parsed[1:], lineno)
    rule.raw = body
    rule.lineno = lineno
    return rule


def _number(token: str, lineno: int, what: str) -> float:
    try:
        return float(token)
    except (TypeError, ValueError):
        raise ValueError(f"line {lineno}: {what} wants a number, got "
                         f"{token!r}") from None


def _words(parsed, start=0) -> str:
    return " ".join(text for text, _ in parsed[start:]).lower()


# ------------------------------------------------------------------ verbs

def _parse_series(parsed, lineno) -> Rule:
    if not parsed:
        raise ValueError(
            f'line {lineno}: series wants something to plot, e.g. '
            f'series total line blue as "Total"')
    opts: dict[str, Any] = {"style": "line", "axis": "left"}
    index = 0
    first = parsed[0][0]
    if first.lower() in AGGREGATES:
        opts["aggregate"] = first.lower()
        index = 1
        if index < len(parsed) and parsed[index][0].lower() == "of":
            index += 1
            columns, index = _column_list(parsed, index)
            if not columns:
                raise ValueError(f"line {lineno}: 'of' wants column names")
            opts["columns"] = columns
    else:
        opts["column"] = first
        index = 1

    while index < len(parsed):
        word = parsed[index][0].lower()
        if word == "from" and index + 1 < len(parsed):
            opts["source"] = parsed[index + 1][0]
            index += 2
        elif word == "as" and index + 1 < len(parsed):
            opts["label"] = parsed[index + 1][0]
            index += 2
        elif word in SERIES_STYLES:
            opts["style"] = word
            index += 1
        elif word in ("right", "left"):
            opts["axis"] = word
            index += 1
        elif word == "thick":
            opts["width"] = 3
            index += 1
        elif word == "width" and index + 1 < len(parsed):
            opts["width"] = _number(parsed[index + 1][0], lineno, "width")
            index += 2
        elif is_colour(parsed[index][0]):
            opts["colour"] = colour(parsed[index][0])
            index += 1
        else:
            raise ValueError(
                f"line {lineno}: series does not understand "
                f"{parsed[index][0]!r}")
    return Rule("series", opts)


def _column_list(parsed, index) -> tuple[list[str], int]:
    """Comma-separated column names from `index` on, stopping at a keyword."""
    columns: list[str] = []
    stop = {"from", "as", "right", "left", "thick", "width"} | set(
        SERIES_STYLES)
    while index < len(parsed):
        text, quoted = parsed[index]
        if not quoted and text.lower().rstrip(",") in stop:
            break
        for part in text.split(","):
            if part.strip():
                columns.append(part.strip())
        index += 1
        if not text.endswith(","):
            break
    return columns, index


def _parse_axis(parsed, lineno) -> Rule:
    if not parsed:
        raise ValueError(f"line {lineno}: axis wants x, y or y2")
    which = parsed[0][0].lower()
    if which not in ("x", "y", "y2"):
        raise ValueError(
            f"line {lineno}: axis wants x, y or y2, got {which!r}")
    opts: dict[str, Any] = {"axis": which}
    index = 1
    while index < len(parsed):
        word = parsed[index][0].lower()
        rest = _words(parsed, index)
        if word == "title" and index + 1 < len(parsed):
            opts["title"] = parsed[index + 1][0]
            index += 2
        elif word == "hide":
            following = (parsed[index + 1][0].lower()
                         if index + 1 < len(parsed) else "")
            if following == "title":
                opts["hide_title"] = True
                index += 2
            elif following in ("ticks", "labels"):
                opts["hide_ticks"] = True
                index += 2
            else:
                opts["hide"] = True
                index += 1
        elif word == "show":
            opts["hide"] = False
            index += 1
        elif word == "format" and index + 1 < len(parsed):
            opts["format"] = parsed[index + 1][0]
            index += 2
        elif word == "range" and index + 2 < len(parsed):
            opts["range"] = [_number(parsed[index + 1][0], lineno, "range"),
                             _number(parsed[index + 2][0], lineno, "range")]
            index += 3
        elif word == "log":
            opts["log"] = True
            index += 1
        elif word == "grid" and index + 1 < len(parsed):
            opts["grid"] = parsed[index + 1][0].lower() == "on"
            index += 2
        elif word == "angle" and index + 1 < len(parsed):
            opts["angle"] = _number(parsed[index + 1][0], lineno, "angle")
            index += 2
        elif word == "slider":
            opts["slider"] = True
            index += 1
        elif word == "order":
            found = next((o for o in _CATEGORY_ORDERS
                          if rest.startswith("order " + o)), None)
            if found is None:
                raise ValueError(
                    f"line {lineno}: order wants one of "
                    f"{', '.join(_CATEGORY_ORDERS)}")
            opts["order"] = found
            index += 1 + len(found.split())
        else:
            raise ValueError(
                f"line {lineno}: axis does not understand "
                f"{parsed[index][0]!r}")
    return Rule("axis", opts)


def _parse_legend(parsed, lineno) -> Rule:
    opts: dict[str, Any] = {}
    index = 0
    while index < len(parsed):
        word = parsed[index][0].lower()
        rest = _words(parsed, index)
        position = next((p for p in sorted(LEGEND_POSITIONS, key=len,
                                           reverse=True)
                         if rest.startswith(p)), None)
        if word == "hide":
            if index + 1 < len(parsed) and parsed[index + 1][0].lower() == "title":
                opts["hide_title"] = True
                index += 2
            else:
                opts["show"] = False
                index += 1
        elif word == "show":
            opts["show"] = True
            index += 1
        elif word == "title" and index + 1 < len(parsed):
            opts["title"] = parsed[index + 1][0]
            index += 2
        elif position is not None:
            opts["position"] = position
            index += len(position.split())
        elif word in ("horizontal", "vertical"):
            opts["orientation"] = "h" if word == "horizontal" else "v"
            index += 1
        elif word == "size" and index + 1 < len(parsed):
            opts["size"] = _number(parsed[index + 1][0], lineno, "size")
            index += 2
        elif word == "background" and index + 1 < len(parsed):
            opts["background"] = colour(parsed[index + 1][0])
            index += 2
        elif word == "border" and index + 1 < len(parsed):
            opts["border"] = colour(parsed[index + 1][0])
            index += 2
            if index < len(parsed):
                try:
                    opts["border_width"] = float(parsed[index][0])
                    index += 1
                except ValueError:
                    pass
        elif word == "order" and index + 1 < len(parsed):
            opts["order"] = parsed[index + 1][0].lower()
            index += 2
        elif word == "clicks" and index + 1 < len(parsed):
            opts["clicks"] = parsed[index + 1][0].lower()
            index += 2
        else:
            raise ValueError(
                f"line {lineno}: legend does not understand "
                f"{parsed[index][0]!r}")
    if not opts:
        raise ValueError(
            f"line {lineno}: legend wants something to do, e.g. legend bottom")
    return Rule("legend", opts)


def _parse_title(parsed, lineno) -> Rule:
    if not parsed:
        raise ValueError(f'line {lineno}: title wants text, e.g. title "Sales"')
    opts: dict[str, Any] = {"text": parsed[0][0]}
    for text, _ in parsed[1:]:
        word = text.lower()
        if word in ("left", "center", "centre", "right"):
            opts["align"] = "center" if word == "centre" else word
        else:
            raise ValueError(
                f"line {lineno}: title does not understand {text!r}")
    return Rule("title", opts)


def _parse_subtitle(parsed, lineno) -> Rule:
    if not parsed:
        raise ValueError(f"line {lineno}: subtitle wants text")
    return Rule("subtitle", {"text": parsed[0][0]})


def _parse_note(parsed, lineno) -> Rule:
    if not parsed:
        raise ValueError(f'line {lineno}: note wants text, e.g. note "Draft"')
    opts: dict[str, Any] = {"text": parsed[0][0], "position": "top left"}
    rest = _words(parsed, 1)
    if rest:
        corner = next((c for c in _CORNERS if rest.startswith(c)), None)
        if corner is None:
            raise ValueError(
                f"line {lineno}: note wants a corner "
                f"({', '.join(_CORNERS)}), got {rest!r}")
        opts["position"] = corner
    return Rule("note", opts)


def _parse_reference_line(parsed, lineno) -> Rule:
    opts: dict[str, Any] = {"axis": "y", "dash": "dash"}
    index = 0
    if parsed and parsed[0][0].lower() == "at":
        index = 1
    if index >= len(parsed):
        raise ValueError(
            f"line {lineno}: line wants a value, e.g. line at 100 red")
    opts["at"] = _number(parsed[index][0], lineno, "line at")
    index += 1
    while index < len(parsed):
        word = parsed[index][0].lower()
        if word == "on" and index + 1 < len(parsed):
            axis = parsed[index + 1][0].lower()
            if axis not in ("x", "y"):
                raise ValueError(f"line {lineno}: line on wants x or y")
            opts["axis"] = axis
            index += 2
        elif word in ("dashed", "dotted", "solid", "dashdot"):
            opts["dash"] = {"dashed": "dash", "dotted": "dot",
                            "solid": "solid", "dashdot": "dashdot"}[word]
            index += 1
        elif word == "label" and index + 1 < len(parsed):
            opts["label"] = parsed[index + 1][0]
            index += 2
        elif word == "width" and index + 1 < len(parsed):
            opts["width"] = _number(parsed[index + 1][0], lineno, "width")
            index += 2
        elif is_colour(parsed[index][0]):
            opts["colour"] = colour(parsed[index][0])
            index += 1
        else:
            raise ValueError(
                f"line {lineno}: line does not understand "
                f"{parsed[index][0]!r}")
    return Rule("refline", opts)


def _parse_font(parsed, lineno) -> Rule:
    opts: dict[str, Any] = {}
    family: list[str] = []
    for text, quoted in parsed:
        if not quoted and re.fullmatch(r"\d+(\.\d+)?", text):
            opts["size"] = float(text)
        elif is_colour(text):
            opts["colour"] = colour(text)
        else:
            family.append(text)
    if family:
        opts["family"] = " ".join(family).strip(",")
    if not opts:
        raise ValueError(
            f"line {lineno}: font wants a family, a size or a colour")
    return Rule("font", opts)


def _parse_background(parsed, lineno) -> Rule:
    opts: dict[str, Any] = {}
    index = 0
    while index < len(parsed):
        word = parsed[index][0].lower()
        if word in ("plot", "paper", "card") and index + 1 < len(parsed):
            key = "plot" if word == "plot" else "paper"
            opts[key] = colour(parsed[index + 1][0])
            index += 2
        elif is_colour(parsed[index][0]):
            opts["plot"] = opts["paper"] = colour(parsed[index][0])
            index += 1
        else:
            raise ValueError(
                f"line {lineno}: background wants plot or paper and a "
                f"colour, got {parsed[index][0]!r}")
    if not opts:
        raise ValueError(f"line {lineno}: background wants a colour")
    return Rule("background", opts)


def _parse_margin(parsed, lineno) -> Rule:
    numbers = [_number(text, lineno, "margin")
               for text, _ in parsed if text.strip(",")]
    if len(numbers) != 4:
        raise ValueError(
            f"line {lineno}: margin wants four numbers — left, right, top, "
            f"bottom")
    return Rule("margin", {"values": numbers})


def _parse_hover(parsed, lineno) -> Rule:
    rest = _words(parsed)
    modes = {"unified": "x unified", "x unified": "x unified", "x": "x",
             "y": "y", "closest": "closest", "off": False}
    if rest not in modes:
        raise ValueError(
            f"line {lineno}: hover wants one of {', '.join(modes)}")
    return Rule("hover", {"mode": modes[rest]})


def _parse_bars(parsed, lineno) -> Rule:
    opts: dict[str, Any] = {}
    index = 0
    while index < len(parsed):
        word = parsed[index][0].lower()
        if word in ("group", "stack", "overlay", "relative"):
            opts["mode"] = word
            index += 1
        elif word == "gap" and index + 1 < len(parsed):
            opts["gap"] = _number(parsed[index + 1][0], lineno, "gap")
            index += 2
        else:
            raise ValueError(
                f"line {lineno}: bars does not understand "
                f"{parsed[index][0]!r}")
    if not opts:
        raise ValueError(
            f"line {lineno}: bars wants group, stack, overlay or relative")
    return Rule("bars", opts)


def _parse_colorbar(parsed, lineno) -> Rule:
    opts: dict[str, Any] = {}
    if parsed and parsed[0][0].lower() == "hide":
        opts["hide"] = True
    elif len(parsed) >= 2 and parsed[0][0].lower() == "title":
        opts["title"] = parsed[1][0]
    else:
        raise ValueError(f'line {lineno}: colorbar wants hide or title "…"')
    return Rule("colorbar", opts)


def _raw_parser(kind: str) -> Callable:
    def parse_raw(parsed, lineno) -> Rule:
        text = " ".join(t for t, _ in parsed).strip()
        if not text:
            raise ValueError(f"line {lineno}: {kind} wants a JSON object")
        try:
            value = json.loads(text)
        except ValueError as exc:
            raise ValueError(
                f"line {lineno}: {kind} is not valid JSON — {exc}") from None
        if not isinstance(value, dict):
            raise ValueError(
                f'line {lineno}: {kind} wants a JSON object like '
                f'{{"bargap": 0.3}}')
        return Rule(kind, {"json": value})
    return parse_raw


_PARSERS: dict[str, Callable] = {
    "series": _parse_series,
    "axis": _parse_axis,
    "legend": _parse_legend,
    "title": _parse_title,
    "subtitle": _parse_subtitle,
    "note": _parse_note,
    "line": _parse_reference_line,
    "font": _parse_font,
    "background": _parse_background,
    "margin": _parse_margin,
    "hover": _parse_hover,
    "bars": _parse_bars,
    "colorbar": _parse_colorbar,
    "layout": _raw_parser("layout"),
    "traces": _raw_parser("traces"),
    "config": _raw_parser("config"),
}

#: Every word the language knows, for completion and the wizard.
KEYWORDS: tuple[str, ...] = tuple(sorted(
    set(_PARSERS)
    | set(AGGREGATES) | set(SERIES_STYLES) | set(BASIC_COLORS)
    | {"from", "compare", "as", "of", "right", "left", "thick", "width",
       "hide", "show", "title", "ticks", "labels", "format", "range", "log",
       "grid", "on", "off", "angle", "slider", "order", "horizontal",
       "vertical", "size", "background", "border", "clicks", "isolate",
       "center", "top", "bottom", "at", "label", "dashed", "dotted", "solid",
       "plot", "paper", "gap", "group", "stack", "overlay", "relative",
       "unified", "closest", "colorbar", "x", "y", "y2"}))


def lint(text: str) -> list[tuple[int, str]]:
    """(line number, message) for each line that cannot be read — what the
    box's editor underlines."""
    out = []
    for lineno, (_, rule, error) in enumerate(parse_rule_lines(text), 1):
        if error:
            out.append((lineno, error))
    return out


# ------------------------------------------------------------------ apply

def apply_rules(fig, rules, *, frame=None, raw=None, compare=None,
                x: str = "", ys: tuple = (), aggregate: str = "") -> list[str]:
    """Apply `rules` to `fig`, in order. Returns what could not be done.

    Nothing here raises: a rule naming a column that isn't there, or a
    series on a node with no data to draw from, is reported and skipped so
    the chart still draws — the same bargain a table's formatting rules
    make.
    """
    problems: list[str] = []
    for rule in rules:
        try:
            _APPLIERS[rule.kind](fig, rule, frame, raw, compare, x, ys,
                                 aggregate)
        except Exception as exc:                        # noqa: BLE001
            problems.append(f"line {rule.lineno}: {exc}")
    return problems


def _apply_axis(fig, rule, frame, raw, compare, x, ys, aggregate) -> None:
    opts = rule.opts
    which = opts["axis"]
    settings: dict[str, Any] = {}
    if "title" in opts:
        settings["title_text"] = opts["title"]
    if opts.get("hide_title"):
        settings["title_text"] = ""
    if opts.get("hide_ticks"):
        settings["showticklabels"] = False
    if "hide" in opts:
        settings["visible"] = not opts["hide"]
    if "format" in opts:
        settings["tickformat"] = opts["format"]
    if "range" in opts:
        settings["range"] = opts["range"]
    if opts.get("log"):
        settings["type"] = "log"
    if "grid" in opts:
        settings["showgrid"] = opts["grid"]
    if "angle" in opts:
        settings["tickangle"] = opts["angle"]
    if opts.get("slider"):
        settings["rangeslider_visible"] = True
    if "order" in opts:
        order = opts["order"]
        settings["categoryorder"] = ("trace" if order == "as plotted"
                                     else order)
    if not settings:
        return
    if which == "x":
        fig.update_xaxes(**settings)
    elif which == "y":
        # update_yaxes walks *every* y axis, which is what a faceted chart
        # wants and what a chart with a right-hand axis does not: the
        # second axis is put back as it was, so `axis y` and `axis y2` stay
        # separate. A facet's own second axis has no `overlaying` and is
        # left to be styled with the rest.
        before = fig.to_plotly_json().get("layout", {}).get("yaxis2") or {}
        fig.update_yaxes(**settings)
        if before.get("overlaying"):
            fig.update_layout(overwrite=True, yaxis2=before)
    else:
        _second_axis(fig, _y2_settings(settings))


def _y2_settings(settings: dict) -> dict:
    """update_yaxes takes `title_text`; a layout dict wants `title`."""
    out = dict(settings)
    if "title_text" in out:
        out["title"] = {"text": out.pop("title_text")}
    if "rangeslider_visible" in out:
        out["rangeslider"] = {"visible": out.pop("rangeslider_visible")}
    return out


def _second_axis(fig, settings: dict) -> None:
    """Add to the right-hand Y axis, making it if this is the first thing
    on it. Read through `to_plotly_json` because `fig.layout.yaxis2` raises
    until something has put one there — a rule may name the axis before the
    series that fills it, or after."""
    current = fig.to_plotly_json().get("layout", {}).get("yaxis2", {})
    fig.update_layout(yaxis2={"overlaying": "y", "side": "right",
                              **current, **settings})


def _apply_legend(fig, rule, *_args) -> None:
    opts = rule.opts
    layout: dict[str, Any] = {}
    spec: dict[str, Any] = {}
    if "show" in opts:
        layout["showlegend"] = opts["show"]
    if "title" in opts:
        layout["legend_title_text"] = opts["title"]
    if opts.get("hide_title"):
        layout["legend_title_text"] = ""
    if "position" in opts:
        spec.update(LEGEND_POSITIONS[opts["position"]])
    if "orientation" in opts:
        spec["orientation"] = opts["orientation"]
    if "size" in opts:
        spec["font"] = {"size": opts["size"]}
    if "background" in opts:
        spec["bgcolor"] = opts["background"]
    if "border" in opts:
        spec["bordercolor"] = opts["border"]
    if "border_width" in opts:
        spec["borderwidth"] = opts["border_width"]
    if "order" in opts:
        spec["traceorder"] = opts["order"].replace(" ", "+")
    if "clicks" in opts:
        clicks = {"off": (False, False), "isolate": ("toggleothers", "toggle"),
                  "toggle": ("toggle", "toggleothers")}
        if opts["clicks"] not in clicks:
            raise ValueError(f"legend clicks wants off, toggle or isolate")
        spec["itemclick"], spec["itemdoubleclick"] = clicks[opts["clicks"]]
    if spec:
        layout["legend"] = spec
    if layout:
        fig.update_layout(**layout)


def _apply_title(fig, rule, *_args) -> None:
    layout: dict[str, Any] = {"title_text": rule.opts["text"]}
    align = rule.opts.get("align")
    if align:
        layout["title_x"] = {"left": 0.0, "center": 0.5, "right": 1.0}[align]
        layout["title_xanchor"] = align
    fig.update_layout(**layout)


def _apply_subtitle(fig, rule, *_args) -> None:
    fig.update_layout(title_subtitle_text=rule.opts["text"])


def _apply_note(fig, rule, *_args) -> None:
    anchors = {"top left": (0.01, 0.99, "left", "top"),
               "top right": (0.99, 0.99, "right", "top"),
               "bottom left": (0.01, 0.01, "left", "bottom"),
               "bottom right": (0.99, 0.01, "right", "bottom")}
    x, y, xanchor, yanchor = anchors[rule.opts["position"]]
    fig.add_annotation(text=rule.opts["text"], xref="paper", yref="paper",
                       x=x, y=y, xanchor=xanchor, yanchor=yanchor,
                       showarrow=False)


def _apply_refline(fig, rule, *_args) -> None:
    opts = rule.opts
    line: dict[str, Any] = {"line_dash": opts["dash"]}
    if "colour" in opts:
        line["line_color"] = opts["colour"]
    if "width" in opts:
        line["line_width"] = opts["width"]
    if "label" in opts:
        line["annotation_text"] = opts["label"]
    if opts["axis"] == "y":
        fig.add_hline(y=opts["at"], **line)
    else:
        fig.add_vline(x=opts["at"], **line)


def _apply_font(fig, rule, *_args) -> None:
    font = {}
    if "family" in rule.opts:
        font["family"] = rule.opts["family"]
    if "size" in rule.opts:
        font["size"] = rule.opts["size"]
    if "colour" in rule.opts:
        font["color"] = rule.opts["colour"]
    fig.update_layout(font=font)


def _apply_background(fig, rule, *_args) -> None:
    layout = {}
    if "plot" in rule.opts:
        layout["plot_bgcolor"] = rule.opts["plot"]
    if "paper" in rule.opts:
        layout["paper_bgcolor"] = rule.opts["paper"]
    fig.update_layout(**layout)


def _apply_margin(fig, rule, *_args) -> None:
    left, right, top, bottom = rule.opts["values"]
    fig.update_layout(margin={"l": left, "r": right, "t": top, "b": bottom})


def _apply_hover(fig, rule, *_args) -> None:
    fig.update_layout(hovermode=rule.opts["mode"])


def _apply_bars(fig, rule, *_args) -> None:
    layout = {}
    if "mode" in rule.opts:
        layout["barmode"] = rule.opts["mode"]
    if "gap" in rule.opts:
        layout["bargap"] = rule.opts["gap"]
    fig.update_layout(**layout)


def _apply_colorbar(fig, rule, *_args) -> None:
    if rule.opts.get("hide"):
        fig.update_coloraxes(showscale=False)
        for trace in fig.data:
            if "showscale" in trace:
                trace.showscale = False
    if "title" in rule.opts:
        fig.update_coloraxes(colorbar_title_text=rule.opts["title"])


def _apply_layout(fig, rule, *_args) -> None:
    fig.update_layout(**rule.opts["json"])


def _apply_traces(fig, rule, *_args) -> None:
    fig.update_traces(**rule.opts["json"])


def _apply_config(fig, rule, *_args) -> None:
    fig._flograph_config = {**getattr(fig, "_flograph_config", {}),
                            **rule.opts["json"]}


def _apply_series(fig, rule, frame, raw, compare, x, ys, aggregate) -> None:
    import plotly.graph_objects as go

    opts = rule.opts
    source = opts.get("source", "")
    data = frame
    if source:
        if source.lower() not in ("compare", "this", "table"):
            raise ValueError(
                f"'from {source}' — the only other table is 'compare', the "
                f"node's second input")
        if source.lower() == "compare":
            if compare is None:
                raise ValueError(
                    "'from compare' needs a table wired into the node's "
                    "compare input")
            data = compare
    if data is None:
        raise ValueError(
            "a series needs the chart's data — add it on the chart node "
            "rather than on Plotly Style")
    if not x:
        raise ValueError("a series needs the chart to have an X column")

    # A column "Group and total" summarised away is still on the raw rows,
    # and grouping it here by X gives the line the same shape as the bars.
    if (not source and "column" in opts and data is not None
            and opts["column"] not in getattr(data, "columns", ())
            and raw is not None and opts["column"] in raw.columns):
        data = raw
    labels, values, name = _series_values(opts, data, x, ys, aggregate)
    style = SERIES_STYLES[opts["style"]]
    mode, dash, fill = style
    marker_line: dict[str, Any] = {}
    if "colour" in opts:
        marker_line["color"] = opts["colour"]
    if mode == "bars":
        trace = go.Bar(x=labels, y=values, name=opts.get("label", name),
                       marker_color=opts.get("colour"))
    else:
        line: dict[str, Any] = {}
        if dash:
            line["dash"] = dash
        if opts.get("style") == "step":
            line["shape"] = "hv"
        if "colour" in opts:
            line["color"] = opts["colour"]
        if "width" in opts:
            line["width"] = opts["width"]
        trace = go.Scatter(
            x=labels, y=values, mode=mode, name=opts.get("label", name),
            line=line or None, fill=fill,
            marker=marker_line or None)
    if opts.get("axis") == "right":
        trace.update(yaxis="y2")
        _second_axis(fig, {})
    fig.add_trace(trace)


def _series_values(opts, data, x, ys, aggregate):
    """(x labels, y values, default legend name) for one series."""
    import pandas as pd

    if x not in data.columns:
        raise ValueError(f"the chart's X column {x!r} is not in that table")
    if "column" in opts:
        column = opts["column"]
        if column not in data.columns:
            raise ValueError(f"column {column!r} is not in that table")
        columns, how = [column], aggregate or "sum"
        name = column
    else:
        how = opts["aggregate"]
        columns = [c for c in opts.get("columns") or list(ys)
                   if c in data.columns]
        if not columns:
            missing = opts.get("columns") or list(ys)
            raise ValueError(
                "none of the chart's Y columns are in that table"
                if not missing else
                f"column(s) {', '.join(missing)} not in that table")
        name = {"total": "Total", "sum": "Total", "average": "Average",
                "mean": "Average", "min": "Minimum", "max": "Maximum",
                "count": "Count", "median": "Median"}[how]
    rows = data[[x, *columns]].copy()
    numbers = rows[columns].apply(pd.to_numeric, errors="coerce")
    how = {"total": "sum", "average": "mean", "mean": "mean"}.get(how, how)
    if how == "count":
        per_row = numbers.notna().sum(axis=1)
    else:
        per_row = getattr(numbers, how)(axis=1)
    rows = rows[[x]].assign(_value=per_row)
    grouped = rows.groupby(x, sort=False, dropna=False)["_value"]
    totals = getattr(grouped, "sum" if how == "count" else how)()
    return list(totals.index), list(totals.values), name


_APPLIERS: dict[str, Callable] = {
    "series": _apply_series,
    "axis": _apply_axis,
    "legend": _apply_legend,
    "title": _apply_title,
    "subtitle": _apply_subtitle,
    "note": _apply_note,
    "refline": _apply_refline,
    "font": _apply_font,
    "background": _apply_background,
    "margin": _apply_margin,
    "hover": _apply_hover,
    "bars": _apply_bars,
    "colorbar": _apply_colorbar,
    "layout": _apply_layout,
    "traces": _apply_traces,
    "config": _apply_config,
}
