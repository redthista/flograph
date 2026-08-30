"""Wait for File

Block the flow until a file turns up — the nightly export, the FTP drop, the
report another job writes — then let the pipeline downstream run against it.

**Stable for** guards against reading a file mid-write: the node waits until
the size has not changed for that many seconds before calling it ready.
**Timeout** caps the wait; **On timeout** decides whether that stops the flow
(`fail`) or just comes out as `ready = false` for you to branch on.

Outputs the resolved `path`, its `size_bytes` and `modified` time, so the
next node (Read CSV, a Shell step) can pick it straight up. Supports a glob —
`inbox/vendor_*.csv` — and returns the newest match.
"""
NODE = {
    "label": "Wait for File",
    "category": "Automation",
    "version": "1.0",
    "inputs": [("path", "any", {"optional": True})],
    "outputs": [
        ("ready", "bool"),
        ("path", "string"),
        ("size_bytes", "number"),
        ("modified", "string"),
    ],
}
PARAMS = [
    {"name": "path", "type": "string", "label": "Path or glob",
     "default": "", "placeholder": "inbox/vendor_*.csv"},
    {"name": "timeout", "type": "float", "label": "Timeout (s)",
     "default": 300.0, "min": 1.0, "max": 86400.0},
    {"name": "poll", "type": "float", "label": "Poll every (s)",
     "default": 2.0, "min": 0.2, "max": 300.0},
    {"name": "stable_for", "type": "float", "label": "Stable for (s)",
     "default": 3.0, "min": 0.0, "max": 3600.0},
    {"name": "min_bytes", "type": "int", "label": "Minimum size (bytes)",
     "default": 1, "min": 0, "max": 1_000_000_000},
    {"name": "on_timeout", "type": "choice", "label": "On timeout",
     "options": ["fail", "return not-ready"], "default": "fail"},
]


def _newest_match(pattern):
    import glob
    import os

    hits = [h for h in glob.glob(pattern) if os.path.isfile(h)]
    if not hits:
        return None
    return max(hits, key=os.path.getmtime)


def run(ctx, path=None):
    import datetime as dt
    import os
    import time

    p = ctx.params
    pattern = (path if isinstance(path, str) and path else p.get("path") or "").strip()
    if not pattern:
        raise ValueError("no path — set 'Path or glob'")

    timeout = float(p.get("timeout", 300.0))
    poll = float(p.get("poll", 2.0))
    stable_for = float(p.get("stable_for", 3.0))
    min_bytes = int(p.get("min_bytes", 1))
    deadline = time.monotonic() + timeout

    last_size = -1
    stable_since = None
    while True:
        ctx.check_cancelled()
        found = _newest_match(pattern) if any(c in pattern for c in "*?[") \
            else (pattern if os.path.isfile(pattern) else None)

        if found:
            size = os.path.getsize(found)
            if size >= min_bytes:
                if size == last_size:
                    if stable_since is None:
                        stable_since = time.monotonic()
                    if time.monotonic() - stable_since >= stable_for:
                        mtime = dt.datetime.fromtimestamp(
                            os.path.getmtime(found)).isoformat(timespec="seconds")
                        ctx.log(f"ready: {found} ({size} bytes)")
                        return {"ready": True, "path": found,
                                "size_bytes": int(size), "modified": mtime}
                else:
                    last_size, stable_since = size, None

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if p.get("on_timeout", "fail") == "fail":
                raise ValueError(
                    f"timed out after {timeout:g}s waiting for {pattern!r}")
            ctx.log(f"timed out waiting for {pattern!r}")
            return {"ready": False, "path": "", "size_bytes": 0, "modified": ""}
        ctx.progress(1.0 - remaining / timeout)
        time.sleep(min(poll, remaining))
