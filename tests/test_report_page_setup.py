"""Ideas A1-A3: how a report sits on the page.

Page setup (size, orientation, margins, cover), running headers and
footers, and forced page breaks. The three are one feature because they are
one settings surface — a PageSetup, kept Qt-free so the shelved HTML
export (ideas_archived.md item 8) can read the same thing rather than
inventing a second one.
"""
import pandas as pd
import pytest
from PySide6.QtGui import QTextBlockFormat, QUndoStack

from flograph.core import Graph, Page
from flograph.core.page_setup import (PAGE_SIZES, PageSetup, expand, page_css)
from flograph.core.report import PAGEBREAK_TOKEN, mark_page_breaks
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.engine.cache import OutputCache
from flograph.ui.commands import SetPageSetupCommand
from flograph.ui.report.export import body_rect, export_pdf, page_layout
from flograph.ui.report.render import FIGURE_WIDTH, render_body, render_report


@pytest.fixture(autouse=True)
def _app(qapp):
    """Rendering and printing both want a QApplication — a QPdfWriter with
    no application behind it takes the process down rather than raising."""
    return qapp


def blocks(document):
    """(text, starts a new page) for every block, which is the only part of
    pagination visible without printing."""
    out = []
    block = document.begin()
    while block.isValid():
        out.append((block.text(),
                    block.blockFormat().pageBreakPolicy()
                    == QTextBlockFormat.PageBreak_AlwaysBefore))
        block = block.next()
    return out


def nothing(ref, port):
    return None, "", ""


class TestTheSettings:

    def test_defaults_are_what_reports_did_before(self):
        """The whole compatibility story in one assertion: a page nobody has
        set up is A4 portrait at 15mm, which is what export.py hardcoded."""
        setup = PageSetup()
        assert setup.size == "A4" and not setup.landscape
        assert setup.margin_top == setup.margin_left == 15.0
        assert not setup.cover and not setup.has_header()
        assert not setup.has_footer()

    def test_the_default_body_width_is_the_old_figure_width(self):
        """A4 less 15mm each side, in points, is the constant embedded
        figures were already drawn at — so the default really is a no-op."""
        assert PageSetup().body_width_points() == FIGURE_WIDTH

    def test_landscape_swaps_the_sheet(self):
        portrait = PageSetup(size="A4")
        landscape = PageSetup(size="A4", landscape=True)
        assert portrait.page_mm() == (210.0, 297.0)
        assert landscape.page_mm() == (297.0, 210.0)
        assert landscape.body_width_points() > portrait.body_width_points()

    def test_margins_change_the_text_column(self):
        wide = PageSetup(margin_left=5.0, margin_right=5.0)
        narrow = PageSetup(margin_left=40.0, margin_right=40.0)
        assert wide.body_width_points() > narrow.body_width_points()

    def test_a_page_left_alone_saves_nothing(self):
        assert PageSetup().to_dict() == {}

    def test_only_the_changes_are_saved(self):
        setup = PageSetup(size="Letter", footer_center="Page {page}")
        assert setup.to_dict() == {"size": "Letter",
                                   "footer_center": "Page {page}"}

    def test_a_saved_setup_round_trips(self):
        setup = PageSetup(size="Legal", landscape=True, margin_top=22.5,
                          cover=True, cover_subtitle="Board pack",
                          header_right="{date}", first_page_number=3)
        assert PageSetup.from_dict(setup.to_dict()) == setup

    def test_a_file_from_a_later_build_still_loads(self):
        """Forward compatibility beats validation: a field this build has
        never heard of should cost that field, not the whole page."""
        setup = PageSetup.from_dict({"size": "A5", "watermark": "DRAFT"})
        assert setup.size == "A5"
        assert not hasattr(setup, "watermark")

    def test_nonsense_is_pulled_back_into_range(self):
        setup = PageSetup.from_dict(
            {"size": "Papyrus", "margin_left": "wide", "margin_top": 900,
             "first_page_number": -4, "header_left": 12})
        assert setup.size == "A4"                # unknown size -> the default
        assert setup.margin_left == 15.0         # unparseable -> the default
        assert setup.margin_top == 100.0         # clamped
        assert setup.first_page_number == 0
        assert setup.header_left == "12"         # drawn by a painter, so str

    def test_a_copy_is_independent(self):
        setup = PageSetup()
        copy = setup.copy()
        copy.margin_top = 40.0
        assert setup.margin_top == 15.0

    def test_every_named_size_is_portrait_and_sane(self):
        for name, (width, height) in PAGE_SIZES.items():
            assert 0 < width < height, name


