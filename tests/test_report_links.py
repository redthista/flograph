"""Links in a report page (N7).

A Note's `[Costs](page:Costs)` went to that page, but a report page is
drawn as paper, and the paper took no clicks at all — web links included.
The preview now maps a click back into the document and hit-tests it
there. On paper and in HTML a `page:` link goes nowhere, so there it is
set as the plain words.
"""
import pytest
from PySide6.QtCore import QPointF, Qt

from flograph.core.page_setup import PageSetup
from flograph.ui.report.export import body_rect, printable_points
from flograph.ui.report.html import report_html
from flograph.ui.report.preview import PagedPreview, link_tooltip
from flograph.ui.report.render import render_body

BODY = ("[the costs](page:Costs) and [the site](https://example.com)\n\n"
        "Some more words.\n")


@pytest.fixture(autouse=True)
def _app(qapp):
    return qapp


def nothing(ref, port):
    return None, "", ""


@pytest.fixture
def preview(qtbot):
    widget = PagedPreview()
    qtbot.addWidget(widget)
    widget.resize(700, 900)
    widget.show()
    return widget


def _links(document) -> dict:
    """Each link's href -> its words."""
    found = {}
    block = document.begin()
    while block.isValid():
        pieces = block.begin()
        while not pieces.atEnd():
            fragment = pieces.fragment()
            href = fragment.charFormat().anchorHref()
            if href:
                found[href] = found.get(href, "") + fragment.text()
            pieces += 1
        block = block.next()
    return found


def _on_screen(preview, href, setup) -> QPointF:
    """The viewport point over the first letters of the link `href` — the
    forward mapping, worked out here independently of `document_point`."""
    document = preview.document()
    layout = document.documentLayout()
    block = document.begin()
    while block.isValid():
        pieces = block.begin()
        while not pieces.atEnd():
            fragment = pieces.fragment()
            if fragment.charFormat().anchorHref() == href:
                line = block.layout().lineForTextPosition(
                    fragment.position() - block.position())
                top = layout.blockBoundingRect(block).top()
                x = line.cursorToX(fragment.position() - block.position())
                x = x[0] if isinstance(x, tuple) else x
                point = QPointF(x + 3, top + line.y() + line.height() / 2)
                body = body_rect(printable_points(setup), setup)
                page = int(point.y() // body.height())
                sheet = preview._sheet_rect(page + (1 if setup.cover else 0))
                scale = preview.zoom()
                return QPointF(
                    sheet.left() + (body.left() + point.x()) * scale,
                    sheet.top() + (body.top() + point.y()
                                   - page * body.height()) * scale)
            pieces += 1
        block = block.next()
    raise AssertionError(f"no link {href!r} in the document")


class TestThePreviewFollowsLinks:

    def test_a_page_link_is_found_under_the_pointer(self, preview):
        setup = PageSetup()
        preview.set_report(render_body(BODY, nothing, page_links=True).document,
                           setup)
        at = _on_screen(preview, "page:Costs", setup)
        assert preview.link_at(at) == "page:Costs"
        assert preview.link_at(_on_screen(preview, "https://example.com",
                                          setup)) == "https://example.com"

    def test_clicking_it_fires(self, preview, qtbot):
        setup = PageSetup()
        preview.set_report(render_body(BODY, nothing, page_links=True).document,
                           setup)
        at = _on_screen(preview, "page:Costs", setup).toPoint()
        with qtbot.waitSignal(preview.link_activated) as fired:
            qtbot.mouseClick(preview.viewport(), Qt.LeftButton, pos=at)
        assert fired.args == ["page:Costs"]

    def test_a_click_off_the_words_does_not(self, preview, qtbot):
        setup = PageSetup()
        preview.set_report(render_body(BODY, nothing, page_links=True).document,
                           setup)
        fired = []
        preview.link_activated.connect(fired.append)
        # the desk to the left of the sheet, and the top margin of the paper
        sheet = preview._sheet_rect(0)
        for point in (QPointF(2, sheet.top() + 40),
                      QPointF(sheet.left() + 60, sheet.top() + 4)):
            assert preview.link_at(point) == ""
            qtbot.mouseClick(preview.viewport(), Qt.LeftButton,
                             pos=point.toPoint())
        assert fired == []

    def test_a_link_on_a_later_page_and_after_a_cover(self, preview):
        """The page offset and the cover are both in the mapping."""
        setup = PageSetup(cover=True)
        body = "One\n\n\\pagebreak\n\n[the costs](page:Costs) on page two\n"
        preview.set_report(render_body(body, nothing, page_links=True).document,
                           setup)
        assert preview.page_count() == 2
        at = _on_screen(preview, "page:Costs", setup)
        assert preview._sheet_rect(2).contains(at)
        assert preview.link_at(at) == "page:Costs"
        # the cover is not the document
        cover = preview._sheet_rect(0)
        assert preview.document_point(cover.center()) is None

    def test_resting_on_a_link_says_where_it_goes(self):
        assert link_tooltip("page:Sales%20North") == \
            "Go to the page “Sales North”"
        assert link_tooltip("https://example.com") == "https://example.com"
        assert link_tooltip("") == ""


class TestOnPaperItIsTheWords:

    def test_a_printed_page_link_is_plain_text(self):
        document = render_body(BODY, nothing).document
        links = _links(document)
        assert "page:Costs" not in links
        assert links.get("https://example.com") == "the site", \
            "a web link still works on paper and in HTML"
        assert "the costs and the site" in document.toPlainText()

    def test_and_the_preview_keeps_it(self):
        links = _links(render_body(BODY, nothing, page_links=True).document)
        assert links.get("page:Costs") == "the costs"

    def test_the_html_has_no_dead_link(self):
        html = report_html(render_body(BODY, nothing))
        assert "page:" not in html
        assert "the costs" in html

    def test_one_in_a_table_cell_too(self):
        body = "| where | n |\n| - | - |\n| [costs](page:Costs) | 2 |\n"
        document = render_body(body, nothing).document
        assert "page:Costs" not in _links(document)
        assert "costs" in document.toPlainText()

    def test_it_prints_on_the_same_pages(self):
        """Only the underline and colour go, so paper breaks where the
        preview does."""
        body = "\n\n".join(f"[page {i}](page:P{i}) " + "words " * 80
                           for i in range(12))
        setup = PageSetup()
        size = body_rect(printable_points(setup), setup)
        counts = []
        for links in (True, False):
            document = render_body(body, nothing, page_links=links).document
            document.setPageSize(size.size())
            counts.append(document.pageCount())
        assert counts[0] == counts[1] > 1
