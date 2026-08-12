"""The report preview shown as sheets of paper.

It used to be a QTextBrowser — one continuous scroll, honest about the
content and silent about the page. Everything page setup adds (a cover,
running headers, where a page actually ends) was invisible until the PDF
came out, which is the least useful moment to find out.

The rule these tests exist to hold: the preview draws through the *same*
routines as the PDF writer. A preview that reimplements the page loop is
one that will eventually disagree with the export.
"""
import pytest

from flograph.core import Graph, Page
from flograph.core.page_setup import PageSetup
from flograph.ui.report.preview import MAX_ZOOM, MIN_ZOOM, PagedPreview
from flograph.ui.report.render import render_body


@pytest.fixture(autouse=True)
def _app(qapp):
    return qapp


def nothing(ref, port):
    return None, "", ""


def long_body(sections=10):
    return "\n\n".join(f"## Section {i}\n\n" + "words " * 100
                       for i in range(sections))


@pytest.fixture
def preview(qtbot):
    widget = PagedPreview()
    qtbot.addWidget(widget)
    widget.resize(700, 900)
    return widget


class TestPagination:

    def test_a_short_report_is_one_sheet(self, preview):
        preview.set_report(render_body("Hello", nothing).document, PageSetup())
        assert preview.page_count() == 1
        assert preview.sheet_count() == 1

    def test_a_long_report_is_several(self, preview):
        preview.set_report(render_body(long_body(), nothing).document,
                           PageSetup())
        assert preview.page_count() > 1

    def test_bigger_paper_needs_fewer_sheets(self, preview):
        document = render_body(long_body(), nothing).document
        preview.set_report(document, PageSetup(size="A5"))
        small = preview.page_count()
        preview.set_report(document, PageSetup(size="A3"))
        assert preview.page_count() < small

    def test_a_cover_is_an_extra_sheet_but_not_a_page(self, preview):
        document = render_body(long_body(3), nothing).document
        preview.set_report(document, PageSetup())
        plain = preview.sheet_count()
        preview.set_report(document, PageSetup(cover=True))
        assert preview.sheet_count() == plain + 1
        assert preview.page_count() == plain   # the cover is not page 1

    def test_a_forced_break_makes_a_sheet(self, preview):
        plain = render_body("One\n\nTwo\n", nothing).document
        preview.set_report(plain, PageSetup())
        assert preview.page_count() == 1
        broken = render_body("One\n\n\\pagebreak\n\nTwo\n", nothing).document
        preview.set_report(broken, PageSetup())
        assert preview.page_count() == 2

    def test_it_agrees_with_the_exporter(self, preview):
        """The claim the whole design rests on: what the preview paginates
        and what the PDF paginates are the same count, because they compute
        it the same way."""
        from flograph.ui.report.export import page_count
        document = render_body(long_body(), nothing).document
        for setup in (PageSetup(), PageSetup(size="A5"),
                      PageSetup(landscape=True),
                      PageSetup(footer_center="Page {page}"),
                      PageSetup(margin_top=45.0, margin_bottom=45.0)):
            preview.set_report(document, setup)
            assert preview.page_count() == page_count(document, setup), setup

    def test_an_empty_preview_paints_without_a_document(self, preview,
                                                        qtbot):
        from PySide6.QtGui import QPixmap
        assert preview.document() is None
        preview.render(QPixmap(preview.size()))   # must not raise


class TestZoom:

    def test_it_fits_the_width_by_default(self, preview, qapp):
        """A narrower pane draws smaller paper — the sheet is always as wide
        as the pane allows, because that is the only zoom nobody has to
        choose."""
        preview.show()
        qapp.processEvents()
        preview.set_report(render_body("Hi", nothing).document, PageSetup())
        wide = preview.zoom()
        preview.resize(380, 900)
        qapp.processEvents()
        assert preview.zoom() < wide
        preview.hide()

    def test_an_explicit_zoom_survives_a_resize(self, preview):
        """Fit-to-width is the default, not a rule — otherwise zooming in to
        proofread would be undone by the next splitter drag."""
        preview.set_report(render_body("Hi", nothing).document, PageSetup())
        preview.set_zoom(1.25)
        preview.resize(500, 700)
        assert preview.zoom() == pytest.approx(1.25)

    def test_none_goes_back_to_fitting(self, preview):
        preview.set_report(render_body("Hi", nothing).document, PageSetup())
        fitted = preview.zoom()
        preview.set_zoom(2.0)
        preview.set_zoom(None)
        assert preview.zoom() == pytest.approx(fitted)

    def test_zoom_is_clamped(self, preview):
        preview.set_report(render_body("Hi", nothing).document, PageSetup())
        preview.set_zoom(99.0)
        assert preview.zoom() == pytest.approx(MAX_ZOOM)
        preview.set_zoom(0.0001)
        assert preview.zoom() == pytest.approx(MIN_ZOOM)

    def test_zooming_in_gives_something_to_scroll(self, preview):
        preview.set_report(render_body(long_body(), nothing).document,
                           PageSetup())
        preview.set_zoom(3.0)
        assert preview.verticalScrollBar().maximum() > 0
        assert preview.horizontalScrollBar().maximum() > 0


