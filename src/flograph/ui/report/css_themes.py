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
table's outer cells are styled (`.flograph-table > tbody > tr > td`), and
a colour a rule put on a cell is kept. A data bar's empty track is
`.fg-db > i`, whose `background-color` is the theme's to set. The total,
group and subtotal rows do take the theme's colours — delete the
"structure rows" block to keep your own `group =>` colours instead.
"""
from __future__ import annotations

#: Every starter theme ends with this. Qt writes a table cell's value as a
#: paragraph, so a theme's paragraph spacing (`p { margin: 4px 0 }`) and
#: its roomy line height reached every row — Aurora's plain-table rows came
#: out 36px tall against 21px with no theme at all. Tables keep the page's
#: type but not its paragraph spacing. A ```columns block is layout, not a
#: table of data, and keeps its paragraphs as they are.
COMPACT_CELLS = """
/* tables stay compact: a cell's value is a paragraph (Qt writes it so),
   and the page's paragraph spacing is not meant for it */
.flograph-table td p, .flograph-table th p,
table[cellspacing="2"] td p { margin: 0 !important; max-width: none !important; }
.flograph-table, table[cellspacing="2"] { line-height: 1.3; }
/* a chart drawn as a picture sits in a paragraph: no reading width for it */
p:has(> img) { max-width: none !important; }
/* ...and so does an icon in a table cell, which a theme's framing of a
   chart picture (padding, a border, a shadow) squeezed to nothing */
.flograph-table td img, .flograph-table th img,
table[cellspacing="2"] td img, table[cellspacing="2"] th img {
  display: inline; margin: 0; padding: 0; border: 0; box-shadow: none;
  max-width: none; }
