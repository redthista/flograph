# Managed Folders

A **Managed Folder** keeps files inside your `.flograph` project. Use it for
lookup versions, reference files, or results you want to carry with a flow.
The files are original file bytes, separate from execution caches: resetting
caches does not delete them.

## File formats and encodings

A folder can store any file as original bytes. Tabular readers and lookups support
CSV/TSV/delimited text, Excel (.xlsx, .xlsm, .xls, .xlsb), OpenDocument
spreadsheets, JSON/JSON Lines/NDJSON and Parquet (.parquet/.pq). Excel and
Parquet use the existing optional engines; older Excel/binary Excel/ODS use
calamine when installed, otherwise pandas requests the relevant engine.
No dependencies are installed automatically.

For CSV/text/JSON, specify **Encoding** explicitly: UTF-8, UTF-8 with BOM
(utf-8-sig), Latin-1 (latin-1), Windows-1252 (cp1252), UTF-16, and standard
Python encodings are accepted. No encoding guessing is performed. Rules may
override encoding, separator, format and Excel sheet per lookup, allowing mixed
files in one run. Blank rule settings inherit the node settings. Decoding and
engine errors appear in rules-mode diagnostics.

Gzip, bzip2, xz and single-file ZIP wrappers are supported for named formats
such as lookup.csv.gz. Parquet retains its native internal compression support.
Unsupported formats remain available as bytes/text through Read Managed File.

## Add and browse files

Add **Managed Folder** from the library. Its canvas card has an **Upload…**
button and accepts files dropped from your file manager. Switch between
**Details** (name, type and size) and **Large icons**. Duplicate names ask
before replacement. Import, rename and remove support Undo and Redo.

Right-click a file for **Save As…**, which opens the system save dialog,
**Rename…**, **Remove**, or **Use in Flow**. Use in Flow adds a reader and
connects it to the selected file. Drag files out to your desktop or file
manager to copy them out. Exporting keeps the originals in the project.

## Duplicate and edit CSV files

Right-click a file and choose **Duplicate…**, then enter a new filename. The
copy keeps the original bytes and metadata, and can be undone. Duplicate works
for all stored file types.

For a CSV or TSV file, **Edit CSV…** opens a cell editor. Values stay as text,
so leading zeros are preserved. Columns size to their content and headers, with long columns initially limited
to 480 pixels. Drag a column edge to adjust it. **Wrap text** at the top wraps
long values and fits row heights, including after column resizing. Turning wrap
off restores compact rows. Compact row height is also the default when opening
the editor. Wrapping breaks long URLs/identifiers as well as ordinary paragraphs. Column fitting after edits is batched to keep typing
responsive. These view settings do not change the CSV values.

The first CSV row supplies the column headers. Right-click a header to rename
it or add/remove columns; right-click cells or row numbers for row commands. Open **Find and Replace…** from the right-click menu for a separate dialog with
**Find next**, **Replace**, and **Replace all**. **F3** repeats the search.
**Ctrl+F** opens the dialog at Find; **Ctrl+H** opens it at Replace with. Match case and Whole
cell are optional. Search wraps through data cells. Rename headers from their right-click menu. Empty replacement text removes matches; an empty search makes no changes.
Replacements stay in the editor until Save, so Cancel leaves the original file.

Check the encoding
and separator; change them and press **Reload** if needed. Reload asks before
discarding edits. Non-UTF-8 files require an explicit encoding selection unless
stored metadata already provides one. The editor suggests common separators.

**Save** replaces the embedded file, keeping its metadata and adding an
`edited_at` timestamp; the original source file on disk is unchanged. The editor
retains the selected encoding and original line-ending style. Cancel leaves the
file untouched; saving without changes preserves the original bytes exactly.
Edits and duplicates support Undo/Redo and invalidate downstream results.

## File metadata and custom columns

The **Details** view can show filename, extension, size in bytes, **source modified**
and **imported** timestamps. Dates are stored as UTC ISO timestamps. They are a
snapshot at import: changing a file on disk does not update the embedded copy.
Older embedded files and generated data have no source modified date unless known.

Right-click a column header in **Details** to show/hide fields. Choose **Add metadata column…** to add your
own field, such as owner, version, status or notes. Double-click a custom cell in
Details to edit its text. Built-in fields are read-only. Changes support Undo/Redo.
Custom values stay attached when files are renamed and are removed with their file.
Replacing a file preserves its custom values while refreshing available import dates.

Metadata and custom columns are saved inside the project. The **files** output
contains all metadata columns even when hidden in the visual. Connect it to an
existing Join to add file-level metadata to your data using the filename column.
Newly added custom columns are included even before they have values. Exporting a
file writes its original bytes; custom project metadata is not inserted into those bytes.

## Read a file without code

Connect **Managed Folder → folder** to **Read Managed File → folder**, then
choose a filename in the reader's dropdown. Connect its **table** output to
existing nodes such as Join, Filter Rows or Show Table. CSV, TSV, Excel,
JSON and Parquet are supported; Excel and Parquet need their usual packages.
The reader's Properties include format, CSV separator, Excel sheet and encoding.
For another file type, choose **Read as = bytes** or **text** and use **data**.

For dynamic selection, connect a Choice or other string-producing node to the
reader's **filename** input. That wire overrides the dropdown. Merely selecting
a file in the folder card never changes a reader's selected filename.

