"""Upload to Managed Folder

Choose a local file, or wire a file path, bytes, or a table into source.
Tables are saved as CSV; bytes require a Save as name. Connect the folder
output to a Managed Folder card's incoming port. An optional folder input
lets several upload nodes build a folder in sequence. Existing names are
rejected unless Replace existing file is enabled.
"""
NODE = {
    "label": "Upload to Managed Folder", "category": "IO", "version": "1.1",
    "inputs": [("folder", "object", {"optional": True}),
               ("source", "any", {"optional": True})],
    "outputs": [("folder", "object")],
}
PARAMS = [
    {"name": "path", "type": "file_open", "label": "File to upload", "default": ""},
    {"name": "filename", "type": "string", "label": "Save as name (optional)", "default": ""},
    {"name": "replace", "type": "bool", "label": "Replace existing file", "default": False},
]


def run(ctx, folder=None, source=None):
    from pathlib import Path
    from flograph.core.managed_folder import ManagedFolder, import_metadata
    path = source if source is not None else ctx.params.get("path", "")
    if source is None and not path:
        raise ValueError("Choose a file to upload, or connect a file path to source")
    if folder is None:
        folder = ManagedFolder()
    if not isinstance(folder, ManagedFolder):
        raise TypeError("Connect a managed folder to folder")
    ctx.check_cancelled()
    metadata = import_metadata()
    name = ctx.params.get("filename", "").strip()
    if isinstance(source, bytes):
        data = source
        if not name:
            raise ValueError("Set Save as name when uploading bytes")
    elif hasattr(source, "to_csv"):
        data = source.to_csv(index=False).encode("utf-8")
        name = name or "table.csv"
    else:
        data = Path(path).read_bytes()
        metadata = import_metadata(Path(path))
        name = name or Path(path).name
    return {"folder": folder.with_file(name, data, replace=ctx.params.get("replace", False), metadata=metadata)}
