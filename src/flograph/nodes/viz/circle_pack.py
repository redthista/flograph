"""Circle Pack

Nested bubbles: every group is a circle, every circle holds its members,
and area is the value. Where a treemap gives you rectangles that are easy
to measure and hard to like, circle packing gives you shape — one huge
customer inside an otherwise even region, a category that is really six
equal things, a long tail that looks like a long tail.

**Install the D3 web library once** from Tools ▸ Web Libraries. From then
on it draws from your own machine, offline.

Point **Group by** at one or more columns — that is the nesting, outermost
first (`region, city, store`) — and **Size by** at a number. Leave **Size
by** empty to size by row count, which is the right answer when the rows
*are* the thing being counted.

**Click a circle** to filter: its name goes to **selected** and **table**
narrows to the rows underneath it, at whatever level you clicked. Click the
same one again to clear.

Bubbles are labelled where the label fits; the rest carry their name in the
tooltip, because a circle too small for text is exactly the one you want to
hover.
"""
NODE = {
    "label": "Circle Pack",
    "category": "Viz",
    "version": "1.0",
    "card": "webview",
    "interactive": True,
    "inputs": [("table", "dataframe")],
    "outputs": [("html", "string"), ("selected", "any"),
                ("table", "dataframe")],
}
PARAMS = [
    {"name": "group_by", "type": "columns", "label": "Group by",
     "default": "", "placeholder": "outermost first, e.g. region, city"},
    {"name": "size_by", "type": "columns", "label": "Size by", "multi": False,
     "default": "", "placeholder": "blank counts rows"},
    {"name": "palette", "type": "choice", "label": "Palette",
     "options": ["cool", "warm", "mixed"], "default": "cool"},
    {"name": "on_click", "type": "choice", "label": "On click",
     "options": ["nothing", "select one", "select many"],
     "default": "select one"},
    {"name": "selected", "type": "string", "label": "Clicked circles",
     "default": "", "placeholder": '["north"] — blank keeps every row',
     "visible_when": {"on_click": ["select one", "select many"]}},
    {"name": "width", "type": "int", "label": "Width", "default": 460,
     "min": 200, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height", "default": 460,
     "min": 120, "max": 2000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

_PALETTES = {
    "cool": ["#1e3a8a", "#2563eb", "#38bdf8", "#67e8f9"],
    "warm": ["#7c2d12", "#ea580c", "#f59e0b", "#fde047"],
    "mixed": ["#2563eb", "#10b981", "#f59e0b", "#ef4444", "#a855f7"],
}

# Not an f-string — see the note in network_graph.py.
_PAGE = """
<style>
  html, body { margin: 0; height: 100%; background: #0b1220;
               font-family: system-ui, sans-serif; }
  #pack { width: 100%; height: 100%; }
  circle { cursor: pointer; }
  circle.picked { stroke: #f8fafc; stroke-width: 2.5px; }
  text { pointer-events: none; fill: #e2e8f0; text-anchor: middle;
         paint-order: stroke; stroke: rgba(2,6,23,.65); stroke-width: 2.5px; }
</style>
<svg id="pack"></svg>
<script>
  var TREE = /*TREE*/, RAMP = /*RAMP*/;
  var PICKED = /*PICKED*/, MODE = /*MODE*/, UNIT = /*UNIT*/;

  var svg = d3.select("#pack");
  var colour = d3.scaleOrdinal().range(RAMP);

  function draw() {
    var box = document.getElementById("pack").getBoundingClientRect();
    var size = Math.max(80, Math.min(box.width, box.height)) - 4;
    svg.attr("viewBox", "0 0 " + size + " " + size)
       .attr("width", box.width).attr("height", box.height);
    svg.selectAll("*").remove();

    var root = d3.hierarchy(TREE)
        .sum(function (d) { return d.value || 0; })
        .sort(function (a, b) { return b.value - a.value; });
    d3.pack().size([size, size]).padding(3)(root);

    var node = svg.selectAll("g")
      .data(root.descendants().filter(function (d) { return d.depth > 0; }))
      .join("g")
        .attr("transform", function (d) {
          return "translate(" + d.x + "," + d.y + ")"; });

    node.append("circle")
        .attr("r", function (d) { return d.r; })
        .attr("fill", function (d) { return colour(d.depth); })
        .attr("fill-opacity", function (d) { return d.children ? 0.25 : 0.85; })
        .attr("class", function (d) {
          return PICKED.indexOf(d.data.name) !== -1 ? "picked" : null; })
        .on("click", function (event, d) {
          event.stopPropagation();
          if (MODE === "nothing") { return; }
          var name = d.data.name;
          if (MODE === "select many") {
            var at = PICKED.indexOf(name);
            if (at === -1) { PICKED.push(name); } else { PICKED.splice(at, 1); }
          } else {
            PICKED = (PICKED.length === 1 && PICKED[0] === name) ? [] : [name];
          }
          draw();
          flograph.select(PICKED);
        })
      .append("title")
        .text(function (d) {
          return d.data.name + " — " + d3.format(",")(d.value) + " " + UNIT; });

    // Only where it fits: a label wider than its circle is worse than none.
    node.filter(function (d) { return !d.children && d.r > 14; })
        .append("text")
        .attr("dy", "0.35em")
        .style("font-size", function (d) {
          return Math.min(12, d.r / 2.2) + "px"; })
        .text(function (d) {
          var room = Math.floor(d.r / 3.2);
          return d.data.name.length > room
            ? d.data.name.slice(0, Math.max(1, room - 1)) + "…"
            : d.data.name; });
  }

  draw();
  window.addEventListener("resize", draw);
</script>
"""


def run(ctx, table):
    import json

    import pandas as pd

    from flograph.core.controls import selected_values
    from flograph.weblibs import markup

    params = ctx.params
    raw_groups = str(params.get("group_by", "") or "")
    groups = [part.strip() for part in raw_groups.split(",") if part.strip()]
    if not groups:
        raise ValueError("set 'Group by' — circle packing needs at least one "
                         "column to nest by")
    for column in groups:
        if column not in table.columns:
            available = ", ".join(str(c) for c in table.columns)
            raise ValueError(f"Group by column {column!r} is not in the table "
                             f"(has: {available})")

    size_by = str(params.get("size_by", "") or "").strip()
    if size_by and size_by not in table.columns:
        raise ValueError(f"Size by column {size_by!r} is not in the table")

    frame = table.copy()
    for column in groups:
        frame[column] = frame[column].astype(str).str.strip()
    if size_by:
        frame["_value"] = pd.to_numeric(frame[size_by], errors="coerce")
        frame = frame[frame["_value"].notna() & (frame["_value"] > 0)]
        unit = size_by
    else:
        frame["_value"] = 1.0
        unit = "rows"
    if frame.empty:
        raise ValueError(
            f"nothing to draw — no row had a positive number in {size_by!r}"
            if size_by else "nothing to draw — the table is empty")

    totals = frame.groupby(groups, as_index=False)["_value"].sum()

    # A dict tree, built level by level. Circle packing wants leaves to
    # carry the value and branches to carry only children — d3's .sum()
    # rolls the branches up, and giving a branch its own value as well
    # would double-count it.
    root: dict = {"name": "all", "children": []}
    index: dict = {(): root}
    # Positional, not by attribute: `totals` is the grouping columns then
    # the value, and itertuples renames anything with a space in it.
    for row in totals.itertuples(index=False, name=None):
        path = tuple(str(value) for value in row[:len(groups)])
        parent = root
        for depth, _ in enumerate(path):
            key = path[:depth + 1]
            if key not in index:
                child = {"name": key[-1]}
                if depth < len(path) - 1:
                    child["children"] = []
                index[key] = child
                parent.setdefault("children", []).append(child)
            parent = index[key]
        parent["value"] = round(float(row[-1]), 4)

    ctx.log(f"{len(totals)} leaf circle(s) over {len(groups)} level(s), "
            f"{totals['_value'].sum():g} {unit} total")

    picked = selected_values(params.get("selected", ""))
    mode = str(params.get("on_click", "select one") or "nothing")
    filtered = table
    if mode != "nothing" and picked:
        wanted = set(picked)
        # A click can land on any level, so a row matches if the name shows
        # up in any of the grouping columns.
        keep = None
        for column in groups:
            hit = table[column].astype(str).str.strip().isin(wanted)
            keep = hit if keep is None else (keep | hit)
        filtered = table[keep]
        ctx.log(f"clicked {', '.join(picked)}: kept {len(filtered)} of "
                f"{len(table)} rows")

    ramp = _PALETTES.get(str(params.get("palette", "cool")), _PALETTES["cool"])
    page = (_PAGE
            .replace("/*TREE*/", json.dumps(root))
            .replace("/*RAMP*/", json.dumps(ramp))
            .replace("/*PICKED*/", json.dumps(picked))
            .replace("/*MODE*/", json.dumps(mode))
            .replace("/*UNIT*/", json.dumps(unit)))
    html = ("<!doctype html><html><head><meta charset='utf-8'>"
            f"{markup('d3')}</head><body>{page}</body></html>")
    return {"html": html, "selected": picked, "table": filtered}
