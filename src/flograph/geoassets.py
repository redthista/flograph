"""Map outlines for Plotly's geo charts — from disk, never from a CDN.

plotly.js draws a `scatter_geo` or `choropleth` map on a topojson file of
country outlines, and fetches it from cdn.plot.ly when the map is drawn:
on a card, in the snapshot a report prints, and in a saved web page opened
on someone else's machine. A map that worked at your desk was a blank
ocean on a train, behind a proxy, or in a file emailed to a colleague.

Here the outlines come from disk, the way Tools ▸ Web Libraries does for
scripts (see weblibs.py and its rule: a CDN is where something is
*installed from*, never where it is rendered from):

* **Built in:** the 1:110m set — plotly's default `geo.resolution` — for
  every `geo.scope`, 604 KB in flograph/assets/topojson.
* **Installed once:** the 1:50m set, for a map drawn at `resolution=50`,
  is the Web Library `plotly-map-outlines`.

plotly.js looks in `window.PlotlyGeoAssets.topojson[name]` before it
fetches, so a page that carries the files there never asks. And so that a
file that is *not* on disk fails where it can be seen rather than quietly
coming from the CDN, every page also points plotly's `topojsonURL` at a
local folder that does not exist (LOCAL_TOPOJSON_URL).

Tile maps (`scatter_map`, `density_map`, …) are street or satellite tiles
from a tile server: there is no file to install, so they are the one kind
of map that needs the internet — `needs_the_internet` says so, and a web
page keeps them as the picture the app drew.

Qt-free, stdlib only.
"""
from __future__ import annotations

import functools
import json
import re
from pathlib import Path
from typing import Iterable, Optional

#: The shipped 1:110m outlines.
BUNDLED_DIR = Path(__file__).parent / "assets" / "topojson"

#: The Web Library holding the 1:50m outlines (weblibs.CATALOGUE).
DETAIL_LIBRARY = "plotly-map-outlines"

#: plotly's own names for `geo.scope`, and its two resolutions.
SCOPES = ("world", "usa", "europe", "asia", "africa", "north america",
          "south america")
RESOLUTIONS = (110, 50)

#: Where plotly.js is told to fetch outlines from: a relative folder that
#: does not exist. Never the CDN — a file that is not on disk fails, and
#: the page (or the report's problem list) says which one to install.
LOCAL_TOPOJSON_URL = "flograph-map-outlines/"

#: Traces drawn on outlines — fine offline once the outlines are on disk.
GEO_TRACES = frozenset({"scattergeo", "choropleth"})
#: Traces drawn on tiles from a tile server — never offline.
TILE_TRACES = frozenset({
    "scattermap", "choroplethmap", "densitymap",
    "scattermapbox", "choroplethmapbox", "densitymapbox",
})

_GEO_KEY = re.compile(r"^geo\d*$")


def topojson_name(scope: str = "world", resolution=110) -> str:
    """plotly.js's own file name: `geo.scope` with dashes for spaces, then
    the resolution — "north-america_50m" (its getTopojsonName)."""
    scope = str(scope or "world").replace(" ", "-")
    try:
        resolution = int(float(resolution or 110))
    except (TypeError, ValueError):
        resolution = 110
    return f"{scope}_{resolution}m"


def as_spec(figure) -> dict:
    """A figure as plain {"data": [...], "layout": {...}} — a Plotly figure,
    its `to_plotly_json()`, or its JSON text."""
    if isinstance(figure, str):
        try:
            figure = json.loads(figure)
        except ValueError:
            return {}
    if isinstance(figure, dict):
        return figure
    data, layout = getattr(figure, "data", None), getattr(figure, "layout", None)
    if data is not None and layout is not None:
        # A figure object: read only what these questions need rather than
        # converting every point — a chart can hold a million of them.
        try:
            traces = []
            for trace in data:
                geojson = getattr(trace, "geojson", None)
                traces.append({
                    "type": getattr(trace, "type", None),
                    "geo": getattr(trace, "geo", None),
                    "geojson": geojson if isinstance(geojson, str) else None,
                })
            return {"data": traces, "layout": layout.to_plotly_json()}
        except Exception:
            pass
    to_json = getattr(figure, "to_plotly_json", None)
    if callable(to_json):
        try:
            return to_json()
        except Exception:
            return {}
    return {}


