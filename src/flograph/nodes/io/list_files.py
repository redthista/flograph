"""List Files

Turn a folder into a table — one row per file, with its path, name,
extension, size, and modified time. The front of a batch: list `inbox/*.csv`,
filter to the ones newer than the last run, and feed each path into a read +
load pipeline.

**Pattern** is a glob relative to **Folder** (`**/*.parquet` with **Recurse**
on walks subfolders). **Modified after** keeps only files changed since an
ISO date/time — the poor-man's "new since". **Sort** and **Newest first**
order the result; wire the `paths` output (a list) into a Loop node.
"""
NODE = {
    "label": "List Files",
    "category": "IO",
    "version": "1.0",
    "inputs": [("folder", "any", {"optional": True})],
    "outputs": [("files", "dataframe"), ("paths", "object"), ("count", "number")],
}
PARAMS = [
    {"name": "folder", "type": "folder_open", "label": "Folder", "default": ""},
    {"name": "pattern", "type": "string", "label": "Pattern",
     "default": "*", "placeholder": "*.csv"},
    {"name": "recurse", "type": "bool", "label": "Recurse", "default": False},
    {"name": "modified_after", "type": "string", "label": "Modified after",
     "default": "", "placeholder": "2026-08-01  or  2026-08-01T09:00"},
    {"name": "min_bytes", "type": "int", "label": "Minimum size (bytes)",
     "default": 0, "min": 0, "max": 1_000_000_000},
    {"name": "sort", "type": "choice", "label": "Sort by",
     "options": ["modified", "name", "size"], "default": "modified"},
    {"name": "newest_first", "type": "bool", "label": "Newest / largest first",
     "default": True},
]


def run(ctx, folder=None):
    import datetime as dt
    import fnmatch
    import os

    import pandas as pd

    p = ctx.params
    root = (folder if isinstance(folder, str) and folder
            else p.get("folder") or "").strip()
    if not root:
        raise ValueError("no folder — set 'Folder'")
    if not os.path.isdir(root):
        raise ValueError(f"not a folder: {root}")

    pattern = p.get("pattern") or "*"
    after = None
    raw_after = (p.get("modified_after") or "").strip()
    if raw_after:
        try:
            after = dt.datetime.fromisoformat(raw_after).timestamp()
        except ValueError:
            raise ValueError(f"'Modified after' is not an ISO date/time: "
                             f"{raw_after!r}")
    min_bytes = int(p.get("min_bytes", 0))

    rows = []
    walker = (os.walk(root) if p.get("recurse")
              else [(root, [], os.listdir(root))])
    for dirpath, _dirs, names in walker:
        for name in names:
            if not fnmatch.fnmatch(name, pattern):
                continue
            full = os.path.join(dirpath, name)
            if not os.path.isfile(full):
                continue
            st = os.stat(full)
            if st.st_size < min_bytes:
                continue
            if after is not None and st.st_mtime < after:
                continue
            rows.append({
                "path": full,
                "name": name,
                "ext": os.path.splitext(name)[1].lstrip("."),
                "size_bytes": st.st_size,
                "modified": dt.datetime.fromtimestamp(
                    st.st_mtime).isoformat(timespec="seconds"),
            })

    key = {"modified": "modified", "name": "name", "size": "size_bytes"}[p["sort"]]
    rev = bool(p.get("newest_first", True))
    rows.sort(key=lambda r: r[key], reverse=rev)

    files = pd.DataFrame(
        rows, columns=["path", "name", "ext", "size_bytes", "modified"])
    ctx.log(f"{len(files)} file(s) under {root} matching {pattern!r}")
    return {"files": files, "paths": [r["path"] for r in rows],
            "count": int(len(files))}
