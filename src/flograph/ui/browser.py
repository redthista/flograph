"""Handing a webview node's output to the user's real browser.

The embedded card is a genuine Chromium view, so this is not about
capability — it is about *room*, and about everything a browser gives you
that a card on a canvas can't: a full screen, zoom, find-in-page, print,
devtools, and a URL you can keep open beside the app while you carry on
editing the graph.

The HTML is exactly what the card renders (flograph.core.html.to_html, the
one coercion both paths call), written to a file under a session temp
directory. A file rather than a data: URL because a self-contained Plotly
page carries ~3 MB of plotly.js, and because a file has a path the user can
keep, mail, or reload. The path is stable per node, so after a re-run the
browser tab the user already has open shows the new output on a refresh
instead of leaving them with an orphaned tab per run.
"""
from __future__ import annotations

import re
from typing import Optional

_tmp = None  # TemporaryDirectory holding the pages, cleaned up at exit

#: node id -> the page written for it, for every node opened this session.
#: What makes a browser tab keep up with the graph: the file is rewritten
#: whenever the node runs again, so the tab the user already has open is
#: never showing an older chart than the canvas is.
_open_pages: "dict[str, str]" = {}


def _tmp_dir():
    import tempfile
    from pathlib import Path
    global _tmp
    if _tmp is None:
        _tmp = tempfile.TemporaryDirectory(prefix="flograph-browser-")
    return Path(_tmp.name)


def slug(text: str) -> str:
    """A node label as a filename stem. The browser shows it in the tab and
    in Save As, so it is worth keeping readable rather than hashing it."""
    cleaned = re.sub(r"[^\w\- ]+", "", text or "").strip()
    cleaned = re.sub(r"[\s_]+", "-", cleaned)
    return cleaned[:60] or "view"


def html_for(node, entry) -> Optional[str]:
    """The page a webview node's card is showing, or None if there is
    nothing to show — not run yet, or its output doesn't coerce to HTML.

    Reads the node's *first declared output port*, the same rule the card
    itself uses: a webview node is free to name its port whatever suits it.
    """
    from flograph.core.chart_grid import grid_settings
    from flograph.core.html import titled, to_html

    if node is None or entry is None:
        return None
    port = node.spec.outputs[0].name if node.spec.outputs else "figure"
    html = to_html(entry.outputs.get(port), *grid_settings(node.params))
    return None if html is None else titled(html, node.label)


def can_open(node, entry) -> bool:
    """Whether Open in Browser would have anything to open. Cheap enough to
    call while building a context menu — the coercion is string work over an
    object already in the cache."""
    if entry is not None and not entry.resident:
        # Cached but not loaded. Reading the blob back to answer a context
        # menu would be the one thing a lazily-opened project must not do, so
        # answer from the port list and let the open itself load it. Worst
        # case the menu offers something that turns out not to coerce.
        port = node.spec.outputs[0].name if node.spec.outputs else "figure"
        return port in entry.ports()
    return html_for(node, entry) is not None


def open_html(html: str, name: str, token: str = "") -> str:
    """Write `html` where a browser can read it and ask the desktop to open
    it. Returns the path written.

    The return value is the path, not whether the browser appeared: handing
    a URL to the desktop is the last point at which anything is knowable —
    what it launches, and when, is out of our hands.
    """
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    stem = slug(name)
    path = _tmp_dir() / f"{stem}-{token}.html" if token else _tmp_dir() / f"{stem}.html"
    path.write_text(html, encoding="utf-8")
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    return str(path)


def open_node(node, entry) -> Optional[str]:
    """Open one webview node's current output in the browser. Returns the
    path written, or None when the node has nothing to show."""
    html = html_for(node, entry)
    if html is None:
        return None
    path = open_html(html, node.label, token=node.id[:8])
    _open_pages[node.id] = path
    return path


def refresh_node(node, entry) -> Optional[str]:
    """Rewrite the page of a node the user has already opened, so the tab
    they left open shows this run's output on a refresh.

    Called on every successful run, and deliberately *silent*: nothing is
    handed to the desktop, so a re-run never steals focus or spawns a second
    tab. Confined to nodes actually opened this session — the file is only
    interesting to someone looking at it, and a webview page can carry
    several megabytes of plotly.js.

    A run that produces nothing renderable leaves the old page alone rather
    than blanking it: the tab would otherwise go empty with no way to tell
    whether the node broke or the feature did.
    """
    path = _open_pages.get(node.id)
    if path is None:
        return None
    html = html_for(node, entry)
    if html is None:
        return None
    from pathlib import Path
    Path(path).write_text(html, encoding="utf-8")
    return path


def remember(node_id: str, path: str) -> None:
    """Record a page opened by something that built its own HTML.

    `open_node` does this for webview nodes, whose HTML comes from the
    cache. A report card's does not — it is rendered from the card's text
    and its wired inputs — so it hands the path back here instead, and
    then gets the same "the tab keeps up" behaviour as everything else.
    """
    _open_pages[node_id] = path


def rewrite(node_id: str, html: str) -> "str | None":
    """Rewrite an already-opened page in place, silently.

    Silent is the point: nothing is handed to the desktop, so a re-render
    never steals focus or spawns a second tab — the tab the user already
    has open just shows the new version when they refresh it.
    """
    path = _open_pages.get(node_id)
    if path is None or not html:
        return None
    from pathlib import Path
    try:
        Path(path).write_text(html, encoding="utf-8")
    except OSError:
        # The temp dir went away, or the disk did. A stale tab is not worth
        # interrupting an edit for.
        return None
    return path


def is_open(node_id: str) -> bool:
    """Whether this node has a page a browser may still be showing."""
    return node_id in _open_pages


def forget(node_id: str) -> None:
    """Drop a node's page — it was deleted, or the project was closed."""
    _open_pages.pop(node_id, None)


def forget_all() -> None:
    _open_pages.clear()


def status_message(node, path: Optional[str]) -> str:
    """What to tell the user after asking the desktop to open a page.

    Worth saying at all because a cold browser can take several seconds to
    appear, and silence in the meantime reads as the click having missed.
    A dirty node is called out: the page is the last run's output, which is
    the same thing the card is showing but much easier to forget once it is
    in a window of its own, away from the STALE badge.
    """
    if path is None:
        return f"{node.label}: nothing to open — run the node first"
    stale = " (showing the last run — the node is dirty)" if node.dirty else ""
    return f"Opened {node.label} in your browser{stale} — {path}"


def open_node_from(widget, node, entry) -> Optional[str]:
    """Open `node` in the browser and report it on the window's status bar.

    Takes the widget rather than the window so the canvas and a dashboard
    page — which has no status bar of its own — share one implementation;
    a widget with no window to speak of (a test harness) just skips the
    message.
    """
    path = open_node(node, entry)
    window = widget.window() if widget is not None else None
    bar = getattr(window, "statusBar", None)
    if callable(bar):
        bar().showMessage(status_message(node, path), 8000)
    return path