def _layout(spec: dict) -> dict:
    layout = spec.get("layout")
    return layout if isinstance(layout, dict) else {}


def _traces(spec: dict) -> list:
    data = spec.get("data")
    return [t for t in (data or []) if isinstance(t, dict)]


def names_for(figure) -> list:
    """The outline files this figure's geo maps are drawn on, in order.

    One per geo subplot — `layout.geo`, `geo2`, … and any a geo trace names
    — at that subplot's scope and resolution, plotly's defaults (world,
    110) filling the gaps. A figure with no geo map needs none.
    """
    spec = as_spec(figure)
    layout = _layout(spec)
    subplots = [key for key in layout if _GEO_KEY.match(str(key))]
    for trace in _traces(spec):
        if trace.get("type") in GEO_TRACES:
            subplots.append(str(trace.get("geo") or "geo"))
    names: list = []
    for key in subplots:
        geo = layout.get(key)
        geo = geo if isinstance(geo, dict) else {}
        name = topojson_name(geo.get("scope"), geo.get("resolution"))
        if name not in names:
            names.append(name)
    return names


def find(name: str) -> Optional[Path]:
    """Where outline file `name` is on this machine: built in, else in the
    installed Web Library. None if neither — never a URL."""
    bundled = BUNDLED_DIR / f"{name}.json"
    if bundled.is_file():
        return bundled
    from flograph import weblibs
    try:
        path = weblibs.asset_path(DETAIL_LIBRARY, f"{name}.json")
    except weblibs.WebLibError:
        return None
    return path if path.is_file() else None


def missing(names: Iterable[str]) -> list:
    """The ones of `names` that are not on disk."""
    return [name for name in names if find(name) is None]


def needs_the_internet(figure) -> bool:
    """Would this figure fetch anything when drawn in a browser, even with
    every installable outline installed? Tile maps do; so does a
    choropleth whose `geojson` is a URL rather than the shapes themselves.
    A geo map on outlines does not — see `missing` for whether they are
    here yet."""
    spec = as_spec(figure)
    layout = _layout(spec)
    for trace in _traces(spec):
        if trace.get("type") in TILE_TRACES:
            return True
        if isinstance(trace.get("geojson"), str):
            return True
    return any(isinstance(layout.get(key), dict) and layout.get(key)
               for key in ("map", "mapbox"))


def install_hint(names: Iterable[str]) -> str:
    """What to do about outlines that are not here, for a problem list."""
    names = list(names)
    if not names:
        return ""
    return (f"the map outlines {', '.join(names)} are not installed — "
            f"install “Plotly map outlines — fine detail” from "
            f"Tools ▸ Web Libraries")


@functools.lru_cache(maxsize=32)
def _read(path: str, stamp: float) -> str:
    # `</` would end the <script> element the text is written into
    return Path(path).read_text(encoding="utf-8").replace("</", "<\\/")


def preload_js(names: Iterable[str]) -> str:
    """JavaScript putting outline files where plotly.js looks before it
    fetches. Files not on disk are left out (see `missing`); "" if none."""
    parts = []
    for name in names:
        path = find(name)
        if path is None:
            continue
        text = _read(str(path), path.stat().st_mtime)
        parts.append(f"G[{json.dumps(name)}]={text};")
    if not parts:
        return ""
    return ("(function(){var A=window.PlotlyGeoAssets="
            "window.PlotlyGeoAssets||{};var G=A.topojson=A.topojson||{};"
            + "".join(parts) + "})();")


def preload_script(names: Iterable[str]) -> str:
    """`preload_js` as a <script> element, or ""."""
    js = preload_js(names)
    return f"<script>{js}</script>" if js else ""


def with_outlines(html: str, figures: Iterable) -> str:
    """A full page of Plotly charts with their outlines put in its head, so
    the maps draw with no network. A page with no geo map is unchanged."""
    names: list = []
    for figure in figures:
        for name in names_for(figure):
            if name not in names:
                names.append(name)
    script = preload_script(names)
    if not script:
        return html
    found = re.search(r"<head[^>]*>", html, re.IGNORECASE)
    if found:
        return html[:found.end()] + script + html[found.end():]
    return script + html
