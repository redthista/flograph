"""Starter themes made for a *live* report page — compact, detailed, and
aware of the live charts and tables (ui/report/live.py).

They are ordinary CSS inserted into the page's CSS tab, like the older
themes in html.py, but they know three things about the page those do not:

**Qt's HTML fights back.** The body arrives with an inline font and size,
every run of text is a `<span style="font-family:'sans-serif';
font-size:11pt">`, and a heading's size sits on the span inside it. Inline
style beats a stylesheet, so the few rules that have to win say
`!important`, and they select Qt's own markup by its inline style: a quote
is the paragraph indented 40px each side, inline code the monospace span,
a ```columns block the borderless table.

**A live chart can be themed.** The page script reads `--fg-chart-paper`,
`--fg-chart-plot`, `--fg-chart-ink`, `--fg-chart-grid` and
`--fg-chart-font` and lays them over the figure's layout, so a dark page
gets a dark chart. `--chart-shape` is the shape the theme gives a chart
box (the chart redraws to fit, labels at their real size); delete that
line to keep each chart's own shape.

**A table's own cells are not the theme's to repaint.** Only the live
table's outer cells are styled (`.flograph-table > tbody > tr > td`): a
data bar is a small table inside a cell and must be left alone, and a
colour a rule put on a cell is kept. The total, group and subtotal rows do
take the theme's colours — delete the "structure rows" block to keep your
own `group =>` colours instead.
"""
from __future__ import annotations

COMPACT = """/* Compact — dense and exact. Small type, hairline rules, numbers that
   line up, headings that label rather than shout. Made for live pages:
   the charts take the theme too (see the --fg-chart- lines). */
:root {
  --ink: #1b2130;
  --muted: #687085;
  --line: #e4e7ed;
  --line-strong: #c9ced8;
  --accent: #2563eb;
  --band: #f5f7fa;
  --fg-head: #ffffff;
  --chart-shape: 2.6 / 1;
  --fg-chart-paper: #ffffff;
  --fg-chart-plot: #ffffff;
  --fg-chart-ink: #3b4356;
  --fg-chart-grid: #edf0f4;
  --fg-chart-font: Inter, "Segoe UI", "Noto Sans", system-ui, sans-serif;
}
body {
  font-family: Inter, "Segoe UI", "Noto Sans", system-ui, sans-serif !important;
  font-size: 12.5px !important;
  line-height: 1.45;
  color: var(--ink);
  background: #ffffff;
  max-width: 1180px;
  margin: 0 auto !important;
  padding: 22px 30px 40px !important;
  font-variant-numeric: tabular-nums;
}
/* Qt's spans carry their own font and size; let the theme's through */
span[style*="font-family:'sans-serif'"] { font-family: inherit !important; }
p span, li, li span, h1 span, h2 span, h3 span { font-size: inherit !important; }
p { margin: 3px 0 !important; max-width: 92ch; }

h1 {
  font-size: 21px; font-weight: 700; letter-spacing: -0.015em;
  margin: 0 0 8px !important; padding: 0 0 8px !important;
  border-bottom: 2px solid var(--ink);
}
h2 {
  display: flex; align-items: center; gap: 10px;
  font-size: 10.5px; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--muted); margin: 22px 0 6px !important;
}
h2::after { content: ""; flex: 1; height: 1px; background: var(--line); }
h3 { font-size: 12.5px; margin: 14px 0 3px !important; }

/* a > quote is a note in the margin, not an indent */
p[style*="margin-left:40px; margin-right:40px"] {
  margin: 10px 0 !important; padding: 7px 12px;
  border-left: 3px solid var(--accent); background: #f3f6fd;
  color: #26314a; max-width: none;
}
span[style*="font-family:'monospace'"] {
  font-family: "JetBrains Mono", "Cascadia Code", Consolas, monospace !important;
  font-size: 0.92em !important; background: var(--band);
  border: 1px solid var(--line); border-radius: 3px; padding: 0 3px;
}
ul { margin: 6px 0 !important; padding-left: 18px; }
li { margin: 1px 0 !important; }

/* charts: a thin panel at the theme's shape */
.fg-chart {
  width: 100% !important; aspect-ratio: var(--chart-shape);
  border: 1px solid var(--line); border-radius: 6px; overflow: hidden;
  margin: 6px 0 !important; background: var(--fg-chart-paper);
}
.fg-chart > img { height: 100%; object-fit: contain; }
p > img { border: 1px solid var(--line); border-radius: 6px; }

/* live tables */
.fg-table { margin: 6px 0 !important; }
.fg-scroll { border: 1px solid var(--line); border-radius: 6px; }
.fg-scroll .flograph-table { width: 100%; border-collapse: collapse; }
.flograph-table > thead > tr > th {
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase; color: var(--muted);
  padding: 6px 8px; border-bottom: 1px solid var(--line-strong);
  white-space: nowrap;
}
.flograph-table > tbody > tr > td {
  padding: 3px 8px; border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
.fg-scroll tbody tr:hover > td { box-shadow: inset 0 0 0 9999px rgba(37, 99, 235, 0.06); }
.flograph-table table[bgcolor] { background-color: var(--band); }
/* structure rows: total, group, subtotal (delete to keep your own colours) */
.flograph-table > tbody > tr[data-fg-kind] > td {
  background-color: var(--band) !important; color: var(--ink) !important;
  border: 0 !important; border-bottom: 1px solid var(--line-strong) !important;
  font-weight: 600;
}
.flograph-table > tbody > tr[data-fg-kind="total"] > td {
  background-color: #eef1f6 !important; border-top: 1px solid var(--ink) !important;
  border-bottom: 1px solid var(--ink) !important;
}
.fg-bar input {
  font-size: 12px; padding: 4px 9px; border: 1px solid var(--line-strong);
  border-radius: 5px; outline: none;
}
.fg-bar input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15); }

/* ```columns: an even grid with a gutter */
table[style*="border-style:none"] { width: 100% !important; table-layout: fixed; }
table[style*="border-style:none"] > tbody > tr > td { padding: 0 6px !important; }
table[style*="border-style:none"] .fg-chart { aspect-ratio: 1.45 / 1; }
"""


