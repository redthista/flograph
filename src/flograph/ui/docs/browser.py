"""The reading pane of the documentation window.

A `QTextBrowser` — the same Markdown engine the report preview and the
sticky-note cards use — pointed at the bundled `flograph/docs/*.md` pages.
`[[wikilinks]]` are turned into ordinary links by `core.docpages` before the
text reaches Qt; clicking one loads that page here. External `http(s)` links
open in the real browser, as the web-view "Open in Browser" action does.
"""
from __future__ import annotations

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QTextBrowser

from flograph.core.docpages import catalog, render_links

from .. import theme

HOME_SLUG = "home"

# Qt rich text supports only a small CSS subset (same note as report/render.py).
_DOCS_CSS = f"""
body {{ color: {theme.NODE_TEXT.name()}; }}
h1 {{ font-size: 20px; color: {theme.NODE_TEXT.name()}; }}
h2 {{ font-size: 16px; color: {theme.NODE_TEXT.name()};
      border-bottom: 1px solid {theme.NODE_BORDER.name()}; padding-bottom: 3px; }}
h3 {{ font-size: 13px; color: {theme.FRAME_TITLE.name()}; }}
a {{ color: {theme.BUTTON_ACCENT.name()}; }}
code, pre {{ background: {theme.NODE_HEADER.name()};
             color: {theme.NODE_TEXT.name()}; }}
pre {{ padding: 6px; }}
table {{ border: 1px solid {theme.NODE_BORDER.name()};
         border-collapse: collapse; }}
th, td {{ border: 1px solid {theme.NODE_BORDER.name()}; padding: 3px 8px; }}
blockquote {{ color: {theme.NODE_SUBTEXT.name()};
              border-left: 2px solid {theme.NODE_BORDER.name()};
              padding-left: 8px; }}
"""

_NOT_FOUND = "# Page not found\n\nThere is no documentation page called `{name}`."


class DocsBrowser(QTextBrowser):
    """Renders one page at a time and keeps its own back/forward history —
    QTextBrowser's built-in history is tied to `setSource`/`loadResource`,
    which a list of visited slugs sidesteps more legibly."""

    #: emitted after navigation so the toolbar can re-sync its buttons
    navigated = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setOpenLinks(False)  # every link comes through _on_anchor
        self.anchorClicked.connect(self._on_anchor)
        self.document().setDefaultStyleSheet(_DOCS_CSS)

        self._catalog = catalog()
        self._history: list[str] = []
        self._pos = -1
        self.go_home()

    # ---------------------------------------------------------------- pages

    def current_slug(self) -> str | None:
        return self._history[self._pos] if 0 <= self._pos < len(self._history) else None

    def show_page(self, slug: str, *, anchor: str | None = None,
                  record: bool = True) -> None:
        page = self._catalog.get(slug)
        if page is None:
            self.setMarkdown(_NOT_FOUND.format(name=slug))
        else:
            text, _ = render_links(page.path.read_text(encoding="utf-8"),
                                   self._catalog)
            self.setMarkdown(text)
        if anchor:
            self.scrollToAnchor(anchor)
        else:
            self.verticalScrollBar().setValue(0)
        if record and slug != self.current_slug():
            del self._history[self._pos + 1:]
            self._history.append(slug)
            self._pos = len(self._history) - 1
        self.navigated.emit()

    # -------------------------------------------------------------- history

    def can_go_back(self) -> bool:
        return self._pos > 0

    def can_go_forward(self) -> bool:
        return self._pos < len(self._history) - 1

    def go_back(self) -> None:
        if self.can_go_back():
            self._pos -= 1
            self.show_page(self._history[self._pos], record=False)

    def go_forward(self) -> None:
        if self.can_go_forward():
            self._pos += 1
            self.show_page(self._history[self._pos], record=False)

    def go_home(self) -> None:
        self.show_page(HOME_SLUG)

    # ---------------------------------------------------------------- links

    def _on_anchor(self, url: QUrl) -> None:
        scheme = url.scheme()
        if scheme in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
            return
        path = url.path()
        anchor = url.fragment() or None
        if not path:  # a bare "#heading" on the current page
            if anchor:
                self.scrollToAnchor(anchor)
            return
        slug = path[:-3] if path.endswith(".md") else path
        self.show_page(slug.strip("/").lower(), anchor=anchor)
