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

What an embed can ask for: `search` puts a search box over a table,
`static` keeps an embed the way the PDF has it.
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
    for index, chart in charts.items():
        html, hit = re.subn(_IMG_RE.format(index),
                            lambda m, i=index, c=chart: _chart_box(m.group(0),
                                                                   i, c),
                            html, count=1)
        drawn += hit
    for marker, build, search, rows in tables:
        span = _enclosing_table(html, marker)
        if span is None:
            continue
        try:
            table = build()
        except Exception:
            continue            # stays Qt's table — still the report
        start, end = span
        html = html[:start] + _table_box(table, search, rows) + html[end:]
    head = f"<style>{LIVE_CSS}</style>"
    script = _plotly_script(plotly_src) if drawn else ""
    body = script + f"<script>{LIVE_JS}</script>"
    html = _into(html, "</head>", head)
    return _into(html, "</body>", body)


def _chart_box(img: str, index: int, chart: dict) -> str:
    """The picture inside a box the live chart will be drawn over, with the
    figure beside it.

    The picture stays in the page, invisible, once the chart is up: it is
    what gives the box its size. It was taken at the figure's own shape,
    so the chart lands exactly where it was and the page does not jump —
    and a box sized any other way collapses inside a column layout's
    auto-sized cell (it did: `aspect-ratio` on an empty box in a table
    cell has no width to be a ratio of).
    """
    width = re.search(r'\bwidth="(\d+)"', img)
    size = f"width:{width.group(1)}px;" if width else ""
    # `</` would end the script element early — a label with "</b>" in it
    data = chart["json"].replace("</", "<\\/")
    return (f'<div class="fg-chart" data-fg-chart="{index}" '
            f'style="{size}">{img}</div>'
            f'<script type="application/json" id="fg-fig-{index}">'
            f"{data}</script>")


def _table_box(table: str, search: bool, rows: int) -> str:
    flag = ' data-fg-search="1"' if search else ""
    return (f'<div class="fg-table"{flag} style="--fg-rows:{int(rows)}">'
            f'<div class="fg-scroll">{table}</div></div>')


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
.fg-chart > img { display: block; width: 100%; height: auto; margin: 0; }
.fg-chart.fg-drawn > img { visibility: hidden; }
.fg-chart > .fg-plot { position: absolute; inset: 0; }
.fg-table { margin: 0.6em 0; }
.fg-scroll {
  max-height: calc(var(--fg-rows, 30) * 2.1em + 2.6em);
  overflow: auto;
}
.fg-scroll table { border-collapse: collapse; }
.fg-scroll thead th {
  position: sticky; top: 0; z-index: 1;
  background: var(--fg-head, #eeeeee);
}
.fg-scroll thead tr + tr th { top: 2em; }
.fg-scroll tbody tr:hover > td { box-shadow: inset 0 0 0 9999px rgba(0,0,0,.05); }
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
.fg-bar { display: flex; gap: .6em; align-items: center; margin: 0 0 .4em; }
.fg-bar input {
  flex: 0 1 18em; font: inherit; padding: .3em .55em;
  border: 1px solid #c8c8c8; border-radius: 4px;
}
.fg-bar span { opacity: .65; font-size: .9em; }
/* Paper gets the picture, which is the PDF's own at print resolution.
   A live chart re-laid out for the printed page came out squashed in a
   column layout — Plotly resizes to a box that is mid-reflow — and a
   chart someone has zoomed into is not the one the report is about. */
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
  function drawChart(box) {
    if (box.classList.contains("fg-drawn") || !window.Plotly) return;
    var data = document.getElementById("fg-fig-" + box.dataset.fgChart);
    if (!data) return;
    var fig;
    try { fig = JSON.parse(data.textContent); } catch (e) { return; }
    var layout = fig.layout || {};
    delete layout.width; delete layout.height;   // the box sets the size
    layout.autosize = true;
    var host = document.createElement("div");
    host.className = "fg-plot";
    box.appendChild(host);
    Plotly.newPlot(host, fig.data || [], layout,
                   {responsive: true, displaylogo: false})
      .then(function () { box.classList.add("fg-drawn"); })
      .catch(function () { host.remove(); });   // the picture stays
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

  function tooltip(table, cell) {
    if (cell.title || cell.tagName !== "TD") return;
    var row = cell.parentNode, k = kind(row);
    var head = table.tHead && table.tHead.rows[table.tHead.rows.length - 1];
    var name = head && head.cells[cell.cellIndex]
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
    var simpleHead = table.tHead && table.tHead.rows.length === 1;
    if (!grouped && simpleHead) {
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
    if (box.dataset.fgSearch) {
      var bar = document.createElement("div");
      bar.className = "fg-bar";
      var input = document.createElement("input");
      input.type = "search"; input.placeholder = "Search…";
      var count = document.createElement("span");
      bar.appendChild(input); bar.appendChild(count);
      box.insertBefore(bar, box.firstChild);
      table.fgCount = count;
      input.addEventListener("input", function () {
        table.fgQuery = input.value.trim();
        refresh(table);
      });
    }
    if (grouped) refresh(table);
  });
})();
"""