DASHBOARD = """/* Dashboard — every chart and table on a card, on a quiet canvas. A
   quote becomes the headline insight. Compact type, generous structure.
   The charts take the theme too (see the --fg-chart- lines). */
:root {
  --canvas: #eef1f6;
  --card: #ffffff;
  --ink: #172033;
  --muted: #64708a;
  --line: #e6e9f0;
  --accent: #4f46e5;
  --accent-soft: #eef0ff;
  --band: #f6f7fb;
  --shadow: 0 1px 2px rgba(16, 24, 40, 0.06), 0 4px 14px rgba(16, 24, 40, 0.06);
  --fg-head: #ffffff;
  --chart-shape: 2.4 / 1;
  --fg-chart-paper: #ffffff;
  --fg-chart-plot: #ffffff;
  --fg-chart-ink: #384259;
  --fg-chart-grid: #eef0f5;
  --fg-chart-font: Inter, "Segoe UI", "Noto Sans", system-ui, sans-serif;
}
body {
  font-family: Inter, "Segoe UI", "Noto Sans", system-ui, sans-serif !important;
  font-size: 13px !important;
  line-height: 1.5;
  color: var(--ink);
  background: var(--canvas);
  max-width: 1240px;
  margin: 0 auto !important;
  padding: 0 28px 48px !important;
  font-variant-numeric: tabular-nums;
}
span[style*="font-family:'sans-serif'"] { font-family: inherit !important; }
p span, li, li span, h1 span, h2 span, h3 span { font-size: inherit !important; }
p { margin: 4px 0 !important; }

/* the title is a header band across the top */
h1 {
  font-size: 22px; font-weight: 750; letter-spacing: -0.02em;
  margin: 0 -28px 14px !important; padding: 22px 28px 16px !important;
  background: var(--card); border-bottom: 1px solid var(--line);
  box-shadow: var(--shadow);
}
h1 + p { color: var(--muted); }
h2 {
  font-size: 11px; font-weight: 700; letter-spacing: 0.09em;
  text-transform: uppercase; color: var(--muted);
  margin: 26px 0 8px !important;
}
h2::before {
  content: ""; display: inline-block; width: 8px; height: 8px;
  border-radius: 2px; background: var(--accent); margin-right: 8px;
  vertical-align: 1px;
}
h3 { font-size: 13px; margin: 16px 0 4px !important; }

/* a > quote is the insight card */
p[style*="margin-left:40px; margin-right:40px"] {
  margin: 14px 0 !important; padding: 14px 18px 14px 50px;
  background: var(--accent-soft); border: 1px solid #dcdffd;
  border-radius: 12px; position: relative; font-size: 13.5px;
}
p[style*="margin-left:40px; margin-right:40px"]::before {
  content: "\\2139"; position: absolute; left: 16px; top: 13px;
  width: 22px; height: 22px; border-radius: 50%; background: var(--accent);
  color: #fff; font: 700 13px/22px Georgia, serif; text-align: center;
}
span[style*="font-family:'monospace'"] {
  font-family: "JetBrains Mono", "Cascadia Code", Consolas, monospace !important;
  font-size: 0.9em !important; background: var(--accent-soft);
  color: var(--accent); border-radius: 4px; padding: 1px 5px;
}
ul { margin: 8px 0 !important; padding: 12px 18px 12px 34px;
     background: var(--card); border-radius: 12px; box-shadow: var(--shadow); }
li { margin: 2px 0 !important; }

/* cards */
.fg-chart, .fg-table, p > img {
  background: var(--card); border-radius: 12px; box-shadow: var(--shadow);
}
.fg-chart {
  width: 100% !important; aspect-ratio: var(--chart-shape);
  overflow: hidden; margin: 8px 0 !important;
}
.fg-chart > img { height: 100%; object-fit: contain; }
p > img { padding: 8px; box-sizing: border-box; }
.fg-table { padding: 12px 14px; margin: 8px 0 !important; }
.fg-scroll .flograph-table { width: 100%; border-collapse: collapse; }
.flograph-table > thead > tr > th {
  font-size: 11px; font-weight: 600; color: var(--muted);
  padding: 7px 9px; border-bottom: 2px solid var(--line); white-space: nowrap;
}
.flograph-table > tbody > tr > td {
  padding: 5px 9px; border-bottom: 1px solid var(--line); white-space: nowrap;
}
.fg-scroll tbody tr:hover > td { box-shadow: inset 0 0 0 9999px rgba(79, 70, 229, 0.05); }
.flograph-table table[bgcolor] { background-color: var(--band); }
/* structure rows: total, group, subtotal (delete to keep your own colours) */
.flograph-table > tbody > tr[data-fg-kind] > td {
  background-color: var(--band) !important; color: var(--ink) !important;
  border: 0 !important; border-bottom: 1px solid var(--line) !important;
  font-weight: 650;
}
.flograph-table > tbody > tr[data-fg-kind="group"] > td:first-child {
  color: var(--accent) !important;
}
.flograph-table > tbody > tr[data-fg-kind="total"] > td {
  background-color: var(--accent-soft) !important;
  border-bottom: 2px solid var(--accent) !important;
}
.fg-bar { margin-bottom: 10px; }
.fg-bar input {
  font-size: 12.5px; padding: 6px 12px 6px 30px; border: 1px solid var(--line);
  border-radius: 999px; background: var(--band) no-repeat 10px 50% /
    13px url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='7' cy='7' r='5' fill='none' stroke='%2364708a' stroke-width='2'/%3E%3Cpath d='M11 11l4 4' stroke='%2364708a' stroke-width='2'/%3E%3C/svg%3E");
  outline: none;
}
.fg-bar input:focus { background-color: #fff; border-color: var(--accent); }

/* ```columns: cards side by side */
table[style*="border-style:none"] { width: 100% !important; table-layout: fixed; }
table[style*="border-style:none"] > tbody > tr > td { padding: 0 7px !important; }
table[style*="border-style:none"] > tbody > tr > td:first-child { padding-left: 0 !important; }
table[style*="border-style:none"] > tbody > tr > td:last-child { padding-right: 0 !important; }
table[style*="border-style:none"] .fg-chart { aspect-ratio: 1.4 / 1; }

@media print {
  body { background: #fff; }
  .fg-chart, .fg-table, p > img, ul, h1 { box-shadow: none; border: 1px solid var(--line); }
}
"""


