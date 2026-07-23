"""Table

A spreadsheet you fill in directly on the canvas — type values into the
grid and they flow out as a DataFrame.

Cells starting with = are Excel-style formulas: A1-style references
(=A2*B2, =SUM(C1:C10), $A$1 pins), named column references ([@Price] for
this row's value, [Price] for the whole column — =[@Price]*[@Qty],
=SUM([Total])), the usual operators, and functions like SUM, AVERAGE,
IF, ROUND, CONCAT. Row 1 is the first data row. Named references follow
renames and don't shift when columns move — ideal for linked-input
tables whose column layout may change.

Each column has a type (right-click its header): auto guesses numbers,
while text/number/integer/date/bool make the output dtype explicit —
values that don't fit become missing (the grid flags them red as you
type). Use the expand button on the card for the full editor with a
formula bar, and paste straight from Excel or Sheets.

The optional input links the table to upstream data, like an Excel table
with custom columns beside a Power Query load: every run refreshes the
columns the input owns (matched by name), while columns you add on top
survive — their formulas fill down as rows grow. Edits to input-owned
cells are overwritten on the next run; put your work in your own columns.
Right-click the node for "Import input into table" to snapshot everything
into the grid (then disconnect to fully own the data).
"""
import json

NODE = {
    "label": "Table",
    "category": "IO",
    "card": "grid",
    "inputs": [("table", "dataframe", {"optional": True})],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "data", "type": "text", "label": "Table data (JSON)",
     "hidden": True,
     "default": json.dumps({
         "version": 2,
         "columns": [{"name": "A", "type": "auto"},
                     {"name": "B", "type": "auto"}],
         "rows": [["", ""], ["", ""]],
     })},
    {"name": "width", "type": "int", "label": "Width",
     "default": 320, "min": 220, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 220, "min": 140, "max": 2000},
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
            typed = series.map(
                lambda v: v if isinstance(v, (bool, type(None)))
                else _TRUTHY.get(str(v).strip().upper()))
            bad = int(sum(1 for v, orig in zip(typed, series)
                          if v is None and orig is not None))
            if bad:
                ctx.log(f"column {spec.name!r}: {bad} value(s) aren't "
                        "TRUE/FALSE, set to missing")
            table[col] = typed.astype("boolean")

    ctx.log(f"{len(table)} rows x {len(table.columns)} columns")
    return table
