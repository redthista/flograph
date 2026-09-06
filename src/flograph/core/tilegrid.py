"""Where each place sits on a tile-grid map.

A tile-grid cartogram gives every region the same square, arranged so the
shape still reads as the country. It answers the question a real map is bad
at — *compare these places* — because on a real map Highland is the size of
Wales and the City of London is a dot, so the eye reads area as importance
and gets the answer backwards before it has read a single number.

The trade is that the geography is approximate by construction. These grids
are compromises, and a compromise somebody disagrees with is not a bug; it
is why **Custom** exists, where a grid is three columns of text:

    name, row, column

Rows count down from the top and columns across from the left, both from
zero, and a grid may be as sparse as it likes.

Qt-free and pandas-free, like the rest of `core`.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

#: Every built-in grid, as `name: {place: (row, column)}`.
#: Written out as text pictures below and parsed once at import, because a
#: dict of coordinate pairs is unreadable and unreviewable — the point of a
#: tile grid is its shape, and you should be able to see the shape.
_PICTURES: dict[str, str] = {}

_PICTURES["UK regions"] = """
        .   .   SCO .   .
        .   NW  NE  .   .
        NI  .   YH  .   .
        .   WAL WM  EM  EE
        .   .   SW  SE  LON
"""

_PICTURES["UK nations"] = """
        .   SCO
        NI  .
        .   ENG
        WAL .
"""

# The layout in general circulation (NPR / statebins lineage). It buys its
# compactness with a few knowing lies — Illinois sits west of Wisconsin, and
# Hawaii and Alaska are parked in the corners nearest their real bearing.
_PICTURES["US states"] = """
    AK  .   .   .   .   .   .   .   .   .   .   ME
    .   .   .   .   .   .   .   .   .   .   VT  NH
    .   WA  ID  MT  ND  MN  IL  WI  MI  NY  RI  MA
    .   OR  NV  WY  SD  IA  IN  OH  PA  NJ  CT  .
    .   CA  UT  CO  NE  MO  KY  WV  VA  MD  DE  .
    .   .   AZ  NM  KS  AR  TN  NC  SC  DC  .   .
    .   .   .   OK  LA  MS  AL  GA  .   .   .   .
    HI  .   TX  .   .   .   .   FL  .   .   .   .
