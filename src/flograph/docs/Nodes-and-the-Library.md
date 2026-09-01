# Nodes and the Library

## The library dock

The **Node Library** dock (left) lists every node type by category. Type in
the search box to filter, or press **Tab** on the canvas for the same search
as a popup.

Right-click a node ▸ **Add to Favorites** (or **Ctrl+Shift+F** on a selected
row) pins it in a **★ Favorites** section at the top and puts it first in the
Tab popup. The star button beside the search box narrows the tree to
favorites only. Favorites persist per machine.

## The standard library

**Input** — Slider, Between Slider, Number, Text, Date, Toggle, Choice. You
*set* these rather than compute them; see [[Dashboards and Reports]].

**IO** — **Read File** reads CSV, Excel, JSON/JSONL, Parquet and SQLite
through one node: pick the **Format** (or leave it *auto*) and the **Engine**
(*polars* parses in Rust and releases the GIL, so several readers genuinely
run at once). The single-format Read nodes are still there, as are Write
CSV/Excel/Parquet/JSON/SQLite and **Write Text**. **Read … (Folder)** reads a
directory as one stacked table; **Read PDF** turns documents into a table,
one row per page. **Table** is a real spreadsheet you edit on the canvas,
with formulas.

**Connect** — SQL Query and SQL Write (any database SQLAlchemy reaches),
DuckDB SQL, HTTP Request and REST Paginate, and the **Dataiku** trio:
**Dataiku Source** (read a DSS dataset, run SQL on a DSS connection, list a
project's objects, or download a managed-folder file), **Dataiku Upload**
(replace a file in a DSS flow — overwrite one path in a managed folder, or
add to an uploaded-files dataset — then pass the table on), and **Dataiku
Action** (run a scenario, build a dataset or folder, or set a project
variable, on an order edge after the upload). Each Dataiku node has one
**Operation** dropdown that shows only the fields that operation needs; leave
**API key** blank to read `$DKU_API_KEY`. Needs `dataiku-api-client`.

**Transform** — Select Columns, Filter Rows, Sort, Join, Group By,
Expression, Concatenate, Missing Values, Duplicate Row Filter, Rename
Columns, Pivot, Unpivot, Row Sampling, Convert Types, String Manipulation,
Statistics, Data Profile.

**Viz** — Show Table, Show Plot (matplotlib), Show Plotly (an interactive
plotly.js chart on the canvas, in any of the 28 Plotly Express chart types),
Plotly Style, Plotly Table, Show Web View (anything that produces HTML —
folium, altair, bokeh, your own template), Card (a KPI number), Chart per
Value, Gantt Chart (a project plan that works its own dates out), Image, PDF
Viewer, Report. Any web-view node has **Open in Browser** on its right-click
menu.

**Util** — Constant, Reroute, Note, Action Button, Goto, From, Variables.

**Scripting** — Python Script, plus Node Template and Control Template to
fork when writing your own.

## Every node is Python

Double-click any node to read or fork its code in the built-in editor —
syntax highlighting, jedi completion, find/replace, error markers on the
failing line. There is no privileged built-in tier: the Group By node is a
file you can open and change. **[[Writing a Node]]** is the full contract —
the `NODE` dict, every param type, the `run` context, cards, and where node
files live.

## Packages

**Tools ▸ Manage Packages** installs, upgrades and uninstalls pip packages in
flograph's own environment. Nodes run in-process, so a new install is
importable from `run()` immediately — no restart. flograph's own core
dependencies are protected from uninstall.
