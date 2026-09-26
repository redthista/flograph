"""The window's half of the Save Report node (see engine.report_export).

A worker asks; this renders on the GUI thread and answers. The render is the
same one the page's Save HTML… and Export PDF… buttons do — `render_report`
at print resolution, then `report_html` or `export_pdf` — so the file a run
writes is the file a click would have.

Requests are served one at a time. `render_report` re-enters the event loop
(a web chart is printed to a picture, and that waits), so a second request
arriving mid-render would otherwise start a render inside the first one.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from flograph.engine import report_export
from flograph.engine.report_export import ExportRequest, ReportExportError


def stale_embeds(graph, body: str) -> list[str]:
    """Embeds whose cached output is not what the flow makes now — a node
    that failed keeps its last good result, and one that was skipped
    because something above it failed keeps an older one. The render draws
    either without complaint, so they are named here."""
    from flograph.core.node import NodeStatus
    from flograph.core.reportlinks import embedded_nodes

    problems = []
    for node_id in embedded_nodes(graph, body):
        node = graph.nodes[node_id]
        if node.status == NodeStatus.ERROR:
            problems.append(f"“{node.label}” failed")
        elif node.dirty:
            problems.append(f"“{node.label}” is out of date")
    return problems


class ReportNodeExporter(QObject):
    # Emitted on the worker thread; this object lives on the GUI thread, so
    # the connection to a bound method below is queued onto it.
    asked = Signal(object)

    def __init__(self, engine, parent=None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._queue: deque = deque()
        self._busy = False
        self.asked.connect(self._on_asked)
        report_export.register(self.offer)

    def close(self) -> None:
        report_export.unregister(self.offer)
        # anything still waiting would otherwise wait for a window that is
        # going away — until Stop, which a closing app may never press
        while self._queue:
            request = self._queue.popleft()
            request.error = "the window closed before the report was saved"
            request.done()

    # ------------------------------------------------ worker thread

    def offer(self, request: ExportRequest) -> bool:
        """Serve this request if the node is in this window's graph."""
        try:
            if request.node_id not in self._engine.graph.nodes:
                return False
            self.asked.emit(request)
        except RuntimeError:      # the window's C++ side is already gone
            return False
        return True

    # --------------------------------------------------- GUI thread

    def _on_asked(self, request: ExportRequest) -> None:
        self._queue.append(request)
        if self._busy:
            return
        self._busy = True
        try:
            while self._queue:
                self._serve(self._queue.popleft())
        finally:
            self._busy = False

    def _serve(self, request: ExportRequest) -> None:
        try:
            if not request.abandoned:
                self._save(request)
        except ReportExportError as exc:
            request.error = str(exc)
        except OSError as exc:
            request.error = f"could not write {request.path}: {exc}"
        except Exception as exc:  # noqa: BLE001 — the node reports it
            request.error = f"{type(exc).__name__}: {exc}"
        finally:
            request.done()

    def _save(self, request: ExportRequest) -> None:
        from .export import export_pdf
        from .html import report_html
        from .render import render_report

        graph = self._engine.graph
        page = graph.pages.get(request.page_id)
        if page is None or page.kind != "report":
            raise ReportExportError("choose the report page to save")
        report_export.prepare_path(request, page.title)
        rendered = render_report(page.body, graph, self._engine.cache,
                                 image_scale=2.0, setup=page.setup,
                                 page_break_rule=False)
        request.problems = [*stale_embeds(graph, page.body),
                            *rendered.problems]
        if request.abandoned:
            return
        if request.problems and not request.save_anyway:
            raise ReportExportError(report_export.refusal(request.problems))
        html = ""
        if request.fmt == "HTML" or request.want_html:
            html = report_html(rendered, page.title, setup=page.setup,
                               custom_css=page.custom_css)
        if request.path:
            if request.fmt == "PDF":
                export_pdf(rendered.document, request.path, title=page.title,
                           setup=page.setup)
            else:
                Path(request.path).write_text(html, encoding="utf-8")
        request.html = html if request.want_html else ""
