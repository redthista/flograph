# Node Council — background

Six personas sat down and brainstormed what flograph is missing. Each read
the existing library first, so nothing here duplicates what ships today. The
result was 50 concrete node ideas — every one implementable as a single node
script under `src/flograph/nodes/<category>/`, plus a section on how each
persona uses flograph to get their job done now and what the new nodes would
unlock.

**Shipped 2026-08-31**, deleted from the list below: #5 Ranking & Percentiles
and #6 Percentage Share (both fold into the new **Window Function**), #12
**Data Quality Gate**, #42 **HTTP Request**, #44 **Wait for File**, #45
**Shell Command**, #47 **Notify**, and #49 Diff DataFrames (shipped as **Diff
Tables**). The same batch also added, off the council's list: SQL Query / SQL
Write, DuckDB SQL, REST Paginate, List Files, Fuzzy Join, PII Scan, SVG
Template, Mermaid Diagram, Read HTML Tables, and LLM Enrich / Classify /
Extract. Numbers are not reused; the gaps stay.
**Shipped 2026-09-13**, deleted from the list below: #1 **Period Comparison**,
#7 **Numeric Binning** and #10 **Crosstab** — three Transform nodes with a
shared example, **Segment Compare Matrix**. Their running mates from the
analyst batch — Date Bucketing (#2), Date Arithmetic (#3), Complete Date
Range (#4), Column Splitter (#8), Text Cleaning (#9), Cohort Analysis (#11)
and Multi-Sheet Excel Export (#50) — are still open. #8 and #14 were already
answered (as **Split Column** and **Explode Column**).

The existing library is: Input (Slider, Number, Text, Date, Toggle, Choice,
Between Slider); IO (Read/Write CSV/Excel/Parquet/JSON/SQLite, Table, read
folder variants); Transform (Select Columns, Filter Rows, Sort, Join, Group
By, Expression, Concatenate, Missing Values, Duplicate Row Filter, Rename,
Pivot, Unpivot, Row Sampling, Convert Types, String Manipulation, Statistics,
Data Profile); Viz (Show Table, Show Plot, Show Plotly, Show Web View, Card,
Table Spec, Chart per Value, Slicer, Report); Util (Constant, Reroute, Note,
Action Button, Goto, From, Variables); Scripting (Python Script + templates).

---

## The Council

| Persona | Lens | What they kept asking for |
|---|---|---|
| **Data Analyst** | Weekly reporting, Excel-style cleanup, period comparisons | Compare periods, bucket dates, rank, clean text, validate data |
| **Data Scientist** | ML workflows, feature engineering, model eval | Splits, encoders, scalers, models, metrics, clustering |
| **App Builder** | Interactive dashboards, input controls, UX | More controls, stateful choices, app actions |
| **End User** | Reading a dashboard, understanding numbers | Context, goals, deltas, status, export, "as of" |
| **Engineer** | ETL, automation, glue, files, notifications | HTTP, watch folders, shell, notify, diffs, gates |
| **Power User** | Python hacker, glue scripts, text/data plumbing | Formatting, regex, JSON navigation, sequences, units |

---

## How each persona uses flograph

### Data Analyst
**Today:** Loads CSVs → Data Profile / Statistics to sanity-check, then Filter
Rows, Group By, Pivot, Chart per Value to build a weekly report. String
Manipulation + Expression handle the "one-off" cleanup. Writes the result to
Excel for the boss.

**Example goal — "why did revenue drop?"** Read `sales.csv`, Filter Rows to
this year, Group By product line + month, Chart per Value of monthly revenue,
then Cross-tab it against last year with the new **Period Comparison** node so
the delta column does the talking.

**Going forward:** The 14 transform ideas below replace the recurring
"Expression hand-rolled glue" with single nodes: cohort retention tables,
date bucketing, ranking within groups, percentage share, text cleaning in one
pass, and a data-quality gate that blocks a report when the feed is dirty.

### Data Scientist
**Today:** Prepares features with Select Columns, Missing Values, Convert
Types, then writes a Python Script for anything model-shaped (sklearn) and
Show Plots the result. Every model is a one-off script.

**Example goal — "churn prediction for the ops team":** Read `customers.csv`,
Join with usage data, Missing Values, then the new **Train/Test Split** feeds
**Feature Scaler** + **One-Hot Encode** into **Train Model**, **Model
Evaluation** scores the test split, and the confusion matrix renders on
canvas — no Python Script node in sight.

**Going forward:** A real `ml` category: split, encode, scale, train, predict,
evaluate, cross-validate, cluster, outlier-flag, and time-series features all
as reusable nodes. Models become objects that flow between nodes like any
other value.

### App Builder
**Today:** Builds dashboards: Input controls (Slider/Choice) feed transforms,
results land as Card / Show Plotly / Show Web View on dashboard pages, with a
Slicer or two and an Action Button to re-run.

**Example goal — "a self-serve sales explorer for the commercial team":**
Range Slider for the date band, Multi Select for regions, a Search Box for
customer name; all three feed Filter Rows → Chart per Value. File Picker lets
them load "this week's export", and Export Report makes the PDF.

**Going forward:** The control family grows to multi-select, radio, toggle
groups, range sliders, color picker, file picker and a **Remembered Choice**
that survives project reopen. App actions (open in browser, copy to
clipboard, run external command) turn dashboards into tools, not just views.

### End User
**Today:** Reads cards and tables, drags the Slicer, waits for the builder to
add anything.

**Example goal — "is the quarter on track?"** A dashboard whose top row is
**Goal Cards** (revenue vs target with a delta arrow and progress bar),
**Sparkline Cards** for each cost line, a **Status Light** for cash runway,
and an **Alert List** at the top for anything overdue.

**Going forward:** Numbers come with context — trend sparklines, goal
progress, green/amber/red status, best & worst highlights, a plain-English
summary sentence and an as-of timestamp so nobody acts on stale data. And a
one-click **Export Report** so they stop asking for screenshots.

### Engineer
**Today:** Read folder → transforms → Write SQLite/CSV, triggered by running
the flow. Error handling means reading the Log console.

**Example goal — "nightly vendor file, cleaned, loaded, and reported":**
**Watch Folder** / **Wait for File** waits for the FTP drop, **Data Quality
Gate** validates it, File Operations archives it, Write SQLite loads it, and
**Notify** emails the ops team — success or failure — with the gate's report
attached.

**Going forward:** with HTTP, Wait for File, Shell, Notify and Diff Tables
shipped, what is left is folder watching, file ops and row loops — plus the
engine-level schedule / webhook triggers. Flows stop being "run it by hand"
and become scheduled, watched, notified pipelines.

### Power User
**Today:** Reaches for Python Script constantly for glue — formatting a
string, pulling a dict key, converting units — and forks builtins when they
are close.

**Example goal — "turn a messy API response into a table":** **HTTP Request**
fetches, **JSON Path Query** plucks the array, Explode List Column unpacks
nested rows, Lookup Map translates status codes to labels, Format Number
tidies the money, Generate Sequence makes the missing dates.

**Going forward:** Cheap, high-frequency glue nodes: format string, regex
extract, JSON path, merge dicts, pluck, unit conversion, sequences, explode,
lookup maps. Fewer "I'll just write a script" moments; more flows built
entirely from library nodes.

---

The ideas themselves are cards on the flograph project board
(https://github.com/users/redthista/projects/2), titled "Node idea N: …".
This page keeps the personas, themes and build order they came with.

---

## Honourable mentions & themes

Strong ideas that didn't make the list but are worth remembering:

- **Progress Ring / Delta Badge** — folded into Goal Card (#36).
- **Two-Period Compare** — folded into Period Comparison (#1).
- **Quick Search** — folded into Search Box (#32).
- **JSON from API** — shipped as **REST Paginate** (page / offset / cursor /
  Link-header, with records-path flattening) alongside **HTTP Request**.
- **Run Python Script (subprocess)** — a wrapper for legacy/heavy scripts;
  overlaps Python Script but useful for isolation.
- **Try/Catch Wrapper, Log to File, Env/Secrets** — engine-level controls the
  council wants, but they touch the scheduler/caching scope rather than being
  single scripts; worth a separate design pass.
- **Schedule / Interval Trigger, Reset Filters, Page Navigator** — dashboard
  and engine features, not node scripts; belong on the board.
- **PCA, TF-IDF Text Features, Transpose, Window Aggregates, Format String,
  Regex Extract, JSON Path Query, Unit Converter, Generate Sequence, Merge
  Dicts, Pluck, Merge Messy Files** — solid glue nodes; include them in a
  second batch.

### Recurring themes the council kept hitting
- **Context on every number** — deltas, goals, trends, status, as-of stamps.
- **Period math without hand-rolled Expression glue** — comparison, bucketing,
  cohorts, complete date ranges.
- **Models as flowing values** — train → predict → evaluate as a pipeline of
  ordinary nodes.
- **"App" actions** — file dialogs, clipboard, browser, shell, notify.
- **Gates, not just transforms** — data quality pass/fail so downstream can
  branch.

---

## Suggested build order

1. **Analyst batch** (#2–#4, #8, #9, #11, #13, #50): highest daily
   frequency, pure pandas, no new deps — most are near-copies of existing
   node patterns.
2. **Input controls** (#27–#34): reuses the `card: "control"` host and
   `core/controls.py` helpers already in place.
3. **Viz context cards** (#35–#41): reuse the Card/kpi machinery.
4. **ML batch** (#15–#26): needs an `ml` category package + sklearn inside
   `run()`; `exclusive=True` on the figure-emitting ones.
5. **Automation** (#43 Watch Folder, #46 File Operations, #48 Loop over
   Rows): the rest of the batch shipped 2026-08-31. Watch Folder needs
   engine polling; Loop over Rows needs subgraph fan-out.

Each lands via the `new-node` skill: script under
`src/flograph/nodes/<category>/`, headless test in `test_stdlib_nodes.py`,
verified with `test_registry.py` + `test_stdlib_nodes.py`.