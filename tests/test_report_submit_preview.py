"""A report page's preview can wait to be asked (Live off).

On a very large page every keystroke re-rendered the preview. With Live
off the preview waits: Update preview or Ctrl+Enter renders what has been
written; the flow running still refreshes it; the choice is saved with
the page.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, Page
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.ui.report.layout_job import wait_idle


@pytest.fixture
def env(qtbot, registry):
    from flograph.engine import ExecutionEngine
    from flograph.ui.report import ReportPage
    graph = Graph()
    graph.add_page(Page(id="p1", title="R", kind="report", body="# Report\n"))
    engine = ExecutionEngine(graph)
    stack = QUndoStack()
    page = ReportPage(graph, engine, stack, "p1")
    qtbot.addWidget(page)
    page.resize(900, 600)
    page.show()
    qtbot.waitUntil(lambda: not page.preview_busy(), timeout=20000)
    yield page, graph, stack
    page.dispose()
    wait_idle()


def type_into(qtbot, editor, text):
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    qtbot.keyClicks(editor, text)


def renders(page):
    """How many renders have been asked for so far."""
    return page._wanted


def test_a_page_is_live_to_begin_with(env, qtbot):
    page, graph, _ = env
    assert graph.page("p1").preview_live is True
    assert page._live_btn.isChecked() and not page._update_btn.isVisible()
    before = renders(page)
    type_into(qtbot, page.editor, " live")
    qtbot.waitUntil(lambda: renders(page) > before, timeout=3000)


def test_off_typing_waits_until_asked(env, qtbot):
    page, graph, _ = env
    page._live_btn.setChecked(False)
    assert graph.page("p1").preview_live is False
    assert page._update_btn.isVisible() and not page._update_btn.isEnabled()
    before = renders(page)
    type_into(qtbot, page.editor, " waiting")
    qtbot.wait(900)                 # well past the typing pause
    assert renders(page) == before
    assert graph.page("p1").body.endswith(" waiting")   # the text is saved
    assert page._update_btn.isEnabled()
    # Ctrl+Enter in the editor renders what was written
    qtbot.keyClick(page.editor, Qt.Key_Return, Qt.ControlModifier)
    assert renders(page) == before + 1
    assert not page._update_btn.isEnabled()
    assert graph.page("p1").body.endswith(" waiting")   # no newline typed


def test_off_the_css_waits_too(env, qtbot):
    page, _, _ = env
    page._live_btn.setChecked(False)
    before = renders(page)
    type_into(qtbot, page.css_editor, "h1 { color: red; }")
    qtbot.wait(900)
    assert renders(page) == before
    page._update_btn.click()
    assert renders(page) == before + 1


def test_back_to_live_shows_what_was_waiting(env, qtbot):
    page, _, _ = env
    page._live_btn.setChecked(False)
    type_into(qtbot, page.editor, " pending")
    before = renders(page)
    page._live_btn.setChecked(True)
    assert renders(page) == before + 1
    assert not page._update_btn.isVisible()


def test_off_the_flow_running_still_refreshes_it(env, qtbot):
    """Off is about typing. New numbers from a run are what the preview is
    for, so they still show — taking any waiting text with them."""
    page, _, _ = env
    page._live_btn.setChecked(False)
    type_into(qtbot, page.editor, " pending")
    before = renders(page)
    page._schedule_preview()        # what a node finishing calls
    qtbot.waitUntil(lambda: renders(page) > before, timeout=3000)
    assert not page._update_btn.isEnabled()


def test_the_choice_is_one_undo_step_and_the_button_follows(env, qtbot):
    page, graph, stack = env
    page._live_btn.setChecked(False)
    assert stack.undoText() == "preview on request"
    stack.undo()
    assert graph.page("p1").preview_live is True
    assert page._live_btn.isChecked()


def test_saved_only_when_off():
    graph = Graph()
    graph.add_page(Page(id="a", title="A", kind="report"))
    graph.add_page(Page(id="b", title="B", kind="report", preview_live=False))
    data = graph_to_dict(graph)
    pages = {p["id"]: p for p in data["graph"]["pages"]}
    assert "preview_on_submit" not in pages["a"]
    assert pages["b"]["preview_on_submit"] is True
    back = graph_from_dict(data, None)
    assert back.page("a").preview_live is True
    assert back.page("b").preview_live is False
