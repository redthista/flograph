"""Sankey Flow

Where things go, drawn as bands whose width is how many went that way.
Budget from source to department, applicants through a hiring funnel,
traffic from channel to page to outcome, energy in to losses out. The
question a Sankey answers that a bar chart cannot is *where did the rest of
it go* — the bands have to add up, so a leak is visible rather than absent.

**Install the Apache ECharts web library once** from Tools ▸ Web Libraries.
From then on it draws from your own machine, offline.

One row per flow: **From**, **To**, and **Value**. Rows sharing a From/To
pair are added together, so you can hand it raw transactions.

**More than two stages** need nothing special — just more rows. A row
`applied → screened` and a row `screened → offer` chain into one diagram
because they share the name `screened`. That is also the one thing to get
right: **stage names must match exactly**, and a name that appears on both
sides of the same row (`a → a`) is dropped, because a loop has no width.

**One shared ending makes a messy picture.** If every stage drops out into
a single `rejected`, that node lands in the final column and each stage
drags a band across the whole diagram to reach it — correct, and hard to
read. Give each stage its own ending (`screened out`, `not progressed`,
`no offer`) and the crossings go away; you also get to see *where* people
left, which was the question.

**Stage placement** decides which column a stage sits in when it could sit
in several. `even` spreads them across the width (the usual choice).
`early` puts each one as soon as it can go, which is what makes a funnel
look like a funnel — a stage's drop-out sits beside the stage it left
rather than at the far edge. `late` pushes everything as far right as it
will go.

**Click a band or a stage** to filter: the name goes to **selected** and
**table** narrows to the rows touching it.
"""
NODE = {
    "label": "Sankey Flow",
    "category": "Viz",
    "version": "1.2",
    "card": "webview",
    "interactive": True,
    "inputs": [("table", "dataframe")],
    "outputs": [("html", "string"), ("selected", "any"),
                ("table", "dataframe")],
}
PARAMS = [
    {"name": "source", "type": "columns", "label": "From", "multi": False,
     "default": ""},
    {"name": "target", "type": "columns", "label": "To", "multi": False,
     "default": ""},
    {"name": "value", "type": "columns", "label": "Value", "multi": False,
     "default": "", "placeholder": "blank counts rows"},
    {"name": "orient", "type": "choice", "label": "Direction",
     "options": ["left to right", "top to bottom"],
     "default": "left to right"},
    {"name": "align", "type": "choice", "label": "Stage placement",
     "options": ["even", "early", "late"], "default": "even"},
    {"name": "on_click", "type": "choice", "label": "On click",
     "options": ["nothing", "select one", "select many"],
     "default": "select one"},
    {"name": "selected", "type": "string", "label": "Clicked stages",
     "default": "", "placeholder": '["screened"] — blank keeps every row',
     "visible_when": {"on_click": ["select one", "select many"]}},
    {"name": "width", "type": "int", "label": "Width", "default": 560,
     "min": 260, "max": 4000, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height", "default": 380,
     "min": 200, "max": 4000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

_PALETTE = ["#2563eb", "#10b981", "#f59e0b", "#ef4444", "#a855f7",
            "#14b8a6", "#f472b6", "#84cc16", "#38bdf8", "#fb923c"]

#: The size the chart is laid out at before it is scaled to fit the
#: card. It matches this node's default card size, so an unresized
#: card is drawn 1:1; it is a constant rather than the width/height
#: params because those are cosmetic and run() must not depend on
#: them (see TestCardSizeIsPresentation).
_NOMINAL = (560, 380)

# Not an f-string — see the note in network_graph.py.
_PAGE = """
<style>
  html, body { margin: 0; height: 100%; background: #0b1220;
               overflow: hidden; }
  #chart { width: 100%; height: 100%; }
</style>
<div id="chart"></div>
<script>
  var NODES = /*NODES*/, LINKS = /*LINKS*/, ORIENT = /*ORIENT*/;
  var ALIGN = /*ALIGN*/;
  var NOMW = /*NOMW*/, NOMH = /*NOMH*/;
  var PICKED = /*PICKED*/, MODE = /*MODE*/;

  var el = document.getElementById("chart");

  function room() {
    // The box this chart has to fill, or null when it has none. Every
    // measurement comes back 0 wherever the view is not on screen — which
    // is exactly how a report takes its picture of a card — and ECharts
    // draws nothing at all at 0x0.
    var w = el.clientWidth, h = el.clientHeight;
    return (w > 0 && h > 0) ? {width: w, height: h} : null;
  }

  // SVG, not canvas — a report photographs a card through printToPdf, and
  // Chromium's print rendering drops canvas content (the page's text comes
  // through and the chart is a blank rectangle). SVG survives it.
  var space = room();
  var chart = echarts.init(el, null, {
    renderer: "svg",
    width: space ? space.width : NOMW,
    height: space ? space.height : NOMH
  });
  function draw() {
    chart.setOption({
      backgroundColor: "transparent",
      // No entry animation. A report photographs the card a fraction of a
      // second after it loads, and a sankey animates in over a full second
      // behind an expanding clip — so the picture came out empty. Drawing
      // at once is also what you want from a chart you are reading rather
      // than presenting.
      animation: false,
      tooltip: {trigger: "item", triggerOn: "mousemove"},
      series: [{
        type: "sankey", orient: ORIENT, nodeAlign: ALIGN,
        // Room for the last column's labels, which ECharts draws *outside*
        // the node — with an even margin they run off the edge and the
        // final stage is the one you most want to read.
        left: 12, right: ORIENT === "vertical" ? 14 : 92,
        top: 14, bottom: ORIENT === "vertical" ? 40 : 14,
        // A gap wide enough that two small stages landing beside each
        // other keep their labels apart — the tail of a funnel is all
        // small stages, and they collided.
        nodeGap: 16, nodeWidth: 14,
        emphasis: {focus: "adjacency"},
        data: NODES.map(function (n) {
          var on = PICKED.indexOf(n.name) !== -1;
          return {name: n.name, itemStyle: {
            color: n.colour,
            borderColor: on ? "#f8fafc" : "transparent",
            borderWidth: on ? 2 : 0}};
        }),
        links: LINKS,
        // ECharts draws a stage's label beside it, which puts it straight
        // on top of the bands flowing past. An outline in the background
        // colour lifts it off them — the same trick the bubbles use — so a
        // name stays readable wherever it happens to land.
        label: {color: "#e2e8f0", fontSize: 11,
                textBorderColor: "rgba(2,6,23,0.85)", textBorderWidth: 3},
        lineStyle: {color: "gradient", opacity: PICKED.length ? 0.25 : 0.45}
      }]
    });
    rescale();
  }

  function rescale() {
    // Only when there was no box to measure. The chart was then laid out
    // at its nominal size, so give the SVG a viewBox and let it scale like
    // any other vector — that is what makes a report's picture come out
    // right. Where there *is* a box, ECharts has already filled it and a
    // viewBox would letterbox the drawing inside its own tile.
    if (room()) { return; }
    var svg = document.querySelector("#chart svg");
    if (!svg) { return; }
    svg.setAttribute("viewBox", "0 0 " + NOMW + " " + NOMH);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    svg.style.width = "100%";
    svg.style.height = "100%";
    svg.style.display = "block";
    if (svg.parentNode && svg.parentNode.id !== "chart") {
      svg.parentNode.style.width = "100%";
      svg.parentNode.style.height = "100%";
    }
  }

  function fit() {
    // The card or tile was resized: lay the chart out again at the new
    // size rather than scaling the old drawing, so text stays the size it
    // was designed at. Drops any viewBox left over from a nominal render.
    var space = room();
    if (!space) { return; }
    var svg = document.querySelector("#chart svg");
    if (svg) { svg.removeAttribute("viewBox"); }
    chart.resize(space);
  }
  window.addEventListener("resize", fit);
  draw();

  if (MODE !== "nothing") {
    chart.on("click", function (params) {
      // A band reports both ends; a stage reports its name. Either way the
      // useful answer is "the names you just pointed at".
      var names = (params.dataType === "edge")
        ? [params.data.source, params.data.target]
        : [params.name];
      if (MODE === "select many") {
        names.forEach(function (name) {
          var at = PICKED.indexOf(name);
          if (at === -1) { PICKED.push(name); } else { PICKED.splice(at, 1); }
        });
      } else {
        var same = names.length === PICKED.length
          && names.every(function (n) { return PICKED.indexOf(n) !== -1; });
        PICKED = same ? [] : names;
      }
      draw();
      flograph.select(PICKED);
    });
  }
</script>
"""


def run(ctx, table):
    import json

    import pandas as pd

    from flograph.core.controls import selected_values
    from flograph.weblibs import markup

    params = ctx.params
    source = str(params.get("source", "") or "").strip()
    target = str(params.get("target", "") or "").strip()
    if not source or not target:
        raise ValueError("set 'From' and 'To' — a Sankey needs one row per "
                         "flow between two stages")
    for name, column in (("From", source), ("To", target)):
        if column not in table.columns:
            available = ", ".join(str(c) for c in table.columns)
            raise ValueError(f"{name} column {column!r} is not in the table "
                             f"(has: {available})")

    value_column = str(params.get("value", "") or "").strip()
    if value_column and value_column not in table.columns:
        raise ValueError(f"Value column {value_column!r} is not in the table")

    frame = pd.DataFrame({
        "source": table[source].astype(str).str.strip(),
        "target": table[target].astype(str).str.strip(),
    })
    if value_column:
        frame["value"] = pd.to_numeric(table[value_column], errors="coerce")
    else:
        frame["value"] = 1.0

    usable = ((frame["source"] != "") & (frame["target"] != "")
              & (frame["source"] != frame["target"])
              & frame["value"].notna() & (frame["value"] > 0))
    dropped = int((~usable).sum())
    frame = frame[usable]
    if frame.empty:
        raise ValueError(
            "no flows to draw — every row was blank, self-referring, or had "
            "no positive value")
    if dropped:
        ctx.log(f"{dropped} row(s) skipped (blank, a loop, or no value)")

    totals = frame.groupby(["source", "target"], as_index=False)["value"].sum()
    names = list(dict.fromkeys(
        list(totals["source"]) + list(totals["target"])))
    nodes = [{"name": name,
              "colour": _PALETTE[index % len(_PALETTE)]}
             for index, name in enumerate(names)]
    links = [{"source": row.source, "target": row.target,
              "value": round(float(row.value), 4)}
             for row in totals.itertuples()]
    ctx.log(f"{len(nodes)} stages, {len(links)} flows, "
            f"{totals['value'].sum():g} total")

    picked = selected_values(params.get("selected", ""))
    mode = str(params.get("on_click", "select one") or "nothing")
    filtered = table
    if mode != "nothing" and picked:
        wanted = set(picked)
        keep = (table[source].astype(str).str.strip().isin(wanted)
                | table[target].astype(str).str.strip().isin(wanted))
        filtered = table[keep]
        ctx.log(f"clicked {', '.join(picked)}: kept {len(filtered)} of "
                f"{len(table)} rows")

    orient = ("vertical"
              if str(params.get("orient", "")) == "top to bottom"
              else "horizontal")
    # ECharts' nodeAlign, named for what it does to the picture rather than
    # for the library's word. "early" is what makes a funnel look like a
    # funnel: a stage's drop-out sits beside the stage it left, instead of
    # being parked in the final column with a band dragged across the whole
    # diagram to reach it.
    align = {"early": "left", "late": "right"}.get(
        str(params.get("align", "even")), "justify")
    page = (_PAGE
            .replace("/*NODES*/", json.dumps(nodes))
            .replace("/*LINKS*/", json.dumps(links))
            .replace("/*ORIENT*/", json.dumps(orient))
            .replace("/*ALIGN*/", json.dumps(align))
            .replace("/*PICKED*/", json.dumps(picked))
            .replace("/*MODE*/", json.dumps(mode))
            .replace("/*NOMW*/", str(_NOMINAL[0]))
            .replace("/*NOMH*/", str(_NOMINAL[1])))
    html = ("<!doctype html><html><head><meta charset='utf-8'>"
            f"{markup('echarts')}</head><body>{page}</body></html>")
    return {"html": html, "selected": picked, "table": filtered}
