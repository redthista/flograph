"""The web page's live charts and tables.

A report reaches the browser as Qt's own HTML (see html.py): the document
the PDF is printed from, written back out. That makes the two agree, and it
is also why nothing in it can move — a Plotly chart is a photograph by then,
and a table has been through Qt's rich text, which keeps the colours and
drops everything a script could hold on to (`class`, `id`, `title`,
`data-*`, `<th>`, `<tbody>`; checked, not assumed).

So the live versions are not layered *onto* Qt's output; they *replace*
parts of it, afterwards. Two handles survive Qt's round trip and say where:

* a chart is `<img src="embed:N">`, and the resolver kept figure N's JSON
  (RenderedReport.live_charts). The picture stays inside the chart's box
  as the fallback — a mail client that runs no script shows the report as
  the PDF has it, rather than an empty frame.
* a table carries its invisible marker in the first header cell, and the
  resolver kept a builder that writes the same table for a browser
  (frame_to_html's `live`): every row up to LIVE_TABLE_ROWS, folded groups
  included and tagged, so the page can fold, sort and search it.

The page stays one file with nothing to fetch. Plotly's script is the one
that ships inside the plotly package, inlined once however many charts
there are — never a CDN, the same rule the Web Libraries follow.

Opt-in, per embed: `![[Chart|live]]`, `![[Sales|live]]`, and
`![[Sales|search]]` for a live table with a search box. An embed that asks
for neither is exactly what the PDF has, so a report nobody has touched
saves the HTML it always did — and carries no Plotly unless a chart is
live.
"""
from __future__ import annotations

import json
import re

_IMG_RE = r'<img\b[^>]*\bsrc="embed:{}"[^>]*>'
_TABLE_TAG_RE = re.compile(r"<\s*(/?)\s*table\b", re.IGNORECASE)


def make_live(html: str, rendered, plotly_src: "str | None" = None) -> str:
    """`html` (Qt's, images not yet inlined) with its live parts put in.

    `plotly_src` is where the page loads Plotly from: None inlines it (a
    file to keep), a relative path points at a copy beside the page (the
    Web preview, which writes the page again on every keystroke and should
    not re-read 4 MB of script each time).
    """
    charts = getattr(rendered, "live_charts", None) or {}
    tables = getattr(rendered, "live_tables", None) or []
    if not charts and not tables:
        return html
    drawn = 0
    images = getattr(rendered, "images", None) or []
    for index, chart in charts.items():
        shape = _shape_of(images[index] if index < len(images) else None)
        html, hit = re.subn(_IMG_RE.format(index),
                            lambda m, i=index, c=chart, k=shape:
                            _chart_box(m.group(0), i, c, k),
                            html, count=1)
        drawn += hit
    shares = dict(getattr(rendered, "table_widths", None) or ())
    for marker, build, search, rows in tables:
        span = _enclosing_table(html, marker)
        if span is None:
            continue
        try:
            table = build()
        except Exception:
            continue            # stays Qt's table — still the report
        start, end = span
        box = _table_box(table, search, rows, shares.get(marker, ""))
        html = html[:start] + box + html[end:]
    head = f"<style>{LIVE_CSS}</style>"
    script = _plotly_script(plotly_src) if drawn else ""
    if drawn:
        # a live map's outlines, once for every map on the page, so it
        # draws with no network (flograph.geoassets)
        from flograph.geoassets import preload_script
        outlines = []
        for chart in charts.values():
            for name in chart.get("outlines", ()):
                if name not in outlines:
                    outlines.append(name)
        script += preload_script(outlines)
    body = script + f"<script>{LIVE_JS}</script>"
    html = _into(html, "</head>", head)
    return _into(html, "</body>", body)


def _shape_of(image) -> str:
    """`aspect-ratio` for a chart box, from its picture's pixels, or ""."""
    try:
        w, h = image.width(), image.height()
    except Exception:
        return ""
    return f"aspect-ratio:{w} / {h};" if w > 0 and h > 0 else ""


