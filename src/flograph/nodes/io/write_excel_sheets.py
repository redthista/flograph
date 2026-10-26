"""Write Excel (Sheets)

Several tables into one workbook, one sheet each — the P&L, by product and
by region as tabs of a single client-ready file instead of three exports.

Wire the first table into **sheet1** and the next into **sheet2**; every
time you fill the empty port at the bottom another appears, so five sheets
is one node. **Sheet names**, one per line in port order, name the tabs
(blank lines and missing names become Sheet1, Sheet2, …). Excel allows 31
characters and none of `[ ] : * ? / \\`; a name that breaks that is cut
down and cleaned rather than failing the write.

**Summary sheet** adds a first tab listing every sheet with its rows and
columns. **Fit columns** sizes each column to its contents, **Bold header**
and **Freeze header** make the header row read as one.

The file is written whole each run, replacing what was there. Needs the
`openpyxl` package (the `excel` extra). **path** comes out for the next
step — an email, a File Operations move to an archive folder.
"""
NODE = {
    "label": "Write Excel (Sheets)",
    "category": "IO",
    "version": "1.0",
    "inputs": [
        ("sheet1", "dataframe"),
        ("sheet2", "dataframe", {"optional": True}),
        # the always-empty slot at the bottom: wiring it adds a permanent
        # port (in3, in4, ...) and a fresh empty slot appears below
        ("more", "dataframe", {"optional": True, "spare": True}),
    ],
    "outputs": [("path", "string")],
}
PARAMS = [
    {"name": "path", "type": "file_save", "label": "Output file",
     "default": ""},
    {"name": "add_summary", "type": "bool", "label": "Summary sheet",
     "default": False},
    {"name": "autofit", "type": "bool", "label": "Fit columns",
     "default": True},
    {"name": "bold_header", "type": "bool", "label": "Bold header",
     "default": True},
    {"name": "freeze_header", "type": "bool", "label": "Freeze header",
     "default": True},
    {"name": "index", "type": "bool", "label": "Write index",
     "default": False},
    {"name": "sheet_names", "type": "text", "label": "Sheet names",
     "default": "", "placeholder": "P&L\nBy product\nBy region"},
]

_FIXED_ORDER = ("sheet1", "sheet2")
_BAD = set('[]:*?/\\')


def _clean(name, n, taken):
    """A sheet name Excel will take, unique in this workbook."""
    text = "".join(ch for ch in str(name).strip() if ch not in _BAD)
    text = text.strip("'")[:31] or f"Sheet{n}"
    base, k = text, 2
    while text.lower() in taken:
        suffix = f" ({k})"
        text = base[:31 - len(suffix)] + suffix
        k += 1
    taken.add(text.lower())
    return text


def run(ctx, **inputs):
    import os

    import pandas as pd

    p = ctx.params
    path = str(p["path"]).strip()
    if not path:
        raise ValueError("no file chosen — set 'Output file'")
    if not path.lower().endswith((".xlsx", ".xlsm")):
        raise ValueError("'Output file' must end in .xlsx")

    def grown_number(name):
        return int(name[2:]) if name[2:].isdigit() else 0

    names = [n for n in _FIXED_ORDER if inputs.get(n) is not None]
    names += sorted((k for k in inputs
                     if k.startswith("in") and inputs[k] is not None),
                    key=grown_number)
    frames = [inputs[n] for n in names]
    if not frames:
        raise ValueError("connect at least one table to 'sheet1'")

    typed = p["sheet_names"].splitlines()
    taken = {"summary"} if p["add_summary"] else set()
    titles = [_clean(typed[i] if i < len(typed) else "", i + 1, taken)
              for i in range(len(frames))]

    try:
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Write Excel (Sheets) needs openpyxl — install it from Tools ▸ "
            "Manage Packages…") from exc

    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    index = bool(p["index"])
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        if p["add_summary"]:
            pd.DataFrame({
                "sheet": titles,
                "rows": [len(f) for f in frames],
                "columns": [f.shape[1] for f in frames],
            }).to_excel(writer, sheet_name="Summary", index=False)
        for title, frame in zip(titles, frames):
            ctx.check_cancelled()
            frame.to_excel(writer, sheet_name=title, index=index)

        for sheet in writer.book.worksheets:
            if sheet.max_row < 1:
                continue
            if p["bold_header"]:
                for cell in sheet[1]:
                    cell.font = Font(bold=True)
            if p["freeze_header"]:
                sheet.freeze_panes = "A2"
            if p["autofit"]:
                for i, column in enumerate(sheet.iter_cols(
                        max_row=min(sheet.max_row, 2000)), 1):
                    widest = max((len(str(c.value)) for c in column
                                  if c.value is not None), default=0)
                    sheet.column_dimensions[get_column_letter(i)].width = \
                        min(60, max(8, widest + 2))

    ctx.log(f"wrote {len(frames)} sheet(s) to {os.path.basename(path)}: "
            + ", ".join(f"{t} ({len(f)} rows)" for t, f in zip(titles, frames)))
    return {"path": path}