class TestTheFields:

    def test_each_field_expands(self):
        assert expand("{title} — {page}/{pages} — {date}", 2, 7, "Q3",
                      "1 May") == "Q3 — 2/7 — 1 May"

    def test_a_stray_brace_does_not_raise(self):
        """str.format would; this is why it is a plain replace."""
        assert expand("100% {of budget}", 1, 1, "T", "D") == "100% {of budget}"

    def test_an_unknown_field_is_left_visible(self):
        assert expand("{chapter}", 1, 1, "T", "D") == "{chapter}"

    def test_empty_text_stays_empty(self):
        assert expand("", 1, 1, "T", "D") == ""


class TestPageBreaks:

    @pytest.mark.parametrize("marker", ["\\pagebreak", "\\newpage",
                                        "<!-- pagebreak -->",
                                        "<!--newpage-->"])
    def test_every_spelling_is_recognised(self, marker):
        assert PAGEBREAK_TOKEN in mark_page_breaks(f"A\n\n{marker}\n\nB\n")

    def test_prose_mentioning_the_word_is_left_alone(self):
        """The marker is a line of its own — the word in a sentence is just
        the word."""
        assert PAGEBREAK_TOKEN not in mark_page_breaks(
            "Insert a \\pagebreak here to split it.\n")

    def test_the_break_lands_on_the_block_after_it(self):
        document = render_body("First\n\n\\pagebreak\n\nSecond\n",
                               nothing).document
        assert blocks(document) == [("First", False), ("Second", True)]

    def test_the_marker_leaves_no_blank_paragraph(self):
        document = render_body("First\n\n\\pagebreak\n\nSecond\n",
                               nothing).document
        assert document.toPlainText() == "First\nSecond"

    def test_a_marker_written_tight_against_the_text_still_works(self):
        """No blank line either side — markdown would otherwise fold it into
        the paragraph above and the break would silently do nothing."""
        document = render_body("First\n\\pagebreak\nSecond\n",
                               nothing).document
        assert blocks(document) == [("First", False), ("Second", True)]

    def test_a_break_before_everything_is_dropped(self):
        """It would ask for a page break before page one, which is a blank
        sheet and nothing else."""
        document = render_body("\\newpage\n\nOnly\n", nothing).document
        assert blocks(document) == [("Only", False)]

    def test_a_break_after_everything_is_dropped(self):
        document = render_body("Only\n\n\\newpage\n", nothing).document
        assert blocks(document) == [("Only", False)]

    def test_several_breaks(self):
        document = render_body(
            "A\n\n\\newpage\n\nB\n\n\\newpage\n\nC\n", nothing).document
        assert blocks(document) == [("A", False), ("B", True), ("C", True)]

    def test_a_break_from_an_embedded_string(self):
        """A node returning markdown can force its own break — which is how
        one section per region gets a page each."""
        document = render_body(
            "Intro\n\n![[Sections]]\n",
            lambda ref, port: ("\\newpage\n\nRegion one\n", "", "")).document
        assert blocks(document) == [("Intro", False), ("Region one", True)]

    def test_the_preview_draws_a_rule_instead(self):
        """The preview is one continuous scroll, so a real break would be
        invisible there and the writer could not tell it had worked."""
        rendered = render_body("A\n\n\\pagebreak\n\nB\n", nothing,
                               page_break_rule=True)
        assert "<hr" in rendered.document.toHtml()

    def test_print_gets_no_rule(self):
        rendered = render_body("A\n\n\\pagebreak\n\nB\n", nothing)
        assert "<hr" not in rendered.document.toHtml()


