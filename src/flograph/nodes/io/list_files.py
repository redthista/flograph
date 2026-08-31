"""List Files

Turn a folder into a table — one row per file, with its path, name,
extension, size, and modified time. The front of a batch: list `inbox/*.csv`,
filter to the ones newer than the last run, and feed each path into a read +
load pipeline.

**Pattern** is a glob relative to **Folder** (`**/*.parquet` with **Recurse**
on walks subfolders). **Modified after** keeps only files changed since an
ISO date/time — the poor-man's "new since". **Sort** and **Newest first**
order the result; wire the `paths` output (a list) into a Loop node.

Recursive scans probe the first few folders: a fast local disk is walked on
one thread (thread hand-off would only cost more), a slow one — a network
mount, a cold cache — fans the remaining subtree out across a thread pool so
directories are read in parallel instead of one blocking `stat` at a time.
**Workers** forces the pool size; 0 auto-picks per the probe.
"""
import os

NODE = {
    "label": "List Files",
    "category": "IO",
    "version": "1.1",
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
    {"name": "workers", "type": "int", "label": "Workers (0 = auto)",
     "default": 0, "min": 0, "max": 128},
]


def _scan_dir(path, matcher, keep, out, subdirs):
    """Scan one directory: append matching (path, name, stat) to *out*,
    append child directories to *subdirs*. Never raises."""
    try:
        it = os.scandir(path)
    except OSError:
        return
    with it:
        for entry in it:
            try:
                if entry.is_dir(follow_symlinks=False):
                    subdirs.append(entry.path)
                    continue
                if not matcher(entry.name):
                    continue
                if not entry.is_file():  # follows symlinks, like os.path.isfile
                    continue
                st = entry.stat()
            except OSError:
                continue
            if keep(st):
                out.append((entry.path, entry.name, st))


def _drain_parallel(pending, rows, matcher, keep, workers):
    """Walk every directory in *pending* (and their subtrees) across a thread
    pool, extending *rows* in place. Returns *rows*."""
    import queue
    import threading

    dirq = queue.Queue()
    for d in pending:
        dirq.put(d)
    lock = threading.Lock()

    def worker():
        while True:
            path = dirq.get()
            try:
                if path is None:
                    return
                local, subdirs = [], []
                _scan_dir(path, matcher, keep, local, subdirs)
                if local:
                    with lock:
                        rows.extend(local)
                for sub in subdirs:
                    dirq.put(sub)
            finally:
                dirq.task_done()

    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(workers)]
    for t in threads:
        t.start()
    dirq.join()
    for _ in threads:
        dirq.put(None)
    for t in threads:
        t.join()
    return rows


# Above this per-directory scan cost (seconds) the filesystem is latency-bound
# and a thread pool pays off; below it, one thread is fastest.
_SLOW_DIR_SECONDS = 5e-4


def _walk(root, matcher, keep, workers):
    """Recursively collect (path, name, stat) tuples under *root*. Probes the
    first handful of directories, then stays single-threaded on a fast disk or
    fans the rest out across *workers* threads on a slow one (workers<=0 =
    auto)."""
    import time

    rows = []
    pending = [root]
    probe_time = 0.0
    probe_n = 0
    while pending and probe_n < 8:
        d = pending.pop()
        subdirs = []
        t0 = time.perf_counter()
        _scan_dir(d, matcher, keep, rows, subdirs)
        probe_time += time.perf_counter() - t0
        probe_n += 1
        pending.extend(subdirs)

    if not pending:
        return rows

    if workers <= 0:
        slow = probe_time / probe_n > _SLOW_DIR_SECONDS
        workers = min(32, (os.cpu_count() or 4) * 4) if slow else 1

    if workers <= 1:
        while pending:
            subdirs = []
            _scan_dir(pending.pop(), matcher, keep, rows, subdirs)
            pending.extend(subdirs)
        return rows

    return _drain_parallel(pending, rows, matcher, keep, workers)


def run(ctx, folder=None):
    import datetime as dt
    import fnmatch
    import re

    import pandas as pd

    p = ctx.params
    root = (folder if isinstance(folder, str) and folder
            else p.get("folder") or "").strip()
    if not root:
        raise ValueError("no folder — set 'Folder'")
    if not os.path.isdir(root):
        raise ValueError(f"not a folder: {root}")

    pattern = p.get("pattern") or "*"
    # fnmatch.fnmatch recompiles + case-folds on every call; do it once.
    _rx = re.compile(fnmatch.translate(os.path.normcase(pattern))).match

    def matcher(name):
        return _rx(os.path.normcase(name)) is not None

    after = None
    raw_after = (p.get("modified_after") or "").strip()
    if raw_after:
        try:
            after = dt.datetime.fromisoformat(raw_after).timestamp()
        except ValueError:
            raise ValueError(f"'Modified after' is not an ISO date/time: "
                             f"{raw_after!r}")
    min_bytes = int(p.get("min_bytes", 0))

    def keep(st):
        if st.st_size < min_bytes:
            return False
        if after is not None and st.st_mtime < after:
            return False
        return True

    if bool(p.get("recurse")):
        found = _walk(root, matcher, keep, int(p.get("workers") or 0))
    else:
        found = []
        _scan_dir(root, matcher, keep, found, [])

    rows = [{
        "path": full,
        "name": name,
        "ext": os.path.splitext(name)[1].lstrip("."),
        "size_bytes": st.st_size,
        "modified": dt.datetime.fromtimestamp(
            st.st_mtime).isoformat(timespec="seconds"),
    } for full, name, st in found]

    key = {"modified": "modified", "name": "name", "size": "size_bytes"}[p["sort"]]
    rev = bool(p.get("newest_first", True))
    rows.sort(key=lambda r: r[key], reverse=rev)

    files = pd.DataFrame(
        rows, columns=["path", "name", "ext", "size_bytes", "modified"])
    ctx.log(f"{len(files)} file(s) under {root} matching {pattern!r}")
    return {"files": files, "paths": [r["path"] for r in rows],
            "count": int(len(files))}
