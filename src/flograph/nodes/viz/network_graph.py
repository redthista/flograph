"""Network Graph

An edge list becomes a real network you can drag, zoom and click — who
emails whom, which service calls which, which parts share a supplier, how a
document set cites itself. Drawn with Cytoscape, the library built for
exactly this, so the layout untangles itself instead of being a hairball.

**Install the Cytoscape web library once** from Tools ▸ Web Libraries. From
then on it draws from your own machine, offline.

Give it a table with a **From** and a **To** column — one row per link.
Everything else is optional: **Label** puts text on the arrows, **Weight**
makes busy links thicker, and a second table wired into **nodes** can carry
a **Size by** and **Colour by** column for the circles themselves.

**Click a node** and it filters: the node's name goes to **selected**, and
**table** narrows to the rows touching it — one hop of the network, ready
for a Show Table beside it. Click it again to clear. Set **On click** to
*nothing* for a picture that doesn't answer back.

**Layout** is how the graph arranges itself. `cose` is the force-directed
one you usually want (connected things drift together); `concentric` rings
the busiest nodes in the middle; `breadthfirst` is for hierarchies;
`circle` and `grid` are tidy rather than meaningful.
"""
NODE = {
    "label": "Network Graph",
    "category": "Viz",
    "version": "1.1",
    "card": "webview",
    "interactive": True,
    "inputs": [("edges", "dataframe"),
               ("nodes", "dataframe", {"optional": True})],
    "outputs": [("html", "string"), ("selected", "any"),
                ("table", "dataframe")],
}
PARAMS = [
    {"name": "source", "type": "columns", "label": "From", "multi": False,
     "default": ""},
    {"name": "target", "type": "columns", "label": "To", "multi": False,
     "default": ""},
    {"name": "label", "type": "columns", "label": "Label", "multi": False,
     "default": "", "placeholder": "text on the arrows"},
    {"name": "weight", "type": "columns", "label": "Weight", "multi": False,
     "default": "", "placeholder": "thicker arrows for bigger numbers"},
    {"name": "layout", "type": "choice", "label": "Layout",
     "options": ["cose", "concentric", "breadthfirst", "circle", "grid"],
     "default": "cose"},
    {"name": "node_key", "type": "columns", "label": "Node id", "multi": False,
     "default": "", "placeholder": "in the 'nodes' table"},
    {"name": "size_by", "type": "columns", "label": "Size by", "multi": False,
     "default": "", "placeholder": "in the 'nodes' table"},
    {"name": "colour_by", "type": "columns", "label": "Colour by",
     "multi": False, "default": "",
     "placeholder": "in the 'nodes' table"},
    {"name": "directed", "type": "bool", "label": "Arrows", "default": True},
    {"name": "on_click", "type": "choice", "label": "On click",
     "options": ["nothing", "select one", "select many"],
     "default": "select one"},
    {"name": "selected", "type": "string", "label": "Clicked nodes",
     "default": "", "placeholder": 'e.g. ["CEO"] — blank keeps every row',
     "visible_when": {"on_click": ["select one", "select many"]}},
    {"name": "width", "type": "int", "label": "Width", "default": 520,
     "min": 200, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height", "default": 420,
     "min": 120, "max": 2000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

# Kept out of an f-string on purpose: this is a page full of braces, and
# doubling every one of them to satisfy str.format is how a working script
# turns into an unreadable one. The placeholders are substituted below.
_PAGE = """
<style>
  html, body { margin: 0; height: 100%; background: #0b1220;
               overflow: hidden; }
  #cy { width: 100%; height: 100%; }
  #shot { display: none; width: 100%; height: 100%; object-fit: contain; }
  #hint { position: absolute; left: 8px; bottom: 6px; font: 11px system-ui;
          color: #64748b; pointer-events: none; }
  /* Cytoscape draws on a canvas, and Chromium's print rendering drops
     canvas content — which is how a report takes its picture of a card, so
     one would photograph an empty box. The graph keeps a picture of itself
     alongside and print media shows that instead. The hint goes too: it is
     an instruction for a live card, not something to put on paper. */
  @media print {
    #cy, #hint { display: none; }
    #shot { display: block; }
  }
</style>
<div id="cy"></div>
<img id="shot" alt="">
<div id="hint"></div>
<script>
  var ELEMENTS = /*ELEMENTS*/;
  var PICKED = /*PICKED*/, MODE = /*MODE*/, LAYOUT = /*LAYOUT*/;
  var DIRECTED = /*DIRECTED*/;

  var cy = cytoscape({
    container: document.getElementById("cy"),
    elements: ELEMENTS,
    layout: {name: LAYOUT, animate: false, padding: 18},
    style: [
      {selector: "node", style: {
        "background-color": "data(colour)",
        "width": "data(size)", "height": "data(size)",
        "label": "data(label)", "font-size": 10, "color": "#cbd5e1",
        "text-valign": "center", "text-halign": "right",
        "text-margin-x": 4, "min-zoomed-font-size": 7}},
      {selector: "edge", style: {
        "width": "data(weight)", "line-color": "#334155",
        "curve-style": "bezier", "opacity": 0.85,
        "label": "data(label)", "font-size": 8, "color": "#64748b",
        "text-rotation": "autorotate",
        "target-arrow-shape": DIRECTED ? "triangle" : "none",
        "target-arrow-color": "#334155", "arrow-scale": 0.8}},
      {selector: ".picked", style: {
        "background-color": "#f59e0b", "border-width": 3,
        "border-color": "#fbbf24", "z-index": 10}},
      {selector: ".faded", style: {"opacity": 0.15}}
    ]
  });

  var shot = document.getElementById("shot");
  function capture() {
    // Redrawn whenever the picture would change, so what a report prints is
    // the graph as it stands — selection and all — not as it first loaded.
    try {
      shot.src = cy.png({full: true, scale: 2, bg: "#0b1220"});
    } catch (err) {
      // A graph too large to rasterise still renders live; only the
      // printed copy is lost, and a broken card would be worse.
    }
  }
  cy.ready(capture);
  cy.on("layoutstop", capture);

  function paint() {
    cy.elements().removeClass("picked faded");
    if (!PICKED.length) { capture(); return; }
    var chosen = cy.nodes().filter(function (n) {
      return PICKED.indexOf(n.id()) !== -1; });
    if (!chosen.length) { capture(); return; }
    // Everything not touching the selection dims, so one hop of a busy
    // network reads at a glance rather than having to be traced.
    var near = chosen.closedNeighborhood();
    cy.elements().difference(near).addClass("faded");
    chosen.addClass("picked");
    capture();
  }
  paint();

  if (MODE !== "nothing") {
    cy.on("tap", "node", function (event) {
      var id = event.target.id();
      if (MODE === "select many") {
        var at = PICKED.indexOf(id);
        if (at === -1) { PICKED.push(id); } else { PICKED.splice(at, 1); }
      } else {
        PICKED = (PICKED.length === 1 && PICKED[0] === id) ? [] : [id];
      }
      paint();
      flograph.select(PICKED);
    });
    // Tapping the background clears, the way every map and chart behaves.
    cy.on("tap", function (event) {
      if (event.target === cy && PICKED.length) {
        PICKED = []; paint(); flograph.select([]);
      }
    });
    var hint = document.getElementById("hint");
    hint.textContent = "Click a node to filter";
  }
</script>
"""


def _text(value) -> str:
    return "" if value is None else str(value)


def run(ctx, edges, nodes=None):
    import json

    from flograph.core.controls import selected_values
    from flograph.weblibs import markup

    params = ctx.params
    source = str(params.get("source", "") or "").strip()
    target = str(params.get("target", "") or "").strip()
    if not source or not target:
        raise ValueError("set 'From' and 'To' — a network needs one row "
                         "per link between two things")
    for name, column in (("From", source), ("To", target)):
        if column not in edges.columns:
            available = ", ".join(str(c) for c in edges.columns)
            raise ValueError(
                f"{name} column {column!r} is not in the table "
                f"(has: {available})")

    label = str(params.get("label", "") or "").strip()
    weight = str(params.get("weight", "") or "").strip()
    picked = selected_values(params.get("selected", ""))
    mode = str(params.get("on_click", "select one") or "nothing")

    # ---- edges, and the node set they imply -----------------------------
    weights = []
    if weight and weight in edges.columns:
        for raw in edges[weight]:
            try:
                weights.append(float(raw))
            except (TypeError, ValueError):
                weights.append(0.0)
        widest = max(weights) if weights else 0.0
    else:
        widest = 0.0

    seen: dict = {}
    edge_elements = []
    for index, (_, row) in enumerate(edges.iterrows()):
        a, b = _text(row[source]).strip(), _text(row[target]).strip()
        if not a or not b:
            continue                      # a link to nothing is not a link
        seen.setdefault(a, None)
        seen.setdefault(b, None)
        # `label` is always present, even empty: the stylesheet maps
        # data(label) for every edge, and Cytoscape warns once per element
        # for a mapping whose data field is missing.
        data = {"id": f"e{index}", "source": a, "target": b, "weight": 1.4,
                "label": ""}
        if label and label in edges.columns:
            data["label"] = _text(row[label])
        if widest > 0:
            # 1..6 px: a weight column is about relative traffic, and a
            # linear map of raw values makes one outlier hide everything.
            data["weight"] = round(1.0 + 5.0 * (weights[index] / widest), 2)
        edge_elements.append({"data": data})

    if not edge_elements:
        raise ValueError("no links to draw — every row had a blank end")

    # ---- node attributes, if a second table supplied any -----------------
    sizes: dict = {}
    colours: dict = {}
    if nodes is not None and len(nodes):
        key = str(params.get("node_key", "") or "").strip()
        if not key:
            key = str(nodes.columns[0])
        if key not in nodes.columns:
            raise ValueError(f"Node id column {key!r} is not in the "
                             f"'nodes' table")
        size_by = str(params.get("size_by", "") or "").strip()
        colour_by = str(params.get("colour_by", "") or "").strip()
        if size_by and size_by in nodes.columns:
            values = {}
            for _, row in nodes.iterrows():
                try:
                    values[_text(row[key])] = float(row[size_by])
                except (TypeError, ValueError):
                    continue
            biggest = max(values.values()) if values else 0.0
            if biggest > 0:
                sizes = {name: round(14 + 34 * (value / biggest))
                         for name, value in values.items()}
        if colour_by and colour_by in nodes.columns:
            palette = ["#2563eb", "#10b981", "#f59e0b", "#ef4444", "#a855f7",
                       "#14b8a6", "#f472b6", "#84cc16"]
            order: dict = {}
            for _, row in nodes.iterrows():
                group = _text(row[colour_by])
                order.setdefault(group, palette[len(order) % len(palette)])
                colours[_text(row[key])] = order[group]

    node_elements = [{"data": {
        "id": name,
        "label": name,
        "size": sizes.get(name, 22),
        "colour": colours.get(name, "#2563eb"),
    }} for name in seen]

    ctx.log(f"{len(node_elements)} nodes, {len(edge_elements)} links")

    # ---- the filtered table ----------------------------------------------
    filtered = edges
    if mode != "nothing" and picked:
        wanted = set(picked)
        keep = [bool({_text(row[source]).strip(),
                      _text(row[target]).strip()} & wanted)
                for _, row in edges.iterrows()]
        filtered = edges[keep]
        ctx.log(f"clicked {', '.join(picked)}: kept {len(filtered)} of "
                f"{len(edges)} links")

    page = (_PAGE
            .replace("/*ELEMENTS*/", json.dumps(
                {"nodes": node_elements, "edges": edge_elements}))
            .replace("/*PICKED*/", json.dumps(picked))
            .replace("/*MODE*/", json.dumps(mode))
            .replace("/*LAYOUT*/", json.dumps(
                str(params.get("layout", "cose") or "cose")))
            .replace("/*DIRECTED*/",
                     "true" if params.get("directed", True) else "false"))
    html = ("<!doctype html><html><head><meta charset='utf-8'>"
            f"{markup('cytoscape')}</head><body>{page}</body></html>")
    return {"html": html, "selected": picked, "table": filtered}