class TestTheLayout:

    def test_the_bands_only_cost_room_when_used(self):
        from PySide6.QtCore import QRectF
        printable = QRectF(0, 0, 500, 700)
        plain = body_rect(printable, PageSetup())
        assert plain == printable

        with_footer = body_rect(printable,
                                PageSetup(footer_center="Page {page}"))
        assert with_footer.height() < printable.height()
        assert with_footer.top() == printable.top()   # footer is at the foot

    def test_a_header_pushes_the_body_down(self):
        from PySide6.QtCore import QRectF
        printable = QRectF(0, 0, 500, 700)
        rect = body_rect(printable, PageSetup(header_left="{title}"))
        assert rect.top() > printable.top()

    def test_the_layout_carries_the_setup(self):
        from PySide6.QtGui import QPageLayout
        layout = page_layout(PageSetup(size="Letter", landscape=True,
                                       margin_left=25.0))
        assert layout.pageSize().name().startswith("Letter")
        assert layout.orientation() == QPageLayout.Landscape
        assert layout.margins().left() == 25.0

    def test_landscape_can_still_be_forced(self):
        """The pre-page-setup callers passed this, and "print it sideways"
        is a reasonable thing to ask without editing the page."""
        from PySide6.QtGui import QPageLayout
        assert page_layout(PageSetup(), landscape=True).orientation() \
            == QPageLayout.Landscape
        assert page_layout(PageSetup(landscape=True),
                           landscape=False).orientation() \
            == QPageLayout.Portrait

    def test_the_css_rule_matches_the_setup(self):
        """Unused by the Qt export — it is the evidence that this settings
        surface can drive the HTML one without being redesigned."""
        css = page_css(PageSetup(size="A4", margin_top=20.0))
        assert "size: 210mm 297mm;" in css
        assert "margin: 20mm 15mm 15mm 15mm;" in css


class TestExporting:

    @pytest.fixture
    def long_report(self):
        body = "\n\n".join(f"## Section {i}\n\n" + "words " * 120
                           for i in range(1, 9))
        return render_body("# Report\n\n" + body, nothing)

    def page_count(self, path):
        """Pages, counted off the PDF itself rather than trusted from the
        code that wrote it."""
        return open(path, "rb").read().count(b"/Type /Page\n")

    def test_a_plain_export_is_unchanged(self, long_report, tmp_path):
        target = tmp_path / "plain.pdf"
        export_pdf(long_report.document, str(target), title="Report")
        assert target.read_bytes()[:5] == b"%PDF-"

    def test_a_cover_adds_exactly_one_page(self, long_report, tmp_path):
        plain = tmp_path / "plain.pdf"
        covered = tmp_path / "covered.pdf"
        export_pdf(long_report.document, str(plain), title="Report")
        export_pdf(long_report.document, str(covered), title="Report",
                   setup=PageSetup(cover=True, cover_subtitle="Board pack"))
        assert self.page_count(str(covered)) == self.page_count(str(plain)) + 1

    def test_bigger_paper_takes_fewer_pages(self, long_report, tmp_path):
        small = tmp_path / "a5.pdf"
        big = tmp_path / "a3.pdf"
        export_pdf(long_report.document, str(small), setup=PageSetup(size="A5"))
        export_pdf(long_report.document, str(big), setup=PageSetup(size="A3"))
        assert self.page_count(str(big)) < self.page_count(str(small))

    def test_the_export_survives_every_band_being_set(self, long_report,
                                                      tmp_path):
        target = tmp_path / "full.pdf"
        export_pdf(long_report.document, str(target), title="Report",
                   setup=PageSetup(
                       cover=True, cover_title="{title}",
                       header_left="{title}", header_center="c",
                       header_right="{date}", footer_left="l",
                       footer_center="Page {page} of {pages}",
                       footer_right="r", bands_on_first_page=False))
        assert target.read_bytes()[:5] == b"%PDF-"
        assert target.stat().st_size > 1000

    def test_an_unwritable_path_raises_oserror(self, long_report, tmp_path):
        with pytest.raises(OSError):
            export_pdf(long_report.document,
                       str(tmp_path / "no" / "such" / "dir" / "x.pdf"))

    def test_exporting_does_not_reflow_the_original(self, long_report,
                                                    tmp_path):
        """A clone is printed, so exporting must not change the document the
        preview is showing."""
        before = long_report.document.pageSize()
        export_pdf(long_report.document, str(tmp_path / "x.pdf"),
                   setup=PageSetup(size="A3", landscape=True))
        assert long_report.document.pageSize() == before


