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

**Click a band or a stage** to filter: the name goes to **selected** and
**table** narrows to the rows touching it.
"""
NODE = {
    "label": "Sankey Flow",
    "category": "Viz",
    "version": "1.0",
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
    {"name": "on_click", "type": "choice", "label": "On click",
     "options": ["nothing", "select one", "select many"],
     "default": "select one"},
    {"name": "selected", "type": "string", "label": "Clicked stages",
     "default": "", "placeholder": '["screened"] — blank keeps every row',
     "visible_when": {"on_click": ["select one", "select many"]}},
    {"name": "width", "type": "int", "label": "Width", "default": 560,
     "min": 200, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height", "default": 380,
     "min": 120, "max": 2000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

_PALETTE = ["#2563eb", "#10b981", "#f59e0b", "#ef4444", "#a855f7",
            "#14b8a6", "#f472b6", "#84cc16", "#38bdf8", "#fb923c"]

# Not an f-string — see the note in network_graph.py.
_PAGE = """
<style>
  html, body { margin: 0; height: 100%; background: #0b1220; }
  #chart { width: 100%; height: 100%; }
</style>
<div id="chart"></div>
<script>
  var NODES = /*NODES*/, LINKS = /*LINKS*/, ORIENT = /*ORIENT*/;
  var PICKED = /*PICKED*/, MODE = /*MODE*/;

  var chart = echarts.init(document.getElementById("chart"));
  function draw() {
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {trigger: "item", triggerOn: "mousemove"},
      series: [{
        type: "sankey", orient: ORIENT,
        left: 12, right: 12, top: 14, bottom: 14,
        nodeGap: 10, nodeWidth: 14,
        emphasis: {focus: "adjacency"},
        data: NODES.map(function (n) {
          var on = PICKED.indexOf(n.name) !== -1;
          return {name: n.name, itemStyle: {
            color: n.colour,
            borderColor: on ? "#f8fafc" : "transparent",
            borderWidth: on ? 2 : 0}};
        }),
        links: LINKS,
        label: {color: "#cbd5e1", fontSize: 11},
        lineStyle: {color: "gradient", opacity: PICKED.length ? 0.25 : 0.45}
      }]
    });
  }
  draw();
  window.addEventListener("resize", function () { chart.resize(); });

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
    page = (_PAGE
            .replace("/*NODES*/", json.dumps(nodes))
            .replace("/*LINKS*/", json.dumps(links))
            .replace("/*ORIENT*/", json.dumps(orient))
            .replace("/*PICKED*/", json.dumps(picked))
            .replace("/*MODE*/", json.dumps(mode)))
    html = ("<!doctype html><html><head><meta charset='utf-8'>"
            f"{markup('echarts')}</head><body>{page}</body></html>")
    return {"html": html, "selected": picked, "table": filtered}
