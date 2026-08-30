"""The reading pane of a wiki — the documentation window and the Markdown
Wiki card both embed one.

A `QTextBrowser` — the same Markdown engine the report preview and the
sticky-note cards use — pointed at a folder of `*.md` pages (the bundled
`flograph/docs/` by default). `core.docpages` turns `[[wikilinks]]` and
Obsidian `![[embeds]]` into ordinary Markdown before the text reaches Qt;
clicking a link loads that page here, external `http(s)` links open in the
real browser.

Every page is rendered Markdown → `toHtml` → fix-ups → `setHtml`, the same
detour `report/render.py` takes and for the same reasons. `setMarkdown`
alone drops images, never shades a `` ``` `` code block (the stylesheet's
`pre` rule doesn't reach it), and gives headings no anchors for a
`[[Page#heading]]` link to land on. The fix-up pass puts all three back:
images loaded from disk, `<pre>` / inline `code` styled, headings tagged.
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QTextDocument
from PySide6.QtWidgets import QTextBrowser

from flograph.core.docpages import (
    anchor_slug, catalog, render_links, sidebar,
)

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
code, pre {{ background-color: {theme.NODE_HEADER.name()};
             color: {theme.NODE_TEXT.name()}; }}
pre {{ padding: 8px; border: 1px solid {theme.NODE_BORDER.name()}; }}
table {{ border: 1px solid {theme.NODE_BORDER.name()};
         border-collapse: collapse; }}
th, td {{ border: 1px solid {theme.NODE_BORDER.name()}; padding: 3px 8px; }}
blockquote {{ color: {theme.NODE_SUBTEXT.name()};
              border-left: 2px solid {theme.NODE_BORDER.name()};
              padding-left: 8px; }}
"""

_NOT_FOUND = "# Page not found\n\nThere is no page called `{name}` in this folder."
_EMPTY = "# Nothing here\n\nThis folder has no Markdown (`.md`) pages."

_IMAGE_MD_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_IMAGE_TOKEN = "@@wikiimg-{}@@"

# Qt renders markdown `code` as a bare monospace <span> (no background) and
# gives headings no anchor. `_fix_up_html` repairs both on the toHtml output.
_MONO_SPAN_RE = re.compile(
    r"<span style=\"[^\"]*font-family:'monospace'[^\"]*\">([^<]*)</span>")
_HEADING_RE = re.compile(r"(<h[1-6][^>]*>)(.*?)(</h[1-6]>)", re.DOTALL)
_TAGS_RE = re.compile(r"<[^>]+>|&[#0-9a-zA-Z]+;")


def _fix_up_html(html: str) -> str:
    """Monospace spans → `<code>` (so the stylesheet shades them), and an
    `<a name>` on every heading matching `docpages.anchor_slug`, so an
    in-page `[[Page#heading]]` link scrolls to it."""
    html = _MONO_SPAN_RE.sub(r"<code>\1</code>", html)

    def anchored(m: "re.Match[str]") -> str:
        title = _TAGS_RE.sub("", m.group(2)).strip()
        return (f'{m.group(1)}<a name="{anchor_slug(title)}"></a>'
                f'{m.group(2)}{m.group(3)}')

    return _HEADING_RE.sub(anchored, html)


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
            self._render(_EMPTY)
            self.navigated.emit()
            return
        page = self._catalog.get(slug) if slug else None
        if page is None:
            self._render(_NOT_FOUND.format(name=slug))
        else:
            text, _ = render_links(page.path.read_text(encoding="utf-8"),
                                   self._catalog)
            self._render(text, page.path.parent)
        if anchor:
            self.scrollToAnchor(anchor)
        else:
            self.verticalScrollBar().setValue(0)
        if record and page is not None and slug != self.current_slug():
            del self._history[self._pos + 1:]
            self._history.append(slug)
            self._pos = len(self._history) - 1
        self.navigated.emit()

    # ---------------------------------------------------------- rendering

    def _render(self, text: str, base: Path | None = None) -> None:
        """Render one page: Markdown → `toHtml` → fix-ups → `setHtml`.

        Each `![alt](src)` is swapped for a token that survives `setMarkdown`
        and, once the picture has loaded from disk and been registered as a
        document resource, spliced back in as an `<img>` — Qt's Markdown
        reader drops images outright. `_fix_up_html` then shades code and
        anchors headings. Remote (`http`) images are left for Qt to ignore."""
        doc = self.document()
        base = base or Path()
        specs: list[tuple[str, str, int | None]] = []  # token, url, width

        def stash(m: "re.Match[str]") -> str:
            alt, src = m.group(1), m.group(2).strip()
            if src.startswith(("http://", "https://", "data:", "//")):
                return m.group(0)
            width: int | None = None
            if "|" in alt:  # Obsidian sizing: ![[img.png|200]]
                alt, _, size = alt.partition("|")
                if size.strip().isdigit():
                    width = int(size.strip())
            image = self._load_image(src, base)
            if image is None or image.isNull():
                return alt or src.rsplit("/", 1)[-1]
            token = _IMAGE_TOKEN.format(len(specs))
            url = f"wikiimg:{len(specs)}"
            doc.addResource(QTextDocument.ImageResource, QUrl(url), image)
            specs.append((token, url, width))
            return token

        staged = QTextDocument()
        staged.setMarkdown(_IMAGE_MD_RE.sub(stash, text))
        html = staged.toHtml()
        for token, url, width in specs:
            w = f' width="{width}"' if width else ""
            html = html.replace(token, f'<img src="{url}"{w} />')
        self.setHtml(_fix_up_html(html))

    def _load_image(self, src: str, base: Path) -> QImage | None:
        from urllib.parse import unquote
        src = unquote(src).lstrip("/")
        for cand in (base / src, (self._dir or base) / src):
            if cand.is_file():
                return QImage(str(cand))
        return None

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
