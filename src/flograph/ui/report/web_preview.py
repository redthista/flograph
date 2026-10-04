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

import html as html_text
import re
import tempfile
import uuid
from urllib.parse import quote, unquote
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

#: Where the preview's page finds Plotly: a copy written beside it once,
#: rather than 4 MB of script inlined into a page rewritten on every
#: keystroke. A file you keep inlines it instead (see live.make_live).
PREVIEW_PLOTLY = "flograph-plotly.js"


def is_app_link(href) -> bool:
    """A link only the app can follow: a `page:` link to another page of
    the project, or an Action Button (core.report.BUTTON_SCHEME). Chromium
    has nowhere to go with either, so the preview hands them over."""
    from flograph.core.page_nav import is_page_link
    from flograph.core.report import button_target
    return is_page_link(href) or bool(button_target(href))


#: Where an app link points while it is in the preview. Chromium never asks
#: the page about a scheme it does not know — `page:` and `flograph-button:`
#: go straight to its unknown-scheme policy, which drops a scripted click
#: and hands a real one to the desktop — so each is dressed as an https
#: address the page *is* asked about, carrying the link it stands for. The
#: `.invalid` domain can never resolve, so one that slipped through goes
#: nowhere. Only the preview does this: a saved file has no app links.
APP_LINK = "https://flograph-app-link.invalid/?href="
_APP_HREF_RE = re.compile(r'href="((?:page|flograph-button):[^"]*)"',
                          re.IGNORECASE)


def routed(html: str) -> str:
    """`html` with every app link pointed at APP_LINK."""
    return _APP_HREF_RE.sub(
        lambda m: 'href="%s%s"' % (
            APP_LINK, quote(html_text.unescape(m.group(1)), safe="")),
        html)


def app_link_of(url: str) -> str:
    """The app link an APP_LINK address stands for, or ""."""
    if not url.startswith(APP_LINK):
        return ""
    href = unquote(url[len(APP_LINK):])
    return href if is_app_link(href) else ""


def _link_page(profile, parent, on_link):
    """The browser's page, with app links taken off it before Chromium
    navigates to them. Built here rather than at import: WebEngine may not
    be installed."""
    from PySide6.QtWebEngineCore import QWebEnginePage

    class _Page(QWebEnginePage):
        def acceptNavigationRequest(self, url, kind, is_main_frame):
            href = app_link_of(url.toString())
            if href:
                on_link(href)
                return False
            return super().acceptNavigationRequest(url, kind, is_main_frame)

    return _Page(profile, parent)


class WebPreview(QWidget):
    """A continuously scrolling report preview backed by QWebEngineView."""

    #: a `page:` link or a button was clicked: its href, as written
    link_activated = Signal(str)

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
            self.browser.setPage(_link_page(
                self.browser.page().profile(), self.browser,
                self.link_activated.emit))
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
            from .live import plotly_js
            (Path(self._folder.name) / PREVIEW_PLOTLY).write_text(
                plotly_js(), encoding="utf-8")
        self._path.write_text(routed(html), encoding="utf-8")
        position = self.browser.page().scrollPosition()
        if self._scroll is None and (position.x() or position.y()):
            self._scroll = (position.x(), position.y())
        url = QUrl.fromLocalFile(str(self._path))
        # the same file again is a reload of the rewritten file — compared
        # without the #…, which the page keeps up to date with the open tab
        # and sections (web_layout.py); a reload keeps it, so the preview
        # stays on the tab being looked at as it re-renders
        shown = QUrl(self.browser.url())
        shown.setFragment(None)
        if shown == url:
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
