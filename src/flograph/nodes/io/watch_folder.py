"""Watch Folder

Hand on the files that have turned up in a folder since this node last ran —
the inbound drop, the nightly exports — so the flow below works through each
new file once instead of the whole folder every time.

Every run looks at the folder again, even when nothing in the flow changed
(the folder is outside the flow, so only looking can tell). **Mode** picks
whether a file that was already there but has since been rewritten counts
too. **Already there on the first run** decides what happens the very first
time: hand over the backlog, or only what arrives from now on.

**Wait for a new file** keeps the run here, looking every **Look every**
seconds, until something new turns up or **Wait up to** runs out (then the
outputs are empty, not an error). A file still being written is left alone
until it has not changed for **Settled for** seconds, and picked up on a
later look.

What this node has seen is kept in a small file in flograph's own user
folder, one per Watch Folder node, or in **Seen list** if you name one —
point a scheduled `flograph run` and the app at the same list and they agree.
Untick **Remember what was seen** to look without using anything up. To
start over, delete the list (the log says where it is).

Outputs: `files` (path, name, ext, size_bytes, modified, change), `paths` (a
list, for a loop) and `count`.
"""
import os

NODE = {
    "label": "Watch Folder",
    "category": "IO",
    "version": "1.0",
    "always_run": True,
    "inputs": [("folder", "any", {"optional": True})],
    "outputs": [("files", "dataframe"), ("paths", "object"), ("count", "number")],
}
NEW = "New files"
NEW_OR_CHANGED = "New or changed files"
HAND_OVER = "Hand them over"
SKIP = "Skip them"
NO_WAIT = "Don't wait"
WAIT = "Wait for a new file"
PARAMS = [
    {"name": "folder", "type": "folder_open", "label": "Folder", "default": ""},
    {"name": "pattern", "type": "string", "label": "Pattern",
     "default": "*", "placeholder": "*.csv"},
    {"name": "include_subdirs", "type": "bool", "label": "Include subfolders",
     "default": False},
    {"name": "mode", "type": "choice", "label": "Mode",
     "options": [NEW, NEW_OR_CHANGED], "default": NEW},
    {"name": "first_run", "type": "choice",
     "label": "Already there on the first run",
     "options": [HAND_OVER, SKIP], "default": HAND_OVER},
    {"name": "wait", "type": "choice", "label": "When nothing is new",
     "options": [NO_WAIT, WAIT], "default": NO_WAIT},
    {"name": "poll_interval_s", "type": "float", "label": "Look every (s)",
     "default": 2.0, "min": 0.2, "max": 3600.0},
    {"name": "timeout_s", "type": "float", "label": "Wait up to (s)",
     "default": 300.0, "min": 1.0, "max": 86400.0},
    {"name": "settle_s", "type": "float", "label": "Settled for (s)",
     "default": 2.0, "min": 0.0, "max": 3600.0},
    {"name": "remember", "type": "bool", "label": "Remember what was seen",
     "default": True},
    {"name": "seen_file", "type": "file_save", "label": "Seen list",
     "default": "", "placeholder": "blank = flograph's own"},
]


def _listing(root, pattern, recurse):
    """{path: (size, mtime_ns)} for every matching file under root."""
    import fnmatch
    import re

    rx = re.compile(fnmatch.translate(os.path.normcase(pattern))).match
    found = {}
    pending = [root]
    while pending:
        try:
            it = os.scandir(pending.pop())
        except OSError:
            continue
        with it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if recurse:
                            pending.append(entry.path)
                        continue
                    if rx(os.path.normcase(entry.name)) is None:
                        continue
                    if not entry.is_file():
                        continue
                    st = entry.stat()
                except OSError:
                    continue
                found[entry.path] = (st.st_size, st.st_mtime_ns)
    return found


def _seen_path(ctx, p):
    named = (p.get("seen_file") or "").strip()
    if named:
        return named
    from flograph.paths import user_data_dir
    return str(user_data_dir() / "watch_folder" / f"{ctx.node_id}.json")


def _load(path):
    import json

    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise ValueError(f"can't read the seen list {path}: {exc} — "
                         f"delete it to start over") from exc
    return data.get("watches", {}) if isinstance(data, dict) else {}


