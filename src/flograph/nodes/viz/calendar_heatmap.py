"""Calendar Heatmap

A year of days as a grid of squares, each shaded by what happened that day —
the GitHub contribution chart, over your own data. Sales per day, incidents
per day, hours logged, orders shipped. It is the fastest way to see a
weekly rhythm, a quiet August, or the fortnight everything went wrong.

**Install the Apache ECharts web library once** from Tools ▸ Web Libraries.
From then on it draws from your own machine, offline.

Point **Date** at a date column and **Value** at a number, and pick how days
that appear more than once are combined — **Combine** defaults to *sum*,
which is what "per day" almost always means. Leave **Value** empty to count
rows instead, which is the right answer for a log of events.

**Year** picks which one to draw; leave it blank for the most recent year in
the data. A table spanning several years draws the one you asked for and
says in the log how many rows it left out.

**Click a day** and it filters: the date goes to **selected** and **table**
narrows to that day's rows. Click it again to clear.
"""
NODE = {
    "label": "Calendar Heatmap",
    "category": "Viz",
    "version": "1.1",
    "card": "webview",
    "interactive": True,
    "inputs": [("table", "dataframe")],
    "outputs": [("html", "string"), ("selected", "any"),
                ("table", "dataframe")],
}
PARAMS = [
    {"name": "date", "type": "columns", "label": "Date", "multi": False,
     "default": ""},
    {"name": "value", "type": "columns", "label": "Value", "multi": False,
     "default": "", "placeholder": "blank counts rows"},
    {"name": "combine", "type": "choice", "label": "Combine",
     "options": ["sum", "mean", "max", "min", "count"], "default": "sum"},
    {"name": "year", "type": "string", "label": "Year", "default": "",
     "placeholder": "blank = the latest year in the data"},
    {"name": "palette", "type": "choice", "label": "Palette",
     "options": ["green", "blue", "orange", "purple", "red"],
     "default": "green"},
    {"name": "on_click", "type": "choice", "label": "On click",
     "options": ["nothing", "select one", "select many"],
     "default": "select one"},
    {"name": "selected", "type": "string", "label": "Clicked days",
     "default": "", "placeholder": '["2026-03-04"] — blank keeps every row',
     "visible_when": {"on_click": ["select one", "select many"]}},
    {"name": "width", "type": "int", "label": "Width", "default": 620,
     "min": 260, "max": 4000, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height", "default": 220,
     "min": 200, "max": 4000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

#: Low-to-high ends for the colour ramp. Deliberately not a rainbow: a
#: calendar is read as "more or less", and a hue ramp makes that a lookup.
_RAMPS = {
    "green": ["#0f2417", "#22c55e"],
    "blue": ["#0d1b2e", "#3b82f6"],
    "orange": ["#2a1a0a", "#f59e0b"],
    "purple": ["#1c1230", "#a855f7"],
    "red": ["#2a1113", "#ef4444"],
}

#: The size the chart is laid out at before it is scaled to fit the
#: card. It matches this node's default card size, so an unresized
#: card is drawn 1:1; it is a constant rather than the width/height
#: params because those are cosmetic and run() must not depend on
#: them (see TestCardSizeIsPresentation).
_NOMINAL = (620, 220)

# Not an f-string: the page is mostly braces, and doubling every one to
# satisfy str.format is how a readable script stops being one.
_PAGE = """
<style>
  html, body { margin: 0; height: 100%; background: #0b1220;
               overflow: hidden; }
  #chart { width: 100%; height: 100%; }
</style>
<div id="chart"></div>
<script>
  var DATA = /*DATA*/, YEAR = /*YEAR*/, RAMP = /*RAMP*/;
  var NOMW = /*NOMW*/, NOMH = /*NOMH*/;
  var TOP = /*TOP*/, PICKED = /*PICKED*/, MODE = /*MODE*/, UNIT = /*UNIT*/;

  var el = document.getElementById("chart");

  function room() {
    // The box this chart has to fill, or null when it has none. Every
    // measurement comes back 0 wherever the view is not on screen — which
    // is exactly how a report takes its picture of a card — and ECharts
    // draws nothing at all at 0x0.
    var w = el.clientWidth, h = el.clientHeight;
    return (w > 0 && h > 0) ? {width: w, height: h} : null;
  }

  // SVG, not canvas. A report takes its picture of a card through
  // printToPdf, and Chromium's print rendering drops canvas content — the
  // page's own HTML and text come through and the chart is a blank
  // rectangle. SVG survives it, and stays sharp on paper besides.
  var space = room();
  var chart = echarts.init(el, null, {
    renderer: "svg",
    width: space ? space.width : NOMW,
    height: space ? space.height : NOMH
  });
  function draw() {
    chart.setOption({
      backgroundColor: "transparent",
      // No entry animation: a report photographs the card a fraction of a
      // second after it loads, and anything still animating is caught
      // half-drawn (a sankey came out entirely blank this way).
      animation: false,
      tooltip: {formatter: function (p) {
        return p.value[0] + "<br/><b>" + p.value[1] + "</b> " + UNIT; }},
      visualMap: {min: 0, max: TOP, calculable: false, show: false,
                  inRange: {color: RAMP}},
      calendar: {
        range: YEAR, left: 34, right: 12, top: 26, cellSize: ["auto", 14],
        itemStyle: {color: "#111c30", borderColor: "#0b1220", borderWidth: 2},
        splitLine: {show: false},
        yearLabel: {show: false},
        monthLabel: {color: "#94a3b8", fontSize: 10},
        dayLabel: {color: "#64748b", fontSize: 9, firstDay: 1}
      },
      series: [{
        type: "heatmap", coordinateSystem: "calendar", data: DATA,
        itemStyle: {borderRadius: 2}
      }, {
        // The selection ring is its own series: repainting one scatter
        // point is cheaper and far simpler than restyling the heatmap.
        type: "scatter", coordinateSystem: "calendar", symbolSize: 13,
        symbol: "rect", z: 5,
        itemStyle: {color: "transparent", borderColor: "#f8fafc",
                    borderWidth: 1.5},
        data: PICKED.map(function (d) { return [d, 0]; })
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
      if (!params.value) { return; }
      var day = params.value[0];
      if (MODE === "select many") {
        var at = PICKED.indexOf(day);
        if (at === -1) { PICKED.push(day); } else { PICKED.splice(at, 1); }
      } else {
        PICKED = (PICKED.length === 1 && PICKED[0] === day) ? [] : [day];
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
    date_column = str(params.get("date", "") or "").strip()
    if not date_column:
        raise ValueError("set 'Date' — a calendar needs a date column")
    if date_column not in table.columns:
        available = ", ".join(str(c) for c in table.columns)
        raise ValueError(f"Date column {date_column!r} is not in the table "
                         f"(has: {available})")

    value_column = str(params.get("value", "") or "").strip()
    if value_column and value_column not in table.columns:
        raise ValueError(f"Value column {value_column!r} is not in the table")

    # Coercing whatever is in the column is the whole point here, so
    # pandas' "could not infer format" warning is noise: it fires on
    # exactly the mixed input this is written to survive, and it would
    # land in the user's log looking like a fault.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        days = pd.to_datetime(table[date_column], errors="coerce")
    usable = days.notna()
    if not usable.any():
        raise ValueError(
            f"nothing in {date_column!r} reads as a date — a Convert Types "
            f"node before this one will fix it")
    if (~usable).any():
        ctx.log(f"{int((~usable).sum())} row(s) had no usable date")

    frame = pd.DataFrame({"day": days[usable]})
    combine = str(params.get("combine", "sum") or "sum")
    if value_column and combine != "count":
        frame["value"] = pd.to_numeric(
            table.loc[usable, value_column], errors="coerce")
        grouped = frame.dropna(subset=["value"]).groupby(
            frame["day"].dt.normalize())["value"].agg(combine)
        unit = value_column
    else:
        grouped = frame.groupby(frame["day"].dt.normalize())["day"].count()
        unit = "rows"

    # Which year to draw. Blank means the latest one present, which is what
    # someone looking at a live feed wants without having to say so.
    asked = str(params.get("year", "") or "").strip()
    years = sorted({stamp.year for stamp in grouped.index})
    if asked:
        try:
            year = int(asked)
        except ValueError:
            raise ValueError(f"Year {asked!r} is not a year like 2026") from None
        if year not in years:
            listed = ", ".join(str(y) for y in years) or "none"
            raise ValueError(f"no rows fall in {year} (the data covers: "
                             f"{listed})")
    else:
        year = years[-1]
    if len(years) > 1:
        left_out = sum(1 for stamp in grouped.index if stamp.year != year)
        ctx.log(f"drawing {year}; {left_out} day(s) in other years not shown")

    points = [[stamp.strftime("%Y-%m-%d"), round(float(amount), 4)]
              for stamp, amount in grouped.items() if stamp.year == year]
    top = max((point[1] for point in points), default=1.0) or 1.0
    ctx.log(f"{len(points)} day(s) in {year}, peak {top:g} {unit}")

    picked = selected_values(params.get("selected", ""))
    mode = str(params.get("on_click", "select one") or "nothing")

    filtered = table
    if mode != "nothing" and picked:
        stamps = days.dt.strftime("%Y-%m-%d")
        filtered = table[stamps.isin(picked)]
        ctx.log(f"clicked {', '.join(picked)}: kept {len(filtered)} of "
                f"{len(table)} rows")

    ramp = _RAMPS.get(str(params.get("palette", "green")), _RAMPS["green"])
    page = (_PAGE
            .replace("/*DATA*/", json.dumps(points))
            .replace("/*YEAR*/", json.dumps(str(year)))
            .replace("/*RAMP*/", json.dumps(ramp))
            .replace("/*TOP*/", json.dumps(top))
            .replace("/*PICKED*/", json.dumps(picked))
            .replace("/*MODE*/", json.dumps(mode))
            .replace("/*NOMW*/", str(_NOMINAL[0]))
            .replace("/*NOMH*/", str(_NOMINAL[1]))
            .replace("/*UNIT*/", json.dumps(unit)))
    html = ("<!doctype html><html><head><meta charset='utf-8'>"
            f"{markup('echarts')}</head><body>{page}</body></html>")
    return {"html": html, "selected": picked, "table": filtered}
