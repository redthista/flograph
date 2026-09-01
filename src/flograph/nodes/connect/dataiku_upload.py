"""Dataiku Upload

Push the incoming table (or a local file) into a Dataiku DSS flow, replacing
what's there — then pass the table straight through so the rest of the
flograph pipeline keeps going. Wire **Dataiku Action** after it (on an order
edge) to rebuild the DSS flow once the new data has landed.

**Target**:

  • **managed folder** — overwrite one file at a path inside a managed folder
    (`put_file`). This is the literal "replace a file in the workflow": a
    files-in-folder dataset sits on top of it and picks up the new bytes.
  • **uploaded dataset** — add a file to an "Uploaded files" dataset and
    re-detect its schema. `uploaded_add_file` *appends*, so choose
    **replace = clear first** to drop the existing files before uploading.

**Source** is the wired table (serialised to CSV / Parquet / JSON / Excel) or
a local file read as-is.

Leave **API key** blank to fall back to `$DKU_API_KEY`. Uses the external
`dataikuapi` client. This is a write — set the node to *manual* if you don't
want every Run All pushing to DSS.
"""
NODE = {
    "label": "Dataiku Upload",
    "category": "Connect",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "host", "type": "string", "label": "DSS URL",
     "default": "", "placeholder": "https://dss-host:11200"},
    {"name": "api_key", "type": "password", "label": "API key",
     "default": "", "placeholder": "blank = $DKU_API_KEY / ${env:DKU_API_KEY}"},
    {"name": "project_key", "type": "string", "label": "Project key",
     "default": "", "placeholder": "e.g. WORKFORCE_LOADING"},

    {"name": "target", "type": "choice", "label": "Target",
     "options": ["managed folder", "uploaded dataset"],
     "default": "managed folder"},
    {"name": "folder_id", "type": "string", "label": "Managed folder id",
     "default": "",
     "visible_when": {"target": ["managed folder"]}},
    {"name": "path", "type": "string", "label": "File path in folder",
     "default": "", "placeholder": "/incoming/data.csv",
     "visible_when": {"target": ["managed folder"]}},
    {"name": "dataset_name", "type": "string", "label": "Dataset name",
     "default": "",
     "visible_when": {"target": ["uploaded dataset"]}},

    {"name": "source", "type": "choice", "label": "Upload",
     "options": ["the wired table", "a local file"],
     "default": "the wired table"},
    {"name": "format", "type": "choice", "label": "Serialise table as",
     "options": ["csv", "parquet", "json", "xlsx"], "default": "csv",
     "visible_when": {"source": ["the wired table"]}},
    {"name": "file", "type": "file_open", "label": "Local file",
     "default": "",
     "visible_when": {"source": ["a local file"]}},

    {"name": "replace", "type": "choice", "label": "Replace",
     "options": ["overwrite this file", "clear first"],
     "default": "overwrite this file"},
    {"name": "insecure_tls", "type": "bool", "label": "Disable TLS verification",
     "default": False},
]


def run(ctx, table):
    import io
    import os

    from flograph.nodes.connect import _dataiku

    p = ctx.params

    # Build the payload bytes.
    if p.get("source") == "a local file":
        fpath = (p.get("file") or "").strip()
        if not fpath:
            raise ValueError("no file — set 'Local file' (or switch 'Upload' "
                             "to the wired table)")
        if not os.path.isfile(fpath):
            raise ValueError(f"file not found: {fpath}")
        with open(fpath, "rb") as fh:
            payload = fh.read()
        filename = os.path.basename(fpath)
    else:
        fmt = p.get("format", "csv")
        payload, ext = _dataiku.serialise(table, fmt)
        filename = f"flograph-upload.{ext}"

    _client, project = _dataiku.connect(p)
    clear_first = p.get("replace") == "clear first"

    if p.get("target") == "managed folder":
        fid = (p.get("folder_id") or "").strip()
        path = (p.get("path") or "").strip()
        if not fid or not path:
            raise ValueError("set both 'Managed folder id' and 'File path in "
                             "folder'")
        folder = project.get_managed_folder(fid)
        if clear_first:
            for item in folder.list_contents().get("items", []):
                folder.delete_file(item["path"])
            ctx.log("cleared existing folder contents")
        folder.put_file(path, io.BytesIO(payload))
        ctx.log(f"put {len(payload)} bytes -> folder {fid}:{path}")

    else:  # uploaded dataset
        name = (p.get("dataset_name") or "").strip()
        if not name:
            raise ValueError("no dataset — set 'Dataset name'")
        dataset = project.get_dataset(name)
        if clear_first:
            existing = dataset.uploaded_list_files()
            remove = getattr(dataset, "uploaded_remove_file", None)
            if remove is None:
                raise ValueError(
                    "this dataikuapi version can't delete files from an "
                    "uploaded dataset — recreate the dataset in DSS, or use "
                    "the 'managed folder' target instead")
            for f in existing:
                remove(f["id"])
            ctx.log(f"cleared {len(existing)} existing file(s)")
        dataset.uploaded_add_file(io.BytesIO(payload), filename)
        dataset.autodetect_settings().save()
        ctx.log(f"added {filename} ({len(payload)} bytes) -> dataset {name}, "
                "schema re-detected")

    return table