def _save(path, watches):
    import json
    import tempfile

    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    # Written beside it and swapped in, so a run stopped mid-write (or a
    # second flow reading it) never meets half a list.
    fd, tmp = tempfile.mkstemp(prefix=".watch-", suffix=".json", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "watches": watches}, fh)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _settled(listing, settle_s, now_ns):
    """The files that have not been touched for settle_s seconds — the ones
    safe to read. The rest are probably still being written."""
    edge = now_ns - int(settle_s * 1e9)
    return {path: sig for path, sig in listing.items() if sig[1] <= edge}


def _changes(settled, before, mode):
    picked = {}
    for path, sig in settled.items():
        old = before.get(path)
        if old is None:
            picked[path] = "new"
        elif mode == NEW_OR_CHANGED and tuple(old) != tuple(sig):
            picked[path] = "changed"
    return picked


def run(ctx, folder=None):
    import datetime as dt
    import time

    import pandas as pd

    p = ctx.params
    root = (folder if isinstance(folder, str) and folder
            else p.get("folder") or "").strip()
    if not root:
        raise ValueError("no folder — set 'Folder'")
    if not os.path.isdir(root):
        raise ValueError(f"not a folder: {root}")
    pattern = p.get("pattern") or "*"
    recurse = bool(p.get("include_subdirs"))
    mode = p.get("mode") or NEW
    settle_s = float(p.get("settle_s") or 0.0)
    remember = bool(p.get("remember", True))

    seen_path = _seen_path(ctx, p)
    watches = _load(seen_path)
    # One list can serve several watches: each is keyed by what it watches,
    # so pointing the node at another folder starts that folder afresh.
    key = "|".join([os.path.abspath(root), pattern, "sub" if recurse else ""])
    first = key not in watches
    before = dict(watches.get(key, {}))

    settled = _settled(_listing(root, pattern, recurse), settle_s,
                       time.time_ns())
    if first and p.get("first_run") == SKIP:
        ctx.log(f"first look: {len(settled)} file(s) already in {root}, "
                f"counted as seen")
        before = dict(settled)
        picked = {}
    else:
        picked = _changes(settled, before, mode)

    if not picked and p.get("wait") == WAIT:
        interval = max(0.2, float(p.get("poll_interval_s") or 2.0))
        timeout = float(p.get("timeout_s") or 300.0)
        started = time.monotonic()
        ctx.log(f"waiting up to {timeout:g}s for a new file in {root}")
        while not picked:
            elapsed = time.monotonic() - started
            if elapsed >= timeout:
                ctx.log("nothing new turned up")
                break
            ctx.progress(elapsed / timeout)
            # sleep in short slices so Stop is answered promptly
            until = time.monotonic() + min(interval, timeout - elapsed)
            while time.monotonic() < until:
                ctx.check_cancelled()
                time.sleep(min(0.1, max(0.0, until - time.monotonic())))
            settled = _settled(_listing(root, pattern, recurse), settle_s,
                               time.time_ns())
            picked = _changes(settled, before, mode)

    if remember:
        # What is on disk now and settled becomes the baseline. A file that
        # was deleted drops out, so if it comes back it is new again; one
        # still being written stays out until a later look finds it settled.
        watches[key] = {path: list(sig) for path, sig in settled.items()}
        _save(seen_path, watches)

    rows = []
    for path in sorted(picked, key=lambda q: (settled[q][1], q)):
        size, mtime_ns = settled[path]
        name = os.path.basename(path)
        rows.append({
            "path": path,
            "name": name,
            "ext": os.path.splitext(name)[1].lstrip("."),
            "size_bytes": size,
            "modified": dt.datetime.fromtimestamp(
                mtime_ns / 1e9).isoformat(timespec="seconds"),
            "change": picked[path],
        })
    files = pd.DataFrame(rows, columns=["path", "name", "ext", "size_bytes",
                                        "modified", "change"])
    ctx.log(f"{len(files)} new file(s) in {root} matching {pattern!r}"
            + ("" if remember else " (not remembered)")
            + f"; seen list: {seen_path}")
    return {"files": files, "paths": [r["path"] for r in rows],
            "count": int(len(files))}
