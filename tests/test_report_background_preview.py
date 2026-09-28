"""A report page's preview is laid out off the UI thread.

With a big table on the page a re-render was most of a second of rich-text
layout, and it ran every time typing paused — so the editor froze between
words and the keys typed meanwhile arrived in a burst. The embeds still
resolve on the UI thread; the layout after them is done in the background,
and the preview is swapped in when it is ready, under a thin loading bar.
"""
import threading
import time

import pandas as pd
import pytest
from PySide6.QtCore import QRunnable, QThreadPool
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, Page
from flograph.core.page_setup import PageSetup
from flograph.ui.report.layout_job import wait_idle
from flograph.ui.report.preview import paginate, paginate_in_background
from flograph.ui.report.render import finish_body, render_body, stage_report


def big_table(rows=400):
    return pd.DataFrame({
        "Product": [f"Item {i}" for i in range(rows)],
        "Region": ["North", "South", "East", "West"] * (rows // 4),
        "Sales": list(range(rows)),
    })


@pytest.fixture
def env(qtbot, registry):
    from flograph.engine import ExecutionEngine
    from flograph.ui.report import ReportPage
    graph = Graph()
    node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
    graph.set_label(node.id, "Big")
    engine = ExecutionEngine(graph)
    frame = big_table()
    engine.cache.set(node.id, {"table": frame, "style": None,
                               "filtered": frame}, 0.0)
    graph.add_page(Page(id="p1", title="R", kind="report",
                        body="# Report\n\n![[Big|rows=400]]\n"))
    stack = QUndoStack()
    page = ReportPage(graph, engine, stack, "p1")
    qtbot.addWidget(page)
    page.resize(1000, 700)
    page.show()
    yield page, graph, engine
    page.dispose()
    wait_idle()


def settle(qtbot, page):
    qtbot.waitUntil(lambda: not page.preview_busy(), timeout=20000)
    wait_idle()


def shown_text(page):
    return page.preview.document().toPlainText()


class TestTheSamePages:

    def test_the_background_road_lays_out_the_same_pages(self, qapp):
        """paginate_in_background goes by way of print_, for the lock it
        lets go of — it must land on exactly the layout paginate does."""
        body = "# T\n\n" + "\n\n".join(f"Paragraph {i} " * 30
                                        for i in range(60))
        setup = PageSetup()
        plain = render_body(body, lambda r, p: (None, "", None)).document
        printed = render_body(body, lambda r, p: (None, "", None)).document
        assert paginate(plain, setup) == paginate_in_background(printed,
                                                                setup) > 3
        layout_a, layout_b = plain.documentLayout(), printed.documentLayout()
        a, b = plain.begin(), printed.begin()
        while a.isValid():
            assert layout_a.blockBoundingRect(a) == layout_b.blockBoundingRect(b)
            a, b = a.next(), b.next()

    def test_it_runs_on_a_thread_of_its_own(self, qapp, env):
        """And the UI thread can run Python while it does — which is the
        whole point: every key typed goes through a Python slot."""
        page, graph, engine = env
        staged = stage_report(graph.pages["p1"].body, graph, engine.cache,
                              setup=PageSetup())
        done = threading.Event()
        pages = []

        class Job(QRunnable):
            def run(self):
                rendered = finish_body(staged)
                pages.append(paginate_in_background(rendered.document,
                                                    PageSetup()))
                done.set()

        pool = QThreadPool()
        pool.start(Job())
        spins = 0
        while not done.is_set():
            spins += 1
            time.sleep(0.001)
        pool.waitForDone()
        assert pages[0] > 1
        assert spins > 3


class TestTyping:

    def test_typing_shows_the_bar_and_the_preview_catches_up(
            self, qtbot, env):
        page, graph, _engine = env
        settle(qtbot, page)
        assert not page._busy_bar.isVisible()
        page.editor.appendPlainText("\nA new closing line")
        assert page._busy_bar.isVisible()
        settle(qtbot, page)
        assert "A new closing line" in shown_text(page)
        assert "Item 399" in shown_text(page)
        assert not page._busy_bar.isVisible()
        assert page.preview.page_count() > 1

    def test_the_editor_is_never_behind_the_model(self, qtbot, env):
        """Typing reaches the page at once; only the preview waits."""
        page, graph, _engine = env
        page.editor.appendPlainText("more")
        assert graph.pages["p1"].body.endswith("more")

    def test_only_the_newest_text_is_shown(self, qtbot, env):
        page, graph, _engine = env
        settle(qtbot, page)
        page.request_preview()          # a layout of the old text starts
        page.editor.setPlainText("# Replaced\n\nOnly this.")
        page.request_preview()          # asked again while it runs
        settle(qtbot, page)
        assert "Only this." in shown_text(page)
        assert "Item 1" not in shown_text(page)

    def test_a_synchronous_refresh_overtakes_one_in_flight(self, qtbot, env):
        page, graph, _engine = env
        settle(qtbot, page)
        page.request_preview()
        graph.set_page_body("p1", "# Now\n\nsync")
        page.refresh_preview()
        assert "sync" in shown_text(page)
        settle(qtbot, page)
        assert "sync" in shown_text(page)
        assert not page._busy_bar.isVisible()

    def test_the_web_preview_is_built_in_the_background_too(
            self, qtbot, env, monkeypatch):
        page, graph, _engine = env
        written = []
        monkeypatch.setattr(page.web_preview, "set_html", written.append)
        page._set_preview_mode("web")
        page.request_preview()
        settle(qtbot, page)
        assert written and "Item 399" in written[-1]

    def test_a_table_measured_against_the_page_is_laid_out_here(
            self, qtbot, env):
        """`height=` and `fit` rebuild a table once it has been measured,
        and a rebuilt table paints through the card's pixmap cache — which
        only the UI thread may touch. Such a page is finished here."""
        page, graph, engine = env
        staged = stage_report("![[Big|height=200]]", graph, engine.cache,
                              setup=PageSetup())
        assert not staged.finishes_anywhere
        assert stage_report("![[Big]]", graph, engine.cache,
                            setup=PageSetup()).finishes_anywhere
        graph.set_page_body("p1", "![[Big|height=200]]")
        page.request_preview()
        assert page._layout_job is None       # done already, on this thread
        settle(qtbot, page)
        assert "Item 1" in shown_text(page)

    def test_a_closed_page_drops_its_layout(self, qtbot, env):
        page, _graph, _engine = env
        page.request_preview()
        page.dispose()
        wait_idle()
        qtbot.wait(50)                  # the queued result arrives, harmlessly


class TestTheThreadOutlivesItsDocument:
    """A laid-out document draws with the fonts of the thread that laid it
    out, and Qt frees a thread's fonts when the thread ends. A pooled
    thread retiring while its document was still on screen crashed the
    next repaint — so each layout's thread waits for its document."""

    def test_the_thread_is_kept_while_its_document_is_shown(
            self, qtbot, env):
        from flograph.ui.report import layout_job
        page, graph, _engine = env
        page.request_preview()
        job = page._layout_job
        settle(qtbot, page)
        assert job._thread.is_alive()           # parked, fonts intact
        page.preview.viewport().repaint()        # and drawing is safe
        # replaced by a document made here: the old one goes, and its
        # thread with it
        page.refresh_preview()
        qtbot.waitUntil(lambda: not job._thread.is_alive(), timeout=5000)
        assert id(job) not in layout_job._LIVE

    def test_a_dropped_layout_lets_its_thread_go(self, qtbot, env):
        page, graph, _engine = env
        page.request_preview()
        job = page._layout_job
        page.refresh_preview()          # overtakes it: its result is stale
        qtbot.waitUntil(lambda: not job._thread.is_alive(), timeout=10000)
