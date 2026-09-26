"""Saving a report page from inside a run — the Save Report node's way to
the window.

A report is rendered by the window, not by a node: it needs the whole graph
(embeds are found by label), the output cache, a QTextDocument, and for web
charts Chromium printing to PDF — all GUI-thread things a node's `ctx`
deliberately does not reach. So the node asks here, and a window that has
registered an exporter does the render on its own thread and hands back the
path and the HTML while the node's worker waits.

Ordering is not this module's problem: the node depends on everything its
page embeds through derived report edges (core.reportlinks), so by the time
it runs they are all in the cache.

Qt-free on purpose. With no window — a headless run — nothing is registered,
and the node fails saying so instead of hanging.

The file-name half (`{page}`/`{date}`/`{time}` and what to do when the file
exists) is pure. The window calls `prepare_path` before it renders — it is
the side that knows the page's title — so a "Fail" never pays for a render.
"""
from __future__ import annotations

import os
import re
import threading
import weakref
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

FORMATS = {"HTML": ".html", "PDF": ".pdf"}
IF_EXISTS = ("Overwrite", "Add a number", "Fail")

TOKENS = {
    "page": "the report page's title",
    "date": "today, as 2026-09-24",
    "time": "the time, as 14-05-09",
    "datetime": "both, as 2026-09-24 14-05-09",
}
_TOKEN_RE = re.compile(r"\{([A-Za-z_]*)\}")
# Characters no file name may hold on Windows — a page title is free text.
_UNSAFE_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

#: How often a waiting worker looks up to see whether Stop was pressed.
_POLL_SECONDS = 0.1


class ReportExportError(Exception):
    """The report could not be saved. The message is for the user."""


def refusal(problems: list) -> str:
    """Why a report with problems in it was not saved, for the node."""
    unique = list(dict.fromkeys(problems))
    more = f" (+{len(unique) - 1} more)" if len(unique) > 1 else ""
    return (f"not saved — the report has errors: {unique[0]}{more}. Set "
            f"'If the report has errors' to Save anyway to save it with "
            f"the gaps marked")


# ------------------------------------------------------------- file names

def safe_name(text: str) -> str:
    cleaned = _UNSAFE_RE.sub("-", str(text or "")).strip(" .")
    return cleaned or "Report"


def expand_name(template: str, page_title: str,
                now: Optional[datetime] = None) -> str:
    """The path with every `{token}` filled in. An unknown token raises,
    rather than leaving `{dte}` in a file name to be found next month."""
    now = now or datetime.now()
    values = {
        "page": safe_name(page_title),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H-%M-%S"),
        "datetime": now.strftime("%Y-%m-%d %H-%M-%S"),
    }

    def fill(match: re.Match) -> str:
        name = match.group(1).lower()
        if name not in values:
            known = ", ".join("{" + t + "}" for t in TOKENS)
            raise ReportExportError(
                f"{match.group(0)} is not something a file name can hold "
                f"— use {known}")
        return values[name]

    return _TOKEN_RE.sub(fill, str(template or ""))


def target_path(template: str, fmt: str, page_title: str, if_exists: str,
                now: Optional[datetime] = None) -> str:
    """Where this save writes: tokens filled, the format's extension added
    when the name has none, and the if-exists rule applied."""
    path = expand_name(template, page_title, now).strip()
    if not path:
        raise ReportExportError(
            "no file set — choose where to save in the node's properties")
    path = os.path.expanduser(path)
    extension = FORMATS.get(fmt, ".html")
    root, ext = os.path.splitext(path)
    if not ext:
        path = root + extension
    if not os.path.exists(path) or if_exists == "Overwrite":
        return path
    if if_exists == "Fail":
        raise ReportExportError(
            f"{path} already exists — set 'If the file exists' to Overwrite "
            f"or Add a number, or put {{date}} or {{time}} in the name")
    root, ext = os.path.splitext(path)
    number = 2
    while os.path.exists(f"{root} ({number}){ext}"):
        number += 1
    return f"{root} ({number}){ext}"


# ---------------------------------------------------------- the hand-off

@dataclass
class ExportRequest:
    """One save, as the worker asks for it. The window calls
    `prepare_path`, renders, fills `html`/`problems` (or `error`) and calls
    `done()`."""
    node_id: str
    page_id: str
    fmt: str
    template: str             # "Save to" as typed, tokens and all
    if_exists: str
    create_dirs: bool
    want_html: bool
    save_anyway: bool = False  # write it even with problems in it
    now: datetime = field(default_factory=datetime.now)
    path: str = ""            # set by prepare_path; "" = write nothing
    html: str = ""
    problems: list = field(default_factory=list)
    error: Optional[str] = None
    abandoned: bool = False   # Stop was pressed while the window worked
    _done: threading.Event = field(default_factory=threading.Event,
                                   repr=False)

    def done(self) -> None:
        self._done.set()


def prepare_path(request: ExportRequest, page_title: str) -> None:
    """Settle where the request writes, making folders if asked. An empty
    "Save to" is allowed only when the HTML is wanted on the output — then
    nothing is written. Raises ReportExportError."""
    if not str(request.template or "").strip() and request.want_html:
        request.path = ""
        return
    request.path = target_path(request.template, request.fmt, page_title,
                               request.if_exists, request.now)
    if request.create_dirs:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(request.path)),
                        exist_ok=True)
        except OSError as exc:
            raise ReportExportError(str(exc)) from None


#: Each takes a request and returns True if it will serve it — it must then
#: call `request.done()`, from whatever thread, when it has. A window only
#: serves the nodes of its own graph, which is what keeps two windows (and
#: a test that builds several) from saving each other's reports. Held
#: weakly when it is a bound method, so a window nobody closed properly does
#: not live on in here.
_exporters: list = []
_lock = threading.Lock()


def _ref(exporter):
    if hasattr(exporter, "__self__"):
        return weakref.WeakMethod(exporter)
    return lambda: exporter


def _live() -> list[Callable[[ExportRequest], bool]]:
    with _lock:
        _exporters[:] = [ref for ref in _exporters if ref() is not None]
        return [ref() for ref in _exporters]


def register(exporter: Callable[[ExportRequest], bool]) -> None:
    with _lock:
        _exporters.append(_ref(exporter))


def unregister(exporter: Callable[[ExportRequest], bool]) -> None:
    with _lock:
        _exporters[:] = [ref for ref in _exporters
                         if ref() is not None and ref() != exporter]


def export(ctx, page_id: str, fmt: str, template: str, if_exists: str,
           create_dirs: bool, want_html: bool,
           save_anyway: bool = False) -> ExportRequest:
    """Ask a window to render and save, and wait for it. Called on the
    node's worker thread; Stop still works while it waits."""
    request = ExportRequest(node_id=ctx.node_id, page_id=page_id, fmt=fmt,
                            template=str(template or ""),
                            if_exists=if_exists, create_dirs=create_dirs,
                            want_html=want_html, save_anyway=save_anyway)
    if not any(exporter(request) for exporter in _live()):
        raise ReportExportError(
            "saving a report needs the flograph window — reports are drawn "
            "by it, so a headless run cannot save one")
    try:
        while not request._done.wait(_POLL_SECONDS):
            ctx.check_cancelled()
    except BaseException:
        request.abandoned = True
        raise
    if request.error:
        raise ReportExportError(request.error)
    return request
