# ETL Review

Status: thinking list, based on a review of the built-in nodes on 2026-09-13.

## Short Summary

flograph is already strong for interactive, local, batch ETL over pandas tables.
It has good coverage for files, folders, common database access, REST ingestion,
joins, reshaping, cleaning, validation and outputs.

The main weakness is not the number of table transforms. It is the gap between
"a table transformed successfully" and "a reliable, repeatable, observable
pipeline processed a changing external data source".

The library is currently closer to a desktop data-preparation tool than a
production ETL/orchestration system.

## Product Focus

The primary product is not a general-purpose ETL catalogue. It is a desktop,
local and private way to bring Python's power to people who want Python-based
workflows without having to assemble and maintain the Python environment
themselves.

The important handoff is:

1. Someone technical builds or adjusts a `.flograph` workflow.
2. The workflow is handed to another person.
3. That person opens the project, presses an update/run button and uses the
   resulting dashboards and reports.

This positions flograph between KNIME, Power Query and Power BI, while keeping
the advantages of local execution, Python extensibility and private data. The
node catalogue can grow as real workflows demand it; it does not need to cover
every ETL use case before the core product is useful.

The most important product questions are therefore:

- Does a handed-over project open reliably on another machine?
- Are missing packages, credentials and input files explained clearly?
- Does pressing Update produce the same dependable result every time?
- Are cached results, failures and partial runs understandable?
- Can a report/dashboard consumer use the project without understanding the
  graph or Python?
- Can the technical author extend a workflow without destabilising the user
  experience?

Node breadth should follow those questions. A node is worth adding when it
solves a real workflow need; core stability, reproducibility and handoff are
the product priorities.

## Current Strengths

- CSV, Excel, JSON, Parquet, SQLite, PDF and folder ingestion.
- Folder readers can stack files and retain source-file/folder metadata.
- SQLAlchemy database reads and writes, plus DuckDB queries.
- HTTP requests and several common REST pagination styles.
- Broad pandas transformations: joins, concatenation, filtering, grouping,
  reshaping, deduplication, type conversion, text cleanup and date parts.
- Data Quality Gate with row-level checks, reports and optional failure.
- File discovery, file waiting, shell execution and notifications.
- Good support for local, visual, analyst-driven workflows.

## Main Weaknesses

### 1. No iteration or batch primitive

There is no built-in Loop / For Each / Batch node. `List Files` describes a
`paths` output feeding a Loop node, but no such node currently exists in the
node catalogue (`src/flograph/nodes/io/list_files.py`).

This prevents clean workflows for:

- Processing each file independently.
- Retrying one failed file without rerunning everything.
- Producing one output per input file.
- Passing per-item metadata through a subflow.
- Processing large inputs in bounded batches.
- Running a subflow once per customer, date, partition or API record.
- Collecting per-item successes and failures at the end.

This is the highest-value missing ETL primitive, but it should be treated as a
core execution capability rather than only as another library node. A loop that
is implemented inside a Python Script node can solve one immediate job, but it
does not give the engine visibility into progress, cancellation, caching,
errors, concurrency or fan-in semantics.

### 2. Weak operational lifecycle

`Wait for File` can poll for a file, but there is no durable ingestion state or
file-operation layer. Missing capabilities include:

- Move, copy, archive and delete nodes.
- Claiming or locking a file before processing.
- A processed-file registry.
- Exactly-once or idempotent file handling.
- A real folder watcher.
- Cron, schedule or webhook triggers.
- Run history suitable for a recurring pipeline.

The current pattern is effectively "someone starts the flow, then it waits".
That is useful for desktop work, but not enough for unattended ETL.

### 3. Data contracts and schema drift

`Data Quality Gate` covers useful value checks such as `not_null`, `unique`,
`in`, `between`, regex and row counts. It does not yet provide a complete data
contract layer.

Useful missing checks include:

- Required and optional columns.
- Expected data types.
- Unexpected extra columns.
- Schema versioning and schema diffs.
- Referential integrity between tables.
- Freshness or maximum-age checks.
- Volume and distribution anomaly checks.
- A rejected/quarantine output with a rule reason per row.

The current `clean` output removes failed rows, but a dedicated rejected table
would make investigation and reprocessing much easier.

### 4. Missing high-frequency ETL glue

The transformation catalogue is broad but still lacks several common building
blocks:

- Lookup/map/reference-table enrichment.
- JSON path extraction from table columns.
- Normalisation of nested JSON columns.
- Date arithmetic between columns.
- Date shifting and business-day calculations.
- Complete date-range generation and gap filling.
- Explicit schema alignment before unioning tables.
- Unit conversion and standardised column-name normalisation.

The existing `Date Part` node handles extraction and period boundaries well,
but date arithmetic and complete time-series ranges are separate needs.

