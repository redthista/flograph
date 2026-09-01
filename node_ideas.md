# flograph — Node Council: Node Ideas

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

## The Ideas

### Transform — dates, periods & time

**1. Period Comparison** — *analyst* — `transform`
Compare a measure against the prior period or same-period-last-year; adds
previous value, absolute delta and % change, aligned on a date column plus
optional group keys.
`dataframe → dataframe` · params: `date_column`, `measure`, `period`
(week/month/quarter/year), `basis` (previous / last year).
*Use: monthly revenue report showing each product line's change vs last month
and vs the same month last year.*

**2. Date Bucketing** — *analyst* — `transform`
Floor a datetime column into day/ISO-week/month/quarter/year (or fiscal)
buckets and add a formattable label column.
`dataframe → dataframe` · params: `date_column`, `bucket`, `label_format`
(e.g. `2026-Q1`).
*Use: group daily clickstream timestamps into ISO weeks for a year-over-year
weekly trend.*

**3. Date Arithmetic** — *analyst* — `transform`
Compute date differences (calendar or business days) between two date columns
or against a fixed date; or shift a date column by an offset.
`dataframe → dataframe` · params: `start_column`, `end_column` (optional),
`fixed_date`, `unit`, `mode` (difference / shifted date).
*Use: invoice age in business days from issue to payment to find chronically
slow payers.*

**4. Complete Date Range** — *analyst* — `transform`
Reindex a grouped date series so every date in a span appears, filling gaps
with 0/NaN/forward-fill.
`dataframe → dataframe` · params: `date_column`, `group_by`, `fill`,
`range`.
*Use: backfill empty days in daily signups so the 30-day trend chart isn't
ragged and weekly sums are honest.*

### Transform — bins

**7. Numeric Binning** — *analyst / power user* — `transform`
Cut a numeric column into fixed-width, quantile, or custom-edge bins with
labeled buckets (`<100`, `100–250`, `250+`).
`dataframe → dataframe` · params: `value_column`, `method` (fixed/quantile/
custom), `bins`, `edges`, `labels`.
*Use: bucket customer lifetime value into high/medium/low tiers as a reusable
segment column for slicers and reports.*

**8. Column Splitter** — *analyst / power user* — `transform`
Split one text column into several by delimiter, regex, or fixed width, with
trimming and drop-source options.
`dataframe → dataframe` · params: `source_column`, `method`, `delimiter`,
`widths`, `max_parts`, `drop_source`.
*Use: split a `FirstName|LastName|Email` column imported from a legacy CRM
into proper fields.*

**9. Text Cleaning** — *analyst* — `transform`
Apply a checklist of fixes in one pass: strip, collapse whitespace, case
normalisation, strip non-printables, remove URLs/emails, replace NA.
`dataframe → dataframe` · params: `columns`, `ops`, `replace_na`.
*Use: sanitise free-text survey notes before keyword matching — no ten-regex
Expression chain.*

### Transform — tables, cohorts & quality

**10. Crosstab / Frequency Matrix** — *analyst* — `transform`
Build a two-dimensional frequency (or weighted) table from two category
columns, optionally normalised by row/column/grand totals.
`dataframe → dataframe` · params: `row_column`, `column_column`, `weight`,
`normalize`, `fill_value`.
*Use: device-type × browser matrix for a traffic report, row-normalised to
see each device's browser mix.*

**11. Cohort Analysis** — *analyst* — `transform`
Label each row with a cohort key (first-seen period) and a period index since
cohort start — the exact table that feeds a retention matrix.
`dataframe → dataframe` · params: `user_id`, `date_column`, `cohort_unit`,
`period_unit`, `min_count`.
*Use: signup-month cohort retention table from subscription events for the
monthly exec pack.*

**13. Lookup Map** — *power user* — `transform`
Translate a column through an inline `key=value` mapping (or a small
reference dataframe input); unmatched rows keep value or get a default.
`dataframe → dataframe` · params: `column`, `mapping`, `default`.
*Use: map ISO country codes to names, or status codes to labels.*