class TestThroughTheModel:

    def test_a_page_carries_its_setup_through_a_save(self, registry):
        graph = Graph()
        page = Page(id="p1", title="Q3", kind="report", body="# Q3")
        page.setup = PageSetup(size="Letter", cover=True,
                               footer_center="Page {page}")
        graph.add_page(page)
        reloaded = graph_from_dict(graph_to_dict(graph), registry)
        assert reloaded.page("p1").setup == page.setup

    def test_an_older_project_loads_with_the_defaults(self, registry):
        graph = Graph()
        graph.add_page(Page(id="p1", title="Q3", kind="report"))
        payload = graph_to_dict(graph)
        for entry in payload["graph"]["pages"]:
            entry.pop("setup", None)     # written before page setup existed
        assert graph_from_dict(payload, registry).page("p1").setup \
            == PageSetup()

    def test_setting_it_stores_a_copy(self):
        """The dialog edits a working copy; if the model kept that object,
        the next edit would change the model behind the undo stack."""
        graph = Graph()
        graph.add_page(Page(id="p1", kind="report"))
        setup = PageSetup(size="A3")
        graph.set_page_setup("p1", setup)
        setup.size = "A5"
        assert graph.page("p1").setup.size == "A3"

    def test_undo_puts_the_old_setup_back(self):
        graph = Graph()
        graph.add_page(Page(id="p1", kind="report"))
        stack = QUndoStack()
        stack.push(SetPageSetupCommand(graph, "p1", PageSetup(size="Legal")))
        assert graph.page("p1").setup.size == "Legal"
        stack.undo()
        assert graph.page("p1").setup == PageSetup()
        stack.redo()
        assert graph.page("p1").setup.size == "Legal"
        stack.clear()

    def test_a_duplicated_page_gets_its_own_setup(self):
        from flograph.ui.commands import DuplicatePageCommand
        graph = Graph()
        graph.add_page(Page(id="p1", kind="report",
                            setup=PageSetup(size="A3")))
        stack = QUndoStack()
        stack.push(DuplicatePageCommand(graph, "p1"))
        copy = [p for p in graph.pages.values() if p.id != "p1"][0]
        assert copy.setup.size == "A3"
        copy.setup.size = "A5"
        assert graph.page("p1").setup.size == "A3"
        stack.clear()