The folder's **files** output is a metadata table with `filename`, `extension`
and `size_bytes`, suitable for existing filtering and selection nodes.

## Choose a lookup file from a table column

Use **Lookup Chooser** when different rows need different lookup versions.
Connect your data to **table** and the Managed Folder to **folder**. Set:

- **Filename column**: the column containing a lookup filename for each row.
- **Left columns (data)**: join keys from your data, such as `product, region`.
- **Right columns (lookup)**: matching keys in the files, such as `sku, area`.

Multiple names are separated by commas and paired in the same order. Every
row uses the file named in that row. The result keeps input order and all
input rows; unmatched keys have blank lookup columns. Duplicate right-side join keys are omitted; existing main columns are retained. Each file is read once per run. Lookup keys
must be unique within each file, preventing accidental row multiplication.
Missing files, missing columns and blank filenames stop with an explanation.

The bottom branch in **42 Managed Folder** demonstrates filenames stored in
`lookup_file` and a two-column match. Its output prices are **10, 25, 12**.

## Apply several lookups from a rules table

Connect a table to Lookup Chooser's optional **rules** input. Set **Source filename
column (with rules)** to the main table's source filename column, such as `filename`.
The node applies every rule matching a source file, in rules-table order.

| Rules column | Meaning |
| --- | --- |
| source_file | Source filename in the concatenated main data |
| lookup_file | File in the Managed Folder |
| left_on | Main keys, comma-separated |
| right_on | Lookup keys, paired with left_on in order |
| columns | Optional: blank = all lookup values; otherwise comma-separated return columns |
| encoding | Optional per-rule text encoding, such as utf-8, utf-8-sig, latin-1 or cp1252 |
| separator | Optional CSV delimiter, such as comma, semicolon, \t, or auto |
| sheet | Optional Excel sheet name or zero-based index; blank = node setting / first sheet |
| format | Optional auto, csv, excel, json or parquet override |

Right-side join keys are omitted. Original main columns are retained; duplicate
lookup columns are skipped. Different source groups can populate the same new
column. If two rules target the same row and column, the first matched rule wins
and diagnostics identify the conflict. A missing match leaves the value blank.

The **diagnostics** output is an ordinary table. It reports no applicable rule,
source file absent from the main data, missing lookup files/columns, invalid or
duplicate keys, unmatched main keys, unused lookup keys, empty lookup values,
and retained existing columns/conflicts. Main rows are identified by zero-based
position (safe even with duplicate index labels); rules use one-based row numbers.
File/rule failures are reported without dropping main rows. A malformed rules
schema or missing source filename column stops the node with an explanation.
Unused lookup keys are reported per rule/source, rather than globally across sources.

**Performance:** existing pandas/NumPy only; no new dependencies. Source groups
are computed once and each distinct lookup/read-settings combination is read once per run. Joins
operate on groups using just keys and requested return columns. Diagnostics
necessarily grow with the number of problems found.

The example's **Rules-driven lookups** canvas tab shows one source file receiving
two lookups, optional column selection, and diagnostics alongside the enriched table.

**Reader appearance:** change **Description above dropdown** in Read Managed
File's Properties to customize its hint. The card automatically fits the description
and dropdown; an empty description hides the hint.

## Upload files through nodes

Use **Upload to Managed Folder → Managed Folder → Read Managed File**.
Choose a local file in the upload node's Properties, or wire a file path into
**source**. You can also wire an existing table into source: it becomes a CSV,
with **Save as name** defaulting to `table.csv`. Raw bytes need an explicit name.

The optional **folder** input lets multiple upload nodes build a collection in
sequence. Replacing a name already in that input requires **Replace existing
file**. A Managed Folder card overlays its incoming collection onto its stored
files: incoming names win. After a desktop run, incoming files are imported as
an undoable edit and included when you save the project. The flow refreshes
once to reflect that stored snapshot.

An attached upload node owns its incoming files: rename/remove on the card
will be overwritten the next time that upload is applied. Disconnect incoming
to work with the imported files independently. Local file paths on upload nodes
still require those external sources when you re-run the upload.

Headless runs produce the same immutable folder outputs without editing the
source project. Save the imported snapshot from the desktop when you want it
to become a permanent project asset.

## Save and share

Save `.flograph` to store files as separate assets inside the project bundle.
Save As carries them along, even when no output caches are saved. Workflow-only
`.flowf` exports embed the files as base64, so they remain portable too (large
files make that text export larger). Removing the last reference to a file and
saving removes its asset from the new bundle.

## Example

Open **42 Managed Folder** from the example templates. It includes sales and
two lookup versions, a Choice control, a Join and a Show Table. Run it, change
the lookup version, and run again: the joined prices change. A second branch
uploads the joined table as CSV to an **Export files** folder. The canvas note
and **How this example works** report explain each connection.

## Optional Python API

No Python is required for the workflow above. A custom node receiving a wired
folder can read it directly:

```python
def run(ctx, folder):
    import pandas as pd
    with folder.open("lookup_v2.csv", "rb") as stream:
        table = pd.read_csv(stream)
    return {"table": table}
```

`folder.names()` lists filenames. `folder.read_bytes(name)` returns original
bytes. `folder.open(name, "r", encoding="utf-8")` reads text. Folder inputs are
immutable snapshots; use the upload node to produce an updated collection.