**14. Explode List Column** — *power user* — `transform`
One row per element of a list-valued column (pandas `explode`); other columns
repeat.
`dataframe → dataframe` · params: `column`.
*Use: turn rows with `tags=["a","b"]` into per-tag rows for group-by/joins.*

### ML — preparation

**15. Train/Test Split** — *data scientist* — `ml`
Split a dataframe into train/test subsets with optional stratification and a
fixed seed.
`dataframe → train (dataframe), test (dataframe)` · params: `test_size`,
`stratify`, `shuffle`, `seed`.
*Use: split features + target 80/20 and wire both halves into Train Model and
Model Evaluation.*

**16. Feature Scaler** — *data scientist* — `ml`
Fit a Standard/MinMax/Robust scaler and return scaled features plus the fitted
scaler object; feed the object back in with new data to reuse the transform.
`dataframe → scaled (dataframe), scaler (object)`; optional `scaler` input
transforms only · params: `method`, `columns`, `copy`.
*Use: fit a MinMaxScaler on training features, pass the object + test split
back in so the test set is scaled by the same parameters.*

**17. One-Hot Encode** — *data scientist* — `ml`
Convert categorical columns to 0/1 indicators, optionally dropping the first
level to avoid collinearity.
`dataframe → dataframe` · params: `columns`, `drop_first`,
`handle_unknown`.
*Use: encode `city`/`color` so categorical features can feed logistic
regression.*

**18. Label Encode** — *data scientist* — `ml`
Map categorical columns to integer codes 0..n-1 and return the mapping object
so predictions can be decoded back to labels.
`dataframe → encoded (dataframe), mappings (object)` · params: `columns`,
`missing_value`.
*Use: encode the class target for a tree model, then decode Predict's output
with the emitted mapping.*

**19. Correlation Matrix** — *data scientist* — `ml`
Pearson/Spearman/Kendall correlation over numeric columns, rendered as an
annotated heatmap plus the numeric matrix. `exclusive=True` (matplotlib).
`dataframe → figure (figure), matrix (dataframe)` · params: `method`,
`columns`, `colormap`, `annotate`.
*Use: check which features correlate with the target before choosing what to
feed the model.*

### ML — modelling

**20. Train Model** — *data scientist* — `ml`
Fit a scikit-learn model (linear/ridge/lasso/logistic/random forest/gradient
boosting) on features + target, returning the model object, train metrics and
feature importances.
`dataframe → model (object), metrics (dataframe), importances (dataframe)` ·
params: `task`, `algorithm`, `target_column`, `feature_columns`, `test_size`,
`seed`.
*Use: train a RandomForest on housing features + price and pass the model to
Predict.*

**21. Predict** — *data scientist* — `ml`
Apply a trained model object to a features dataframe; classifiers can also
emit predicted probabilities.
`model (object), dataframe → predictions (series), probabilities (dataframe,
optional)` · params: `task`, `probability`, `round`.
*Use: score a fresh batch of rows through the upstream model and inspect the
predictions in Show Table.*

**22. Model Evaluation** — *data scientist* — `ml`
Regression: MAE/MSE/RMSE/R². Classification: accuracy/precision/recall/F1 plus
a confusion-matrix heatmap and raw counts table. `exclusive=True`.
`y_true (series), y_pred (series) → metrics (dataframe), confusion (figure),
counts (dataframe)` · params: `task`, `normalize`, `multi_class`.
*Use: feed the test target and Predict's output in, read off RMSE, eyeball the
confusion matrix for the weak class.*

**23. Cross-Validation** — *data scientist* — `ml`
Run k-fold CV of a chosen model and report per-fold plus mean/std scores.
`dataframe → scores (dataframe), summary (dataframe)` · params: `folds`,
`task`, `algorithm`, `scoring`, `target_column`, `seed`.
*Use: compare Ridge vs RandomForest on the same features by mean CV RMSE
before committing.*

