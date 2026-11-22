"""The customiser's text mode, without Qt: a theme as one editable block of
TOML, and the reverse — what the text says, and which of its lines are wrong.
"""
from __future__ import annotations

import re
import tomllib
from typing import NamedTuple

from . import SECTIONS, Theme, _toml_value

SECTION_TITLES = {
    "ui": "Window and panels",
    "chrome": "Title bar and toolbar",
    "canvas": "Canvas and nodes",
    "status": "Status lights",
    "wires": "Wires, by port type",
    "frame": "Frames (strength, 0 to 1)",
    "surface": "Widget surfaces",
    "editor": "Code editor",
    "syntax": "Code syntax colours",
    "style": "Style choices",
}
CHOICES = {"card_shadow": ("dark", "soft")}
#: whole-number settings that are not a plain 0..12: (smallest, largest).
#: Wide enough to be useful, narrow enough that no value breaks a layout.
RANGES = {
    "divider_width": (0, 12),
    "focus_width": (1, 4),
    "node_corner_radius": (0, 40),
    "node_width": (100, 400),
    "node_header_height": (16, 60),
    "node_row_height": (14, 48),
    "node_compact_size": (40, 120),
}
DEFAULT_RANGE = (0, 12)
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def is_hex(value) -> bool:
    return isinstance(value, str) and bool(HEX_RE.match(value))


def full_text(theme: Theme) -> str:
    """Every setting of `theme`, as TOML with a comment above each section.
    No ``[meta]``: the customiser keeps the name and kind beside the text."""
    out = []
    for section in SECTIONS:
        items = theme.values.get(section)
        if not items:
            continue
        out += [f"# {SECTION_TITLES.get(section, section)}", f"[{section}]"]
        out += [f"{k} = {_toml_value(v)}" for k, v in items.items()]
        out.append("")
    return "\n".join(out)


def find_colour(theme: Theme, value: str, near: int = 6):
    """Which settings of `theme` paint `value` (a ``#rrggbb``)?

    Returns ``(exact, closest)``: the (section, key) pairs whose colour is
    exactly `value`, and — only when there are none — the `near` nearest by
    plain RGB distance, as ``(section, key, distance)``. This is what the
    customiser's eyedropper answers with: a pixel off the screen is the
    colour a setting painted, so an exact match is the usual case; shadows,
    anti-aliasing and blended tints are why a nearest list exists."""
    want = value.lower()
    r, g, b = (int(want[i:i + 2], 16) for i in (1, 3, 5))
    exact, scored = [], []
    for section in SECTIONS:
        for key, have in theme.values.get(section, {}).items():
            if not is_hex(have):
                continue
            if have.lower() == want:
                exact.append((section, key))
                continue
            hr, hg, hb = (int(have[i:i + 2], 16) for i in (1, 3, 5))
            scored.append((((hr - r) ** 2 + (hg - g) ** 2 + (hb - b) ** 2)
                           ** 0.5, section, key))
    if exact:
        return exact, []
    scored.sort()
    return [], [(s, k, d) for d, s, k in scored[:near]]


class Problem(NamedTuple):
    line: int            # 1-based
    message: str
    where: tuple = ()    # (section, key) when one setting is at fault

    # the editor's diagnostics read .severity
    @property
    def severity(self) -> str:
        return "error"


class TextResult(NamedTuple):
    overrides: dict      # section -> {key: value}, only what differs from base
    problems: list       # [Problem]; the overrides are only trustworthy if empty


def _lines_of(text: str) -> dict:
    """(section, key) -> 1-based line, and section -> line, by scanning."""
    where, section = {}, None
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        head = re.match(r"^\[\s*([\w.-]+)\s*\]", line)
        if head:
            section = head.group(1)
            where[section] = number
            continue
        pair = re.match(r"^([\w.-]+)\s*=", line)
        if pair and section:
            where.setdefault((section, pair.group(1)), number)
    return where


def _check(was, key, value):
    """(ok, value as it should be kept, what was expected)."""
    if isinstance(was, bool):
        return isinstance(value, bool), value, "true or false"
    if isinstance(was, float):
        ok = (isinstance(value, (int, float)) and not isinstance(value, bool)
              and 0.0 <= float(value) <= 1.0)
        return ok, (float(value) if ok else value), "a number from 0 to 1"
    if isinstance(was, int):
        low, high = RANGES.get(key, DEFAULT_RANGE)
        ok = (isinstance(value, int) and not isinstance(value, bool)
              and low <= value <= high)
        return ok, value, f"a whole number from {low} to {high}"
    if is_hex(was):
        ok = is_hex(value)
        return ok, (value.lower() if ok else value), 'a colour like "#1a2b3c"'
    if key in CHOICES:
        return value in CHOICES[key], value, " or ".join(CHOICES[key])
    return isinstance(value, str), value, "text"


def parse_text(text: str, base: Theme) -> TextResult:
    """Read the customiser's text against `base`: which values differ, and
    every line that cannot be used (bad TOML, unknown section or key, a
    value of the wrong sort)."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        message = str(exc)
        found = re.search(r"line (\d+)", message)
        return TextResult({}, [Problem(int(found.group(1)) if found else 1,
                                       message)])
    where = _lines_of(text)
    problems, overrides = [], {}
    for section, items in data.items():
        if section == "meta":
            continue
        line = where.get(section, 1)
        if section not in SECTIONS:
            problems.append(Problem(line, f"unknown section [{section}]"))
            continue
        if not isinstance(items, dict):
            problems.append(Problem(line, f"[{section}] must be a table"))
            continue
        known = base.values.get(section, {})
        for key, value in items.items():
            line = where.get((section, key), line)
            if key not in known:
                problems.append(Problem(
                    line, f"unknown setting {key!r} in [{section}]",
                    (section, key)))
                continue
            ok, value, expected = _check(known[key], key, value)
            if not ok:
                problems.append(Problem(line, f"{key}: expected {expected}",
                                        (section, key)))
            elif value != known[key]:
                overrides.setdefault(section, {})[key] = value
    return TextResult(overrides, problems)
