"""Web View Template

A commented starting point for a **visual** node: one that draws with HTML,
SVG and JavaScript instead of returning a table. Drop it on the canvas,
right-click and choose Edit Code — every placed node carries its own copy,
so you can rewrite it freely.

It runs as it stands (a small SVG bar chart, no libraries needed) and every
rule that matters is a comment beside the line it applies to. Working
examples of the finished shape: **Calendar Heatmap**, **Sankey Flow**,
**Circle Pack**, **Network Graph**.

## The contract

* `NODE["card"] = "webview"` makes the node a live Chromium view on the
  canvas and a tile on a dashboard. Return HTML from `run()`.
* `NODE["interactive"] = True` lets the page write this node's own params
  from JavaScript, which re-runs everything downstream. That is how a click
  inside a chart filters the board.
* Three outputs is the shape that has earned its keep: **html** (what the
  card draws), **selected** (what the user clicked) and **table** (the
  input filtered to it), so the visual can feed a Show Table beside it.

## Drawing with a JavaScript library

Install it once from **Tools ▸ Web Libraries**, then ask for it by name:

    from flograph.weblibs import markup
    head = markup("echarts")      # or "d3", "cytoscape", "leaflet", ...

`markup()` returns `<script>`/`<link>` tags pointing at your own machine.
Nothing is ever fetched from the internet when a visual renders — a library
is either installed or the node says which one to install, the same way a
missing Python package behaves.

## Five traps

Each of these renders **perfectly on the card** and fails somewhere else,
so none of them shows up until someone tries a report, a browser, or a
tile of a different shape. They are why the code below looks the way it
does.

1. **A report measures zero.** A report photographs the card by printing
   the page, in a view that is never shown — so inside it `innerWidth`,
   `clientWidth`, `%` heights and even `vw`/`vh` all come back **0**.
   Chart libraries draw nothing at all at 0x0. Fall back to a nominal size
   and give the SVG a `viewBox` so it scales.
2. **Printing drops `<canvas>`.** The page's text prints and the chart is a
   blank rectangle. Draw as **SVG** (`{renderer: "svg"}` in ECharts). A
   canvas-only library needs a picture of itself that `@media print` shows
   instead — see Network Graph.
3. **Anything still animating is caught half-drawn.** The picture is taken
   a fraction of a second after load. Turn entry animation off.
4. **A `viewBox` fixes printing and breaks tiles** — it makes the drawing
   fixed-aspect, so it letterboxes in any tile that is not your default
   shape. Use the nominal size *only* when there is no box to measure.
5. **Leaving the app breaks `file://` links.** Handled for you: Open in
   Browser and Save View as HTML inline the libraries, because a browser
   will not load a script from another directory.

And two rules with sharp edges:

* **Never read `width`/`height` in `run()`.** They are cosmetic, so
  resizing the card does not re-run the node — the cached page would be
  stuck at the size it was first drawn at. Measure in JavaScript instead,
  with a module constant as the fallback.
* **Build the page with placeholders, not an f-string.** A page is mostly
  `{` and `}`, and doubling every one to satisfy an f-string is how a
  readable script stops being one.
"""
NODE = {
    "label": "Web View Template",
    "category": "Scripting",
    "version": "1.0",
    # the live Chromium view on the canvas and on a dashboard tile
    "card": "webview",
    # ...and permission for that page to write this node's params
    "interactive": True,
    "inputs": [("table", "dataframe", {"optional": True})],
    "outputs": [("html", "string"), ("selected", "any"),
                ("table", "dataframe")],
}
PARAMS = [
    {"name": "label_column", "type": "columns", "label": "Label",
     "multi": False, "default": ""},
    {"name": "value_column", "type": "columns", "label": "Value",
     "multi": False, "default": "", "placeholder": "blank counts rows"},
    {"name": "on_click", "type": "choice", "label": "On click",
     "options": ["nothing", "select one", "select many"],
     "default": "select one"},
    # What the page writes through flograph.select(). Visible rather than
    # hidden: when a click isn't filtering what you expect, the first
    # question is what the page actually sent, and this is the answer.
    {"name": "selected", "type": "string", "label": "Clicked values",
     "default": "", "placeholder": '["north"] — blank keeps every row',
     "visible_when": {"on_click": ["select one", "select many"]}},
    # Card size only. run() must never read these — see trap notes above.
    {"name": "width", "type": "int", "label": "Width", "default": 460,
     "min": 200, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height", "default": 320,
     "min": 120, "max": 2000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

#: The size the drawing is laid out at when there is no box to measure
#: (trap 1). A module constant, matching this node's default card size —
#: never the width/height params, which are cosmetic.
_NOMINAL = (460, 320)

# The page. A plain string with /*PLACEHOLDER*/ markers filled in by run(),
# not an f-string — see the note in the docstring.
_PAGE = """
<style>
  /* overflow:hidden, or a few stray pixels give the card a scrollbar that
     never goes away and then steals width from the drawing. */
  html, body { margin: 0; height: 100%; background: #0b1220;
               overflow: hidden; font-family: system-ui, sans-serif; }
  /* display:block, or an inline <svg> sits on a text baseline and its
     descender space overflows the page. */
  #chart { display: block; width: 100%; height: 100%; }
  .bar { cursor: pointer; }
  .bar.picked { stroke: #f8fafc; stroke-width: 2px; }
  text { fill: #cbd5e1; font-size: 11px; pointer-events: none;
         paint-order: stroke; stroke: rgba(2,6,23,.75); stroke-width: 3px; }
</style>
<svg id="chart"></svg>
<script>
  var ROWS = /*ROWS*/, PICKED = /*PICKED*/, MODE = /*MODE*/;
  var NOMW = /*NOMW*/, NOMH = /*NOMH*/;

  var svg = document.getElementById("chart");

  function room() {
    // The box to draw in, or null when there is none — which is what a
    // report snapshot sees (trap 1). Everything downstream branches here.
    var box = svg.getBoundingClientRect();
    return (box.width > 0 && box.height > 0)
      ? {width: box.width, height: box.height} : null;
  }

  function draw() {
    var space = room();
    var w = space ? space.width : NOMW;
    var h = space ? space.height : NOMH;
    // A viewBox only matters when we fell back to the nominal size; with a
    // real box we drew to it already, and scaling would letterbox the
    // drawing inside its own tile (trap 4).
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    svg.setAttribute("preserveAspectRatio",
                     space ? "none" : "xMidYMid meet");
    while (svg.firstChild) { svg.removeChild(svg.firstChild); }
    if (!ROWS.length) { return; }

    var top = 0, i;
    for (i = 0; i < ROWS.length; i++) {
      top = Math.max(top, ROWS[i].value);
    }
    var pad = 26, gap = 6;
    var band = (w - pad * 2) / ROWS.length;

    for (i = 0; i < ROWS.length; i++) {
      var row = ROWS[i];
      var tall = top > 0 ? (h - pad * 2) * (row.value / top) : 0;
      var rect = document.createElementNS("http://www.w3.org/2000/svg",
                                          "rect");
      rect.setAttribute("x", pad + i * band + gap / 2);
      rect.setAttribute("y", h - pad - tall);
      rect.setAttribute("width", Math.max(1, band - gap));
      rect.setAttribute("height", tall);
      rect.setAttribute("rx", 3);
      rect.setAttribute("fill", "#2563eb");
      rect.setAttribute("class",
        "bar" + (PICKED.indexOf(row.name) !== -1 ? " picked" : ""));
      rect.addEventListener("click", pick(row.name));
      svg.appendChild(rect);

      var text = document.createElementNS("http://www.w3.org/2000/svg",
                                          "text");
      text.setAttribute("x", pad + i * band + band / 2);
      text.setAttribute("y", h - pad + 14);
      text.setAttribute("text-anchor", "middle");
      text.textContent = row.name;
      svg.appendChild(text);
    }
  }

  function pick(name) {
    return function (event) {
      event.stopPropagation();
      if (MODE === "nothing") { return; }
      if (MODE === "select many") {
        var at = PICKED.indexOf(name);
        if (at === -1) { PICKED.push(name); } else { PICKED.splice(at, 1); }
      } else {
        // Clicking the selected one again clears it, so a visual that
        // filters can always be un-filtered from the visual itself.
        PICKED = (PICKED.length === 1 && PICKED[0] === name) ? [] : [name];
      }
      draw();
      // Writes this node's "selected" param and re-runs everything
      // downstream. The node then redraws from the new param, so there is
      // no state to keep in the page.
      flograph.select(PICKED);
    };
  }

  draw();
  // Lay out again at the new size rather than scaling the old drawing, so
  // text stays the size it was designed at.
  window.addEventListener("resize", draw);
</script>
"""


def run(ctx, table=None):
    import json

    from flograph.core.controls import selected_values

    # A library would be asked for here, and the node would report which one
    # to install if it were missing:
    #
    #     from flograph.weblibs import markup
    #     head = markup("echarts")
    #
    # ...then put `head` in the page's <head>. This template draws with
    # plain SVG so it runs before anything is installed.
    params = ctx.params
    picked = selected_values(params.get("selected", ""))
    mode = str(params.get("on_click", "select one") or "nothing")

    label_column = str(params.get("label_column", "") or "").strip()
    value_column = str(params.get("value_column", "") or "").strip()

    rows = []
    if table is not None and len(table):
        if not label_column:
            label_column = str(table.columns[0])
        if label_column not in table.columns:
            available = ", ".join(str(c) for c in table.columns)
            raise ValueError(f"Label column {label_column!r} is not in the "
                             f"table (has: {available})")
        if value_column and value_column not in table.columns:
            raise ValueError(f"Value column {value_column!r} is not in the "
                             f"table")
        import pandas as pd
        frame = table[[label_column]].astype(str)
        frame.columns = ["name"]
        if value_column:
            frame["value"] = pd.to_numeric(table[value_column],
                                           errors="coerce").fillna(0.0)
        else:
            frame["value"] = 1.0
        totals = frame.groupby("name", as_index=False)["value"].sum()
        rows = [{"name": r.name, "value": round(float(r.value), 4)}
                for r in totals.itertuples(index=False)]
    else:
        rows = [{"name": n, "value": v} for n, v in
                (("north", 7), ("south", 4), ("east", 9), ("west", 3))]
    ctx.log(f"{len(rows)} bar(s); {len(picked)} selected")

    # The filtered table is what makes the visual worth wiring into
    # anything: click a bar, and a Show Table beside it shows those rows.
    filtered = table
    if table is not None and mode != "nothing" and picked and label_column:
        filtered = table[table[label_column].astype(str).isin(picked)]
        ctx.log(f"clicked {', '.join(picked)}: kept {len(filtered)} of "
                f"{len(table)} rows")

    page = (_PAGE
            .replace("/*ROWS*/", json.dumps(rows))
            .replace("/*PICKED*/", json.dumps(picked))
            .replace("/*MODE*/", json.dumps(mode))
            .replace("/*NOMW*/", str(_NOMINAL[0]))
            .replace("/*NOMH*/", str(_NOMINAL[1])))
    html = ("<!doctype html><html><head><meta charset='utf-8'>"
            f"</head><body>{page}</body></html>")
    return {"html": html, "selected": picked, "table": filtered}