"""


def _plain_tables(head_bg: str, head_ink: str, line: str, group_bg: str,
                  group_ink: str, track: str, table_bg: str = "transparent",
                  head_rule: str = "", vertical: bool = True,
                  dark: bool = False, extra: str = "",
                  pad: str = "3px 9px") -> str:
    """A theme's look for a *plain* table: one Qt wrote — an embed without
    `|live`, or a Markdown table — which arrives dressed for paper, its
    colours inline: a grey header, #999 grid lines on every cell, grey
    total and group rows (#cdced1) and a pale track behind each data bar
    (#eceef1). The table itself is `cellspacing="2"`; a data bar's own
    small tables are 0, so they are left alone.

    `dark`: a cell a rule coloured keeps its colour, but its words, unless
    the rule gave them a colour, are the page's — white on a pastel. They
    are set dark instead.
    """
    t = 'table[cellspacing="2"]'
    cells = f"{t} > thead > tr > td, {t} > tbody > tr > td"
    side = "" if vertical else (
        f"\n  border-left: 0 !important; border-right: 0 !important;")
    rule = head_rule or line
    css = f"""
/* plain tables: an embed without |live, or a Markdown table (Qt wrote it
   for paper, colours inline) */
{t} {{ border-collapse: collapse !important; background: {table_bg};
  margin: 8px 0 !important; }}
/* a ```columns block is a table too, but layout: no table's ground */
{t}[style*="border-style:none"] {{ background: transparent !important; }}
{cells} {{
  border-color: {line} !important; padding: {pad} !important;{side}
}}
{t} > thead > tr > td {{
  background-color: {head_bg} !important;
  border-bottom: 1px solid {rule} !important;
}}
{t} > thead > tr > td p, {t} > thead > tr > td span {{
  background-color: transparent !important; color: {head_ink} !important;
}}
{t} > tbody > tr > td[bgcolor="#cdced1"] {{ background-color: {group_bg} !important; }}
{t} > tbody > tr > td[bgcolor="#cdced1"] p,
{t} > tbody > tr > td[bgcolor="#cdced1"] span {{
  background-color: transparent !important; color: {group_ink} !important;
}}
table[bgcolor="#eceef1"] {{ background-color: {track} !important; }}
/* the figure beside a data bar: Qt sets it in monospace so it lines up —
   the theme's own face, with even-width digits, does that too */
{t} td span[style*="monospace"] {{
  font-family: inherit !important; font-variant-numeric: tabular-nums;
}}
"""
    if dark:
        css += f"""{t} > tbody > tr > td[bgcolor]:not([bgcolor="#cdced1"]) span:not([style*=" color:"]) {{
  color: #14161c !important;
}}
"""
    return css + extra + COMPACT_CELLS


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
  /* the web layout: sidebar, top bar, tabs, folding sections */
  --fg-text-size: 12.5px;
  --fg-accent: #2563eb;
  --fg-nav-bg: #ffffff;
  --fg-nav-ink: #1b2130;
  --fg-nav-muted: #687085;
  --fg-nav-line: #e4e7ed;
  --fg-nav-hover: rgba(37, 99, 235, 0.07);
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
span[style*="font-family:'monospace'"]:not(td *) {   /* code, not a table's figures */
  font-family: "JetBrains Mono", "Cascadia Code", Consolas, monospace !important;
  font-size: 0.92em !important; background: var(--band);
  border: 1px solid var(--line); border-radius: 3px; padding: 0 3px;
}
ul { margin: 6px 0 !important; padding-left: 18px; }
li { margin: 1px 0 !important; }

/* charts: a thin panel at the theme's shape */
.fg-chart {
  width: 100% !important; aspect-ratio: var(--chart-shape) !important;
  border: 1px solid var(--line); border-radius: 6px; overflow: hidden;
  margin: 6px 0 !important; background: var(--fg-chart-paper);
}
.fg-chart > img { height: 100%; object-fit: contain; }
p > img { border: 1px solid var(--line); border-radius: 6px; }

/* live tables */
.fg-table { margin: 6px 0 !important; width: auto; }
.fg-scroll { border: 1px solid var(--line); border-radius: 6px; }
.fg-scroll .flograph-table { width: 100%; border-collapse: collapse; }
.flograph-table > thead > tr > th {
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.04em;
  text-transform: uppercase; color: var(--muted);
  padding: 4px 8px; border-bottom: 1px solid var(--line-strong);
  white-space: nowrap;
}
.flograph-table > tbody > tr > td {
  padding: 3px 8px; border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
.fg-scroll tbody tr:hover > td { box-shadow: inset 0 0 0 9999px rgba(37, 99, 235, 0.06); }
.fg-db > i { background-color: var(--band); }
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
table[style*="border-style:none"] .fg-chart { aspect-ratio: 1.45 / 1 !important; }

/* the web layout: tight bars, hairline sections, tabs that label */
:root { --fg-side-w: 236px; --fg-nav-font: Inter, "Segoe UI", "Noto Sans", system-ui, sans-serif; }
html.fg-has-top { --fg-top-h: 42px; }
.fg-top { font-size: 12.5px; }
.fg-top-title { font-size: 13px; letter-spacing: -0.01em; }
.fg-top-links a { padding: 0 10px; }
.fg-side { font-size: 12.5px; background: #fafbfc; }
.fg-side a { padding: 3px 8px; }
.fg-side-head { font-size: 10.5px; letter-spacing: 0.1em; padding: 12px 10px 6px 14px; }
.fg-tabs { margin: 10px 0; }
.fg-tabbar > button {
  padding: 6px 10px; font-size: 10.5px; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
}
details.fg-details { border-radius: 6px; margin: 8px 0; }
details.fg-details > summary { padding: 6px 10px; font-size: 12.5px; }
.fg-details-body { padding: 4px 12px 8px; }
.fg-drop { border-radius: 0 0 6px 6px; font-size: 12.5px; }
.fg-drop a { padding: 5px 10px; }
.fg-pager a { border-radius: 6px; padding: 7px 11px; }
.fg-pager span { font-size: 12.5px; }
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
  /* the web layout: sidebar, top bar, tabs, folding sections */
  --fg-text-size: 13px;
  --fg-accent: #4f46e5;
  --fg-nav-bg: #ffffff;
  --fg-nav-ink: #172033;
  --fg-nav-muted: #64708a;
  --fg-nav-line: #e6e9f0;
  --fg-nav-hover: #eef0ff;
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
span[style*="font-family:'monospace'"]:not(td *) {   /* code, not a table's figures */
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
  width: 100% !important; aspect-ratio: var(--chart-shape) !important;
  overflow: hidden; margin: 8px 0 !important;
}
.fg-chart > img { height: 100%; object-fit: contain; }
p > img { padding: 8px; box-sizing: border-box; }
.fg-table { padding: 8px 10px; margin: 8px 0 !important; width: auto; }
.fg-scroll .flograph-table { width: 100%; border-collapse: collapse; }
.flograph-table > thead > tr > th {
  font-size: 11px; font-weight: 600; color: var(--muted);
  padding: 4px 9px; border-bottom: 2px solid var(--line); white-space: nowrap;
}
.flograph-table > tbody > tr > td {
  padding: 3px 9px; border-bottom: 1px solid var(--line); white-space: nowrap;
}
.fg-scroll tbody tr:hover > td { box-shadow: inset 0 0 0 9999px rgba(79, 70, 229, 0.05); }
.fg-db > i { background-color: var(--band); }
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
table[style*="border-style:none"] .fg-chart { aspect-ratio: 1.4 / 1 !important; }

/* the web layout: bars and sections are cards; tabs a segmented control */
:root { --fg-nav-font: Inter, "Segoe UI", "Noto Sans", system-ui, sans-serif; }
.fg-top { border-bottom: 0; box-shadow: var(--shadow); }
.fg-side { border-right: 0; box-shadow: var(--shadow); }
.fg-side a.fg-on { background: var(--accent-soft); }
/* the title's band sits under the bar rather than behind it */
html.fg-has-top h1 { margin-top: -20px !important; }
.fg-tabbar { border-bottom: 0 !important; gap: 4px !important; padding: 4px;
  background: #e3e7ef; border-radius: 10px; width: fit-content; max-width: 100%; }
.fg-tabbar > button {
  border: 0; border-radius: 7px; padding: 6px 14px; margin: 0; font-weight: 600;
}
.fg-tabbar > button:hover { background: rgba(255, 255, 255, 0.6); }
.fg-tabbar > button.fg-on { background: var(--card); color: var(--accent);
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.12); }
.fg-tab { padding-top: 10px; }
details.fg-details { border: 0; border-radius: 12px; background: var(--card);
  box-shadow: var(--shadow); }
details.fg-details > summary { padding: 12px 16px; }
details.fg-details[open] > summary { border-bottom-color: var(--line); }
.fg-details-body { padding: 8px 16px 14px; }
/* a card inside a card is only its content */
.fg-details-body .fg-chart, .fg-details-body .fg-table { box-shadow: none;
  border: 1px solid var(--line); }
.fg-drop { border: 0; border-radius: 12px; margin-top: 6px; box-shadow: 0 12px 32px rgba(16, 24, 40, 0.14); }
.fg-pager { border-top: 0; }
.fg-pager a { border: 0; border-radius: 12px; background: var(--card); box-shadow: var(--shadow); }
.fg-inside { list-style: none; padding: 8px !important; }
.fg-inside a { display: block; padding: 6px 10px; border-radius: 8px; text-decoration: none; }
.fg-inside a:hover { background: var(--accent-soft); }

@media print {
  body { background: #fff; }
  .fg-chart, .fg-table, p > img, ul, h1, details.fg-details { box-shadow: none; border: 1px solid var(--line); }
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
  /* the web layout: sidebar, top bar, tabs, folding sections */
  --fg-text-size: 12.5px;
  --fg-accent: #22d3ee;
  --fg-nav-bg: #0d1428;
  --fg-nav-ink: #dbe3f7;
  --fg-nav-muted: #8491b3;
  --fg-nav-line: #222c4d;
  --fg-nav-hover: rgba(34, 211, 238, 0.1);
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
span[style*="font-family:'monospace'"]:not(td *) {   /* code, not a table's figures */
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
  width: 100% !important; aspect-ratio: var(--chart-shape) !important;
  overflow: hidden; margin: 8px 0 !important;
}
.fg-chart > img { height: 100%; object-fit: contain; }
/* a picture was drawn for paper; dim it rather than let it glare */
p > img, .fg-chart:not(.fg-drawn) > img { opacity: 0.9; }
.fg-table { padding: 8px 10px; margin: 8px 0 !important; width: auto; }
.fg-scroll .flograph-table { width: 100%; border-collapse: collapse; }
.flograph-table > thead > tr > th {
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--muted);
  padding: 4px 9px; border-bottom: 1px solid var(--accent); white-space: nowrap;
}
.flograph-table > tbody > tr > td {
  padding: 3px 9px; border-bottom: 1px solid var(--line); white-space: nowrap;
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
.fg-db > i { background-color: rgba(255, 255, 255, 0.07); }
.fg-bar input {
  font-size: 12px; padding: 5px 10px; color: var(--ink);
  background: var(--bg); border: 1px solid var(--line); border-radius: 6px;
  outline: none;
}
.fg-bar input:focus { border-color: var(--accent);
                      box-shadow: 0 0 0 3px rgba(34, 211, 238, 0.18); }
.fg-bar .fg-count { color: var(--muted); }
.fg-bar button { color: var(--ink); border-color: var(--line); }
.fg-bar button:hover { border-color: var(--accent); color: var(--accent); }
.fg-scroll::-webkit-scrollbar { width: 8px; height: 8px; }
.fg-scroll::-webkit-scrollbar-thumb { background: var(--line); border-radius: 4px; }
.fg-scroll { scrollbar-color: var(--line) transparent; }

table[style*="border-style:none"] { width: 100% !important; table-layout: fixed; }
table[style*="border-style:none"] > tbody > tr > td { padding: 0 7px !important; }
table[style*="border-style:none"] > tbody > tr > td:first-child { padding-left: 0 !important; }
table[style*="border-style:none"] > tbody > tr > td:last-child { padding-right: 0 !important; }
table[style*="border-style:none"] .fg-chart { aspect-ratio: 1.4 / 1 !important; }

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

/* the web layout: dark glass bars, panels for sections, a lit tab */
:root { --fg-nav-font: Inter, "Segoe UI", "Noto Sans", system-ui, sans-serif; }
.fg-top { background: rgba(13, 20, 40, 0.82);
  -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px); }
.fg-top-title { background: linear-gradient(90deg, #ffffff, var(--accent));
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.fg-top-links a.fg-on { text-shadow: 0 0 12px rgba(34, 211, 238, 0.55); }
.fg-side { background: linear-gradient(180deg, #0d1428, #0a0f1c); }
.fg-side a.fg-on { box-shadow: inset 2px 0 0 var(--accent); border-radius: 0 6px 6px 0; }
.fg-side ul ul { border-left-color: #1d2747; }
.fg-tabbar > button { font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; }
.fg-tabbar > button.fg-on { color: var(--accent);
  box-shadow: 0 8px 14px -10px rgba(34, 211, 238, 0.9); }
details.fg-details { background: var(--panel); border-color: var(--line);
  border-radius: 10px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3); }
details.fg-details > summary { color: #ffffff; }
details.fg-details[open] > summary { background: var(--panel-2); }
.fg-details-body .fg-chart, .fg-details-body .fg-table { box-shadow: none; }
.fg-drop { background: #0d1428; box-shadow: 0 16px 40px rgba(0, 0, 0, 0.55),
  0 0 0 1px rgba(34, 211, 238, 0.12); }
.fg-pager a { background: var(--panel); }
.fg-pager a:hover { box-shadow: 0 0 0 1px var(--accent), 0 0 18px rgba(34, 211, 238, 0.2); }
.fg-icon-btn { background: var(--panel); }
@media print {
  details.fg-details { background: #fff; box-shadow: none; }
  details.fg-details > summary, details.fg-details[open] > summary { color: #111; background: none; }
}
"""


LEDGER = """/* Ledger — the financial broadsheet. Warm paper, rules above and below a
   table and nowhere else, figures set in columns, one ink-teal accent.
   Minimal on purpose: every line on the page carries a number or says
   what one means. Totals are underlined twice, as an accountant would.
   The charts take the paper and the palette (see the --fg-chart- lines). */
:root {
  --paper: #fbf8f1;
  --paper-2: #f2ede1;
  --ink: #1d1b16;
  --muted: #6f6857;
  --rule: #1d1b16;
  --hair: #dcd4c2;
  --accent: #0e5a61;
  --accent-soft: rgba(14, 90, 97, 0.07);
  --serif: "Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, serif;
  --sans: "Source Sans 3", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  --fg-head: #fbf8f1;
  --chart-shape: 2.5 / 1;
  --fg-chart-paper: #fbf8f1;
  --fg-chart-plot: #fbf8f1;
  --fg-chart-ink: #3d392f;
  --fg-chart-grid: #e7e0d0;
  --fg-chart-font: "Source Sans 3", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  --fg-chart-colors: #0e5a61, #c8553d, #d9a441, #5b7f95, #8c6d9f, #6b8f4e, #9c9484, #2d3142;
  /* the web layout: sidebar, top bar, tabs, sections */
  --fg-text-size: 13px;
  --fg-accent: #0e5a61;
  --fg-nav-bg: #f6f1e6;
  --fg-nav-ink: #1d1b16;
  --fg-nav-muted: #6f6857;
  --fg-nav-line: #dcd4c2;
  --fg-nav-hover: rgba(14, 90, 97, 0.07);
  --fg-nav-font: "Source Sans 3", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  --fg-side-w: 244px;
}
html.fg-has-top { --fg-top-h: 46px; }
body {
  font-family: var(--sans) !important;
  font-size: 13px !important;
  line-height: 1.5;
  color: var(--ink);
  background: var(--paper) !important;
  max-width: 1160px;
  margin: 0 auto !important;
  padding: 30px 38px 60px !important;
  font-variant-numeric: tabular-nums lining-nums;
}
::selection { background: rgba(14, 90, 97, 0.18); }
span[style*="font-family:'sans-serif'"] { font-family: inherit !important; }
p span, li, li span, h1 span, h2 span, h3 span, h4 span { font-size: inherit !important; }
p { margin: 4px 0 !important; max-width: 80ch; }
a { color: var(--accent); text-decoration-thickness: 1px; text-underline-offset: 2px; }

/* the masthead: a serif title over a double rule, the standfirst in italic */
h1 {
  font-family: var(--serif); font-size: 32px; font-weight: 600;
  letter-spacing: -0.012em; line-height: 1.12;
  margin: 0 0 8px !important; padding: 0 0 12px !important;
  border-bottom: 3px double var(--rule);
}
h1 + p { font-family: var(--serif); font-style: italic; font-size: 15px; color: var(--muted); }
h2 {
  font-family: var(--serif); font-size: 20px; font-weight: 600; line-height: 1.2;
  margin: 34px 0 6px !important; padding: 9px 0 0 !important;
  border-top: 1px solid var(--rule);
}
h3 {
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.14em;
  text-transform: uppercase; color: var(--accent);
  margin: 20px 0 5px !important;
}
h4 { font-family: var(--serif); font-style: italic; font-size: 14px; margin: 12px 0 3px !important; }

/* a > quote is the pull quote */
p[style*="margin-left:40px; margin-right:40px"] {
  margin: 16px 0 !important; padding: 2px 0 2px 18px; max-width: 70ch;
  border-left: 3px solid var(--accent);
  font-family: var(--serif); font-size: 16px; line-height: 1.45; color: var(--ink);
}
span[style*="font-family:'monospace'"]:not(td *) {   /* code, not a table's figures */
  font-family: "JetBrains Mono", "IBM Plex Mono", Consolas, monospace !important;
  font-size: 0.88em !important; background: var(--paper-2);
  border-radius: 2px; padding: 0 3px;
}
ul { margin: 6px 0 !important; padding-left: 18px; }
li { margin: 2px 0 !important; }
li::marker { color: var(--accent); }

/* a figure: ruled above, hairline below, no box */
.fg-chart {
  width: 100% !important; aspect-ratio: var(--chart-shape) !important;
  margin: 10px 0 !important; background: var(--fg-chart-paper);
  border-top: 1px solid var(--rule); border-bottom: 1px solid var(--hair);
}
.fg-chart > img { height: 100%; object-fit: contain; }

/* tables, booktabs: a heavy rule above and below, a light one under the
   headings, and no lines between the columns at all */
.fg-table { margin: 12px 0 !important; }
.fg-scroll { border-top: 2px solid var(--rule); border-bottom: 2px solid var(--rule); }
.fg-scroll .flograph-table { border-collapse: collapse; width: 100%; }
.flograph-table > thead > tr > th {
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--muted); padding: 5px 12px 4px !important;
  border-bottom: 1px solid var(--rule); white-space: nowrap;
}
.flograph-table th.fg-band {
  font-family: var(--serif); font-style: italic; font-size: 12.5px;
  letter-spacing: 0; text-transform: none; color: var(--ink);
  border-bottom: 1px solid var(--hair);
}
.flograph-table > tbody > tr > td {
  padding: 3px 12px !important; border-bottom: 1px solid var(--hair); white-space: nowrap;
}
.flograph-table > tbody > tr:last-child > td { border-bottom: 0; }
.fg-scroll tbody tr:hover > td { box-shadow: inset 0 0 0 9999px var(--accent-soft); }
.fg-sortable thead th[data-fg-sort]::after { color: var(--accent); }
.fg-db > i { background-color: var(--paper-2); }
/* structure rows: total, group, subtotal (delete to keep your own colours) */
.flograph-table > tbody > tr[data-fg-kind] > td {
  background-color: var(--paper) !important; color: var(--ink) !important;
  border: 0 !important; border-top: 1px solid var(--hair) !important;
  font-weight: 700;
}
.flograph-table > tbody > tr[data-fg-kind="group"] > td {
  background-color: var(--paper-2) !important; font-family: var(--serif);
  font-size: 13.5px;
}
.flograph-table > tbody > tr[data-fg-kind="group"] > td:first-child { color: var(--accent) !important; }
.flograph-table > tbody > tr[data-fg-kind="total"] > td {
  border-top: 1px solid var(--rule) !important;
  border-bottom: 3px double var(--rule) !important;
}
.fg-bar { margin-bottom: 8px; }
.fg-bar input {
  font-size: 12.5px; padding: 4px 2px; border: 0; border-radius: 0;
  border-bottom: 1px solid var(--rule); background: transparent; outline: none;
}
.fg-bar input:focus { border-bottom: 2px solid var(--accent); }
.fg-bar button { border-radius: 0; border-color: var(--hair); }

/* ```columns: a newspaper's columns, with a rule between them */
table[style*="border-style:none"] { width: 100% !important; table-layout: fixed; }
table[style*="border-style:none"] > tbody > tr > td { padding: 0 14px !important; }
table[style*="border-style:none"] > tbody > tr > td:first-child { padding-left: 0 !important; }
table[style*="border-style:none"] > tbody > tr > td:last-child { padding-right: 0 !important; }
table[style*="border-style:none"] > tbody > tr > td + td { border-left: 1px solid var(--hair) !important; }
table[style*="border-style:none"] .fg-chart { aspect-ratio: 1.45 / 1 !important; }

/* the web layout: a masthead bar, a sidebar like a contents column, tabs
   in small capitals, sections that open with a plus */
.fg-top { background: var(--paper); border-bottom: 3px double var(--rule); }
.fg-top-title { font-family: var(--serif); font-size: 17px; font-weight: 600; letter-spacing: -0.01em; }
.fg-top-links a { font-size: 11px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; }
.fg-top-links a.fg-on { border-bottom-color: var(--rule); color: var(--ink); }
.fg-side { background: var(--fg-nav-bg); border-right: 1px solid var(--rule); }
.fg-side-head { font-family: var(--serif); font-size: 13px; font-style: italic;
  letter-spacing: 0; text-transform: none; color: var(--ink); }
.fg-side a { border-radius: 0; padding: 4px 8px; }
.fg-side a.fg-on { background: transparent; color: var(--accent);
  box-shadow: inset 2px 0 0 var(--accent); }
.fg-icon-btn { border-radius: 0; background: var(--paper); border-color: var(--hair); }
.fg-tabbar { border-bottom: 1px solid var(--rule) !important; }
.fg-tabbar > button { font-variant: small-caps; font-size: 13.5px; letter-spacing: 0.06em;
  border-radius: 0; padding: 6px 14px 5px; }
.fg-tabbar > button.fg-on { color: var(--ink); border-bottom: 3px solid var(--accent); }
details.fg-details { border: 0; border-top: 1px solid var(--rule);
  border-bottom: 1px solid var(--hair); border-radius: 0; margin: 14px 0; }
details.fg-details > summary { font-family: var(--serif); font-size: 15px; padding: 8px 0; }
details.fg-details > summary:hover { background: transparent; color: var(--accent); }
details.fg-details > summary::before {
  content: "+"; border: 0; transform: none; width: 14px; height: auto;
  font: 600 17px/1 var(--sans); color: var(--accent);
}
details.fg-details[open] > summary::before { content: "\\2212"; transform: none; }
details.fg-details[open] > summary { border-bottom: 0; }
.fg-details-body { padding: 0 0 12px 24px; }
.fg-drop { background: var(--paper); border: 1px solid var(--rule); border-radius: 0;
  box-shadow: 4px 4px 0 var(--paper-2); }
.fg-drop a { border-radius: 0; }
.fg-pager { border-top: 3px double var(--rule); }
.fg-pager a { border: 0; border-radius: 0; padding: 6px 0; }
.fg-pager span { font-family: var(--serif); font-size: 15px; color: var(--ink); }
.fg-pager a:hover span { color: var(--accent); }

@media print {
  body { background: #fff !important; }
  .fg-chart { border-top-color: #000; }
}
"""


TERMINAL = """/* Terminal — the trading desk. Near-black glass, amber for what matters,
   a monospace grid where every figure sits in its column, panels headed
   like a market screen. As dense as a page can be and still be read;
   the charts go dark and take the desk's palette (the --fg-chart- lines).
   Printed, it goes back to ink on white. */
:root {
  --bg: #07090c;
  --panel: #0d1117;
  --panel-2: #121821;
  --ink: #d7dde5;
  --dim: #7d8794;
  --line: #1c232e;
  --line-2: #2a3442;
  --amber: #ffb000;
  --green: #3fd07b;
  --red: #ff5a5f;
  --cyan: #4cc9f0;
  --mono: "JetBrains Mono", "IBM Plex Mono", "Cascadia Mono", "SF Mono", Consolas, "DejaVu Sans Mono", monospace;
  --fg-head: #121821;
  --chart-shape: 3 / 1;
  --fg-chart-paper: #0a0d12;
  --fg-chart-plot: #0a0d12;
  --fg-chart-ink: #9aa4b2;
  --fg-chart-grid: #1a212b;
  --fg-chart-font: "JetBrains Mono", "IBM Plex Mono", "Cascadia Mono", Consolas, monospace;
  --fg-chart-colors: #ffb000, #4cc9f0, #3fd07b, #ff5a5f, #b388ff, #f4f1bb, #ff8c42, #9aa4b2;
  /* the web layout */
  --fg-text-size: 12px;
  --fg-accent: #ffb000;
  --fg-nav-bg: #0a0d12;
  --fg-nav-ink: #d7dde5;
  --fg-nav-muted: #7d8794;
  --fg-nav-line: #1c232e;
  --fg-nav-hover: rgba(255, 176, 0, 0.08);
  --fg-nav-font: "JetBrains Mono", "IBM Plex Mono", "Cascadia Mono", Consolas, monospace;
  --fg-side-w: 228px;
}
html.fg-has-top { --fg-top-h: 34px; }
body {
  font-family: var(--mono) !important;
  font-size: 12px !important;
  line-height: 1.45;
  color: var(--ink) !important;
  background:
    linear-gradient(rgba(255, 255, 255, 0.012) 1px, transparent 1px) 0 0 / 100% 3px,
    var(--bg) !important;
  margin: 0 !important;
  padding: 16px 20px 40px !important;
  max-width: none;
  font-variant-numeric: tabular-nums slashed-zero;
}
::selection { background: var(--amber); color: #000; }
span[style*="font-family:'sans-serif'"], span[style*="font-family:'monospace'"] { font-family: inherit !important; }
p span, li, li span, h1 span, h2 span, h3 span, h4 span { font-size: inherit !important; }
p { margin: 3px 0 !important; }
a { color: var(--cyan); }

h1 {
  font-size: 15px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--amber); margin: 0 0 6px !important; padding: 0 0 7px !important;
  border-bottom: 1px solid var(--line-2);
}
h1::before { content: "\\25A0  "; color: var(--amber); }
h1 + p { color: var(--dim); }
/* a panel heading, as on a market screen */
h2 {
  display: flex; align-items: center; gap: 10px;
  font-size: 11px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase;
  color: var(--ink); background: var(--panel-2);
  margin: 18px 0 6px !important; padding: 5px 9px !important;
  border-left: 3px solid var(--amber);
}
h2::after { content: ""; flex: 1; height: 1px; background: var(--line-2); }
h3 { font-size: 11.5px; font-weight: 700; color: var(--cyan); margin: 12px 0 3px !important; }
h3::before { content: "\\203A\\00A0"; color: var(--dim); }
h4 { font-size: 11px; color: var(--dim); text-transform: uppercase; margin: 10px 0 2px !important; }

/* a > quote is a system message */
p[style*="margin-left:40px; margin-right:40px"] {
  margin: 10px 0 !important; padding: 6px 10px 6px 12px;
  border: 1px solid rgba(63, 208, 123, 0.35); border-left: 3px solid var(--green);
  background: rgba(63, 208, 123, 0.06); color: #dff7e9;
}
p[style*="margin-left:40px; margin-right:40px"]::before { content: "\\00BB  "; color: var(--green); }
span[style*="font-family:'monospace'"]:not(td *) {   /* code, not a table's figures */
  color: var(--amber); background: rgba(255, 176, 0, 0.08); padding: 0 3px;
}
ul { margin: 6px 0 !important; padding-left: 16px; }
li { margin: 1px 0 !important; }
li::marker { content: "\\25B8  "; color: var(--amber); }

/* charts: a thin-framed panel */
.fg-chart {
  width: 100% !important; aspect-ratio: var(--chart-shape) !important;
  margin: 6px 0 !important; background: var(--fg-chart-paper);
  border: 1px solid var(--line-2); border-radius: 2px; overflow: hidden;
}
.fg-chart > img { height: 100%; object-fit: contain; opacity: 0.9; }
p > img { border: 1px solid var(--line-2); opacity: 0.9; }

/* tables: a grid, every cell in its own box, figures in columns */
.fg-table { margin: 6px 0 !important; background: var(--panel); border: 1px solid var(--line-2); }
.fg-bar { padding: 6px 8px 0; margin: 0 0 6px !important; }
.fg-scroll .flograph-table { border-collapse: collapse; width: 100%; }
.flograph-table > thead > tr > th {
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--amber); padding: 4px 8px !important;
  border-bottom: 1px solid var(--amber); border-right: 1px solid var(--line);
  white-space: nowrap;
}
.flograph-table th.fg-band { color: var(--cyan); border-bottom-color: var(--line-2); }
.flograph-table > tbody > tr > td {
  padding: 2px 8px !important; color: var(--ink);
  border-bottom: 1px solid var(--line); border-right: 1px solid var(--line);
  white-space: nowrap;
}
.flograph-table > tbody > tr:nth-child(even) > td { background-color: rgba(255, 255, 255, 0.018); }
.fg-scroll tbody tr:hover > td { box-shadow: inset 0 0 0 9999px rgba(255, 176, 0, 0.08); }
.fg-sortable thead th[data-fg-sort] { color: #fff; }
.fg-sortable thead th[data-fg-sort]::after { color: var(--amber); }
.fg-db > i { background-color: rgba(255, 255, 255, 0.07); }
/* structure rows: total, group, subtotal (delete to keep your own colours) */
.flograph-table > tbody > tr[data-fg-kind] > td {
  background-color: #151c27 !important; color: #ffffff !important;
  border-bottom: 1px solid var(--line-2) !important; font-weight: 700;
}
.flograph-table > tbody > tr[data-fg-kind="group"] > td:first-child { color: var(--cyan) !important; }
.flograph-table > tbody > tr[data-fg-kind="total"] > td {
  background-color: #1d1606 !important; color: var(--amber) !important;
  border-top: 1px solid var(--amber) !important;
}
/* the search box is a prompt */
.fg-bar::before { content: ">"; color: var(--amber); font-weight: 700; }
.fg-bar input {
  font: inherit; font-size: 12px; padding: 3px 8px; color: var(--amber);
  caret-color: var(--amber); background: var(--bg);
  border: 1px solid var(--line-2); border-radius: 0; outline: none;
}
.fg-bar input:focus { border-color: var(--amber); }
.fg-bar input::placeholder { color: var(--dim); }
.fg-bar .fg-count { color: var(--dim); }
.fg-bar button {
  border-radius: 0; font-size: 10.5px; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--dim); border-color: var(--line-2);
}
.fg-bar button:hover { color: var(--amber); border-color: var(--amber); background: transparent; }
.fg-scroll::-webkit-scrollbar { width: 8px; height: 8px; }
.fg-scroll::-webkit-scrollbar-thumb { background: var(--line-2); }
.fg-scroll { scrollbar-color: var(--line-2) transparent; }

/* ```columns: panels side by side */
table[style*="border-style:none"] { width: 100% !important; table-layout: fixed; }
table[style*="border-style:none"] > tbody > tr > td { padding: 0 4px !important; }
table[style*="border-style:none"] > tbody > tr > td:first-child { padding-left: 0 !important; }
table[style*="border-style:none"] > tbody > tr > td:last-child { padding-right: 0 !important; }
table[style*="border-style:none"] .fg-chart { aspect-ratio: 1.6 / 1 !important; }

/* the web layout: a command strip with numbered function keys, square
   tabs, sections that open like a [+] */
.fg-top { background: #000; border-bottom: 1px solid var(--line-2); gap: 10px; }
.fg-top-title { color: var(--amber); font-size: 12px; font-weight: 700;
  letter-spacing: 0.1em; text-transform: uppercase; }
.fg-top-links { counter-reset: fg-key; gap: 0 !important; }
.fg-top-links a { font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;
  padding: 0 10px; border-bottom: 0 !important; }
.fg-top-links > a::before, .fg-top-item > a::before {
  counter-increment: fg-key; content: "F" counter(fg-key); color: var(--dim);
  margin-right: 6px;   /* a flex item: a trailing space in it is dropped */
}
.fg-top-links a.fg-on { background: var(--amber); color: #000 !important; }
.fg-top-links a.fg-on::before { color: rgba(0, 0, 0, 0.55); }
.fg-top-item > a.fg-on + .fg-caret { background: var(--amber); color: #000; border-bottom-color: transparent; }
.fg-side { background: #000; border-right: 1px solid var(--line-2); font-size: 11.5px; }
.fg-side-head { color: var(--amber); letter-spacing: 0.14em; }
.fg-side a { border-radius: 0; padding: 3px 8px; }
.fg-side a.fg-on { background: rgba(255, 176, 0, 0.1); color: var(--amber);
  box-shadow: inset 2px 0 0 var(--amber); }
.fg-icon-btn { border-radius: 0; background: #000; border-color: var(--line-2); color: var(--amber); }
.fg-tabbar { border-bottom: 1px solid var(--line-2) !important; gap: 0 !important; }
.fg-tabbar > button {
  font-size: 10.5px; letter-spacing: 0.08em; text-transform: uppercase;
  border: 1px solid transparent; border-bottom: 0; border-radius: 0; padding: 5px 12px;
}
.fg-tabbar > button.fg-on {
  color: var(--amber); background: var(--panel-2); border-color: var(--line-2);
  box-shadow: inset 0 2px 0 var(--amber);
}
details.fg-details { background: var(--panel); border: 1px solid var(--line-2);
  border-radius: 0; margin: 8px 0; }
details.fg-details > summary {
  font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; padding: 5px 9px;
}
details.fg-details > summary::before {
  content: "[+]"; border: 0; transform: none; width: auto; height: auto; color: var(--amber);
}
details.fg-details[open] > summary::before { content: "[\\2212]"; transform: none; }
details.fg-details[open] > summary { background: var(--panel-2); }
.fg-details-body { padding: 6px 10px 8px; }
.fg-drop { background: #000; border: 1px solid var(--line-2); border-top: 2px solid var(--amber);
  border-radius: 0; }
.fg-drop a { border-radius: 0; font-size: 11.5px; }
.fg-pager { border-top: 1px solid var(--line-2); }
.fg-pager a { border-radius: 0; border-color: var(--line-2); background: var(--panel); }
.fg-pager a:hover { border-color: var(--amber); }
.fg-pager span { color: var(--amber); font-size: 12px; }
.fg-inside a { color: var(--cyan); }

@media print {
  body { background: #fff !important; color: #111 !important; }
  h1, h1::before { color: #111; }
  h2 { background: none; color: #111; }
  h3 { color: #111; }
  .fg-table, details.fg-details { background: #fff; }
  .flograph-table > tbody > tr > td { color: #111; }
  .flograph-table > tbody > tr[data-fg-kind] > td { background-color: #eee !important; color: #111 !important; }
}
"""


AURORA = """/* Aurora — the showpiece. A night sky of colour behind frosted-glass
   panels, gradient headings, tabs that light up, the flograph violet
   leading. Maximal, but built for reading numbers: tables stay tight and
   high-contrast, figures line up, totals glow rather than shout. The
   charts go glass-clear and take the palette (the --fg-chart- lines). */
:root {
  --sky: #0a0e1f;
  --glass: rgba(255, 255, 255, 0.055);
  --glass-2: rgba(255, 255, 255, 0.09);
  --edge: rgba(255, 255, 255, 0.12);
  --ink: #eef1ff;
  --muted: #a4acd3;
  --line: rgba(255, 255, 255, 0.08);
  --violet: #7c6cf6;
  --cyan: #22d3ee;
  --pink: #f472b6;
  --gold: #fbbf24;
  --grad: linear-gradient(120deg, #9d8cff 0%, #22d3ee 55%, #f472b6 100%);
  --card: rgba(18, 22, 46, 0.72);
  --fg-head: #161b38;
  --chart-shape: 2.4 / 1;
  --fg-chart-paper: rgba(0, 0, 0, 0);
  --fg-chart-plot: rgba(0, 0, 0, 0);
  --fg-chart-ink: #c7cef3;
  --fg-chart-grid: rgba(255, 255, 255, 0.08);
  --fg-chart-font: Inter, "Segoe UI", "Noto Sans", system-ui, sans-serif;
  --fg-chart-colors: #9d8cff, #22d3ee, #f472b6, #fbbf24, #34d399, #fb7185, #60a5fa, #c084fc;
  /* the web layout */
  --fg-text-size: 13px;
  --fg-accent: #9d8cff;
  --fg-nav-bg: rgba(12, 16, 36, 0.78);
  --fg-nav-ink: #eef1ff;
  --fg-nav-muted: #a4acd3;
  --fg-nav-line: rgba(255, 255, 255, 0.1);
  --fg-nav-hover: rgba(157, 140, 255, 0.14);
  --fg-nav-font: Inter, "Segoe UI", "Noto Sans", system-ui, sans-serif;
  --fg-side-w: 252px;
}
html.fg-has-top { --fg-top-h: 52px; }
body {
  font-family: Inter, "Segoe UI", "Noto Sans", system-ui, sans-serif !important;
  font-size: 13px !important;
  line-height: 1.5;
  color: var(--ink) !important;
  background:
    radial-gradient(900px 520px at 8% -8%, rgba(124, 108, 246, 0.42), transparent 62%),
    radial-gradient(760px 480px at 96% 6%, rgba(34, 211, 238, 0.24), transparent 60%),
    radial-gradient(1000px 640px at 55% 112%, rgba(244, 114, 182, 0.20), transparent 62%),
    var(--sky) !important;
  background-attachment: fixed !important;
  max-width: 1240px;
  margin: 0 auto !important;
  padding: 34px 32px 64px !important;
  font-variant-numeric: tabular-nums;
}
::selection { background: rgba(157, 140, 255, 0.45); }
span[style*="font-family:'sans-serif'"] { font-family: inherit !important; }
p span, li, li span, h1 span, h2 span, h3 span, h4 span { font-size: inherit !important; }
p { margin: 4px 0 !important; }
a { color: var(--cyan); }

h1 {
  font-size: 34px; font-weight: 800; letter-spacing: -0.03em; line-height: 1.1;
  margin: 0 0 10px !important; padding: 0 !important; width: fit-content;
  background: linear-gradient(100deg, #ffffff 0%, #c9c1ff 35%, var(--cyan) 70%, var(--pink) 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
h1 + p { color: var(--muted); font-size: 14px; }
h2 {
  font-size: 19px; font-weight: 750; letter-spacing: -0.015em; color: #ffffff;
  margin: 34px 0 8px !important;
}
h2::after {
  content: ""; display: block; width: 44px; height: 3px; margin-top: 7px;
  border-radius: 3px; background: var(--grad);
}
h3 {
  font-size: 11px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase;
  color: var(--cyan); margin: 20px 0 5px !important;
}
h4 { font-size: 13px; color: var(--muted); margin: 12px 0 3px !important; }

/* a > quote is the insight: a card with a gradient edge */
p[style*="margin-left:40px; margin-right:40px"] {
  margin: 16px 0 !important; padding: 14px 18px; font-size: 15px; line-height: 1.5;
  color: #ffffff; border: 1px solid transparent; border-radius: 16px;
  background:
    linear-gradient(rgba(20, 24, 50, 0.92), rgba(20, 24, 50, 0.92)) padding-box,
    var(--grad) border-box;
  box-shadow: 0 18px 50px rgba(124, 108, 246, 0.18);
}
span[style*="font-family:'monospace'"]:not(td *) {   /* code, not a table's figures */
  font-family: "JetBrains Mono", "Cascadia Code", Consolas, monospace !important;
  font-size: 0.88em !important; color: #d6ceff;
  background: rgba(157, 140, 255, 0.14); border-radius: 5px; padding: 1px 5px;
}
ul { margin: 6px 0 !important; padding-left: 18px; }
li { margin: 2px 0 !important; }
li::marker { color: var(--pink); }

/* glass panels */
.fg-chart, .fg-table, p > img {
  background: var(--glass); border: 1px solid var(--edge); border-radius: 16px;
  -webkit-backdrop-filter: blur(16px) saturate(140%); backdrop-filter: blur(16px) saturate(140%);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.08);
}
.fg-chart {
  width: 100% !important; aspect-ratio: var(--chart-shape) !important;
  overflow: hidden; margin: 10px 0 !important;
}
.fg-chart > img { height: 100%; object-fit: contain; opacity: 0.92; }
/* clear glass is no ground for a chart that fills the screen */
.fg-chart.fg-full.fg-full { background: var(--sky) !important; }
.fg-chart::backdrop { background: var(--sky); }
.fg-table { padding: 8px 10px; margin: 10px 0 !important; }
.fg-scroll .flograph-table { border-collapse: collapse; width: 100%; }
.flograph-table > thead > tr > th {
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--muted); padding: 4px 10px !important;
  border-bottom: 1px solid rgba(157, 140, 255, 0.45); white-space: nowrap;
}
.flograph-table th.fg-band { color: #d6ceff; border-bottom-color: var(--line); }
.flograph-table > tbody > tr > td {
  padding: 3px 10px !important; color: var(--ink);
  border-bottom: 1px solid var(--line); white-space: nowrap;
}
.fg-scroll tbody tr:hover > td { box-shadow: inset 0 0 0 9999px rgba(157, 140, 255, 0.10); }
.fg-sortable thead th[data-fg-sort] { color: #ffffff; }
.fg-sortable thead th[data-fg-sort]::after { color: var(--cyan); }
.fg-db > i { background-color: rgba(255, 255, 255, 0.08); }
/* structure rows: total, group, subtotal (delete to keep your own colours) */
.flograph-table > tbody > tr[data-fg-kind] > td {
  background-color: #1a1f44 !important; color: #ffffff !important;
  border: 0 !important; border-bottom: 1px solid var(--line) !important; font-weight: 700;
}
.flograph-table > tbody > tr[data-fg-kind="group"] > td:first-child { color: var(--cyan) !important; }
.flograph-table > tbody > tr[data-fg-kind="total"] > td {
  background-color: #2a2360 !important;
  border-top: 1px solid rgba(157, 140, 255, 0.7) !important;
  text-shadow: 0 0 14px rgba(157, 140, 255, 0.6);
}
.fg-bar { margin-bottom: 10px; }
.fg-bar input {
  font-size: 12.5px; padding: 6px 14px; color: var(--ink); border-radius: 999px;
  background: rgba(255, 255, 255, 0.07); border: 1px solid var(--edge); outline: none;
}
.fg-bar input::placeholder { color: var(--muted); }
.fg-bar input:focus { border-color: var(--violet); box-shadow: 0 0 0 4px rgba(124, 108, 246, 0.22); }
.fg-bar .fg-count { color: var(--muted); }
.fg-bar button { border-radius: 999px; border-color: var(--edge); color: var(--ink); }
.fg-bar button:hover { background: rgba(157, 140, 255, 0.18); border-color: var(--violet); }
.fg-scroll::-webkit-scrollbar { width: 8px; height: 8px; }
.fg-scroll::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.14); border-radius: 4px; }
.fg-scroll { scrollbar-color: rgba(255, 255, 255, 0.14) transparent; }

/* ```columns: glass side by side */
table[style*="border-style:none"] { width: 100% !important; table-layout: fixed; }
table[style*="border-style:none"] > tbody > tr > td { padding: 0 8px !important; }
table[style*="border-style:none"] > tbody > tr > td:first-child { padding-left: 0 !important; }
table[style*="border-style:none"] > tbody > tr > td:last-child { padding-right: 0 !important; }
table[style*="border-style:none"] .fg-chart { aspect-ratio: 1.45 / 1 !important; }

/* the web layout: frosted bars, a lit pill for the tab, glass sections */
.fg-top, .fg-side, .fg-drop {
  -webkit-backdrop-filter: blur(18px) saturate(150%); backdrop-filter: blur(18px) saturate(150%);
}
.fg-top { border-bottom: 1px solid var(--edge); box-shadow: 0 1px 0 rgba(124, 108, 246, 0.35); }
.fg-top-title {
  font-size: 15px; font-weight: 800; letter-spacing: -0.01em;
  background: var(--grad); -webkit-background-clip: text; background-clip: text; color: transparent;
}
.fg-top-links a { border-bottom-width: 2px; }
.fg-top-links a.fg-on {
  color: #ffffff; border-bottom-color: transparent;
  background: linear-gradient(90deg, #9d8cff, #22d3ee) bottom / 100% 2px no-repeat;
}
.fg-side { border-right: 1px solid var(--edge); }
.fg-side a { border-radius: 8px; }
.fg-side a.fg-on { color: #ffffff; background: linear-gradient(90deg, rgba(157, 140, 255, 0.28), rgba(34, 211, 238, 0.08)); }
.fg-icon-btn { background: rgba(255, 255, 255, 0.06); border-color: var(--edge); border-radius: 10px; }
.fg-tabbar { border-bottom: 0 !important; gap: 4px !important; padding: 4px;
  background: rgba(255, 255, 255, 0.05); border: 1px solid var(--edge);
  border-radius: 999px; width: fit-content; max-width: 100%; }
.fg-tabbar > button { border: 0; border-radius: 999px; padding: 6px 16px; margin: 0; font-weight: 600; }
.fg-tabbar > button:hover { background: rgba(255, 255, 255, 0.07); }
.fg-tabbar > button.fg-on {
  color: #ffffff; background: linear-gradient(120deg, #7c6cf6, #22b8d8);
  box-shadow: 0 6px 20px rgba(124, 108, 246, 0.45);
}
.fg-tab { padding-top: 12px; }
details.fg-details {
  border: 1px solid var(--edge); border-radius: 16px; background: var(--glass);
  -webkit-backdrop-filter: blur(16px); backdrop-filter: blur(16px);
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.28);
}
details.fg-details > summary { padding: 12px 16px; }
details.fg-details > summary::before { border-color: var(--cyan); }
details.fg-details[open] > summary { border-bottom-color: var(--line); }
.fg-details-body { padding: 10px 16px 14px; }
.fg-details-body .fg-chart, .fg-details-body .fg-table { box-shadow: none; }
.fg-drop { background: rgba(14, 18, 40, 0.92); border: 1px solid var(--edge); border-radius: 14px;
  margin-top: 6px; box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5); }
.fg-drop a { border-radius: 8px; }
.fg-pager { border-top: 1px solid var(--line); }
.fg-pager a { border: 1px solid transparent; border-radius: 14px;
  background:
    linear-gradient(rgba(20, 24, 50, 0.92), rgba(20, 24, 50, 0.92)) padding-box,
    linear-gradient(120deg, var(--edge), var(--edge)) border-box; }
.fg-pager a:hover { background:
    linear-gradient(rgba(20, 24, 50, 0.92), rgba(20, 24, 50, 0.92)) padding-box,
    var(--grad) border-box; }
.fg-pager span { color: #ffffff; }
.fg-inside a { color: var(--cyan); }

@media print {
  body { background: #fff !important; color: #111 !important; }
  h1 { background: none; color: #111; }
  h2, h3 { color: #111; }
  h2::after { background: #111; }
  p[style*="margin-left:40px; margin-right:40px"] { background: none; border: 1px solid #999; color: #111; box-shadow: none; }
  .fg-chart, .fg-table, p > img, details.fg-details { background: #fff; box-shadow: none; border-color: #ccc; }
  .flograph-table > tbody > tr > td { color: #111; }
  .flograph-table > tbody > tr[data-fg-kind] > td { background-color: #eee !important; color: #111 !important; text-shadow: none; }
}
"""


# every live theme dresses the plain tables too
COMPACT += _plain_tables("transparent", "#687085", "#e4e7ed", "#f5f7fa", "#1b2130", "#eef1f6", head_rule="#c9ced8", vertical=False, pad="3px 8px")
DASHBOARD += _plain_tables("#ffffff", "#64708a", "#e6e9f0", "#f6f7fb", "#172033", "#eef0f5", table_bg="#ffffff", head_rule="#e6e9f0", vertical=False)
MIDNIGHT += _plain_tables("#111830", "#8491b3", "#222c4d", "#172042", "#ffffff", "rgba(255, 255, 255, 0.07)", table_bg="#111830", head_rule="#22d3ee", dark=True)
LEDGER += _plain_tables("transparent", "#6f6857", "#dcd4c2", "#f2ede1", "#1d1b16", "#f2ede1", head_rule="#1d1b16", vertical=False, pad="3px 12px", extra='table[cellspacing="2"] { border-top: 2px solid #1d1b16 !important; border-bottom: 2px solid #1d1b16 !important; }\n')
TERMINAL += _plain_tables("#121821", "#ffb000", "#1c232e", "#151c27", "#ffffff", "rgba(255, 255, 255, 0.07)", table_bg="#0d1117", head_rule="#ffb000", dark=True, pad="2px 8px")
AURORA += _plain_tables("#161b38", "#a4acd3", "rgba(255, 255, 255, 0.08)", "#1a1f44", "#ffffff", "rgba(255, 255, 255, 0.08)", table_bg="rgba(255, 255, 255, 0.04)", head_rule="rgba(157, 140, 255, 0.45)", vertical=False, dark=True, pad="3px 10px")

STUDIO = """/* Studio — Midnight's layout in Ledger's colours. Every chart and table
   on a panel, small capital headings with a rule running out from them,
   dense tables with figures in columns — on warm paper, in ink, with
   Ledger's teal for what is live or chosen. No gradients, no glow, one
   sans face: modern, simple and functional. The charts take the paper
   and the palette (see the --fg-chart- lines). */
:root {
  --bg: #f4efe4;
  --panel: #fbf8f1;
  --panel-2: #f2ede1;
  --ink: #1d1b16;
  --muted: #6f6857;
  --line: #e2dac8;
  --accent: #0e5a61;
  --accent-soft: rgba(14, 90, 97, 0.07);
  --track: #ebe4d4;
  --sans: Inter, "Source Sans 3", "Segoe UI", "Noto Sans", system-ui, sans-serif;
  --fg-head: #fbf8f1;
  --chart-shape: 2.6 / 1;
  --fg-chart-paper: #fbf8f1;
  --fg-chart-plot: #fbf8f1;
  --fg-chart-ink: #3d392f;
  --fg-chart-grid: #e7e0d0;
  --fg-chart-font: Inter, "Source Sans 3", "Segoe UI", "Noto Sans", system-ui, sans-serif;
  --fg-chart-colors: #0e5a61, #c8553d, #d9a441, #5b7f95, #8c6d9f, #6b8f4e, #9c9484, #2d3142;
  /* the web layout: sidebar, top bar, tabs, folding sections */
  --fg-text-size: 13px;
  --fg-accent: #0e5a61;
  --fg-nav-bg: #f9f5ec;
  --fg-nav-ink: #1d1b16;
  --fg-nav-muted: #6f6857;
  --fg-nav-line: #e2dac8;
  --fg-nav-hover: rgba(14, 90, 97, 0.07);
  --fg-nav-font: Inter, "Source Sans 3", "Segoe UI", "Noto Sans", system-ui, sans-serif;
}
body {
  font-family: var(--sans) !important;
  font-size: 13px !important;
  line-height: 1.5;
  color: var(--ink) !important;
  background: var(--bg) !important;
  max-width: 1220px;
  margin: 0 auto !important;
  padding: 26px 30px 48px !important;
  font-variant-numeric: tabular-nums;
}
::selection { background: rgba(14, 90, 97, 0.18); }
span[style*="font-family:'sans-serif'"] { font-family: inherit !important; }
p span, li, li span, h1 span, h2 span, h3 span { font-size: inherit !important; }
p { margin: 4px 0 !important; }
a { color: var(--accent); text-underline-offset: 2px; }

h1 {
  font-size: 24px; font-weight: 700; letter-spacing: -0.02em; line-height: 1.2;
  margin: 0 0 10px !important; padding: 0 !important; color: var(--ink);
}
h1 + p { color: var(--muted); }
h2 {
  display: flex; align-items: center; gap: 10px;
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.14em;
  text-transform: uppercase; color: var(--accent);
  margin: 26px 0 8px !important;
}
h2::after { content: ""; flex: 1; height: 1px; background: var(--line); }
h3 { font-size: 13px; color: var(--ink); margin: 16px 0 4px !important; }

p[style*="margin-left:40px; margin-right:40px"] {
  margin: 12px 0 !important; padding: 10px 14px;
  background: var(--accent-soft); border-left: 3px solid var(--accent);
  border-radius: 0 8px 8px 0;
}
span[style*="font-family:'monospace'"]:not(td *) {   /* code, not a table's figures */
  font-family: "JetBrains Mono", "Cascadia Code", Consolas, monospace !important;
  font-size: 0.9em !important; color: var(--accent);
  background: var(--accent-soft); border-radius: 4px; padding: 0 4px;
}
ul { margin: 8px 0 !important; padding-left: 18px; }
li::marker { color: var(--accent); }

/* panels */
.fg-chart, .fg-table, p > img {
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  box-shadow: 0 1px 2px rgba(29, 27, 22, 0.05);
}
.fg-chart {
  width: 100% !important; aspect-ratio: var(--chart-shape) !important;
  overflow: hidden; margin: 8px 0 !important;
}
.fg-chart > img { height: 100%; object-fit: contain; }
.fg-table { padding: 8px 10px; margin: 8px 0 !important; width: auto; }
.fg-scroll .flograph-table { width: 100%; border-collapse: collapse; }
.flograph-table > thead > tr > th {
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--muted); background: var(--panel);
  padding: 4px 9px; border-bottom: 1px solid var(--accent); white-space: nowrap;
}
.flograph-table > tbody > tr > td {
  padding: 3px 9px; border-bottom: 1px solid var(--line); white-space: nowrap;
}
.flograph-table > tbody > tr:last-child > td { border-bottom: 0; }
.fg-scroll tbody tr:hover > td { box-shadow: inset 0 0 0 9999px var(--accent-soft); }
.fg-sortable thead th[data-fg-sort]::after { color: var(--accent); }
/* structure rows: total, group, subtotal (delete to keep your own colours) */
.flograph-table > tbody > tr[data-fg-kind] > td {
  background-color: var(--panel-2) !important; color: var(--ink) !important;
  border: 0 !important; border-bottom: 1px solid var(--line) !important;
  font-weight: 650;
}
.flograph-table > tbody > tr[data-fg-kind="group"] > td:first-child {
  color: var(--accent) !important;
}
.flograph-table > tbody > tr[data-fg-kind="total"] > td {
  border-top: 1px solid var(--ink) !important;
}
.fg-db > i { background-color: var(--track); }
.fg-bar input {
  font-size: 12.5px; padding: 5px 10px; color: var(--ink);
  background: var(--bg); border: 1px solid var(--line); border-radius: 6px;
  outline: none;
}
.fg-bar input:focus { border-color: var(--accent);
                      box-shadow: 0 0 0 3px rgba(14, 90, 97, 0.14); }
.fg-bar .fg-count { color: var(--muted); }
.fg-bar button { color: var(--ink); border-color: var(--line); background: var(--panel); }
.fg-bar button:hover { border-color: var(--accent); color: var(--accent); }
.fg-scroll::-webkit-scrollbar { width: 8px; height: 8px; }
.fg-scroll::-webkit-scrollbar-thumb { background: var(--line); border-radius: 4px; }
.fg-scroll { scrollbar-color: var(--line) transparent; }

table[style*="border-style:none"] { width: 100% !important; table-layout: fixed; }
table[style*="border-style:none"] > tbody > tr > td { padding: 0 7px !important; }
table[style*="border-style:none"] > tbody > tr > td:first-child { padding-left: 0 !important; }
table[style*="border-style:none"] > tbody > tr > td:last-child { padding-right: 0 !important; }
table[style*="border-style:none"] .fg-chart { aspect-ratio: 1.4 / 1 !important; }

@media print {
  body { background: #fff !important; }
  .fg-chart, .fg-table, p > img { background: #fff; box-shadow: none; border-color: #ccc; }
}

/* the web layout: paper bars, a teal mark for where you are */
.fg-top { background: rgba(249, 245, 236, 0.9); border-bottom: 1px solid var(--line);
  -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px); }
.fg-top-title { font-weight: 700; letter-spacing: -0.01em; }
.fg-top-links a.fg-on { color: var(--accent); }
.fg-side { background: var(--fg-nav-bg); border-right: 1px solid var(--line); }
.fg-side a.fg-on { box-shadow: inset 2px 0 0 var(--accent); border-radius: 0 6px 6px 0; }
.fg-tabbar > button { font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; }
.fg-tabbar > button.fg-on { color: var(--accent); box-shadow: inset 0 -2px 0 var(--accent); }
details.fg-details { background: var(--panel); border-color: var(--line);
  border-radius: 10px; box-shadow: 0 1px 2px rgba(29, 27, 22, 0.05); }
details.fg-details > summary { color: var(--ink); }
details.fg-details[open] > summary { background: var(--panel-2); }
.fg-details-body .fg-chart, .fg-details-body .fg-table { box-shadow: none; }
.fg-drop { background: var(--panel); border: 1px solid var(--line);
  box-shadow: 0 10px 28px rgba(29, 27, 22, 0.12); }
.fg-pager a { background: var(--panel); }
.fg-pager a:hover { box-shadow: 0 0 0 1px var(--accent); }
.fg-icon-btn { background: var(--panel); }
@media print {
  details.fg-details { background: #fff; box-shadow: none; }
  details.fg-details[open] > summary { background: none; }
}
"""
STUDIO += _plain_tables("#fbf8f1", "#6f6857", "#e2dac8", "#f2ede1", "#1d1b16", "#ebe4d4", table_bg="#fbf8f1", head_rule="#0e5a61", vertical=False, pad="3px 9px")

SWISS = """/* Swiss — the International Typographic Style. White paper, black type,
   one signal red. Heavy grotesk headings set tight, every section numbered
   under a thick black rule, tables ruled in black with no fills, square
   corners and no shadows: the grid does the work. The charts take the
   palette (see the --fg-chart- lines). */
:root {
  --bg: #ffffff;
  --panel: #ffffff;
  --panel-2: #f2f2f2;
  --ink: #111111;
  --muted: #6b6b6b;
  --line: #d9d9d9;
  --accent: #e30613;
  --accent-soft: rgba(227, 6, 19, 0.06);
  --track: #ececec;
  --sans: "Helvetica Neue", Helvetica, Arial, "Nimbus Sans", "Liberation Sans", Inter, system-ui, sans-serif;
  --mono: "JetBrains Mono", "Cascadia Code", Consolas, monospace;
  --fg-head: #ffffff;
  --chart-shape: 2.6 / 1;
  --fg-chart-paper: #ffffff;
  --fg-chart-plot: #ffffff;
  --fg-chart-ink: #111111;
  --fg-chart-grid: #e6e6e6;
  --fg-chart-font: "Helvetica Neue", Helvetica, Arial, "Nimbus Sans", "Liberation Sans", Inter, system-ui, sans-serif;
  --fg-chart-colors: #e30613, #111111, #8c8c8c, #0057b8, #f2a900, #c4c4c4, #3a7d44, #5c2d91;
  /* the web layout: sidebar, top bar, tabs, folding sections */
  --fg-text-size: 13px;
  --fg-accent: #e30613;
  --fg-nav-bg: #ffffff;
  --fg-nav-ink: #111111;
  --fg-nav-muted: #6b6b6b;
  --fg-nav-line: #111111;
  --fg-nav-hover: rgba(227, 6, 19, 0.06);
  --fg-nav-font: "Helvetica Neue", Helvetica, Arial, "Nimbus Sans", "Liberation Sans", Inter, system-ui, sans-serif;
}
body {
  font-family: var(--sans) !important;
  font-size: 13.5px !important;
  line-height: 1.5;
  color: var(--ink) !important;
  background: var(--bg) !important;
  max-width: 1200px;
  margin: 0 auto !important;
  padding: 30px 36px 56px !important;
  font-variant-numeric: tabular-nums;
  counter-reset: fg-section;
}
::selection { background: var(--accent); color: #ffffff; }
span[style*="font-family:'sans-serif'"] { font-family: inherit !important; }
p span, li, li span, h1 span, h2 span, h3 span { font-size: inherit !important; }
p { margin: 4px 0 !important; max-width: 78ch; }
a { color: var(--ink); text-decoration-color: var(--accent);
    text-decoration-thickness: 2px; text-underline-offset: 3px; }
a:hover { color: var(--accent); }
/* Qt puts its own blue and underline on the span inside a link */
a > span[style*="color:#0000ff"] { color: inherit !important; text-decoration: inherit !important; }
strong, b { font-weight: 700; }

/* headings: big and tight; each section numbered under a black rule */
h1 {
  font-size: clamp(30px, 6vw, 44px); font-weight: 800; letter-spacing: -0.035em; line-height: 1.02;
  margin: 0 0 14px !important; padding: 0 0 14px !important;
  border-bottom: 6px solid var(--ink);
}
h1 + p { font-size: 17px; line-height: 1.4; color: var(--ink); max-width: 60ch; }
h2 {
  counter-increment: fg-section;
  display: flex; align-items: baseline; gap: 14px;
  font-size: 22px; font-weight: 800; letter-spacing: -0.02em; line-height: 1.1;
  margin: 40px 0 12px !important; padding: 10px 0 0 !important;
  border-top: 3px solid var(--ink);
}
h2::before {
  content: counter(fg-section, decimal-leading-zero);
  font-size: 13px; font-weight: 700; letter-spacing: 0; color: var(--accent);
  min-width: 26px;
}
h3 {
  font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
  margin: 20px 0 6px !important;
}

/* > quote: a pull quote, large, on a red rule */
p[style*="margin-left:40px; margin-right:40px"] {
  margin: 18px 0 !important; padding: 2px 0 2px 18px;
  border-left: 6px solid var(--accent);
  font-size: 19px; font-weight: 700; line-height: 1.3; letter-spacing: -0.01em;
  max-width: 52ch;
}
span[style*="font-family:'monospace'"]:not(td *) {   /* code, not a table's figures */
  font-family: var(--mono) !important; font-size: 0.88em !important;
  background: var(--panel-2); padding: 0 4px;
}
ul, ol { margin: 8px 0 !important; padding-left: 20px; }
li::marker { color: var(--accent); font-weight: 700; }
hr { border: 0; border-top: 1px solid var(--ink); margin: 28px 0; }

/* charts: no frame but a black hairline above, like a figure on a grid */
.fg-chart, p > img { background: var(--panel); border-top: 1px solid var(--ink); }
.fg-chart {
  width: 100% !important; aspect-ratio: var(--chart-shape) !important;
  overflow: hidden; margin: 10px 0 !important;
}
.fg-chart > img { height: 100%; object-fit: contain; }
p > img { padding-top: 8px; max-width: 100%; height: auto; }

/* live tables: black rules, no fills; a rule's own colours are kept */
.fg-table { margin: 10px 0 !important; }
.fg-scroll .flograph-table { width: 100%; border-collapse: collapse;
  border-top: 3px solid var(--ink); }
.flograph-table > thead > tr > th {
  font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--ink); background: var(--fg-head);
  padding: 6px 10px 5px; border-bottom: 1px solid var(--ink); white-space: nowrap;
}
.flograph-table > tbody > tr > td {
  padding: 4px 10px; border-bottom: 1px solid var(--line); white-space: nowrap;
}
.fg-scroll tbody tr:hover > td { box-shadow: inset 0 0 0 9999px var(--accent-soft); }
.fg-sortable thead th[data-fg-sort] { color: var(--accent); }
.fg-sortable thead th[data-fg-sort]::after { color: var(--accent); }
/* structure rows: total, group, subtotal (delete to keep your own colours) */
.flograph-table > tbody > tr[data-fg-kind] > td {
  background-color: transparent !important; color: var(--ink) !important;
  border: 0 !important; border-bottom: 1px solid var(--ink) !important;
  font-weight: 700;
}
.flograph-table > tbody > tr[data-fg-kind="group"] > td { padding-top: 10px; }
.flograph-table > tbody > tr[data-fg-kind="group"] > td:first-child::before { color: var(--accent); }
.flograph-table > tbody > tr[data-fg-kind="total"] > td {
  border-top: 3px solid var(--ink) !important; border-bottom: 0 !important;
}
.fg-db > i { background-color: var(--track); }
/* the strip over a |search table: a line to write on */
.fg-bar input {
  font: inherit; font-size: 13px; padding: 5px 2px; color: var(--ink);
  background: transparent; border: 0; border-bottom: 2px solid var(--ink);
  border-radius: 0; outline: none; min-width: 220px;
}
.fg-bar input:focus { border-bottom-color: var(--accent); }
.fg-bar .fg-count { color: var(--muted); }
.fg-bar button {
  font: inherit; font-size: 11px; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--ink); background: var(--bg);
  border: 1px solid var(--ink); border-radius: 0; white-space: nowrap;
}
.fg-bar button:hover { background: var(--ink); color: #ffffff; }
.fg-scroll { scrollbar-color: var(--ink) transparent; }

/* columns: the grid's gutters */
table[style*="border-style:none"] { width: 100% !important; table-layout: fixed; }
table[style*="border-style:none"] > tbody > tr > td { padding: 0 12px !important; }
table[style*="border-style:none"] > tbody > tr > td:first-child { padding-left: 0 !important; }
table[style*="border-style:none"] > tbody > tr > td:last-child { padding-right: 0 !important; }
table[style*="border-style:none"] .fg-chart { aspect-ratio: 1.4 / 1 !important; }

/* the web layout: black rules, red for where you are */
.fg-top { background: var(--bg); border-bottom: 3px solid var(--ink); }
.fg-top-title { font-weight: 800; letter-spacing: -0.02em; }
.fg-top-links a { font-weight: 600; }
.fg-top-links a.fg-on { color: var(--accent); border-bottom-color: var(--accent); }
.fg-side { background: var(--bg); border-right: 1px solid var(--ink); }
.fg-side a.fg-on { color: var(--accent); font-weight: 700; box-shadow: inset 3px 0 0 var(--accent); }
.fg-tabbar { border-bottom: 1px solid var(--ink); }
.fg-tabbar > button { font-size: 12px; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--muted); }
.fg-tabbar > button.fg-on { color: var(--ink); border-bottom-color: var(--accent);
  box-shadow: inset 0 -3px 0 var(--accent); }
details.fg-details { background: var(--bg); border: 0; border-top: 1px solid var(--ink);
  border-bottom: 1px solid var(--ink); border-radius: 0; }
details.fg-details + details.fg-details { border-top: 0; }
details.fg-details > summary { font-weight: 700; color: var(--ink); }
details.fg-details[open] > summary { border-bottom-color: var(--line); }
.fg-drop { background: var(--bg); border: 1px solid var(--ink); border-radius: 0;
  box-shadow: 6px 6px 0 var(--ink); }
.fg-pager a { background: var(--bg); border: 1px solid var(--ink); border-radius: 0; }
.fg-pager a:hover { background: var(--ink); color: #ffffff; }
.fg-icon-btn { background: var(--bg); border-radius: 0; }

/* a phone: less margin, taller charts, columns one under another */
@media (max-width: 640px) {
  body { padding: 18px 16px 40px !important; }
  h2 { font-size: 19px; margin-top: 30px !important; }
  p[style*="margin-left:40px; margin-right:40px"] { font-size: 16px; }
  .fg-chart { aspect-ratio: 1.5 / 1 !important; }
  table[style*="border-style:none"], table[style*="border-style:none"] > tbody,
  table[style*="border-style:none"] > tbody > tr,
  table[style*="border-style:none"] > tbody > tr > td {
    display: block; width: auto !important; padding: 0 !important;
  }
}

@media print {
  .fg-drop { box-shadow: none; }
  h2 { break-after: avoid; }
}
"""
SWISS += _plain_tables("#ffffff", "#111111", "#d9d9d9", "#ffffff", "#111111", "#ececec", head_rule="#111111", vertical=False, pad="4px 10px")

LIVE_THEMES = {
    "Compact": COMPACT,
    "Dashboard": DASHBOARD,
    "Midnight": MIDNIGHT,
    "Ledger": LEDGER,
    "Terminal": TERMINAL,
    "Aurora": AURORA,
    "Studio": STUDIO,
    "Swiss": SWISS,
}
