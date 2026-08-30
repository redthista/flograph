"""The reading pane of a wiki — the documentation window and the Markdown
Wiki card both embed one.

A `QTextBrowser` — the same Markdown engine the report preview and the
sticky-note cards use — pointed at a folder of `*.md` pages (the bundled
`flograph/docs/` by default). `[[wikilinks]]` are turned into ordinary links
by `core.docpages` before the text reaches Qt; clicking one loads that page
here. External `http(s)` links open in the real browser, as the web-view
"Open in Browser" action does.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QTextBrowser

from flograph.core.docpages import catalog, render_links, sidebar

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

_NOT_FOUND = "# Page not found\n\nThere is no page called `{name}` in this folder."
_EMPTY = "# Nothing here\n\nThis folder has no Markdown (`.md`) pages."


class DocsBrowser(QTextBrowser):
    """Renders one page at a time and keeps its own back/forward history —
    QTextBrowser's built-in history is tied to `setSource`/`loadResource`,
    which a list of visited slugs sidesteps more legibly."""

    #: emitted after navigation so the toolbar / nav tree can re-sync
    navigated = Signal()

    def __init__(self, parent=None, directory: Path | None = None) -> None:
        super().__init__(parent)
        self.setOpenLinks(False)  # every link comes through _on_anchor
        self.anchorClicked.connect(self._on_anchor)
        self.document().setDefaultStyleSheet(_DOCS_CSS)

        self._dir: Path | None = directory
        self._catalog = catalog(directory)
        self._history: list[str] = []
        self._pos = -1
        self.go_home()

    # ---------------------------------------------------------------- pages

    def set_folder(self, directory: Path | None) -> None:
        """Point the browser at a different folder of pages — clears history
        and shows that folder's home page."""
        self._dir = directory
        self._catalog = catalog(directory)
        self._history = []
        self._pos = -1
        self.go_home()

    def home_slug(self) -> str | None:
        """`home` if the folder has a Home page, else the first page the nav
        tree offers, else the first page alphabetically, else None."""
        if HOME_SLUG in self._catalog:
            return HOME_SLUG
        for entry in _walk(sidebar(self._dir)):
            if entry.slug in self._catalog:
                return entry.slug
        return next(iter(sorted(self._catalog)), None)

    def current_slug(self) -> str | None:
        if 0 <= self._pos < len(self._history):
            return self._history[self._pos]
        return None

    def show_page(self, slug: str | None, *, anchor: str | None = None,
                  record: bool = True) -> None:
        if not self._catalog:
            self.setMarkdown(_EMPTY)
            self.navigated.emit()
            return
        page = self._catalog.get(slug) if slug else None
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
        if record and page is not None and slug != self.current_slug():
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
        self.show_page(self.home_slug())

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


def _walk(entries):
    for entry in entries:
        yield entry
        yield from _walk(entry.children)
