"""File Operations

Copy, move, rename, delete or zip files as a step in the flow — move the
CSVs you just loaded into an archive folder, zip last month's exports, clear
out a scratch folder before a run.

**Source** is a file, a folder, or a pattern (`inbox/*.csv`). Wire a path
into **source** instead — a File control, Write Excel's path, or List Files'
`paths` list or `files` table — and every one is handled.

* **copy** / **move** — into **Destination**. With one source and a
  destination that isn't an existing folder, it is the new file's full
  path; otherwise the destination is a folder (made if missing) and each
  source keeps its name inside it.
* **rename** — one source, given the name in **Destination**, in the same
  folder.
* **zip** — every source into the archive named by **Destination**
  (`archive/2026-09.zip`); a folder goes in with everything under it.
* **delete** — removes the files. A folder is only removed when **Delete
  folders** is ticked, since that takes everything inside it too. There is
  no recycle bin: deleted is gone.

**Overwrite** decides whether an existing destination is replaced or stops
the node. **Dry run** does nothing but log what it *would* do — use it to
check a pattern before letting a delete loose.

**paths** lists every result (for a delete, what was removed), **path** the
first, **count** how many and **bytes** their total size.
"""
NODE = {
    "label": "File Operations",
    "category": "Automation",
    "version": "1.0",
    "inputs": [("source", "any", {"optional": True,
                                  "suggest": ["flograph.io.list_files"]}),
               ("destination", "any", {"optional": True})],
    "outputs": [("path", "string"), ("paths", "object"),
                ("count", "number"), ("bytes", "number")],
}
PARAMS = [
    {"name": "operation", "type": "choice", "label": "Operation",
     "options": ["copy", "move", "rename", "zip", "delete"],
     "default": "copy"},
    {"name": "source", "type": "string", "label": "Source", "default": "",
     "placeholder": "file, folder or pattern — ignored while 'source' "
                    "is wired"},
    {"name": "destination", "type": "string", "label": "Destination",
     "default": "", "placeholder": "folder, new path, new name or .zip",
     "visible_when": {"operation": ["copy", "move", "rename", "zip"]}},
    {"name": "overwrite", "type": "bool", "label": "Overwrite",
     "default": False,
     "visible_when": {"operation": ["copy", "move", "rename", "zip"]}},
    {"name": "delete_folders", "type": "bool", "label": "Delete folders",
     "default": False, "visible_when": {"operation": ["delete"]}},
    {"name": "dry_run", "type": "bool", "label": "Dry run", "default": False},
]


def _sources(wired, typed):
    """Every source path, from a wired string / list / table or the typed
    path or pattern."""
    import glob

    import pandas as pd

    if wired is not None:
        if isinstance(wired, pd.DataFrame):
            if "path" not in wired.columns:
                raise ValueError("a table wired into 'source' needs a 'path' "
                                 "column (List Files' files output has one)")
            items = wired["path"].dropna().tolist()
        elif isinstance(wired, pd.Series):
            items = wired.dropna().tolist()
        elif isinstance(wired, (list, tuple, set)):
            items = list(wired)
        else:
            items = [wired]
        return [str(i) for i in items if str(i).strip()]
    typed = str(typed or "").strip()
    if not typed:
        raise ValueError("no source — set 'Source' or wire a path into it")
    if glob.has_magic(typed):
        return sorted(glob.glob(typed, recursive=True))
    return [typed]


def _size(path):
    import os

    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def run(ctx, source=None, destination=None):
    import os
    import shutil
    import zipfile

    p = ctx.params
    op = p["operation"]
    dry = bool(p["dry_run"])
    sources = _sources(source, p["source"])
    if not sources:
        ctx.log("nothing matched the source — nothing to do")
        return {"path": "", "paths": [], "count": 0, "bytes": 0}
    missing = [s for s in sources if not os.path.exists(s)]
    if missing:
        raise FileNotFoundError(f"source not found: {missing[0]}"
                                + (f" (and {len(missing) - 1} more)"
                                   if len(missing) > 1 else ""))

    dest = str(destination if destination is not None
               else p["destination"]).strip()
    if op != "delete" and not dest:
        raise ValueError(f"'{op}' needs a Destination")
    overwrite = bool(p["overwrite"])
    say = "would " if dry else ""
    results, total = [], 0

    def clear(target):
        if not os.path.exists(target):
            return
        if not overwrite:
            raise FileExistsError(f"{target} already exists — tick "
                                  "'Overwrite' to replace it")
        if not dry:
            if os.path.isdir(target) and not os.path.islink(target):
                shutil.rmtree(target)
            else:
                os.remove(target)

    if op == "delete":
        for s in sources:
            ctx.check_cancelled()
            if os.path.isdir(s) and not os.path.islink(s):
                if not p["delete_folders"]:
                    raise IsADirectoryError(
                        f"{s} is a folder — tick 'Delete folders' to remove "
                        "it and everything in it")
                total += _size(s)
                if not dry:
                    shutil.rmtree(s)
            else:
                total += os.path.getsize(s)
                if not dry:
                    os.remove(s)
            results.append(s)
            ctx.log(f"{say}delete {s}")

    elif op == "zip":
        if not dest.lower().endswith(".zip"):
            dest += ".zip"
        clear(dest)
        if not dry:
            os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
                for s in sources:
                    ctx.check_cancelled()
                    if os.path.isdir(s):
                        parent = os.path.dirname(os.path.abspath(s))
                        for root, _, files in os.walk(s):
                            for name in files:
                                full = os.path.join(root, name)
                                archive.write(full,
                                              os.path.relpath(full, parent))
                    else:
                        archive.write(s, os.path.basename(s))
        total = os.path.getsize(dest) if not dry else sum(map(_size, sources))
        results.append(dest)
        ctx.log(f"{say}zip {len(sources)} item(s) into {dest}")

    else:
        if op == "rename":
            if len(sources) != 1:
                raise ValueError(f"rename takes one source, got "
                                 f"{len(sources)} — use move for several")
            if os.sep in dest or (os.altsep and os.altsep in dest):
                raise ValueError("for rename, Destination is just the new "
                                 "name — use move to change folder")
            targets = [os.path.join(os.path.dirname(sources[0]), dest)]
        elif len(sources) == 1 and not os.path.isdir(dest) \
                and not dest.endswith(("/", "\\")):
            targets = [dest]
        else:
            if not dry:
                os.makedirs(dest, exist_ok=True)
            targets = [os.path.join(dest, os.path.basename(os.path.normpath(s)))
                       for s in sources]
        for s, t in zip(sources, targets):
            ctx.check_cancelled()
            if os.path.abspath(s) == os.path.abspath(t):
                raise ValueError(f"{s} would {op} onto itself")
            size = _size(s)
            clear(t)
            if not dry:
                parent = os.path.dirname(os.path.abspath(t))
                os.makedirs(parent, exist_ok=True)
                if op == "copy":
                    if os.path.isdir(s):
                        shutil.copytree(s, t)
                    else:
                        shutil.copy2(s, t)
                else:
                    shutil.move(s, t)
            total += size
            results.append(t)
            ctx.log(f"{say}{op} {s} -> {t}")

    ctx.log(f"{'dry run: ' if dry else ''}{op} {len(results)} item(s), "
            f"{total:,} bytes")
    return {"path": results[0] if results else "", "paths": results,
            "count": len(results), "bytes": total}
