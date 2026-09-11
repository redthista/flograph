"""The shape of a box, as one number: its width divided by its height.

Two places state a shape. A report embed writes one as `ratio=16:9`, and a
dashboard tile keeps one so that resizing it keeps it. Both read the words
through `parse_aspect` here, so "16:9" cannot mean one thing on paper and
another on a page.

Qt-free, like the rest of `core`.
"""
from __future__ import annotations

import math
import re
from fractions import Fraction
from typing import Optional

#: The shapes offered by name, widest first, as (name, width, height).
#: Whole numbers, because that is how people say them — and "a wide chart,
#: or a long thin one" wants both ends of the list, not just the middle.
PRESETS: tuple = (
    ("Banner", 3, 1),
    ("Wide", 16, 9),
    ("Landscape", 4, 3),
    ("Square", 1, 1),
    ("Portrait", 3, 4),
    ("Tall", 9, 16),
    ("Column", 1, 3),
)


def parse_aspect(raw: str) -> "float | None":
    """A `ratio=` value as the single number width / height.

    `16:9`, `4x3` and `3/2` all mean the same thing; a bare `1.5` is taken
    as that ratio directly. None for anything unparseable or non-positive —
    the caller reports it rather than drawing a nonsense shape.
    """
    text = (raw or "").strip().lower().replace("x", ":").replace("/", ":")
    if not text:
        return None
    try:
        if ":" in text:
            left, _, right = text.partition(":")
            width, height = float(left), float(right)
            if width <= 0 or height <= 0:
                return None
            return width / height
        value = float(text)
        return value if value > 0 and math.isfinite(value) else None
    except ValueError:
        return None


#: What someone types to mean "no shape at all".
ANY_WORDS = ("", "any", "any shape", "free", "none")


def parse_shape(text: str) -> "tuple[bool, float | None]":
    """What a typed shape says: (True, aspect) for a shape, (True, None)
    for any shape, and (False, None) for words that are not one.

    Reads everything `parse_aspect` does, and a preset's name beside it or
    instead of it — "16:9  Wide", "Wide" and "16 : 9" are all 16:9 — so a
    list offering "16:9  Wide" can take back whatever it was given.
    """
    words = (text or "").strip()
    if words.lower() in ANY_WORDS:
        return True, None
    for name, width, height in PRESETS:
        if words.lower() == name.lower():
            return True, width / height
        words = re.sub(rf"\b{name}\b", "", words, flags=re.IGNORECASE)
    aspect = parse_aspect(words.replace(" ", ""))
    return aspect is not None, aspect


def same_aspect(a: Optional[float], b: Optional[float]) -> bool:
    """Whether two shapes are the same to the eye.

    Sizes are whole pixels, so a 16:9 box measures 1.7778 at one width and
    1.7757 at the next. Half a percent is far under what anyone can see
    and far over what rounding one side to a pixel costs. None — no shape
    at all — is only the same as None.
    """
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=0.005)


def preset_for(aspect: Optional[float]) -> Optional[tuple]:
    """The named shape `aspect` is, as its PRESETS row, or None."""
    for row in PRESETS:
        if same_aspect(aspect, row[1] / row[2]):
            return row
    return None


def format_aspect(aspect: float) -> str:
    """`aspect` the way someone would type it back in: "16:9", "5:2".

    A named shape is written as its name says it. Anything else is written
    as the simplest whole-number pair that is the same to the eye, and as a
    plain number when there is none — which `parse_aspect` also reads.
    """
    row = preset_for(aspect)
    if row is not None:
        return f"{row[1]}:{row[2]}"
    pair = Fraction(aspect).limit_denominator(20)
    if pair.numerator and same_aspect(aspect, float(pair)):
        return f"{pair.numerator}:{pair.denominator}"
    return f"{aspect:.3g}"


def keep_aspect(width: float, height: float, aspect: float, lead: str,
                minimum: "tuple[float, float]") -> "tuple[float, float]":
    """(width, height) made into `aspect`, one side leading.

    `lead` is "width" — the width stands and the height follows it — or
    "height", the other way round. The side that follows is rounded to a
    whole pixel; the leading side is left as it came, so a size that was
    snapped to the grid stays on it.

    Neither side goes under `minimum` (min_w, min_h). When the shape would
    take the following side under its floor, the leading side grows until
    it fits: a Column tile at the narrowest a tile can be is still a column,
    just a taller one.
    """
    min_w, min_h = minimum
    if lead == "height":
        height = max(height, min_h, min_w / aspect)
        return float(max(min_w, round(height * aspect))), height
    width = max(width, min_w, min_h * aspect)
    return width, float(max(min_h, round(width / aspect)))


def leading_side(edge: str, press_size: "tuple[float, float]",
                 size: "tuple[float, float]") -> str:
    """Which side a resize drag of `edge` is steering.

    The right edge steers the width and the bottom edge the height. The
    corner steers whichever side the drag has changed more, relative to
    where it started, so a shaped tile follows the hand whichever way it is
    pulled rather than only answering to one axis.
    """
    if edge == "right":
        return "width"
    if edge == "bottom":
        return "height"
    press_w, press_h = press_size
    grew_w = abs(size[0] - press_w) / max(press_w, 1.0)
    grew_h = abs(size[1] - press_h) / max(press_h, 1.0)
    return "width" if grew_w >= grew_h else "height"
