"""Checks on a theme: does its text read, can you see its focus ring and its
wires? Qt-free.

Everything here is a *warning* about a design choice — a theme with a pale
grey label on white still loads and still works. Only invalid syntax (bad
hex, unknown key, number out of range) is an *error*, and that comes from
`text.parse_text`, which the customiser and the file loader both use.
"""
from __future__ import annotations

from typing import NamedTuple

from . import Theme
from .text import is_hex


class Issue(NamedTuple):
    level: str                  # "error" | "warning"
    where: tuple                # ((section, key), ...) the settings involved
    message: str


def _channel(v: int) -> float:
    c = v / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hexcode: str) -> float:
    r, g, b = (int(hexcode[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two ``#rrggbb`` colours, 1 to 21."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# (foreground, background, minimum ratio, what it is). 4.5 is WCAG's bar for
# text; 3 for the graphics you need to see (focus rings, wires, selection);
# 2 where a hairline only has to be visible at all.
_PAIRS = (
    (("ui", "text"), ("ui", "base"), 4.5, "text in inputs and lists"),
    (("ui", "window_text"), ("ui", "window"), 4.5, "window text"),
    (("ui", "mid"), ("ui", "window"), 4.5, "dim text (tab labels, captions)"),
    (("ui", "highlighted_text"), ("ui", "highlight"), 4.5, "selected text"),
    (("ui", "button_text"), ("ui", "button"), 4.5, "button labels"),
    (("ui", "placeholder"), ("ui", "base"), 3.0, "input hint text"),
    (("ui", "disabled_text"), ("ui", "disabled_base"), 2.0,
     "disabled text (still has to be findable)"),
    (("ui", "input_focus"), ("ui", "base"), 3.0,
     "the keyboard focus ring on an input"),
    (("ui", "input_focus"), ("ui", "window"), 3.0,
     "the keyboard focus ring beside the window colour"),
    (("ui", "input_border"), ("ui", "base"), 2.0, "input outlines"),
    (("ui", "tooltip_text"), ("ui", "tooltip_bg"), 4.5, "tooltips"),
    (("canvas", "NODE_TEXT"), ("canvas", "NODE_BODY"), 4.5, "node titles"),
    (("canvas", "NODE_TEXT"), ("canvas", "NODE_HEADER"), 4.5,
     "node titles on the header"),
    (("canvas", "NODE_SUBTEXT"), ("canvas", "NODE_BODY"), 4.5,
     "port names and node captions"),
    (("canvas", "NODE_BORDER"), ("canvas", "NODE_BODY"), 1.5,
     "node outlines"),
    (("canvas", "NODE_BODY"), ("canvas", "CANVAS_BG"), 1.1,
     "a node standing off the canvas"),
    (("canvas", "SELECTION_OUTLINE"), ("canvas", "CANVAS_BG"), 3.0,
     "a selected node, wire or frame on the canvas"),
    (("canvas", "SELECTION_OUTLINE"), ("canvas", "NODE_BODY"), 3.0,
     "a selected node's outline against its body"),
    (("chrome", "fg"), ("chrome", "bar_bg"), 4.5, "title bar text"),
    (("chrome", "fg_dim"), ("chrome", "bar_bg"), 4.5,
     "secondary title bar text"),
    (("editor", "EDITOR_FG"), ("editor", "EDITOR_BG"), 4.5,
     "code editor text"),
    (("surface", "text"), ("surface", "base"), 4.5, "text in dialogs"),
    (("surface", "text_dim"), ("surface", "base"), 4.5, "dialog hints"),
)
_SYNTAX = ("keyword", "builtin", "self", "def_name", "decorator", "string",
           "number", "comment")
_WIRES = ("any", "dataframe", "series", "number", "string", "bool", "object",
          "figure", "flow")


def check(theme: Theme) -> list:
    """Contrast warnings for `theme`, worst first."""
    def colour(section, key):
        value = theme.values.get(section, {}).get(key)
        return value if is_hex(value) else None

    found = []

    def test(fg, bg, minimum, what):
        a, b = colour(*fg), colour(*bg)
        if a is None or b is None:
            return
        ratio = contrast(a, b)
        if ratio < minimum:
            found.append((ratio / minimum, Issue(
                "warning", (fg, bg),
                f"{what}: {fg[1]} on {bg[1]} is {ratio:.1f}:1; "
                f"{minimum:g}:1 is the readable minimum")))

    flat = bool(theme.values.get("style", {}).get("flat_controls"))
    for fg, bg, minimum, what in _PAIRS:
        if fg[1].startswith("input_") and not flat:
            continue            # only drawn when style.flat_controls is on
        test(fg, bg, minimum, what)
    for key in _SYNTAX:
        test(("syntax", key), ("editor", "EDITOR_BG"), 4.5,
             f"code colour {key}")
    for key in _WIRES:
        test(("wires", key), ("canvas", "CANVAS_BG"), 3.0,
             f"{key} wires on the canvas")
    found.sort(key=lambda pair: pair[0])
    return [issue for _, issue in found]