### 5. External connectivity is not yet production-grade

The Connect category is a strong addition, but it needs hardening for less
predictable external systems.

HTTP and REST gaps:

- No OAuth2/client-credentials support.
- Limited authentication choices on `REST Paginate`.
- No robust 429 / `Retry-After` handling.
- No checkpoint or resume after a partial pagination run.
- No watermark-based incremental extraction.
- No per-page diagnostics or partial-error output.

Database gaps:

- No first-class watermark/incremental extraction helper.
- No CDC support.
- No schema comparison or migration behaviour.
- No built-in staging-table-plus-merge workflow.
- Query-mode row limiting can still load the full query result before trimming
  in `src/flograph/nodes/connect/sql_query.py`.

Storage gaps:

- No first-class S3-compatible object storage node.
- No Azure Blob or Google Cloud Storage node.
- No SFTP or FTP node.

### 6. Large-data and resumability limitations

Most transformations materialise pandas DataFrames. DuckDB helps with query
pushdown, but the general node contract has no concept of:

- A partition.
- A stream.
- A batch.
- A watermark.
- A checkpoint.
- A resumable run.

This limits very large files, partitioned data and incremental pipelines.

### 7. Integration tests and documentation lag

The newer Connect and Automation nodes do not appear to have dedicated test
files comparable to the older standard-library transform tests. The highest
risk nodes need focused tests for mocked HTTP, pagination failures, SQL writes,
timeouts, cancellation, file races and retry behaviour.

The README also describes only part of the newer transform catalogue and does
not make the full Connect and Automation surface easy to discover.

## Candidate Backlog

### P0: Build first

- **For Each / Batch**: iterate over a list, table rows or files with bounded
  concurrency, per-item context, cancellation and fan-in.
- **File Operations**: move, copy, archive, delete and atomic claim operations.
- **Processed File Registry**: record identity, size, modified time, checksum,
  status and last error so reruns are safe.

### P1: Make pipelines dependable

- **Schema Contract**: validate required columns, types, extras and versions;
  emit a readable schema diff.
- **Quarantine / Reject Rows**: retain failed rows with rule names and source
  metadata instead of only returning a cleaned table.
- **Incremental Load**: persist and emit a watermark for database/API/file
  sources.
- **Lookup / Map**: enrich a table from a mapping or reference table with
  explicit behaviour for missing keys and duplicate keys.
- **Retry and Rate Limit Policy**: shared HTTP behaviour for retries, 429s,
  `Retry-After`, jitter and cancellation.

### P2: Broaden ETL coverage

- SFTP, FTP and cloud object storage connectors.
- Date arithmetic, business-day offsets and complete date ranges.
- JSON path and nested-record normalisation.
- Referential-integrity and freshness checks.
- Staging-table/merge helpers for database loads.
- Scheduler, webhook trigger and durable run history.

### P3: Improve confidence and discoverability

- Dedicated tests for Connect and Automation nodes.
- End-to-end ETL example projects: API to warehouse, folder to database and
  incremental vendor feed.
- Update README and in-app documentation to match the actual node catalogue.

## What I Would Like To Tackle

The best first implementation target is a **core-supported For Each / Batch
mechanism**, provided it can be added without bypassing the graph's dependency,
cancellation and cache rules.

A sensible first version would be deliberately narrow:

- Input: a list of values or a table of items.
- One child/subflow body executed once per item.
- Configurable maximum concurrent items.
- Stop-on-first-error or collect-errors mode.
- Outputs for successful results, failures and summary counts.
- Cancellation between items and a progress signal.
- Stable item order in the fan-in result.

That feature would make `List Files` materially more useful and would unlock
per-file ETL without immediately requiring a full scheduler or distributed
runtime. More importantly, it would establish a reusable execution primitive
that future nodes can rely on instead of each node inventing its own loop,
progress reporting, retry behaviour and error handling.

The second feature I would take on is a **Schema Contract / Quarantine** pair.
Together they would turn the current Data Quality Gate from a useful validator
into something suitable for protecting recurring loads.

## Core-First Recommended Sequence

1. Stabilise the handoff path: project open, package diagnostics, environment
   requirements, input-file diagnostics and portable dashboard/report results.
2. Specify the execution semantics for For Each / Batch and add a small engine
   prototype.
3. Add headless tests for cancellation, progress, caching, ordering and a
   deliberately failing item.
4. Exercise the one-click Update path on complete example projects from a clean
   environment.
5. Improve run status, error explanations, stale-cache behaviour and recovery
   from partial runs.
6. Add file operations, schema contracts or new connectors only when a real
   handoff workflow needs them.

The success criterion is not "the node catalogue covers every ETL pattern".
It is "a technical user can build a private Python-powered workflow and hand it
to a non-technical user who can refresh and trust the resulting report".