MIDNIGHT = """/* Midnight — a dark control room: dense, high-contrast, cyan for what
   moves. The live charts turn dark with it (see the --fg-chart- lines);
   printed, it goes back to ink on white. */
:root {
  --bg: #0a0f1c;
  --panel: #111830;
  --panel-2: #172042;
  --ink: #dbe3f7;
  --muted: #8491b3;
  --line: #222c4d;
  --accent: #22d3ee;
  --accent-2: #a78bfa;
  --fg-head: #111830;
  --chart-shape: 2.6 / 1;
  --fg-chart-paper: #111830;
  --fg-chart-plot: #111830;
  --fg-chart-ink: #b9c4e2;
  --fg-chart-grid: #1f2a4a;
  --fg-chart-font: Inter, "Segoe UI", "Noto Sans", system-ui, sans-serif;
}
body {
  font-family: Inter, "Segoe UI", "Noto Sans", system-ui, sans-serif !important;
  font-size: 12.5px !important;
  line-height: 1.5;
  color: var(--ink) !important;
  background: radial-gradient(1200px 500px at 15% -10%, #16224a 0%, transparent 60%),
              var(--bg) !important;
  background-attachment: fixed !important;
  max-width: 1220px;
  margin: 0 auto !important;
  padding: 26px 30px 48px !important;
  font-variant-numeric: tabular-nums;
}
span[style*="font-family:'sans-serif'"] { font-family: inherit !important; }
p span, li, li span, h1 span, h2 span, h3 span { font-size: inherit !important; }
p { margin: 4px 0 !important; }
a { color: var(--accent); }

h1 {
  font-size: 23px; font-weight: 750; letter-spacing: -0.02em;
  margin: 0 0 10px !important; padding: 0 !important;
  background: linear-gradient(90deg, #ffffff 0%, var(--accent) 55%, var(--accent-2) 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
  width: fit-content;   /* the gradient spans the words, not the page */
}
h1 + p { color: var(--muted); }
h2 {
  display: flex; align-items: center; gap: 10px;
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.14em;
  text-transform: uppercase; color: var(--accent);
  margin: 26px 0 8px !important;
}
h2::after { content: ""; flex: 1; height: 1px;
            background: linear-gradient(90deg, var(--line), transparent); }
h3 { font-size: 12.5px; color: #ffffff; margin: 16px 0 4px !important; }

p[style*="margin-left:40px; margin-right:40px"] {
  margin: 12px 0 !important; padding: 10px 14px;
  background: linear-gradient(90deg, rgba(34, 211, 238, 0.10), rgba(34, 211, 238, 0.02));
  border: 1px solid rgba(34, 211, 238, 0.25); border-left: 3px solid var(--accent);
  border-radius: 8px;
}
span[style*="font-family:'monospace'"] {
  font-family: "JetBrains Mono", "Cascadia Code", Consolas, monospace !important;
  font-size: 0.9em !important; color: var(--accent);
  background: rgba(34, 211, 238, 0.08); border-radius: 4px; padding: 0 4px;
}
ul { margin: 8px 0 !important; padding-left: 18px; }
li::marker { color: var(--accent); }

/* panels */
.fg-chart, .fg-table, p > img {
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.2), 0 10px 30px rgba(0, 0, 0, 0.35);
}
.fg-chart {
  width: 100% !important; aspect-ratio: var(--chart-shape);
  overflow: hidden; margin: 8px 0 !important;
}
.fg-chart > img { height: 100%; object-fit: contain; }
/* a picture was drawn for paper; dim it rather than let it glare */
p > img, .fg-chart:not(.fg-drawn) > img { opacity: 0.9; }
.fg-table { padding: 10px 12px; margin: 8px 0 !important; }
.fg-scroll .flograph-table { width: 100%; border-collapse: collapse; }
.flograph-table > thead > tr > th {
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--muted);
  padding: 7px 9px; border-bottom: 1px solid var(--accent); white-space: nowrap;
}
.flograph-table > tbody > tr > td {
  padding: 4px 9px; border-bottom: 1px solid var(--line); white-space: nowrap;
  color: var(--ink);
}
.fg-scroll tbody tr:hover > td { box-shadow: inset 0 0 0 9999px rgba(34, 211, 238, 0.07); }
/* structure rows: total, group, subtotal (delete to keep your own colours) */
.flograph-table > tbody > tr[data-fg-kind] > td {
  background-color: var(--panel-2) !important; color: #ffffff !important;
  border: 0 !important; border-bottom: 1px solid var(--line) !important;
  font-weight: 650;
}
.flograph-table > tbody > tr[data-fg-kind="group"] > td:first-child {
  color: var(--accent) !important;
}
.flograph-table > tbody > tr[data-fg-kind="total"] > td {
  background-color: #1b2657 !important; border-top: 1px solid var(--accent) !important;
}
/* a data bar's empty track was drawn for white paper */
.flograph-table table[bgcolor] { background-color: rgba(255, 255, 255, 0.07); }
.fg-bar input {
  font-size: 12px; padding: 5px 10px; color: var(--ink);
  background: var(--bg); border: 1px solid var(--line); border-radius: 6px;
  outline: none;
}
.fg-bar input:focus { border-color: var(--accent);
                      box-shadow: 0 0 0 3px rgba(34, 211, 238, 0.18); }
.fg-bar span { color: var(--muted); }
.fg-scroll::-webkit-scrollbar { width: 8px; height: 8px; }
.fg-scroll::-webkit-scrollbar-thumb { background: var(--line); border-radius: 4px; }
.fg-scroll { scrollbar-color: var(--line) transparent; }

table[style*="border-style:none"] { width: 100% !important; table-layout: fixed; }
table[style*="border-style:none"] > tbody > tr > td { padding: 0 7px !important; }
table[style*="border-style:none"] > tbody > tr > td:first-child { padding-left: 0 !important; }
table[style*="border-style:none"] > tbody > tr > td:last-child { padding-right: 0 !important; }
table[style*="border-style:none"] .fg-chart { aspect-ratio: 1.4 / 1; }

/* paper does not print backgrounds: go back to ink on white */
@media print {
  body { background: #fff !important; color: #111 !important; }
  h1 { background: none; color: #111; }
  h2, h3 { color: #111; }
  .fg-chart, .fg-table, p > img { background: #fff; box-shadow: none;
                                  border-color: #ccc; }
  .flograph-table > tbody > tr > td { color: #111; }
  .flograph-table > tbody > tr[data-fg-kind] > td {
    background-color: #eee !important; color: #111 !important; }
}
"""


LIVE_THEMES = {
    "Compact": COMPACT,
    "Dashboard": DASHBOARD,
    "Midnight": MIDNIGHT,
}