"""

#: Longer names people actually have in their data, mapped onto the codes
#: the pictures use. Matching is case- and punctuation-insensitive on top of
#: this, so only genuinely different words need an entry.
_ALIASES: dict[str, dict[str, str]] = {
    "UK regions": {
        "north east england": "NE", "north east": "NE",
        "north west england": "NW", "north west": "NW",
        "yorkshire and the humber": "YH", "yorkshire": "YH",
        "yorks and humber": "YH", "yorkshire and humber": "YH",
        "east midlands": "EM", "west midlands": "WM",
        "east of england": "EE", "east": "EE", "eastern": "EE",
        "london": "LON", "greater london": "LON",
        "south east england": "SE", "south east": "SE",
        "south west england": "SW", "south west": "SW",
        "wales": "WAL", "cymru": "WAL",
        "scotland": "SCO", "alba": "SCO",
        "northern ireland": "NI",
    },
    "UK nations": {
        "england": "ENG", "scotland": "SCO", "alba": "SCO",
        "wales": "WAL", "cymru": "WAL", "northern ireland": "NI",
    },
    "US states": {
        "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
        "california": "CA", "colorado": "CO", "connecticut": "CT",
        "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI",
        "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
        "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
        "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
        "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
        "montana": "MT", "nebraska": "NE", "nevada": "NV",
        "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
        "new york": "NY", "north carolina": "NC", "north dakota": "ND",
        "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
        "pennsylvania": "PA", "rhode island": "RI",
        "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
        "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA",
        "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
        "wyoming": "WY",
        "district of columbia": "DC", "washington dc": "DC",
        "washington d c": "DC",
    },
}

#: What each tile is captioned with when the caption is not the raw name.
#: Only where the code is not itself the caption you would want.
_CAPTIONS: dict[str, dict[str, str]] = {
    "UK regions": {
        "NE": "NE", "NW": "NW", "YH": "Y&H", "EM": "E Mid", "WM": "W Mid",
        "EE": "East", "LON": "Ldn", "SE": "SE", "SW": "SW", "WAL": "Wal",
        "SCO": "Sco", "NI": "NI",
    },
    "UK nations": {
        "ENG": "Eng", "SCO": "Sco", "WAL": "Wal", "NI": "NI",
    },
}

CUSTOM = "Custom"
_ROW_SPLIT = re.compile(r"[,\t]| {2,}")


class GridError(ValueError):
    """A grid that could not be read, or a place that is not on one."""


def _parse_picture(picture: str) -> dict[str, tuple[int, int]]:
    cells: dict[str, tuple[int, int]] = {}
    for row, line in enumerate(
            [ln for ln in picture.strip("\n").splitlines() if ln.strip()]):
        for column, code in enumerate(line.split()):
            if code != ".":
                cells[code] = (row, column)
    return cells


GRIDS: dict[str, dict[str, tuple[int, int]]] = {
    name: _parse_picture(picture) for name, picture in _PICTURES.items()
}

#: The names offered in the node's dropdown, `Custom` last.
NAMES: tuple[str, ...] = tuple(GRIDS) + (CUSTOM,)


#: Dropped when matching a place name. "Yorkshire and The Humber",
#: "Yorkshire & Humber" and "yorkshire and the humber" are one place, and
#: none of these words is the difference between any two tiles on any grid.
_FILLER = {"the", "and", "of"}


def normalise(name: str) -> str:
    """A place name flattened to the form the alias table is keyed by."""
    text = re.sub(r"[^a-z0-9 ]+", " ", str(name or "").strip().lower())
    return " ".join(w for w in text.split() if w not in _FILLER)


# Keyed by the flattened form, so the aliases are written above the way
# somebody would actually spell them rather than in this function's dialect.
_ALIASES = {grid_name: {normalise(k): v for k, v in table.items()}
            for grid_name, table in _ALIASES.items()}


def parse_custom(text: str) -> dict[str, tuple[int, int]]:
    """A hand-written grid: `name, row, column`, one place per line."""
    cells: dict[str, tuple[int, int]] = {}
    for lineno, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in _ROW_SPLIT.split(line) if p.strip()]
        if len(parts) < 3:
            raise GridError(
                f"grid line {lineno}: expected 'name, row, column' — got "
                f"{line!r}")
        name = " ".join(parts[:-2])
        try:
            row, column = int(parts[-2]), int(parts[-1])
        except ValueError:
            raise GridError(
                f"grid line {lineno}: row and column must be whole numbers "
                f"— got {parts[-2]!r} and {parts[-1]!r}") from None
        if row < 0 or column < 0:
            raise GridError(f"grid line {lineno}: row and column start at 0")
        cells[name] = (row, column)
    if not cells:
        raise GridError("the custom grid is empty — one 'name, row, column' "
                        "per line")
    return cells


def grid(name: str, custom: str = "") -> dict[str, tuple[int, int]]:
    """The named built-in grid, or the custom one written out in `custom`."""
    if name == CUSTOM:
        return parse_custom(custom)
    if name not in GRIDS:
        raise GridError(f"unknown grid {name!r} — one of: "
                        + ", ".join(NAMES))
    return dict(GRIDS[name])


def lookup(place: str, cells: dict[str, tuple[int, int]],
           grid_name: str = "") -> Optional[str]:
    """Which tile a name in the data belongs to, or None if none of them.

    Tried in order: the code exactly, the code case-insensitively, the alias
    table for this grid, and the tile names flattened the same way — so
    "Yorkshire and The Humber", "yorkshire & the humber" and "YH" all land
    on the same square.
    """
    raw = str(place or "").strip()
    if not raw:
        return None
    if raw in cells:
        return raw

    folded = {code.lower(): code for code in cells}
    if raw.lower() in folded:
        return folded[raw.lower()]

    flat = normalise(raw)
    alias = _ALIASES.get(grid_name, {}).get(flat)
    if alias and alias in cells:
        return alias

    for code in cells:
        if normalise(code) == flat:
            return code
    return None


def caption(code: str, grid_name: str = "") -> str:
    """The short label written inside a tile."""
    return _CAPTIONS.get(grid_name, {}).get(code, code)


def bounds(cells: Iterable[tuple[int, int]]) -> tuple[int, int]:
    """How many rows and columns a set of tiles needs."""
    positions = list(cells)
    if not positions:
        return (0, 0)
    return (max(r for r, _ in positions) + 1,
            max(c for _, c in positions) + 1)