class TestTheDialog:

    def test_it_reads_back_what_it_was_given(self, qtbot):
        from flograph.ui.report import PageSetupDialog
        setup = PageSetup(size="Legal", landscape=True, margin_left=25.0,
                          cover=True, cover_subtitle="Board pack",
                          footer_center="Page {page}", first_page_number=2)
        dialog = PageSetupDialog(setup, "Q3")
        qtbot.addWidget(dialog)
        assert dialog.result_setup() == setup

    def test_it_edits_a_copy(self, qtbot):
        """Cancel has to leave the page alone, so the dialog must never hold
        the model's own object."""
        from flograph.ui.report import PageSetupDialog
        setup = PageSetup()
        dialog = PageSetupDialog(setup, "Q3")
        qtbot.addWidget(dialog)
        dialog.margin_boxes["margin_top"].setValue(40.0)
        assert setup.margin_top == 15.0
        assert dialog.result_setup().margin_top == 40.0

    def test_restore_defaults_puts_everything_back(self, qtbot):
        from flograph.ui.report import PageSetupDialog
        dialog = PageSetupDialog(
            PageSetup(size="A3", cover=True, header_left="x"), "Q3")
        qtbot.addWidget(dialog)
        dialog._restore_defaults()
        assert dialog.result_setup() == PageSetup()

    def test_the_summary_says_how_wide_the_text_will_be(self, qtbot):
        from flograph.ui.report import PageSetupDialog
        dialog = PageSetupDialog(PageSetup(), "Q3")
        qtbot.addWidget(dialog)
        assert str(PageSetup().body_width_points()) in dialog._summary.text()


class TestInTheWindow:

    @pytest.fixture
    def window(self, qtbot, registry, tmp_path, monkeypatch):
        from PySide6.QtCore import QSettings
        from flograph.ui import mainwindow as mod
        monkeypatch.setattr(
            mod, "QSettings",
            lambda *a, **k: QSettings(str(tmp_path / "s.ini"),
                                      QSettings.IniFormat))
        win = mod.MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def report_page(self, window):
        window._add_page("report")
        return next(page_id for page_id, page in window.graph.pages.items()
                    if page.kind == "report")

    def accept_with(self, monkeypatch, setup):
        """Stand in for the dialog, which cannot be exec()d in a test."""
        from PySide6.QtCore import QObject, Signal
        from PySide6.QtWidgets import QDialog
        from flograph.ui import report as report_pkg

        class Stub(QObject):
            # a real signal, because the window connects the live-preview
            # callback to it and disconnects on the way out
            setup_changed = Signal(object)

            def __init__(self, *args, **kwargs):
                super().__init__()

            def exec(self):
                return QDialog.Accepted

            def result_setup(self):
                return setup

        monkeypatch.setattr(report_pkg, "PageSetupDialog", Stub)

    def test_accepting_the_dialog_is_one_undo_step(self, window, monkeypatch):
        page_id = self.report_page(window)
        self.accept_with(monkeypatch, PageSetup(size="A3", cover=True))
        before = window.undo_stack.count()
        window._edit_page_setup(page_id)
        assert window.graph.page(page_id).setup.size == "A3"
        assert window.undo_stack.count() == before + 1
        window.undo_stack.undo()
        assert window.graph.page(page_id).setup == PageSetup()

    def test_accepting_an_unchanged_setup_records_nothing(self, window,
                                                          monkeypatch):
        """Opening the dialog and clicking OK is not an edit, and should not
        leave an undo step that appears to do nothing."""
        page_id = self.report_page(window)
        self.accept_with(monkeypatch, PageSetup())
        before = window.undo_stack.count()
        window._edit_page_setup(page_id)
        assert window.undo_stack.count() == before

    def test_a_dashboard_page_has_no_page_setup(self, window, monkeypatch):
        window._add_page("dashboard")
        page_id = next(page_id for page_id, page in window.graph.pages.items()
                       if page.kind == "dashboard")
        self.accept_with(monkeypatch, PageSetup(size="A3"))
        before = window.undo_stack.count()
        window._edit_page_setup(page_id)
        assert window.undo_stack.count() == before

    def test_the_button_asks_the_window(self, window, qtbot, monkeypatch):
        # The window is already connected to this signal, and clicking would
        # otherwise open the real dialog and block the suite on it.
        self.accept_with(monkeypatch, PageSetup())
        page_id = self.report_page(window)
        widget = window._dashboard_pages[page_id]
        with qtbot.waitSignal(widget.page_setup_requested) as blocker:
            widget._setup_btn.click()
        assert blocker.args == [page_id]

    def test_changing_the_setup_re_renders_the_preview(self, window):
        """The preview draws its charts at the body width, so a new paper
        size has to reach it — otherwise it keeps the old proportions."""
        page_id = self.report_page(window)
        widget = window._dashboard_pages[page_id]
        widget._timer.stop()
        window.graph.set_page_setup(page_id, PageSetup(size="A3"))
        assert widget._timer.isActive()

    def test_the_export_uses_the_page_setup(self, window, monkeypatch,
                                            tmp_path):
        """The one wire that makes all of this visible: what the dialog set
        has to arrive at the PDF writer."""
        page_id = self.report_page(window)
        # The starter body demonstrates the syntax with embeds that name
        # nothing, and an export with unresolved embeds ends in a modal
        # warning — which in a test is a hang, not a message.
        window.graph.set_page_body(page_id, "# Q3\n\nPlain prose.\n")
        window.graph.set_page_setup(page_id, PageSetup(size="A5", cover=True))
        seen = {}
        from flograph.ui import report as report_pkg
        real = report_pkg.export_pdf

        def spy(document, path, title="", landscape=None, setup=None):
            seen["setup"] = setup
            return real(document, path, title=title, setup=setup)

        monkeypatch.setattr(report_pkg, "export_pdf", spy)

        # The class in the window's own namespace, not the Qt static method:
        # a PySide static cannot be reassigned, and a real save dialog would
        # sit there modal until the suite was killed.
        from flograph.ui import mainwindow as mod

        class NoDialog:
            @staticmethod
            def getSaveFileName(*args, **kwargs):
                return str(tmp_path / "r.pdf"), ""

        monkeypatch.setattr(mod, "QFileDialog", NoDialog)
        window._export_report_pdf(page_id)
        assert seen["setup"].size == "A5" and seen["setup"].cover