**24. K-Means Clustering** — *data scientist* — `ml`
Cluster rows into k groups; output labels, centers, and a 2-D PCA scatter
coloured by cluster. `exclusive=True`.
`dataframe → clusters (series), centers (dataframe), figure (figure)` ·
params: `k`, `columns`, `standardize`, `seed`.
*Use: segment customers by purchase behaviour, then feed the labels back as a
feature for a churn model.*

**25. Outlier Detection** — *data scientist* — `ml`
Flag anomalous rows via IQR, z-score, or IsolationForest; emit flags plus a
cleaned dataframe (drop/clip/flag-only).
`dataframe → flags (series), cleaned (dataframe)` · params: `method`,
`columns`, `threshold`, `action`, `contamination`.
*Use: flag sensor readings 3σ from the mean before fitting the time-series
model so one spike doesn't skew coefficients.*

### ML — time series

**26. Time Series Features (Resample / Rolling / Lag)** — *data scientist* — `time`
One node, three classic enrichments: resample a datetime-indexed series to a
new frequency with an aggregation; rolling-window stats; or lag/lead shifted
columns.
`series → result (series), shifted (dataframe, for lag op)` · params:
`operation`, `freq`, `agg`, `window`, `lags`, `min_periods`.
*Use: resample daily sales to weekly sums, add lag-1 and lag-7 features so the
model sees seasonality, smooth with a 7-day rolling mean.*

### Input — controls

**27. Multi Select** — *app builder* — `input`
A dropdown whose rows carry checkboxes — pick several of a known set. Reuses
Choice's option-source logic but emits a list.
`options (any, optional) → selected (object: list), count (number)` · params:
caption, items, column, value, width, height.
*Use: analyst picks several regions at once; a filter row and a faceted chart
redraw for exactly those members.*

**28. Radio Buttons** — *app builder* — `input`
Inline mutually-exclusive buttons instead of a dropdown — right when there are
≤5 options that should be visible at a glance.
`options (any, optional) → value (string)` · params: caption, items, column,
selected, orientation, width, height.
*Use: a reporting tool where the user taps Daily / Weekly / Monthly before the
numbers recompute.*

**29. Toggle Group** — *app builder* — `input`
A grid of labelled checkboxes, each independent; emits checked values and a
dict of every option's state.
`options (any, optional) → selected (object: list), state (object)` · params:
caption, items, column, default, grid columns, width, height.
*Use: show/hide chart series or table columns interactively.*

**30. Range Slider** — *app builder* — `input`
A two-handle slider emitting both bounds and the pair; bounds can be
data-driven like Slider.
`minimum (any, optional), maximum (any, optional) → min (number), max
(number), range (object)` · params: caption, lower, upper, step, decimals,
width, height.
*Use: grab "2021–2024" on a timeline and the line chart redraws to that
window.*

**31. Color Picker** — *app builder* — `input`
Open a native color dialog and emit the pick as hex plus RGB, so styling
values flow into the model like any other input.
`→ hex (string), rgb (object)` · params: caption, default, allow_alpha.
*Use: a theming screen — pick an accent color and downstream plots/report CSS
consume it as data.*

**32. Search Box** — *app builder / end user* — `input`
A text box emitting on Enter (or debounced live mode) plus a submit counter so
flows can tell "new search" from "still running".
`→ query (string), submitted (number), is_empty (bool)` · params: caption,
placeholder, mode, debounce_ms, clear_button, width.
*Use: search-over-rows tool — type a term, hit enter, the table below filters.*

**33. File Picker** — *app builder* — `input`
A card that opens a native open-file/open-folder/save-file dialog and emits
the chosen path; a `suggested` input seeds the directory or filename.
`suggested (string, optional) → path (string), exists (bool), parent
(string)` · params: mode, filters, caption, width, height.
*Use: an importer screen — user points at a file, the flow reads and previews
it; branch on `exists` for a cancelled dialog.*

**34. Remembered Choice** — *app builder* — `input`
Like Choice, but the pick is persisted into the project file so a dashboard
reopens on the last thing the user chose.
`options (any, optional) → value (string)` · params: caption, items, column,
persistence, default.
*Use: a weekly dashboard that opens on last week's region and measure every
Monday, not the canned default.*

