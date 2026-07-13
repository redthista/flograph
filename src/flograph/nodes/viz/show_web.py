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
"""

# The "card": "webview" marker is what gives this node the embedded web view —
# it travels with the code, so a copy you Save as a user node keeps the view.
# Ports are (name, type) tuples; the input is optional so the node also works
# standalone. Valid port types: any, dataframe, series, number, string, bool,
# object, figure.
NODE = {
    "label": "Show Web View",
    "category": "Viz",
    "card": "webview",
    "inputs": [("data", "any", {"optional": True})],
    "outputs": [("view", "object")],
}

# Widgets shown in the properties panel; values arrive via ctx.params. Width,
# height and scale drive the card's size on the canvas.
PARAMS = [
    {"name": "title", "type": "string", "label": "Title", "default": ""},
    {"name": "width", "type": "int", "label": "Width",
     "default": 420, "min": 260, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 320, "min": 200, "max": 2000},
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400},
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
    # The default body just renders a sample HTML page so the node shows
    # something immediately.
    title = ctx.params["title"].strip() or "Show Web View"
    if data is None:
        detail = "Connect an input and edit this node's code to render it."
    else:
        detail = f"Received input of type <code>{type(data).__name__}</code>."
    ctx.log("rendered sample HTML page")
    return f"""
    <div style="font-family: system-ui, sans-serif; padding: 24px;
                line-height: 1.5; color: #111827;">
      <h2 style="margin: 0 0 8px;">{title}</h2>
      <p style="color: #4b5563; margin: 0 0 16px;">{detail}</p>
      <p style="margin: 0; font-size: 13px; color: #6b7280;">
        Return an HTML string, or any object with
        <code>to_html()</code> / <code>_repr_html_()</code>,
        to build a visual node from any Python library.
      </p>
    </div>
    """
