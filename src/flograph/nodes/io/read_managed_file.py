"""Read Managed File

Connect a Managed Folder, then choose its filename on the card. A wired
filename overrides the choice, allowing a Choice or conditional node to
select a lookup version. Table output connects to ordinary Join, Filter,
and chart nodes. Original bytes and text are available for other readers.
"""
NODE = {
    "label": "Read Managed File", "category": "IO", "version": "1.3",
    "card": "managed_reader",
    "inputs": [("folder", "object", {"suggest": ["flograph.io.managed_folder"]}),
               ("filename", "string", {"optional": True})],
    "outputs": [("table", "dataframe"), ("data", "object")],
}
PARAMS = [
    {"name": "description", "type": "string", "label": "Description above dropdown",
     "default": "Choose a file, or wire a filename to select it dynamically.", "cosmetic": True},
    {"name": "filename", "type": "string", "label": "Filename", "default": ""},
    {"name": "format", "type": "choice", "label": "Read as", "default": "auto",
     "options": ["auto", "csv", "excel", "json", "parquet", "bytes", "text"]},
    {"name": "separator", "type": "string", "default": ","},
    {"name": "sheet", "type": "string", "label": "Excel sheet (empty = first)", "default": ""},
    {"name": "encoding", "type": "string", "default": "utf-8"},
    {"name": "width", "type": "int", "default": 360, "min": 300, "max": 1200, "cosmetic": True},
    {"name": "height", "type": "int", "default": 0, "hidden": True, "cosmetic": True},
]


def run(ctx, folder, filename=None):
    from flograph.core.managed_folder import ManagedFolder, read_table
    import pandas as pd
    if not isinstance(folder, ManagedFolder):
        raise TypeError("Connect a Managed Folder to folder")
    name = filename if filename is not None else ctx.params.get("filename", "")
    if not name:
        raise ValueError("Choose a filename on the reader card, or connect a filename input")
    fmt = ctx.params.get("format", "auto")
    data = folder.read_bytes(name)
    if fmt in ("bytes", "text"):
        table = pd.DataFrame()
        if fmt == "text":
            data = data.decode(ctx.params.get("encoding", "utf-8"))
    else:
        table = read_table(folder, name, format=fmt,
                           separator=ctx.params.get("separator", ","),
                           sheet=ctx.params.get("sheet", ""),
                           encoding=ctx.params.get("encoding", "utf-8"))
    ctx.log(f"Read {name}")
    return {"table": table, "data": data}
