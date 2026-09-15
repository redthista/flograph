"""Browser-native preview for a report page.

The paged preview intentionally uses QTextDocument so it can match PDF. This
widget is the other target: it displays the exported report HTML in Chromium,
so browser CSS and scrolling behave as they will outside flograph.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
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

    def _ensure_browser(self) -> bool:
        if self.browser is not None:
            return True
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            self.browser = QWebEngineView(self)
        except Exception:
            self._message.setText(
                "Web preview needs the PySide6 WebEngine component.\n"
                "Use Pages preview or install the full PySide6 package.")
            return False
        self._message.hide()
        self._layout.addWidget(self.browser)
        return True

    def set_html(self, html: str) -> None:
        """Display a complete, self-contained report document."""
        if self._ensure_browser():
            self.browser.setHtml(html)

    def clear(self) -> None:
        if self.browser is not None:
            self.browser.setHtml("")