def _chart_box(img: str, index: int, chart: dict, shape: str = "") -> str:
    """The picture inside a box the live chart will be drawn over, with the
    figure beside it.

    The box is the picture's width and the picture's shape from the first
    layout, stated rather than left to the picture: in a column layout's
    auto-sized cell, Firefox laid the box out before the picture had
    decoded and Plotly drew a chart a few pixels tall. With both stated
    the box has a size before anything loads. (A theme's `--chart-shape`
    overrides the shape — it says `!important`.) The picture stays in the
    box, invisible, as the fallback and for print.
    """
    width = re.search(r'\bwidth="(\d+)"', img)
    size = (f"width:{width.group(1)}px;" if width else "") + shape
    # `</` would end the script element early — a label with "</b>" in it
    data = chart["json"].replace("</", "<\\/")
    design = chart.get("design") or ()
    design = (f' data-fg-design="{int(design[0])},{int(design[1])}"'
              if len(design) == 2 else "")
    return (f'<div class="fg-chart" data-fg-chart="{index}"{design} '
            f'style="{size}">{img}</div>'
            f'<script type="application/json" id="fg-fig-{index}">'
            f"{data}</script>")


def _table_box(table: str, search: bool, rows: int, share: str = "") -> str:
    """A live table in its box: `rows` tall and scrolling, or — rows 0,
    `rows=all` — its whole length, no scroll box at all. `share` ("90%",
    from `width=90%`) makes the box that share of the page, and the table
    fill it; without one the box is as wide as the table."""
    flag = ' data-fg-search="1"' if search else ""
    sized = ""
    if share:
        flag += " data-fg-share"
        sized = f"width:{_css_share(share)};"
    if rows <= 0:
        style = f' style="{sized}"' if sized else ""
        return (f'<div class="fg-table fg-whole"{flag}{style}>'
                f'<div class="fg-scroll">{table}</div></div>')
    return (f'<div class="fg-table"{flag} style="{sized}--fg-rows:{int(rows)}">'
            f'<div class="fg-scroll">{table}</div></div>')


def _css_share(share: str) -> str:
    """`90%` as a CSS width — a number and a %, nothing else gets in."""
    try:
        return f"{min(100.0, max(1.0, float(share.rstrip('%')))):g}%"
    except ValueError:
        return "100%"


_TABLE_OPEN_RE = re.compile(r"<table\b[^>]*>", re.IGNORECASE)


def size_tables(html: str, rendered) -> str:
    """Every plain (not live) table given `width=N%`, that share of the
    web page: Qt wrote it at a fixed width in points — the paper's — which a
    browser reads as pixels, so on a wide window `width=100%` stopped at
    the table's own columns. (A live table was sized in its box.)"""
    for marker, share in getattr(rendered, "table_widths", None) or ():
        span = _enclosing_table(html, marker)
        if span is None:
            continue                    # live: replaced, and sized there
        start, _end = span
        tag = _TABLE_OPEN_RE.match(html, start)
        if tag is None:
            continue
        opening = re.sub(r'\swidth="[^"]*"', "", tag.group(0))
        opening = opening[:-1] + f' width="{_css_share(share)}">'
        html = html[:start] + opening + html[tag.end():]
    return html


def _enclosing_table(html: str, marker: str) -> "tuple | None":
    """`(start, end)` of the table whose header holds `marker`, and the
    "showing N of M" note under it.

    The *innermost* table around the marker — render._table_span takes the
    outermost, which is right for the tables it rebuilds but here would
    replace a whole column layout or chart grid that the table sits in.
    """
    from .render import _with_note

    at = html.find(marker)
    if at == -1:
        return None
    stack: list = []
    target = None           # depth of the table that holds the marker
    for match in _TABLE_TAG_RE.finditer(html):
        if target is None and match.start() > at:
            if not stack:
                return None
            target = len(stack)
        if match.group(1) != "/":
            stack.append(match.start())
            continue
        if not stack:
            continue
        start = stack.pop()
        if target is not None and len(stack) == target - 1:
            end = html.find(">", match.end())
            if end == -1:
                return None
            return start, _with_note(html, end + 1, marker)
    return None


def _plotly_script(src: "str | None") -> str:
    if src:
        return f'<script src="{src}"></script>'
    js = plotly_js()
    return f"<script>{js}</script>" if js else ""


def plotly_js() -> str:
    """The plotly.js that ships with the installed plotly, or "" — the page
    then keeps its pictures, which is what they are there for."""
    try:
        from plotly.offline import get_plotlyjs
        return get_plotlyjs()
    except Exception:
        return ""


def _into(html: str, tag: str, block: str) -> str:
    """`block` just before `tag`, or at the end if there is none."""
    found = re.search(re.escape(tag), html, re.IGNORECASE)
    if found is None:
        return html + block
    return html[:found.start()] + block + html[found.start():]


