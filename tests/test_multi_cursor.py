"""Several carets in the code editor (ui/editor/multi_cursor): added with
Alt+Click, Alt+Shift+Up/Down, Ctrl+D and Ctrl+Shift+L, and every edit made
at all of them at once. Driven with real key and mouse events."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from flograph.ui.editor.code_editor import CodeEditor

SAMPLE = "alpha = 1\nbeta = 2\ngamma = 3"
ALT_SHIFT = Qt.AltModifier | Qt.ShiftModifier


@pytest.fixture
def editor(qtbot):
    widget = CodeEditor()
    qtbot.addWidget(widget)
    widget.resize(500, 300)
    widget.show()
    widget.setPlainText(SAMPLE)
    widget.moveCursor(QTextCursor.Start)
    widget.setFocus()
    return widget


def _carets_down(qtbot, editor, times=2):
    for _ in range(times):
        qtbot.keyClick(editor, Qt.Key_Down, ALT_SHIFT)


class TestAddingCarets:
    def test_alt_shift_down_adds_one_below(self, qtbot, editor):
        _carets_down(qtbot, editor)
        assert len(editor.carets.extras) == 2
        qtbot.keyClicks(editor, "# ")
        assert editor.toPlainText() == "# alpha = 1\n# beta = 2\n# gamma = 3"

    def test_a_keystroke_at_every_caret_is_one_undo_step(self, qtbot, editor):
        _carets_down(qtbot, editor)
        qtbot.keyClick(editor, Qt.Key_X)
        assert editor.toPlainText() == "xalpha = 1\nxbeta = 2\nxgamma = 3"
        editor.undo()
        assert editor.toPlainText() == SAMPLE

    def test_alt_click_adds_and_takes_away(self, qtbot, editor):
        cursor = editor.textCursor()
        cursor.setPosition(len("alpha = 1\nbe"))
        point = editor.cursorRect(cursor).center()
        qtbot.mouseClick(editor.viewport(), Qt.LeftButton, Qt.AltModifier, point)
        assert len(editor.carets.extras) == 1
        qtbot.mouseClick(editor.viewport(), Qt.LeftButton, Qt.AltModifier, point)
        assert editor.carets.extras == []

    def test_a_plain_click_goes_back_to_one(self, qtbot, editor):
        _carets_down(qtbot, editor)
        qtbot.mouseClick(editor.viewport(), Qt.LeftButton, Qt.NoModifier,
                         editor.cursorRect().center())
        assert editor.carets.extras == []

    def test_escape_goes_back_to_one(self, qtbot, editor):
        _carets_down(qtbot, editor)
        qtbot.keyClick(editor, Qt.Key_Escape)
        assert editor.carets.extras == []


class TestOccurrences:
    TEXT = "cost = cost + cost_x\ncost"

    def test_ctrl_d_selects_the_word_then_each_next_one(self, qtbot, editor):
        editor.setPlainText(self.TEXT)
        editor.moveCursor(QTextCursor.Start)
        qtbot.keyClick(editor, Qt.Key_D, Qt.ControlModifier)
        assert editor.textCursor().selectedText() == "cost"
        assert editor.carets.extras == []
        qtbot.keyClick(editor, Qt.Key_D, Qt.ControlModifier)
        qtbot.keyClick(editor, Qt.Key_D, Qt.ControlModifier)
        # whole words: cost_x is a different name
        assert len(editor.carets.extras) == 2
        qtbot.keyClicks(editor, "price")
        assert editor.toPlainText() == "price = price + cost_x\nprice"

    def test_ctrl_shift_l_selects_every_one(self, qtbot, editor):
        editor.setPlainText(self.TEXT)
        editor.moveCursor(QTextCursor.Start)
        qtbot.keyClick(editor, Qt.Key_L, Qt.ControlModifier | Qt.ShiftModifier)
        qtbot.keyClick(editor, Qt.Key_L, Qt.ControlModifier | Qt.ShiftModifier)
        assert len(editor.carets.extras) == 2
        qtbot.keyClicks(editor, "c")
        assert editor.toPlainText() == "c = c + cost_x\nc"


class TestEditingAtEveryCaret:
    def test_end_then_type(self, qtbot, editor):
        _carets_down(qtbot, editor)
        qtbot.keyClick(editor, Qt.Key_End)
        qtbot.keyClick(editor, Qt.Key_Semicolon)
        assert editor.toPlainText() == "alpha = 1;\nbeta = 2;\ngamma = 3;"

    def test_backspace(self, qtbot, editor):
        _carets_down(qtbot, editor)
        qtbot.keyClick(editor, Qt.Key_End)
        qtbot.keyClick(editor, Qt.Key_Backspace)
        assert editor.toPlainText() == "alpha = \nbeta = \ngamma = "

    def test_shift_end_selects_and_typing_replaces(self, qtbot, editor):
        _carets_down(qtbot, editor)
        qtbot.keyClick(editor, Qt.Key_End, Qt.ShiftModifier)
        qtbot.keyClick(editor, Qt.Key_Z)
        assert editor.toPlainText() == "z\nz\nz"

    def test_paste_one_line_to_each_caret(self, qtbot, editor):
        _carets_down(qtbot, editor)
        qtbot.keyClick(editor, Qt.Key_End)
        QApplication.clipboard().setText("1\n2\n3")
        qtbot.keyClick(editor, Qt.Key_V, Qt.ControlModifier)
        assert editor.toPlainText() == "alpha = 11\nbeta = 22\ngamma = 33"

    def test_copy_takes_every_selection(self, qtbot, editor):
        _carets_down(qtbot, editor)
        qtbot.keyClick(editor, Qt.Key_End, Qt.ShiftModifier)
        qtbot.keyClick(editor, Qt.Key_C, Qt.ControlModifier)
        assert QApplication.clipboard().text() == SAMPLE