### Viz — cards, status & context

**35. Sparkline Card** — *app builder / end user* — `viz`
A KPI card with an inline mini line chart under the big number, plus a `trend`
output for colouring the arrow.
`table (dataframe) → value (any), trend (number)` · params: value column,
aggregation, trend column, format, width, height.
*Use: ops monitor — one big number plus a tiny sparkline answers "is revenue
up and staying up?".*

**36. Goal Card (delta + progress)** — *app builder / end user* — `viz`
A big value compared against a target: delta arrow with % change, or a
progress bar; threshold colouring with a good/bad direction.
`value (any), comparison (any, optional) → delta (number), pct (number)` ·
params: mode (delta/progress), label, format, higher_is_better, colours.
*Use: a KPI scorecard — "Sales vs last year ▲ +12%" and "Q3 quota 78%" as one
green/red bar set.*

**37. Status Light** — *end user* — `viz`
Map a number to a green/amber/red lamp using thresholds — the whole board can
be scanned as traffic lights.
`number → figure` · params: amber/red breakpoints, label, direction.
*Use: cash-runway days, debt ratio, server uptime — red means someone needs to
act.*

**38. Best & Worst** — *end user* — `viz`
Highlight the top and bottom N rows of a table in green/red.
`dataframe → figure` · params: rank column, top N, bottom N, colours.
*Use: a product list showing the 5 best- and 5 worst-selling SKUs without
building a sort + filter chain.*

**39. Plain-English Summary** — *end user* — `viz`
Turn key numbers into one readable sentence ("Revenue $1.2M, up 9% vs last
month") — the dashboard writes its own headline.
`number inputs → string` · params: sentence template, up/down/flat phrases.
*Use: the top line of a finance dashboard the CEO reads without opening
anything.*

**40. As-of Stamp** — *end user* — `util`
Show the timestamp the data was last refreshed, so nobody acts on stale
numbers; updates when upstream runs.
`any (trigger) → string` · params: format, stale threshold.
*Use: "As of 09:41 today" under a live P&L so the room trusts the figure in a
meeting.*

**41. Alert List** — *end user* — `viz`
Collect every row that breaches a rule into one visible alert panel — a
"needs attention" tray at the top of the dashboard.
`dataframe, number (threshold) → figure` · params: threshold column,
direction, message template.
*Use: overdue invoices or low-stock items appear in a red-tinted tray the
moment they qualify.*

### Automation & IO

**43. Watch Folder** — *engineer* — `io`
Poll a directory for new/changed files since the last run and emit each one
downstream as it appears.
`folder → file (dataframe, one row per new file), paths (object: list)` ·
params: poll_interval_s, pattern, include_subdirs, mode.
*Use: watch an inbound FTP drop folder and feed each new CSV into a cleanup +
DB-load flow.*

**46. File Operations** — *engineer* — `io`
Copy, move, rename, or delete files/directories per the configured operation;
optionally zip a folder.
`source, destination → result_path, exists (bool), bytes_moved (number)` ·
params: operation, overwrite, zip_name.
*Use: after a daily export, move processed CSVs into an archive folder and zip
last month's files.*

**48. Loop over Rows** — *engineer* — `scripting`
Fan-out: split a dataframe into one-row (or N-row chunk) branches, invoking
the downstream subgraph once per item, in order.
`data → item (any), index (number), key (string)` · params: chunk_size, order,
invoke_downstream.
*Use: feed one customer row at a time into a per-customer HTTP-call node
without writing a Python loop.*

**50. Multi-Sheet Excel Export** — *analyst* — `io`
Write several dataframes into one workbook with per-sheet names, an optional
summary sheet, and header/autofit formatting.
`data1..dataN (dataframe) → path (string)` · params: file, sheet_names,
add_summary, autofit.
*Use: assemble one client-ready workbook with P&L, by-product, and by-region
tabs in a single step instead of three CSV exports.*

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
  and engine features, not node scripts; belong in `ideas.md`.
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

1. **Analyst batch** (#1–#4, #7–#11, #13, #14, #50): highest daily
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