LIVE_CSS = """
.fg-chart { max-width: 100%; margin: 0.6em auto; position: relative; }
/* a ```columns block: Qt fixed its cells at the paper's widths, which on
   a screen left two charts side by side at a quarter of the page each;
   here the columns share the width, and a chart fills its column */
table[style*="border-style:none"] { width: 100%; table-layout: fixed; }
table[style*="border-style:none"] .fg-chart { width: 100% !important; }
.fg-chart > img { display: block; width: 100%; height: auto; margin: 0; }
.fg-chart.fg-drawn > img { visibility: hidden; }
.fg-chart > .fg-plot { position: absolute; inset: 0; }
/* as wide as the table, so its bar (search, Expand all) sits over it and
   not at the far side of the page; a theme's full-width card overrides */
.fg-table { margin: 0.6em 0; width: fit-content; max-width: 100%;
  box-sizing: border-box; }   /* a theme's padding and border stay inside a width=N% */
/* `width=90%`: the box is that share of the page, and the table fills it */
.fg-table[data-fg-share] .flograph-table { width: 100%; }
/* Qt pads a report's cells from its own stylesheet; a browser's default
   is a pixel, which ran "$9,937$10,519" together. Every live table gets
   the same room; a theme sets its own. */
.fg-scroll .flograph-table > thead > tr > th,
.fg-scroll .flograph-table > tbody > tr > td { padding: 3px 9px; }
.fg-scroll .flograph-table > thead > tr > th { vertical-align: bottom; }
.fg-scroll {
  max-height: calc(var(--fg-rows, 30) * 2.1em + 2.6em);
  overflow: auto;
}
.fg-scroll table { border-collapse: collapse; }
/* A grand total stays in sight while its table scrolls: pinned to the
   bottom of the box, or under the headings for one at the top. The
   total's own colour usually shows; this is the fallback, since a pinned
   cell over scrolling rows must not be see-through. */
.fg-scroll .flograph-table > tbody > tr.fg-pin > td {
  position: sticky; z-index: 1; background-color: #f2f3f5;
}
.fg-scroll .flograph-table > tbody > tr.fg-pin-bottom > td { bottom: 0; }
.fg-scroll .flograph-table > tbody > tr.fg-pin-top > td {
  top: var(--fg-head-h, 0px);
}
/* `rows=all`: the whole table down the page, no box to scroll */
.fg-table.fg-whole > .fg-scroll { max-height: none; overflow: visible; }
.fg-scroll thead th {
  position: sticky; top: 0; z-index: 1;
  background: var(--fg-head, #eeeeee);
}
.fg-scroll thead tr + tr th { top: 2em; }
.fg-scroll tbody tr:hover > td { box-shadow: inset 0 0 0 9999px rgba(0,0,0,.05); }
/* a data bar is a small table in the cell; Qt sizes the column to it, a
   browser column can be wider — keep it at the right, under its heading */
.fg-scroll .flograph-table > tbody > tr > td > table { margin-left: auto; }
.fg-sortable thead th { cursor: pointer; user-select: none; }
.fg-sortable thead th[data-fg-sort="asc"]::after { content: " \\25B2"; font-size: .75em; }
.fg-sortable thead th[data-fg-sort="desc"]::after { content: " \\25BC"; font-size: .75em; }
tr[data-fg-kind="group"] { cursor: pointer; }
tr[data-fg-kind="group"] > td:first-child::before {
  content: "\\25BE\\00a0"; display: inline-block; width: 1.1em;
}
tr[data-fg-kind="group"][data-fg-folded="1"] > td:first-child::before {
  content: "\\25B8\\00a0";
}
tr.fg-hidden { display: none; }
/* a column heading: click to fold its columns to one, and back */
.flograph-table th.fg-band { cursor: pointer; user-select: none; text-align: center; }
.flograph-table th.fg-band::before { content: "\\25BE\\00a0"; opacity: .7; }
.flograph-table th.fg-band[data-fg-folded="1"]::before { content: "\\25B8\\00a0"; }
.fg-bar { display: flex; gap: .6em; align-items: center; margin: 0 0 .4em; }
.fg-bar input {
  flex: 0 1 18em; font: inherit; padding: .3em .55em;
  border: 1px solid #c8c8c8; border-radius: 4px;
}
.fg-bar .fg-count { opacity: .65; font-size: .9em; }
/* in the page's own colours, so every theme — light or dark — suits them */
.fg-bar .fg-tools { margin-left: auto; display: flex; gap: .35em; }
.fg-bar button {
  font: inherit; font-size: .85em; color: inherit; cursor: pointer;
  padding: .25em .7em; border-radius: 4px; background: transparent;
  border: 1px solid rgba(128, 128, 128, .45);
}
.fg-bar button:hover { background: rgba(128, 128, 128, .14); }
/* Paper gets the picture, which is the PDF's own at print resolution.
   A live chart re-laid out for the printed page came out squashed in a
   column layout — Plotly resizes to a box that is mid-reflow — and a
   chart someone has zoomed into is not the one the report is about. */
/* full screen: the box fills the screen (or the window, where full screen
   is refused), whatever shape a theme gave it; the chart redraws to fit */
/* the class twice: it must beat a theme's !important column shape */
.fg-chart.fg-full.fg-full {
  position: fixed !important; inset: 0 !important; z-index: 2147483000;
  width: auto !important; height: auto !important; max-width: none !important;
  aspect-ratio: auto !important; margin: 0 !important;
  border-radius: 0 !important; border: 0 !important;
  background: var(--fg-chart-paper, #ffffff);
  padding: 12px; box-sizing: border-box;
}
.fg-chart.fg-full > .fg-plot { inset: 12px; }
.fg-chart.fg-full > img { display: none; }
.fg-chart:fullscreen { width: 100vw !important; height: 100vh !important; }
.fg-chart::backdrop { background: var(--fg-chart-paper, #ffffff); }
html.fg-full-page, html.fg-full-page body { overflow: hidden !important; }
@media print {
  .fg-chart.fg-drawn > img { visibility: visible; }
  .fg-chart > .fg-plot { display: none; }
  .fg-bar { display: none; }
  .fg-scroll { max-height: none; overflow: visible; }
  .fg-scroll thead th { position: static; }
}
"""


