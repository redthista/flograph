"""ideas.md items 4 and 17: Ctrl+F find/replace in the code editor, and
lifting an error message out of the footer with one click.

The find bar owns no document state, so these drive it the way a user does
— type in the find box, press Enter, click Replace — rather than calling
QTextDocument.find() and asserting on the result.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor, QUndoStack
from PySide6.QtWidgets import QApplication

from flograph.core import Graph, NodeRegistry
from flograph.engine import NodeError
from flograph.ui.editor.code_editor import CURRENT_MATCH_BG, MATCH_BG, CodeEditor
from flograph.ui.editor.editor_dock import EditorPanel
from flograph.ui.editor.find_bar import FindBar

SAMPLE = "alpha = 1\nbeta = alpha + 2\ngamma = ALPHA\n"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def bar(qtbot):
    """A find bar over an editor holding SAMPLE, cursor at the very top."""
    editor = CodeEditor()
    qtbot.addWidget(editor)
    editor.setPlainText(SAMPLE)
    editor.moveCursor(QTextCursor.Start)
    find = FindBar(editor)
    qtbot.addWidget(find)
    return find, editor


@pytest.fixture
def panel(qtbot, registry):
    graph = Graph()
    widget = EditorPanel(graph, QUndoStack(), registry)
    qtbot.addWidget(widget)
    node = graph.add_node(
        registry.instantiate("flograph.scripting.python_script"))
    widget.set_node(node.id)
    return widget, graph, node


def highlight_backgrounds(editor):
    return [sel.format.background().color()
            for sel in editor.extraSelections()]


class TestFind:
    def test_opening_seeds_from_the_selection(self, bar):
        find, editor = bar
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 5)
        editor.setTextCursor(cursor)
        find.open_bar()
        assert find._find_edit.text() == "alpha"

    def test_typing_jumps_to_the_first_match(self, bar):
        find, editor = bar
        find.open_bar()
        find._find_edit.setText("beta")
        assert editor.textCursor().selectedText() == "beta"

    def test_enter_walks_matches_and_wraps(self, bar):
        find, editor = bar
        find.open_bar()
        find._find_edit.setText("alpha")
        first = editor.textCursor().selectionStart()
        find.find_next()
        second = editor.textCursor().selectionStart()
        assert second > first
        # case-insensitive by default, so ALPHA on line 3 is the third hit
        find.find_next()
        third = editor.textCursor().selectionStart()
        assert third > second
        find.find_next()
        assert editor.textCursor().selectionStart() == first

    def test_shift_enter_walks_backwards(self, bar):
        find, editor = bar
        find.open_bar()
        find._find_edit.setText("alpha")
        find.find_next()
        forward = editor.textCursor().selectionStart()
        find.find_next(backwards=True)
        assert editor.textCursor().selectionStart() < forward

    def test_match_case_narrows_the_hits(self, bar):
        find, _ = bar
        find.open_bar()
        find._find_edit.setText("alpha")
        assert len(find._all_matches()) == 3
        find._case_btn.setChecked(True)
        assert len(find._all_matches()) == 2

    def test_whole_words_narrows_the_hits(self, bar):
        find, editor = bar
        editor.setPlainText("total\nsubtotal\n")
        find.open_bar()
        find._find_edit.setText("total")
        assert len(find._all_matches()) == 2
        find._words_btn.setChecked(True)
        assert len(find._all_matches()) == 1

    def test_count_label_reports_position(self, bar):
        find, _ = bar
        find.open_bar()
        find._find_edit.setText("alpha")
        assert find._count.text() == "1 of 3"
        find.find_next()
        assert find._count.text() == "2 of 3"

    def test_a_missing_needle_says_so(self, bar):
        find, _ = bar
        find.open_bar()
        find._find_edit.setText("nowhere")
        assert find._count.text() == "no matches"
        assert not find.find_next()

    def test_every_match_is_highlighted(self, bar):
        find, editor = bar
        find.open_bar()
        find._find_edit.setText("alpha")
        backgrounds = highlight_backgrounds(editor)
        assert backgrounds.count(MATCH_BG) == 2      # the two not current
        assert backgrounds.count(CURRENT_MATCH_BG) == 1

    def test_closing_clears_the_highlights(self, bar):
        find, editor = bar
        find.open_bar()
        find._find_edit.setText("alpha")
        find.close_bar()
        backgrounds = highlight_backgrounds(editor)
        assert MATCH_BG not in backgrounds
        assert CURRENT_MATCH_BG not in backgrounds

    def test_escape_closes_the_bar(self, qtbot, bar):
        find, _ = bar
        find.open_bar()
        assert not find.isHidden()
        qtbot.keyClick(find, Qt.Key_Escape)
        assert find.isHidden()

    def test_the_error_line_still_shows_under_a_match(self, bar):
        """Search highlights and the error marker share one extra-selection
        list; whichever is applied last must not wipe the other."""
        find, editor = bar
        editor.set_error_line(1)
        find.open_bar()
        find._find_edit.setText("alpha")
        from flograph.ui.editor.code_editor import ERROR_LINE_BG
        assert ERROR_LINE_BG in highlight_backgrounds(editor)
        assert CURRENT_MATCH_BG in highlight_backgrounds(editor)


class TestReplace:
    def test_replace_swaps_the_current_match_only(self, bar):
        find, editor = bar
        find.open_bar(replace=True)
        find._find_edit.setText("alpha")
        find._replace_edit.setText("omega")
        find.replace_current()
        assert editor.toPlainText().startswith("omega = 1")
        assert "beta = alpha + 2" in editor.toPlainText()

    def test_replace_all_swaps_every_match(self, bar):
        find, editor = bar
        find.open_bar(replace=True)
        find._find_edit.setText("alpha")
        find._replace_edit.setText("omega")
        find.replace_all()
        assert "alpha" not in editor.toPlainText().lower()
        assert editor.toPlainText().count("omega") == 3

    def test_replace_all_is_one_undo_step(self, bar):
        find, editor = bar
        before = editor.toPlainText()
        find.open_bar(replace=True)
        find._find_edit.setText("alpha")
        find._replace_edit.setText("omega")
        find.replace_all()
        editor.undo()
        assert editor.toPlainText() == before

    def test_replace_fields_are_hidden_in_plain_find(self, bar):
        find, _ = bar
        find.open_bar()
        assert find._replace_edit.isHidden()
        find.open_bar(replace=True)
        assert not find._replace_edit.isHidden()


class TestEditorPanelWiring:
    def _shortcut(self, widget, keys):
        """QTest.keyClick delivers straight to the widget and never reaches
        the shortcut map, so the binding is looked up and fired instead."""
        from PySide6.QtGui import QKeySequence, QShortcut
        wanted = QKeySequence(keys)
        return next(s for s in widget.findChildren(QShortcut)
                    if s.key() == wanted)

    def test_ctrl_f_opens_the_bar(self, panel):
        widget, _, _ = panel
        assert widget.find_bar.isHidden()
        self._shortcut(widget, "Ctrl+F").activated.emit()
        assert not widget.find_bar.isHidden()
        assert widget.find_bar._replace_edit.isHidden()

    def test_ctrl_h_opens_the_bar_with_replace(self, panel):
        widget, _, _ = panel
        self._shortcut(widget, "Ctrl+H").activated.emit()
        assert not widget.find_bar.isHidden()
        assert not widget.find_bar._replace_edit.isHidden()

    def test_the_shortcuts_are_scoped_to_this_panel(self, panel):
        """Panel-scoped, not application-wide: Ctrl+F on the canvas or in a
        spreadsheet must not be swallowed by an open Code panel."""
        widget, _, _ = panel
        assert self._shortcut(widget, "Ctrl+F").context() \
            == Qt.WidgetWithChildrenShortcut

    def test_f3_with_the_bar_shut_opens_it_rather_than_searching_blind(
            self, panel):
        widget, _, _ = panel
        widget._find_again()
        assert not widget.find_bar.isHidden()

    def test_switching_node_closes_the_bar(self, panel, registry):
        widget, graph, _ = panel
        widget.find_bar.open_bar()
        widget.find_bar._find_edit.setText("def")
        other = graph.add_node(
            registry.instantiate("flograph.scripting.python_script"))
        widget.set_node(other.id)
        assert widget.find_bar.isHidden()
        assert not widget.editor.extraSelections() or \
            MATCH_BG not in highlight_backgrounds(widget.editor)


class TestErrorCopy:
    def _fail(self, widget, node_id, message="boom", tb=""):
        widget.on_node_failed(
            node_id, NodeError(node_id=node_id, message=message,
                               exc_type="ValueError", formatted_tb=tb,
                               script_line=None))

    def test_clicking_an_error_copies_it(self, panel):
        widget, _, node = panel
        QApplication.clipboard().setText("")
        self._fail(widget, node.id, "ValueError: bad column")
        widget._message.clicked.emit()
        assert QApplication.clipboard().text() == "ValueError: bad column"

    def test_the_traceback_is_preferred_over_the_one_liner(self, panel):
        widget, _, node = panel
        self._fail(widget, node.id, "boom",
                   tb="Traceback (most recent call last):\n  ...\nboom")
        widget._message.clicked.emit()
        assert QApplication.clipboard().text().startswith("Traceback")

    def test_the_label_confirms_then_restores_the_error(self, qtbot, panel):
        widget, _, node = panel
        self._fail(widget, node.id, "ValueError: bad column")
        widget._message.clicked.emit()
        assert widget._message.text() == "Copied to clipboard."
        qtbot.waitUntil(
            lambda: widget._message.text() == "ValueError: bad column",
            timeout=3000)

    def test_a_non_error_message_is_not_copyable(self, panel):
        widget, _, _ = panel
        QApplication.clipboard().setText("untouched")
        widget._show_message("Applied.")
        assert widget._message.cursor().shape() == Qt.ArrowCursor
        widget._message.clicked.emit()
        assert QApplication.clipboard().text() == "untouched"

    def test_an_error_advertises_itself_as_clickable(self, panel):
        widget, _, node = panel
        self._fail(widget, node.id, "boom")
        assert widget._message.cursor().shape() == Qt.PointingHandCursor
        assert "click to copy" in widget._message.toolTip().lower()

    def test_a_new_message_wins_over_a_pending_restore(self, panel):
        """The restore is on a timer; a success arriving first must not be
        clobbered by the error being put back a moment later."""
        widget, _, node = panel
        self._fail(widget, node.id, "boom")
        widget._message.clicked.emit()
        widget._show_message("")
        widget._restore_after_copy()
        assert widget._message.text() == ""
