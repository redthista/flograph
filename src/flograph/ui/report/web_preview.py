"""Browser-native preview for a report page.

The paged preview intentionally uses QTextDocument so it can match PDF. This
widget is the other target: it displays the exported report HTML in Chromium,
so browser CSS and scrolling behave as they will outside flograph.

The document is loaded from a temp file, never `setHtml`: that hands the
page over as a data: URL, which Chromium refuses past 2 MB — and a report
with a few hundred formatted table rows is past it, since Qt writes a long
inline style onto every cell. Refused, the preview stayed blank or kept
showing whatever it last managed to load.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class WebPreview(QWidget):
    """A continuously scrolling report preview backed by QWebEngineView."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("report_web_preview")
        self.browser = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._layout = layout
        self._message = QLabel(
            "Select Web to load the browser preview.\n"
            "It displays the same HTML used by web export.")
        self._message.setAlignment(Qt.AlignCenter)
        self._message.setWordWrap(True)
        layout.addWidget(self._message)
        # the file the page is loaded from (see the module docstring); the
        # folder goes when the preview does
        self._folder = None
        self._path = None
        # where the reader had scrolled to, put back once the new copy has
        # loaded — the preview re-renders as you type
        self._scroll = None

    def _ensure_browser(self) -> bool:
        if self.browser is not None:
            return True
        try:
            from ..webprofile import new_view
            self.browser = new_view(self)
        except Exception:
            self._message.setText(
                "Web preview needs the PySide6 WebEngine component.\n"
                "Use Pages preview or install the full PySide6 package.")
            return False
        # A file:// page may not fetch from the web unless told it can; the
        # data: URL setHtml used could, so a custom CSS @import (a web font)
        # would otherwise have stopped working here.
        from PySide6.QtWebEngineCore import QWebEngineSettings
        self.browser.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            True)
        self.browser.loadFinished.connect(self._on_loaded)
        self._message.hide()
        self._layout.addWidget(self.browser)
        return True

    def set_html(self, html: str) -> None:
        """Display a complete, self-contained report document."""
        if not self._ensure_browser():
            return
        if self._folder is None:
            self._folder = tempfile.TemporaryDirectory(
                prefix="flograph-report-")
            self._path = Path(self._folder.name) / f"{uuid.uuid4().hex}.html"
        self._path.write_text(html, encoding="utf-8")
        position = self.browser.page().scrollPosition()
        if self._scroll is None and (position.x() or position.y()):
            self._scroll = (position.x(), position.y())
        url = QUrl.fromLocalFile(str(self._path))
        # the same URL again is a reload of the rewritten file
        if self.browser.url() == url:
            self.browser.reload()
        else:
            self.browser.load(url)

    def _on_loaded(self, ok: bool) -> None:
        if not ok or self._scroll is None:
            return
        x, y = self._scroll
        self._scroll = None
        self.browser.page().runJavaScript(f"window.scrollTo({x}, {y});")

    def clear(self) -> None:
        if self.browser is not None:
            self.browser.setHtml("")
