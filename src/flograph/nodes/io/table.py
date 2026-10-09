"""Table

A spreadsheet you fill in directly on the canvas — type values into the
grid and they flow out as a DataFrame.

Cells starting with = are Excel-style formulas: A1-style references
(=A2*B2, =SUM(C1:C10), $A$1 pins), named column references ([@Price] for
this row's value, [Price] for the whole column — =[@Price]*[@Qty],
=SUM([Total])), the usual operators, and about a hundred of Excel's
functions: SUM, IF and ROUND, lookups (VLOOKUP, XLOOKUP, INDEX/MATCH),
SUMIF/COUNTIF(S), IFERROR, text (SUBSTITUTE, TEXT, TEXTJOIN) and dates
(TODAY, EDATE, DATEDIF, NETWORKDAYS). Dates add and subtract like Excel's:
=[@Due]+7, =[@End]-[@Start]. Row 1 is the first data row. Named references follow
renames and don't shift when columns move — ideal for linked-input
tables whose column layout may change.

The ribbon along the top of the grid holds every command, grouped like
Excel's: Home (clipboard, rows and columns, fill, find), Data (sort, filter,
column type, dropdown lists), View (freeze panes, fit columns) and Formulas.
Right-click any cell, row number or column header for the same commands
where you are. Hover a button for what it does and its shortcut.

Submit: on a big flow, every edit re-running what follows is a lot of
waiting. Turn off Auto-apply on the ribbon (or set Apply edits to submit)
and edits are held — the flow keeps using the table as last submitted until
you press Submit (F9), or Discard to throw them away. Held edits are saved
with the project and undo like any other.

Conditional formatting uses Show Table's rules — colour scales, data
bars, icon sets, highlights — from the ribbon's Conditional Formatting list
or the Conditional formatting box in Properties (its Rules… button builds
them). Rules paint the grid; they never change a value.

Each column has a type (right-click its header): auto guesses numbers,
while text/number/integer/date/bool make the output dtype explicit —
values that don't fit become missing (the grid flags them red as you
type). Use the expand button on the card for the full editor with a
formula bar, and paste straight from Excel or Sheets. Drag the node
onto a dashboard page and the grid comes with it, still editable —
maximize that tile for a full-page spreadsheet, and edits re-run the
visuals beside it.

The optional input links the table to upstream data, like an Excel table
with custom columns beside a Power Query load: every run refreshes the
columns the input owns (matched by name), while columns you add on top
survive — their formulas fill down as rows grow. Edits to input-owned
cells are overwritten on the next run; put your work in your own columns.

A grid holds up to 200,000 linked rows. Past that the node stops with a
message rather than turning millions of rows into spreadsheet cells, which
costs gigabytes of memory before anything is drawn — use Show Table to look
at data that size, or filter it down before the grid.

Disconnect the input and the contents stay — whatever the grid was showing
is written into the table as your own cells, so the node carries the data
from there on. Undo puts the wire and the old sheet back together. Right-
click for "Import input into table" to do the same without disconnecting.
"""
import json

NODE = {
    "label": "Table",
    "category": "IO",
    "version": "1.4",
    "card": "grid",
    "inputs": [("table", "dataframe", {"optional": True})],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "data", "type": "text", "label": "Table data (JSON)",
     "hidden": True,
     # how the sheet looks, not what it holds: changing only these re-runs
     # nothing (core/params.ParamSpec.presentation)
     "presentation": ["freeze", "totals", "notes", "styles", "groups",
                      "hidden_rows", "row_heights", "columns.*.width",
                      "columns.*.format",
                      "columns.*.total", "columns.*.choices",
                      "columns.*.strict", "columns.*.validation",
                      "columns.*.hidden"],
     "default": json.dumps({
         "version": 2,
         "columns": [{"name": "A", "type": "auto"},
                     {"name": "B", "type": "auto"}],
         "rows": [["", ""], ["", ""]],
     })},
    # live: every edit goes straight into the flow. submit: edits wait in
    # `draft` (cosmetic, so it marks nothing out of date and starts no run)
    # until Submit — see ui/spreadsheet/binding.py.
    {"name": "apply", "type": "choice", "label": "Apply edits",
     "options": ["live", "submit"], "default": "live", "cosmetic": True},
    {"name": "draft", "type": "text", "label": "Edits not yet submitted",
     "hidden": True, "default": "", "cosmetic": True},
    # Conditional formatting, in Show Table's rules language and with its
    # rule builder. Paints the grid only: never changes a value or what
    # flows on, so editing it re-runs nothing.
    {"name": "rules", "type": "text", "label": "Conditional formatting",
     "default": "", "cosmetic": True, "rule_wizard": True,
     "placeholder": "Total scale green\nUnits bar blue\n"
                    "Status = Open => bg amber"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 320, "min": 220, "max": 4000, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 260, "min": 160, "max": 4000, "cosmetic": True},
]

