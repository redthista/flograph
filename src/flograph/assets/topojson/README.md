# Map outlines for Plotly geo charts

The 1:110m outlines plotly.js draws a geo map on (`scatter_geo`,
`choropleth`) — one file per `geo.scope`, at plotly's default
`geo.resolution` of 110. Shipped so a map draws with no network: on a card,
in a report's picture, and live in a saved web page. See
`flograph/geoassets.py`.

The finer 1:50m set is not shipped (3.3 MB); it is the Web Library
**Plotly map outlines — fine detail** (`plotly-map-outlines`), fetched once
from Tools ▸ Web Libraries and pinned by sha256 in `flograph/weblibs.py`.

Source: `https://cdn.plot.ly/un/<scope>_110m.json`, the files plotly.js 3.x
loads by default, downloaded 2026-09-29. Distributed by Plotly with
plotly.js (MIT licence); the boundaries are derived from UN geodata.
Confirm the licence terms before a release that ships them changes.

| file | bytes |
|---|---|
| world_110m.json | 285045 |
| usa_110m.json | 68514 |
| europe_110m.json | 38133 |
| asia_110m.json | 79956 |
| africa_110m.json | 36570 |
| north-america_110m.json | 73900 |
| south-america_110m.json | 22523 |
