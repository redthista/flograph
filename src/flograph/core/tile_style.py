"""How a tile on a dashboard page looks: its frame, corners, fill, padding,
shadow and title.

A `TileStyle` is a set of *overrides*. Every field is None until someone
sets it, and None means "whatever the level above says": a tile's style
sits over its page's `tile_style`, which sits over `CARD_LOOK` — the look
tiles had before any of this existed. So a page nobody has formatted draws
exactly as it always did, a page can restyle every tile at once, and one
tile can still differ from its page. That is the Power BI arrangement of a
page theme and a visual's own format, and it is what keeps a dashboard
coherent: set the look once on the page, override only the exceptions.

Qt-free on purpose — the colours are hex strings, and the UI turns them
into QColors. The defaults below restate the theme's card colours for that
reason; `ui.theme` is where they come from.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, fields, replace
from typing import Any, Optional

#: A fill with nothing in it: the page shows through.
TRANSPARENT = "transparent"

ALIGNS = ("left", "center", "right")

#: The ranges a number field is held to, so a hand-edited file can't make a
#: tile whose frame is wider than the tile.
LIMITS = {
    "frame_width": (0.5, 8.0),
    "radius": (0.0, 40.0),
    "padding": (0.0, 60.0),
    "title_size": (6.0, 36.0),
}

_HEX = re.compile(r"#[0-9a-fA-F]{6}")

#: Fields a colour goes in, and which of them may be transparent. A frame
#: colour may not: a frame nobody can see is `frame` off.
COLOUR_FIELDS = ("frame_color", "background", "title_color",
                 "title_background")
CLEARABLE_COLOURS = ("background", "title_background")
TOGGLE_FIELDS = ("frame", "shadow", "title", "title_bold", "maximize")
NUMBER_FIELDS = tuple(LIMITS)


@dataclass
class TileStyle:
    frame: Optional[bool] = None
    frame_color: Optional[str] = None
    frame_width: Optional[float] = None
    radius: Optional[float] = None
    background: Optional[str] = None      # "#rrggbb" or TRANSPARENT
    padding: Optional[float] = None
    shadow: Optional[bool] = None
    # The maximize button. Off, the tile cannot be maximized at all — no
    # button, no double-click on its title — so a finished page is not
    # blown up a tile at a time by whoever is reading it.
    maximize: Optional[bool] = None
    title: Optional[bool] = None
    # The words in the title bar, in place of the node's name. Only a tile
    # has one: a page-wide title text would name every tile the same.
    title_text: Optional[str] = None
    title_size: Optional[float] = None    # points
    title_bold: Optional[bool] = None
    title_align: Optional[str] = None     # one of ALIGNS
    title_color: Optional[str] = None
    title_background: Optional[str] = None  # "#rrggbb" or TRANSPARENT

    def copy(self) -> "TileStyle":
        return replace(self)

    def is_empty(self) -> bool:
        return all(getattr(self, f.name) is None for f in fields(self))

    def with_value(self, name: str, value: Any) -> "TileStyle":
        """A copy with one field set — cleaned the way a loaded file is, so
        the pane and a file can't disagree about what is allowed."""
        if name not in FIELD_NAMES:
            raise KeyError(name)
        return replace(self, **{name: clean(name, value)})

    def to_dict(self) -> dict:
        """Only what was set, the way `PageSetup.to_dict` only writes what
        was changed — a tile nobody formatted writes nothing."""
        return {f.name: getattr(self, f.name) for f in fields(self)
                if getattr(self, f.name) is not None}

    @classmethod
    def from_dict(cls, data: Any) -> "TileStyle":
        """Read a saved style. A value that isn't one — a hand edit, a file
        from something newer — costs that field, never the project."""
        if not isinstance(data, dict):
            return cls()
        return cls(**{name: clean(name, data.get(name))
                      for name in FIELD_NAMES})


FIELD_NAMES = tuple(f.name for f in fields(TileStyle))

#: What a page's own style can set: everything but the title's words.
PAGE_FIELDS = tuple(name for name in FIELD_NAMES if name != "title_text")


def clean(name: str, value: Any) -> Any:
    """`value` made fit for field `name`, or None for anything that isn't."""
    if value is None:
        return None
    if name in TOGGLE_FIELDS:
        return value if isinstance(value, bool) else None
    if name in NUMBER_FIELDS:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        low, high = LIMITS[name]
        return min(high, max(low, number))
    if name in COLOUR_FIELDS:
        text = str(value).strip()
        if text.lower() == TRANSPARENT:
            return TRANSPARENT if name in CLEARABLE_COLOURS else None
        return text.lower() if _HEX.fullmatch(text) else None
    if name == "title_align":
        text = str(value).strip().lower()
        return text if text in ALIGNS else None
    if name == "title_text":
        text = str(value)
        return text if text.strip() else None
    return None


#: The look a tile had before tiles could be formatted: the theme's card.
CARD_LOOK = TileStyle(
    frame=True, frame_color="#17181c", frame_width=1.5, radius=6.0,
    background="#2a2c33", padding=0.0, shadow=False, maximize=True,
    title=True, title_text=None, title_size=9.0, title_bold=True,
    title_align="left", title_color="#e5e7eb", title_background="#363943",
)

#: A Note tile's own look. Its fill, frame colour and text colour are left
#: None: a note's fill is its node's colour, tinted, its edge the theme's
#: grid colour and its words the theme's text, and only the painter knows
#: any of them. A note has no title bar, so the title's text colour is
#: what colours its words once a page or the note sets one.
NOTE_LOOK = replace(CARD_LOOK, frame_color=None, frame_width=1.4,
                    radius=8.0, background=None, title=False,
                    title_color=None)


def resolve(page_style: Optional[TileStyle], tile_style: Optional[TileStyle],
            base: TileStyle = CARD_LOOK) -> TileStyle:
    """The look a tile is drawn with: its own style over its page's over
    `base`, field by field."""
    values = {}
    for name in FIELD_NAMES:
        value = getattr(tile_style, name, None) if tile_style else None
        if value is None and page_style is not None and name != "title_text":
            value = getattr(page_style, name, None)
        if value is None:
            value = getattr(base, name)
        values[name] = value
    return TileStyle(**values)


def clean_background(value: Any) -> Optional[str]:
    """A page background: a hex colour, or None for the theme's canvas."""
    text = str(value or "").strip()
    return text.lower() if _HEX.fullmatch(text) else None


__all__ = [
    "ALIGNS", "CARD_LOOK", "CLEARABLE_COLOURS", "COLOUR_FIELDS",
    "FIELD_NAMES", "LIMITS", "NOTE_LOOK", "NUMBER_FIELDS", "PAGE_FIELDS",
    "TOGGLE_FIELDS", "TRANSPARENT", "TileStyle", "clean",
    "clean_background", "resolve",
]

