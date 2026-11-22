"""Themes as data.

A theme is a TOML file of named colours, grouped into sections, plus a few
on/off style choices. Nothing here knows about Qt: `flograph.ui.theme` turns
the active theme into a palette, a stylesheet and the canvas colours.

Three themes ship, `dark.toml`, `light.toml` and `light_steel.toml`, next to this file. `dark` is
the reference: it defines every key, and every other theme inherits from it
— directly, or through `based_on` — so a theme only lists what it changes::

    [meta]
    label = "Light, warmer"
    based_on = "light"

    [canvas]
    CANVAS_BG = "#ece8e1"

User themes are `*.toml` files in `<user data dir>/themes/`; the file stem is
the theme's name. A user theme with a built-in's name does not replace it.

Sections and what reads them:

==========  ==============================================================
``meta``     label, based_on, kind ("light" | "dark": what Qt is told the
             colour scheme is, and what `theme.is_dark()` answers)
``ui``       the window palette — panels, lists, text, selection, tabs
``chrome``   the title bar and toolbar
``canvas``   node graph: background, grid, nodes, wires' validity, frames
``status``   the status lights (idle, queued, running, done, error)
``wires``    one colour per port type
``frame``    how strongly a frame's own colour shows (alphas, 0..1)
``surface``  what hard-coded dark-theme colours in widget stylesheets turn
             into (see `theme.skin`)
``editor``   the code editor's own surfaces
``syntax``   Python highlighting
``style``    on/off choices: node shadows, category colours, ...
==========  ==============================================================
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).parent
BUILTIN = ("light", "dark", "light_steel")      # the order Settings lists them in
REFERENCE = "dark"

SECTIONS = ("ui", "chrome", "canvas", "status", "wires", "frame",
            "surface", "editor", "syntax", "style")


class ThemeError(ValueError):
    """A theme file that cannot be used: unreadable, or a bad based_on."""


@dataclass
class Theme:
    name: str
    label: str
    kind: str                       # "light" | "dark"
    values: dict = field(default_factory=dict)   # section -> {key: value}
    path: Path | None = None
    builtin: bool = False
    #: what is wrong in a user theme file (bad hex, unknown key, a number out
    #: of range), as "file line N: message". Such values are ignored, never
    #: fatal; the customiser shows them.
    problems: list = field(default_factory=list)

    def get(self, section: str, key: str):
        return self.values[section][key]

    def section(self, section: str) -> dict:
        return self.values[section]


def _read(path: Path) -> dict:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ThemeError(f"{path.name}: {exc}") from exc


def _sources(user_dir: Path | None) -> dict[str, Path]:
    found = {name: HERE / f"{name}.toml" for name in BUILTIN}
    if user_dir is not None and user_dir.is_dir():
        for path in sorted(user_dir.glob("*.toml")):
            found.setdefault(path.stem, path)
    return found


def available(user_dir: Path | None = None) -> list[str]:
    """Every theme name that can be loaded: built-ins first."""
    return list(_sources(user_dir))


def load(name: str, user_dir: Path | None = None) -> Theme:
    """The theme `name`, with everything it does not set inherited."""
    sources = _sources(user_dir)
    chain: list[tuple[str, dict]] = []
    seen = set()
    current = name
    while True:
        if current in seen:
            raise ThemeError(f"{name}: based_on loops through {current!r}")
        seen.add(current)
        path = sources.get(current)
        if path is None:
            raise ThemeError(f"no theme named {current!r}")
        data = _read(path)
        chain.append((current, data))
        if current == REFERENCE:
            break
        current = data.get("meta", {}).get("based_on", REFERENCE)

    problems = _sanitize(chain, sources)
    merged: dict = {s: {} for s in SECTIONS}
    kind = "dark"
    for _, data in reversed(chain):            # reference first
        for section in SECTIONS:
            merged[section].update(data.get(section, {}))
        kind = data.get("meta", {}).get("kind", kind)
    own = chain[0][1].get("meta", {})
    kind = own.get("kind", kind)
    if kind not in ("light", "dark"):
        raise ThemeError(f"{name}: kind must be 'light' or 'dark'")
    return Theme(name=name, label=own.get("label", name.title()), kind=kind,
                 values=merged, path=sources[name],
                 builtin=name in BUILTIN and sources[name].parent == HERE,
                 problems=problems)


def _sanitize(chain, sources) -> list:
    """Judge the user files of an inheritance chain against the reference
    theme's keys, *remove* what is wrong from the loaded data (so a bad hex
    or an unknown key is ignored rather than becoming black), and say what
    was wrong. Built-in files are trusted."""
    from .text import parse_text
    reference = Theme(name=REFERENCE, label="", kind="dark", values={
        s: dict(chain[-1][1].get(s, {})) for s in SECTIONS})
    found = []
    for file_name, data in chain:
        path = sources[file_name]
        if path.parent == HERE:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for problem in parse_text(text, reference).problems:
            found.append(f"{path.name} line {problem.line}: {problem.message}")
            if problem.where and isinstance(data.get(problem.where[0]), dict):
                data[problem.where[0]].pop(problem.where[1], None)
    return found


# ---------------------------------------------------------------- writing
# The theme customiser's half: turn a set of overrides into a user theme
# file, and say what a theme sits on top of.

def meta(name: str, user_dir: Path | None = None) -> dict:
    """The raw ``[meta]`` table of theme `name` (not merged with its base)."""
    path = _sources(user_dir).get(name)
    if path is None:
        raise ThemeError(f"no theme named {name!r}")
    return _read(path).get("meta", {})


def slug(label: str) -> str:
    """A file stem from a theme's display name: letters, digits, ``_``."""
    out = "".join(c.lower() if c.isalnum() else "_" for c in label.strip())
    out = "_".join(part for part in out.split("_") if part)
    return out or "custom"


def with_overrides(base: Theme, overrides: dict, *, label: str | None = None,
                   kind: str | None = None) -> Theme:
    """`base` with `overrides` (section -> {key: value}) laid over it: what
    the customiser previews, before anything is written."""
    values = {s: dict(d) for s, d in base.values.items()}
    for section, items in overrides.items():
        values.setdefault(section, {}).update(items)
    return Theme(name=base.name, label=label or base.label,
                 kind=kind or base.kind, values=values, path=base.path,
                 builtin=False)


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def dumps(label: str, kind: str, based_on: str, overrides: dict) -> str:
    """The text of a user theme file that sets only `overrides`."""
    lines = ["# A flograph theme made in Tools ▸ Theme Customiser.",
             "# Only what differs from `based_on` is listed.", "",
             "[meta]", f"label = {_toml_value(label)}",
             f"kind = {_toml_value(kind)}",
             f"based_on = {_toml_value(based_on)}"]
    for section in SECTIONS:
        items = overrides.get(section)
        if not items:
            continue
        lines += ["", f"[{section}]"]
        lines += [f"{key} = {_toml_value(value)}"
                  for key, value in items.items()]
    return "\n".join(lines) + "\n"


def save_user(user_dir: Path, label: str, kind: str, based_on: str,
              overrides: dict) -> str:
    """Write `<user_dir>/<slug>.toml`; returns the theme's name (the stem).
    A built-in's name is never used: it would be ignored on load."""
    name = slug(label)
    if name in BUILTIN:
        name += "_custom"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / f"{name}.toml").write_text(
        dumps(label, kind, based_on, overrides), encoding="utf-8")
    return name