_TRUTHY = {"TRUE": True, "FALSE": False, "YES": True, "NO": False,
           "1": True, "0": False}


def _coerce_auto(values):
    """Best-effort numeric coercion for a column; None means "leave the
    whole column alone" (mixed or non-numeric content)."""
    numeric = []
    for v in values:
        if v is None or v == "":
            numeric.append(None)
            continue
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            numeric.append(v)
            continue
        try:
            numeric.append(int(v))
            continue
        except (TypeError, ValueError):
            pass
        try:
            numeric.append(float(v))
        except (TypeError, ValueError):
            return None
    return numeric


def run(ctx, table=None):
    import pandas as pd
    from flograph.core.sheet import (cell_name, evaluate_sheet, format_value,
                                     parse_sheet, sheet_from_dataframe)

    if table is not None:
        # linked mode: input columns refresh, user-added columns survive
        from flograph.core.sheet import merge_linked_sheet
        from flograph.core.sheet.engine import MAX_LINKED_ROWS
        if len(table) > MAX_LINKED_ROWS:
            # Every row would become spreadsheet cells — held three times
            # over while the grid refreshes — which is gigabytes before
            # anything is drawn. Refusing is the kindest answer: the flow
            # stops on this node with a way forward, rather than the whole
            # app going down with the data still unseen.
            raise ValueError(
                f"a Table grid holds up to {MAX_LINKED_ROWS:,} rows, and this "
                f"input has {len(table):,}. Every row becomes spreadsheet "
                f"cells, which needs gigabytes of memory before anything is "
                f"drawn. Use Show Table to look at data this size, or filter "
                f"it down before the grid.")
        base = sheet_from_dataframe(table)
        sheet = merge_linked_sheet(base, parse_sheet(ctx.params["data"]))
        extra = sheet.n_cols - base.n_cols
        ctx.log(f"linked input: {base.n_rows} rows x {base.n_cols} columns"
                + (f" + {extra} of your column(s)" if extra else ""))
    else:
        sheet = parse_sheet(ctx.params["data"])
    if not sheet.columns:
        return pd.DataFrame()

    result = evaluate_sheet(sheet)
    if result.errors:
        cells = sorted(result.errors)
        names = ", ".join(cell_name(r, c) for r, c in cells[:5])
        if len(cells) > 5:
            names += f" and {len(cells) - 5} more"
        raise ValueError(
            f"formula error in {names}: {result.errors[cells[0]]}")

    # computed values in, blanks as None so typed columns get real NAs
    table = pd.DataFrame(
        [[None if v == "" else v for v in row] for row in result.values],
        columns=sheet.column_names(), dtype=object)

    for spec, col in zip(sheet.columns, table.columns):
        series = table[col]
        if spec.type == "auto":
            numeric = _coerce_auto(series.tolist())
            if numeric is not None:
                table[col] = numeric
            else:
                # mixed content stays text, like the pre-formula node
                table[col] = series.map(
                    lambda v: v if v is None else format_value(v))
        elif spec.type == "text":
            table[col] = series.map(
                lambda v: v if v is None else str(v)).astype("string")
        elif spec.type in ("number", "integer"):
            typed = pd.to_numeric(series, errors="coerce")
            bad = int((typed.isna() & series.notna()).sum())
            if bad:
                ctx.log(f"column {spec.name!r}: {bad} value(s) aren't "
                        "numbers, set to missing")
            table[col] = typed.astype(
                "Int64" if spec.type == "integer" else "Float64")
        elif spec.type == "date":
            typed = pd.to_datetime(series, errors="coerce", format="mixed")
            bad = int((typed.isna() & series.notna()).sum())
            if bad:
                ctx.log(f"column {spec.name!r}: {bad} value(s) aren't "
                        "dates, set to missing")
            table[col] = typed
        elif spec.type == "bool":
            # a blank cell is an unticked box on the grid, so it is FALSE
            # here too — what the card shows and what flows on agree
            typed = series.map(
                lambda v: False if v is None
                else v if isinstance(v, bool)
                else _TRUTHY.get(str(v).strip().upper()))
            bad = int(sum(1 for v, orig in zip(typed, series)
                          if v is None and orig is not None))
            if bad:
                ctx.log(f"column {spec.name!r}: {bad} value(s) aren't "
                        "TRUE/FALSE, set to missing")
            table[col] = typed.astype("boolean")

    ctx.log(f"{len(table)} rows x {len(table.columns)} columns")
    return table