class TestTheRenderedWidth:
    """Page setup has to reach the *preview*, not only the PDF writer.

    Charts are raster by the time they reach the document, so the width
    they are drawn at is settled before anyone can see whether it fits.
    """

    @pytest.fixture
    def env(self, registry):
        matplotlib = pytest.importorskip("matplotlib")
        matplotlib.use("Agg")
        from matplotlib.figure import Figure

        graph = Graph()
        cache = OutputCache()
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, "Chart")
        figure = Figure(figsize=(4, 3))
        figure.add_subplot(111).plot([1, 2, 3])
        cache.set(node.id, {"value": figure}, 0.0)
        return graph, cache

    def drawn_width(self, rendered):
        import re
        match = re.search(r'<img[^>]*width="(\d+)"', rendered.document.toHtml())
        assert match, "no embedded image in the rendered report"
        return int(match.group(1))

    def test_bigger_paper_draws_a_bigger_chart(self, env):
        graph, cache = env
        wide = render_report("![[Chart]]", graph, cache,
                             setup=PageSetup(size="A3"))
        narrow = render_report("![[Chart]]", graph, cache,
                               setup=PageSetup(size="A5"))
        assert self.drawn_width(wide) > self.drawn_width(narrow)

    def test_wider_margins_draw_a_smaller_chart(self, env):
        graph, cache = env
        rendered = render_report("![[Chart]]", graph, cache,
                                 setup=PageSetup(margin_left=50.0,
                                                 margin_right=50.0))
        assert self.drawn_width(rendered) \
            == PageSetup(margin_left=50.0, margin_right=50.0
                         ).body_width_points()

    def test_no_setup_keeps_the_a4_default(self, env):
        graph, cache = env
        rendered = render_report("![[Chart]]", graph, cache)
        assert self.drawn_width(rendered) == FIGURE_WIDTH