LIVE_JS = r"""
(function () {
  "use strict";

  // ---- charts: drawn as they scroll into view, so a page of forty is quick
  // A stylesheet can theme the live charts: a template sets these on the
  // page (or on one box) and they are laid over the figure's own layout.
  // Unset, the chart is exactly as the node drew it.
  // A theme's own series colours (--fg-chart-colors, a comma list). Plotly
  // Express writes each series' colour into the figure, taken from its
  // template's palette, so setting a palette is not enough: a colour that
  // came from the palette becomes the theme's colour in the same place.
  // One a chart set on purpose — not in the palette — is left alone.
  var PLOTLY_COLORS = ["#636efa", "#ef553b", "#00cc96", "#ab63fa", "#ffa15a",
                       "#19d3f3", "#ff6692", "#b6e880", "#ff97ff", "#fecb52"];
  function recolor(box, fig) {
    var list = getComputedStyle(box).getPropertyValue("--fg-chart-colors").trim();
    if (!list) return;
    var colors = list.split(",").map(function (c) { return c.trim(); })
                     .filter(Boolean);
    if (!colors.length) return;
    var layout = fig.layout = fig.layout || {};
    var template = layout.template && layout.template.layout;
    var from = (template && template.colorway) || layout.colorway || PLOTLY_COLORS;
    var map = {};
    from.forEach(function (c, i) {
      map[String(c).toLowerCase()] = colors[i % colors.length];
    });
    function swap(v) {
      if (typeof v === "string") { return map[v.toLowerCase()] || v; }
      if (Array.isArray(v)) { return v.map(swap); }
      return v;
    }
    (fig.data || []).forEach(function (trace) {
      ["marker", "line"].forEach(function (key) {
        var part = trace[key];
        if (!part) return;
        if (part.color !== undefined) part.color = swap(part.color);
        if (part.colors !== undefined) part.colors = swap(part.colors);
      });
      if (trace.fillcolor) trace.fillcolor = swap(trace.fillcolor);
    });
    layout.colorway = colors;
    if (template) template.colorway = colors;
  }

  function themed(box, layout) {
    var css = getComputedStyle(box);
    function v(name) { return css.getPropertyValue(name).trim(); }
    var paper = v("--fg-chart-paper"), plot = v("--fg-chart-plot");
    var ink = v("--fg-chart-ink"), grid = v("--fg-chart-grid");
    var font = v("--fg-chart-font");
    function unink(o) { if (o && typeof o === "object" && o.font) delete o.font.color; }
    if (paper) layout.paper_bgcolor = paper;
    if (plot) layout.plot_bgcolor = plot;
    if (ink || font) {
      layout.font = Object.assign({}, layout.font);
      if (ink) { layout.font.color = ink; unink(layout.title); }
      if (font) layout.font.family = font;
    }
    if (grid || ink) {
      ["xaxis", "yaxis"].forEach(function (key) {
        if (!layout[key]) layout[key] = {};
      });
      Object.keys(layout).forEach(function (key) {
        if (!/^[xy]axis\d*$/.test(key)) return;
        var axis = layout[key] = Object.assign({}, layout[key]);
        if (grid) { axis.gridcolor = grid; axis.zerolinecolor = grid;
                    axis.linecolor = grid; }
        if (ink) unink(axis.title);
      });
    }
    // a map's own ground comes from its template — white, which on a dark
    // page is a white slab round the globe
    if (plot) {
      Object.keys(layout).forEach(function (key) {
        if (!/^geo\d*$/.test(key)) return;
        layout[key] = Object.assign({}, layout[key], {bgcolor: plot});
      });
    }
    if (paper || ink) {
      layout.legend = Object.assign({bgcolor: "rgba(0,0,0,0)"}, layout.legend);
      if (ink) unink(layout.legend);
    }
    return layout;
  }

  // ---- full screen: the chart redrawn at the size of the screen, not a
  // picture of it scaled up. The browser's own full screen where it is
  // allowed; where it is not — the app's Web preview, a page in a frame —
  // the box fills the window instead. Esc, or the button again, puts it back.
  var EXPAND = {width: 24, height: 24,
                path: "M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2" +
                      "v3zM14 5v2h3v3h2V5h-5z"};
  var full = null;              // the box that is full screen, if any

  function leaveFull() {
    if (!full) return;
    var box = full;
    full = null;
    box.classList.remove("fg-full");
    document.documentElement.classList.remove("fg-full-page");
    if (document.fullscreenElement === box && document.exitFullscreen)
      document.exitFullscreen().catch(function () {});
  }

  function toggleFull(box) {
    if (full === box) { leaveFull(); return; }
    leaveFull();
    full = box;
    box.classList.add("fg-full");
    document.documentElement.classList.add("fg-full-page");
    if (box.requestFullscreen) {
      // refused (no permission, not allowed in a frame): the window it is
      box.requestFullscreen().catch(function () {});
    }
  }

  // leaving the browser's full screen by its own means (Esc, F11) ends ours
  document.addEventListener("fullscreenchange", function () {
    if (full && document.fullscreenElement !== full) leaveFull();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && full) leaveFull();
  });

  // A chart is never drawn smaller than it was designed. Plotly lays out in
  // real pixels with real-size text, so a 700px figure redrawn into a 250px
  // column spent the whole box on its margins, legend and labels and drew
  // a sliver of plot. Narrower than its design, it is drawn at the design
  // size and scaled down — exactly as its picture is; plotly.js reads the
  // CSS scale for hover and drag. Wider (a full-width card, full screen),
  // it is redrawn to the room it has.
  function fit(box, host) {
    var design = (box.dataset.fgDesign || "").split(",").map(Number);
    var css = getComputedStyle(box);
    var padX = parseFloat(css.paddingLeft) + parseFloat(css.paddingRight);
    var padY = parseFloat(css.paddingTop) + parseFloat(css.paddingBottom);
    var w = box.clientWidth - padX, h = box.clientHeight - padY;
    if (design.length === 2 && design[0] > 0 && w > 0 && w < design[0]) {
      var k = w / design[0];
      host.style.cssText =
        "position:absolute;right:auto;bottom:auto;" +
        "left:" + css.paddingLeft + ";top:" + css.paddingTop + ";" +
        "width:" + design[0] + "px;height:" + (h / k) + "px;" +
        "transform:scale(" + k + ");transform-origin:0 0";
    } else {
      host.style.cssText = "";
    }
  }

  function drawChart(box) {
    if (box.classList.contains("fg-drawn") || box.fgDrawing || !window.Plotly)
      return;
    // The picture sizes the box. Drawn before it has decoded, the box has
    // no height yet and Plotly draws a squashed chart it never corrects
    // (Firefox, in a column layout) — so wait for it.
    var img = box.querySelector("img");
    if (img && !img.complete) {
      img.addEventListener("load", function () { drawChart(box); },
                           {once: true});
      return;
    }
    var data = document.getElementById("fg-fig-" + box.dataset.fgChart);
    if (!data) return;
    var fig;
    try { fig = JSON.parse(data.textContent); } catch (e) { return; }
    recolor(box, fig);
    var layout = themed(box, fig.layout || {});
    delete layout.width; delete layout.height;   // the box sets the size
    layout.autosize = true;
    var host = document.createElement("div");
    host.className = "fg-plot";
    box.appendChild(host);
    fit(box, host);
    box.fgDrawing = true;
    Plotly.newPlot(host, fig.data || [], layout,
                   {responsive: true, displaylogo: false,
                    // never cdn.plot.ly: a map's outlines are in the page
                    topojsonURL: "flograph-map-outlines/",
                    modeBarButtonsToAdd: [{
                      name: "fullscreen", title: "Full screen (Esc to leave)",
                      icon: EXPAND,
                      click: function () { toggleFull(box); }
                    }]})
      .then(function () {
        box.classList.add("fg-drawn");
        // Plotly's own `responsive` hears only the window. A box that
        // changes size with the page — a column, a template that makes
        // charts full width — has to be told.
        if ("ResizeObserver" in window) {
          new ResizeObserver(function () {
            fit(box, host);
            Plotly.Plots.resize(host);
          }).observe(box);
        }
      })
      .catch(function () {    // the picture stays
        host.remove(); box.fgDrawing = false;
      });
  }
  var boxes = document.querySelectorAll(".fg-chart");
  if ("IntersectionObserver" in window) {
    var seen = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { seen.unobserve(e.target); drawChart(e.target); }
      });
    }, {rootMargin: "600px"});
    boxes.forEach(function (b) { seen.observe(b); });
  } else {
    boxes.forEach(drawChart);
  }

  // ---- tables
  function kind(r) { return r.getAttribute("data-fg-kind") || "data"; }
  function level(r) { return +(r.getAttribute("data-fg-level") || 0); }

  function number(text) {
    var s = text.replace(/[\s, ]/g, "")
                .replace(/^[^\d\-+.]+/, "").replace(/[^\d.eE\-+]+$/, "");
    if (s === "" || isNaN(s)) return null;
    return parseFloat(s);
  }

  // Each row's enclosing groups, outermost first. A subtotal belongs to its
  // own group (it folds away with it); a grand total to nothing.
  function ancestry(rows) {
    var stack = [];
    return rows.map(function (r) {
      var k = kind(r), d = level(r);
      if (k === "group") {
        while (stack.length && level(stack[stack.length - 1]) >= d) stack.pop();
        var mine = stack.slice(); stack.push(r); return mine;
      }
      if (k === "subtotal") {
        while (stack.length && level(stack[stack.length - 1]) > d) stack.pop();
        return stack.slice();
      }
      if (k === "total") { stack = []; return []; }
      return stack.slice();
    });
  }

  function folded(r) { return r.getAttribute("data-fg-folded") === "1"; }

  function refresh(table) {
    var rows = Array.prototype.slice.call(table.tBodies[0].rows);
    var up = ancestry(rows);
    var q = (table.fgQuery || "").toLowerCase();
    var hits = new Set(), found = new Set(), count = 0, total = 0;
    if (q) {
      rows.forEach(function (r, i) {
        if (kind(r) !== "data") return;
        // A grouped table moves the grouping column into the group rows,
        // so "south" is not in any of south's rows. A row is read with
        // the groups it sits in.
        var text = r.textContent;
        up[i].forEach(function (g) { text += " " + g.cells[0].textContent; });
        if (text.toLowerCase().indexOf(q) < 0) return;
        found.add(r);
        up[i].forEach(function (g) { hits.add(g); });
      });
    }
    rows.forEach(function (r, i) {
      var k = kind(r), show;
      if (k === "total") show = !q;
      else if (q) {
        show = k === "data" ? found.has(r)
             : hits.has(k === "group" ? r : up[i][up[i].length - 1]);
        if (k === "subtotal") show = false;
      } else {
        show = up[i].every(function (g) { return !folded(g); });
      }
      r.classList.toggle("fg-hidden", !show);
      if (k === "data") { total++; if (show) count++; }
    });
    if (table.fgCount)
      table.fgCount.textContent = q ? count + " of " + total + " rows" : "";
  }

  function sortBy(table, th) {
    var body = table.tBodies[0];
    var rows = Array.prototype.slice.call(body.rows);
    var dir = th.getAttribute("data-fg-sort") === "asc" ? "desc" : "asc";
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (c) {
      c.removeAttribute("data-fg-sort");
    });
    th.setAttribute("data-fg-sort", dir);
    var col = th.cellIndex, sign = dir === "asc" ? 1 : -1;
    var data = rows.filter(function (r) { return kind(r) === "data"; });
    var first = rows.indexOf(data[0]);
    var before = rows.slice(0, first).filter(function (r) { return kind(r) !== "data"; });
    var after = rows.slice(first).filter(function (r) { return kind(r) !== "data"; });
    function key(r) {
      var t = (r.cells[col] || {}).textContent || "";
      var n = number(t);
      return n === null ? t.trim().toLowerCase() : n;
    }
    data.sort(function (a, b) {
      var x = key(a), y = key(b);
      if (typeof x !== typeof y) return typeof x === "number" ? -1 : 1;
      return (x < y ? -1 : x > y ? 1 : 0) * sign;
    });
    before.concat(data, after).forEach(function (r) { body.appendChild(r); });
  }

  // ---- column headings that fold. The table carries every column any fold
  // state shows (members and each heading's face) and, in data-fg-bands,
  // which headings sit over which; this lays out the columns and the
  // heading rows for the current folds, the way table_bands.arrange does.
  function setupBands(table) {
    var meta;
    try { meta = JSON.parse(table.getAttribute("data-fg-bands")); }
    catch (e) { return; }
    var lead = meta.lead ? 1 : 0, heads = meta.heads, cols = meta.cols;
    var folded = heads.map(function (h) { return !!h.folded; });
    var first = table.tHead.rows[0];
    var leadTh = lead ? first.cells[0] : null;
    var colTh = Array.prototype.slice.call(first.cells, lead);
    table.fgColNames = (leadTh ? [leadTh.textContent.trim()] : []).concat(
      colTh.map(function (th) { return th.textContent.trim(); }));

    // the headings over a column that are on show: down to the first
    // folded one, which the column then stands for
    function covering(c) {
      var chain = cols[c].chain, out = [];
      for (var i = 0; i < chain.length; i++) {
        out.push(chain[i]);
        if (folded[chain[i]]) break;
      }
      return out;
    }
    function visible(c) {
      var chain = cols[c].chain;
      for (var i = 0; i < chain.length; i++)
        if (folded[chain[i]]) return cols[c].face === chain[i];
      return !cols[c].pure;
    }
    function bandCell(h, span) {
      var th = document.createElement("th");
      th.colSpan = span;
      th.className = "fg-band";
      th.setAttribute("data-fg-folded", folded[h] ? "1" : "0");
      th.textContent = heads[h].label;
      th.title = folded[h] ? "Show its columns" : "Fold to one column";
      th.addEventListener("click", function () {
        folded[h] = !folded[h];
        layout();
        measureHead(table);
      });
      return th;
    }
    function layout() {
      var shown = [], cover = {}, depth = 0;
      cols.forEach(function (_, c) {
        if (!visible(c)) return;
        shown.push(c);
        cover[c] = covering(c);
        depth = Math.max(depth, cover[c].length);
      });
      Array.prototype.forEach.call(table.tBodies[0].rows, function (row) {
        for (var c = 0; c < cols.length; c++) {
          var td = row.cells[c + lead];
          if (td) td.style.display = visible(c) ? "" : "none";
        }
      });
      var thead = table.tHead;
      while (thead.rows.length) thead.deleteRow(0);
      var rows = [];
      for (var r = 0; r <= depth; r++) rows.push(thead.insertRow());
      if (leadTh) { leadTh.rowSpan = depth + 1; rows[0].appendChild(leadTh); }
      for (r = 0; r <= depth; r++) {
        var i = 0;
        while (i < shown.length) {
          var c = shown[i], k = cover[c];
          if (r < k.length) {
            var h = k[r], n = 1;
            while (i + n < shown.length && cover[shown[i + n]].length > r &&
                   cover[shown[i + n]][r] === h) n++;
            rows[r].appendChild(bandCell(h, n));
            i += n;
            continue;
          }
          if (r === k.length) {
            colTh[c].rowSpan = depth + 1 - r;
            rows[r].appendChild(colTh[c]);
          }
          i++;
        }
      }
    }
    table.fgFoldColumns = function (value) {
      folded = folded.map(function () { return value; });
      layout();
      measureHead(table);
    };
    layout();
  }

  // ---- a grand total stays in sight while the table scrolls: the ones
  // above the first data row pin under the headings, the rest to the
  // bottom of the box (CSS .fg-pin). The headings' height is measured,
  // since folding column headings changes how many rows it has.
  function measureHead(table) {
    if (table.tHead)
      table.style.setProperty("--fg-head-h", table.tHead.offsetHeight + "px");
  }
  function pinTotals(table) {
    var above = true;
    Array.prototype.forEach.call(table.tBodies[0].rows, function (r) {
      if (kind(r) !== "total") { above = false; return; }
      r.classList.add("fg-pin", above ? "fg-pin-top" : "fg-pin-bottom");
    });
    measureHead(table);
  }

  function tooltip(table, cell) {
    if (cell.title || cell.tagName !== "TD") return;
    var row = cell.parentNode, k = kind(row);
    var head = table.tHead && table.tHead.rows[table.tHead.rows.length - 1];
    var name = table.fgColNames ? (table.fgColNames[cell.cellIndex] || "")
             : head && head.cells[cell.cellIndex]
             ? head.cells[cell.cellIndex].textContent.trim() : "";
    var text = cell.textContent.trim();
    if (!text) return;
    cell.title = k === "group" && cell.cellIndex === 0 ? text
               : (name ? name + ": " : "") + text;
  }

  document.querySelectorAll(".fg-table").forEach(function (box) {
    var table = box.querySelector("table");
    if (!table || !table.tBodies.length) return;
    var grouped = !!table.querySelector('tr[data-fg-kind="group"]');
    var banded = table.hasAttribute("data-fg-bands");
    if (banded) setupBands(table);
    pinTotals(table);
    var simpleHead = table.tHead && table.tHead.rows.length === 1;
    if (!grouped && !banded && simpleHead) {
      table.classList.add("fg-sortable");
      table.tHead.addEventListener("click", function (e) {
        var th = e.target.closest("th");
        if (th) sortBy(table, th);
      });
    }
    table.tBodies[0].addEventListener("click", function (e) {
      var row = e.target.closest("tr");
      if (!row || kind(row) !== "group" || table.fgQuery) return;
      row.setAttribute("data-fg-folded", folded(row) ? "0" : "1");
      refresh(table);
    });
    table.addEventListener("mouseover", function (e) {
      var cell = e.target.closest("td");
      // only this table's own cells, not a data bar's inner table
      if (cell && cell.closest("table") === table) tooltip(table, cell);
    });
    var bar = null;
    function toolbar() {
      if (!bar) {
        bar = document.createElement("div");
        bar.className = "fg-bar";
        box.insertBefore(bar, box.firstChild);
      }
      return bar;
    }
    if (box.dataset.fgSearch) {
      var input = document.createElement("input");
      input.type = "search"; input.placeholder = "Search…";
      var count = document.createElement("span");
      count.className = "fg-count";
      toolbar().appendChild(input); bar.appendChild(count);
      table.fgCount = count;
      input.addEventListener("input", function () {
        table.fgQuery = input.value.trim();
        refresh(table);
      });
    }
    if (grouped || banded) {
      // every group and every column heading at once — the same state a
      // click on one sets, so folding one by hand carries on as before
      var tools = document.createElement("span");
      tools.className = "fg-tools";
      [["Expand all", "0"], ["Collapse all", "1"]].forEach(function (each) {
        var button = document.createElement("button");
        button.type = "button";
        button.textContent = each[0];
        button.addEventListener("click", function () {
          table.querySelectorAll('tr[data-fg-kind="group"]').forEach(
            function (g) { g.setAttribute("data-fg-folded", each[1]); });
          if (table.fgFoldColumns) table.fgFoldColumns(each[1] === "1");
          refresh(table);
        });
        tools.appendChild(button);
      });
      toolbar().appendChild(tools);
      if (grouped) refresh(table);
    }
  });
})();
"""
