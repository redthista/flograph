"""Show Web View

A template for building a visual node from *any* Python library. It renders
whatever run() returns into an embedded web view (a real Chromium browser), so
you can drive it from any library that can produce HTML.

Drop it on the canvas, right-click and choose Edit Code, then swap the run()
body for your library. The rule is simple: **return HTML** — either

  • a raw HTML string, or
  • any object with a `to_html()` method (e.g. a Plotly figure), or
  • any object with a `_repr_html_()` method (folium maps, Altair charts,
    pandas Stylers, IPython HTML, and most notebook-friendly libraries).

Install third-party libraries from Tools > Manage Packages; import them inside
run() (never at the top of the file) so the node still loads when they're
absent.

**The page can talk back.** Because this node declares
`NODE["interactive"] = True`, its page gets a `flograph` object in JavaScript:

    flograph.select(["north", "south"])   // write the "selected" param
    flograph.set("depth", 3)              // write any param this node declares
    flograph.ready(fn)                    // fn runs once the channel is live
    flograph.connected                    // false in a plain browser

A write commits the param (one Ctrl+Z undoes it) and re-runs this node and
everything downstream — so clicking inside your visual filters the rest of
the board, exactly as a Slicer tick does. A page may only write params this
node actually declares in PARAMS; anything else is reported in the status bar
rather than applied.

`flograph.set` is a no-op outside the app, so the same page still works in
Open in Browser and in an exported file — it just isn't live there.
"""

# The "card": "webview" marker is what gives this node the embedded web view —
# it travels with the code, so a copy you Save as a user node keeps the view.
# "interactive" is what lets that page write back; drop it and the page still
# renders, it just can't reach the graph. Ports are (name, type) tuples; the
# input is optional so the node also works standalone. Valid port types: any,
# dataframe, series, number, string, bool, object, figure.
NODE = {
    "label": "Show Web View",
    "category": "Viz",
    "version": "1.1",
    "card": "webview",
    "interactive": True,
    "inputs": [("data", "any", {"optional": True})],
    "outputs": [("view", "object"), ("selected", "any")],
}

# Widgets shown in the properties panel; values arrive via ctx.params. Width,
# height and scale drive the card's size on the canvas.
PARAMS = [
    {"name": "title", "type": "string", "label": "Title", "default": ""},
    # What the page writes through flograph.select(). Kept visible rather than
    # hidden: when a visual you are building isn't filtering what you expect,
    # the first question is what it actually sent, and this is the answer.
    {"name": "selected", "type": "string", "label": "Selected values",
     "default": "",
     "placeholder": 'written by flograph.select(), e.g. ["north"]'},
    {"name": "width", "type": "int", "label": "Width",
     "default": 420, "min": 260, "max": 4000, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 320, "min": 200, "max": 4000, "cosmetic": True},
    # Cosmetic: run() never reads it — the zoom is applied to the card, to
    # the HTML this node already produced.
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400, "cosmetic": True},
]


def run(ctx, data=None):
    # ---- swap everything below for your library ---------------------------
    # Examples (return the value directly — the card coerces it to HTML):
    #
    #   import plotly.express as px
    #   return px.line(data, y=data.columns)          # object.to_html()
    #
    #   import folium
    #   m = folium.Map(location=[54.6, -3.0], zoom_start=6)
    #   return m                                        # object._repr_html_()
    #
    #   import altair as alt
    #   return alt.Chart(data).mark_bar().encode(x="a", y="b")
    #
    # The default body is a working round trip: it draws one chip per value,
    # each of which calls flograph.select() when clicked. Click one and watch
    # "Selected values" change in the properties panel — that is the whole
    # interactive contract, in a page you can read.
    import html as html_mod
    import json

    from flograph.core.controls import selected_values

    title = ctx.params["title"].strip() or "Show Web View"
    picked = selected_values(ctx.params.get("selected", ""))

    if data is not None and hasattr(data, "columns") and len(data.columns):
        column = str(data.columns[0])
        values = [str(v) for v in data[column].dropna().unique()[:12]]
        source = f"first column, <code>{html_mod.escape(column)}</code>"
    else:
        values = ["north", "south", "east", "west"]
        source = "a sample — connect a table to use its first column"

    chips = "".join(
        f'<button class="chip{" on" if v in picked else ""}" '
        f"onclick='pick({json.dumps(v)})'>{html_mod.escape(v)}</button>"
        for v in values)
    ctx.log(f"rendered {len(values)} values; {len(picked)} selected")

    page = f"""
    <style>
      body {{ font-family: system-ui, sans-serif; padding: 20px; color: #111827;
              line-height: 1.5; }}
      h2 {{ margin: 0 0 4px; font-size: 17px; }}
      p {{ color: #6b7280; margin: 0 0 14px; font-size: 13px; }}
      .chip {{ font: inherit; font-size: 13px; padding: 5px 12px; margin: 0 6px 6px 0;
               border: 1px solid #d1d5db; border-radius: 999px; background: #fff;
               color: #374151; cursor: pointer; }}
      .chip:hover {{ border-color: #9ca3af; }}
      .chip.on {{ background: #2563eb; border-color: #2563eb; color: #fff; }}
      .hint {{ margin-top: 14px; font-size: 12px; color: #9ca3af; }}
    </style>
    <h2>{html_mod.escape(title)}</h2>
    <p>Click to filter — {source}.</p>
    <div>{chips}</div>
    <p class="hint" id="hint"></p>
    <script>
      var picked = {json.dumps(picked)};
      function pick(value) {{
        var at = picked.indexOf(value);
        if (at === -1) {{ picked.push(value); }} else {{ picked.splice(at, 1); }}
        // Writes this node's "selected" param and re-runs everything
        // downstream. The node re-renders from the new param, so the chips
        // come back in their new state on their own.
        flograph.select(picked);
      }}
      // connected is false until the channel finishes its handshake, so ask
      // ready() rather than reading it as the page loads.
      var hint = document.getElementById("hint");
      hint.textContent = "Outside flograph — clicks do nothing here.";
      flograph.ready(function () {{
        hint.textContent = "Live: clicks re-run the flow.";
      }});
    </script>
    """

    # Two outputs, so run() must return a dict keyed by port name: "view"
    # is the HTML the card renders, "selected" hands the ticked values on so
    # this node can drive a Filter Rows the way a Slicer does.
    return {"view": page, "selected": picked}