class TestFlowLayout:
    """Sheets left-to-right and wrapping — the contact sheet, for seeing
    where everything falls at once."""

    def test_one_column_by_default(self, preview):
        preview.set_report(render_body(long_body(), nothing).document,
                           PageSetup())
        assert not preview.flow()
        assert preview.columns() == 1

    def test_flowing_uses_the_width(self, preview, qapp):
        preview.show()
        qapp.processEvents()
        preview.set_report(render_body(long_body(), nothing).document,
                           PageSetup())
        preview.set_zoom(0.2)          # small sheets, so several fit
        preview.set_flow(True)
        assert preview.columns() > 1
        preview.hide()

    def test_single_column_stays_single_however_wide(self, preview, qapp):
        """One page at a time, as big as it goes, is a way of reading — the
        window being wide should not take it away."""
        preview.show()
        qapp.processEvents()
        preview.set_report(render_body(long_body(), nothing).document,
                           PageSetup())
        preview.set_zoom(0.2)
        assert preview.columns() == 1
        preview.hide()

    def test_flowing_is_fewer_rows_to_scroll(self, preview, qapp):
        preview.show()
        qapp.processEvents()
        preview.set_report(render_body(long_body(20), nothing).document,
                           PageSetup())
        preview.set_zoom(0.2)
        tall = preview.verticalScrollBar().maximum()
        preview.set_flow(True)
        assert preview.verticalScrollBar().maximum() < tall
        preview.hide()

    def test_sheets_do_not_overlap(self, preview, qapp):
        preview.show()
        qapp.processEvents()
        preview.set_report(render_body(long_body(6), nothing).document,
                           PageSetup())
        preview.set_zoom(0.2)
        preview.set_flow(True)
        rects = [preview._sheet_rect(i)
                 for i in range(preview.sheet_count())]
        for i, first in enumerate(rects):
            for second in rects[i + 1:]:
                assert not first.intersects(second)

    def test_it_paints_flowed(self, preview, qapp):
        from PySide6.QtGui import QPixmap
        preview.set_report(render_body(long_body(6), nothing).document,
                           PageSetup(cover=True))
        preview.set_zoom(0.2)
        preview.set_flow(True)
        preview.render(QPixmap(preview.size()))   # must not raise


class TestOnTheReportPage:

    @pytest.fixture
    def page(self, qtbot, registry):
        from PySide6.QtGui import QUndoStack
        from flograph.engine import ExecutionEngine
        from flograph.ui.report import ReportPage
        graph = Graph()
        graph.add_page(Page(id="p1", title="Q3", kind="report",
                            body="# Q3\n\nProse.\n"))
        engine = ExecutionEngine(graph)
        widget = ReportPage(graph, engine, QUndoStack(), "p1")
        qtbot.addWidget(widget)
        yield widget, graph
        widget.dispose()

    def test_the_preview_is_paper(self, page):
        widget, _graph = page
        assert isinstance(widget.preview, PagedPreview)
        assert widget.preview.document() is not None

    def test_page_setup_reaches_the_preview(self, page):
        widget, graph = page
        graph.set_page_setup("p1", PageSetup(size="A3"))
        widget.refresh_preview()
        from flograph.ui.report.export import sheet_points
        assert widget.preview._sheet_size() == sheet_points(PageSetup(size="A3"))

    def test_a_trial_setup_shows_without_being_saved(self, page):
        """What makes Page Setup live: the dialog's work-in-progress is
        drawn, but the page keeps its own until OK."""
        widget, graph = page
        widget.preview_setup(PageSetup(size="A5", cover=True))
        assert widget.preview.sheet_count() == 2      # cover + body
        assert graph.page("p1").setup == PageSetup()  # nothing committed

    def test_clearing_the_trial_puts_the_page_back(self, page):
        widget, graph = page
        widget.preview_setup(PageSetup(cover=True))
        widget.preview_setup(None)
        assert widget.preview.sheet_count() == 1

    def test_the_help_dialog_opens_and_is_reused(self, page, qtbot):
        widget, _graph = page
        widget.show_help()
        first = widget._help_dialog
        qtbot.addWidget(first)
        widget.show_help()
        assert widget._help_dialog is first   # not a second window each time

    def test_the_help_covers_the_syntax(self):
        from flograph.ui.report.help import reference_html
        text = reference_html()
        for needed in ("![[", "pagebreak", "{page}", "Page Setup",
                       "Save HTML", "Locked"):
            assert needed in text, needed

    def test_save_html_asks_the_window(self, page, qtbot):
        widget, _graph = page
        with qtbot.waitSignal(widget.export_html_requested) as blocker:
            widget._html_btn.click()
        assert blocker.args == ["p1"]

    def test_the_toolbar_toggles_the_flow(self, page):
        widget, _graph = page
        assert not widget.preview.flow()
        widget._flow_btn.setChecked(True)
        assert widget.preview.flow()
        widget._flow_btn.setChecked(False)
        assert not widget.preview.flow()
