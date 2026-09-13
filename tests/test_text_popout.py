"""The pop-out editor for multi-line text params: a bigger box than the
cramped one in Properties, editing a copy that OK writes back."""
import pytest
from PySide6.QtWidgets import QDialog, QPlainTextEdit, QToolButton

from flograph.ui.properties.text_popout import TextPopOut
from tests.test_column_picker_ux import INSERTER, _panel_for
from tests.test_column_picker_ux import table  # noqa: F401  (fixture)


def _drive(monkeypatch, edit=None, accept=True):
    """Stand in for the modal exec: do `edit` to the open dialog, then close
    it with OK or Cancel."""
    seen = {}

    def fake_exec(self):
        seen["dialog"] = self
        if edit is not None:
            edit(self)
        return QDialog.Accepted if accept else QDialog.Rejected

    monkeypatch.setattr(TextPopOut, "exec", fake_exec)
    return seen


@pytest.fixture
def panel(qtbot, table):  # noqa: F811
    return _panel_for(qtbot, INSERTER, table)


def _open(panel, name):
    panel.findChild(QToolButton, f"param_{name}_popout").click()


class TestTextPopOut:
    def test_every_multiline_box_has_one(self, panel):
        panel, _graph, _node = panel
        for name in ("mapping", "renames", "plain"):
            assert panel.findChild(QToolButton, f"param_{name}_popout"), name

    def test_it_stacks_under_the_column_picker(self, panel):
        """One button's width beside the box, not two."""
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QApplication

        panel, _graph, _node = panel
        panel.resize(380, 600)
        panel.show()
        QApplication.processEvents()
        pick = panel.findChild(QToolButton, "param_renames_columns")
        pop = panel.findChild(QToolButton, "param_renames_popout")
        at_pick = pick.mapTo(panel, QPoint(0, 0))
        at_pop = pop.mapTo(panel, QPoint(0, 0))
        assert at_pop.x() == at_pick.x()
        assert at_pop.y() >= at_pick.y() + pick.height()
        assert pop.width() == pick.width()

    def test_the_box_keeps_its_height(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_plain")
        assert text.parentWidget().maximumHeight() == text.maximumHeight()

    def test_ok_writes_the_text_back_as_one_step(self, panel, monkeypatch):
        panel, graph, node = panel
        _drive(monkeypatch, lambda d: d.editor.setPlainText("a = b\nc = d"))
        _open(panel, "plain")
        assert graph.node(node.id).params["plain"] == "a = b\nc = d"
        box = panel.findChild(QPlainTextEdit, "param_plain")
        assert box.toPlainText() == "a = b\nc = d"
        panel._undo_stack.undo()
        assert graph.node(node.id).params["plain"] == ""

    def test_cancel_leaves_the_param_alone(self, panel, monkeypatch):
        panel, graph, node = panel
        _drive(monkeypatch, lambda d: d.editor.setPlainText("thrown away"),
               accept=False)
        _open(panel, "plain")
        assert graph.node(node.id).params["plain"] == ""
        assert panel.findChild(QPlainTextEdit,
                               "param_plain").toPlainText() == ""

    def test_it_opens_on_the_box_as_typed(self, panel, monkeypatch):
        panel, _graph, _node = panel
        # typed but not yet settled by the idle timer
        panel.findChild(QPlainTextEdit, "param_plain").setPlainText("typed")
        seen = _drive(monkeypatch, accept=False)
        _open(panel, "plain")
        assert seen["dialog"].editor.toPlainText() == "typed"
        assert "Renamer" in seen["dialog"].windowTitle()

    def test_the_column_picker_comes_along_and_waits_for_ok(
            self, panel, monkeypatch):
        panel, graph, node = panel

        def pick(dialog):
            menu = dialog.findChild(QToolButton, "popout_columns").menu()
            menu.aboutToShow.emit()
            next(a for a in menu.actions() if a.text() == "revenue").trigger()

        seen = _drive(monkeypatch, pick, accept=False)
        _open(panel, "renames")
        assert seen["dialog"].editor.toPlainText() == "revenue = "
        assert graph.node(node.id).params["renames"] == ""

    def test_a_plain_box_gets_no_picker(self, panel, monkeypatch):
        panel, _graph, _node = panel
        seen = _drive(monkeypatch, accept=False)
        _open(panel, "plain")
        assert seen["dialog"].findChild(QToolButton, "popout_columns") is None


CONDITIONAL = ("flograph.transform.conditional_column", "rules")


def _offered_by(completer):
    model = completer._completer.completionModel()
    return [model.index(i, 0).data() for i in range(model.rowCount())]


class TestCompletionInTheBox:
    """The pop-out's completion in the Properties box itself, where the box
    has words or columns to offer."""

    def test_a_box_with_a_column_picker_completes_columns(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_mapping")
        text.insertPlainText("reg")
        text.completer.show(force=True)
        assert _offered_by(text.completer) == ["region"]
        text.completer._insert("region")
        assert text.toPlainText() == "region"

    def test_columns_are_asked_for_when_it_opens(self, panel):
        """A run after the panel was built changes what arrives."""
        import pandas as pd

        panel, graph, node = panel
        text = panel.findChild(QPlainTextEdit, "param_mapping")
        source = next(n for n in graph.nodes if n != node.id)
        panel._cache.set(source, {"table": pd.DataFrame({"margin": [1]})}, 0.0)
        text.insertPlainText("mar")
        text.completer.show(force=True)
        assert _offered_by(text.completer) == ["margin"]

    def test_a_free_text_box_gets_none(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_plain")
        assert getattr(text, "completer", None) is None

    def test_a_rules_box_completes_its_own_words(self, qtbot, registry):
        from PySide6.QtGui import QUndoStack

        from flograph.core import Graph
        from flograph.ui.properties.params_panel import ParamsPanel

        graph = Graph()
        node = graph.add_node(registry.instantiate(CONDITIONAL[0]))
        panel = ParamsPanel(graph, QUndoStack())
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        text = panel.findChild(QPlainTextEdit, "param_rules")
        text.insertPlainText("score > 1 an")
        text.completer.show(force=True)
        assert "and" in _offered_by(text.completer)


class TestLintInTheBox:
    """The pop-out's lint in the Properties box: the same wavy underlines,
    and the problems listed on the box's tooltip."""

    @staticmethod
    def _box(qtbot, registry, rules):
        from PySide6.QtGui import QUndoStack

        from flograph.core import Graph
        from flograph.ui.properties.params_panel import ParamsPanel

        graph = Graph()
        node = graph.add_node(registry.instantiate(CONDITIONAL[0]))
        graph.set_param(node.id, "rules", rules)
        panel = ParamsPanel(graph, QUndoStack())
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        return panel.findChild(QPlainTextEdit, "param_rules")

    @staticmethod
    def _underlined(text):
        from PySide6.QtGui import QTextCharFormat
        return [sel.cursor.blockNumber() + 1 for sel in text.extraSelections()
                if sel.format.underlineStyle() == QTextCharFormat.WaveUnderline]

    @staticmethod
    def _row(text):
        from flograph.ui.properties.params_panel import ParamsPanel

        panel = text.parentWidget()
        while not isinstance(panel, ParamsPanel):
            panel = panel.parentWidget()
        tree = panel.tree
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            host = tree.itemWidget(item, 1)
            if host is not None and (host is text or host.isAncestorOf(text)):
                return item
        return None

    def test_a_bad_line_is_marked_as_the_box_appears(self, qtbot, registry):
        from flograph.ui.editor.diagnostics import DIAGNOSTIC_COLORS

        text = self._box(qtbot, registry, "score > 1 => a\nscore north => b")
        assert [d.line for d in text.diagnostics] == [2]
        assert self._underlined(text) == [2]
        assert "line 2" in text.toolTip()
        # and the row's name, where it can't be missed
        qtbot.waitUntil(lambda: self._row(text).foreground(0).color()
                        == DIAGNOSTIC_COLORS["error"])
        assert "line 2" in self._row(text).toolTip(0)
        assert not self._row(text).icon(0).isNull()

    def test_fixing_the_line_clears_the_mark(self, qtbot, registry):
        from flograph.ui.editor.diagnostics import DIAGNOSTIC_COLORS

        text = self._box(qtbot, registry, "score north => b")
        qtbot.waitUntil(lambda: not self._row(text).icon(0).isNull())
        text.setPlainText("score > 1 => b")
        text.run_lint()
        assert text.diagnostics == []
        assert self._underlined(text) == []
        assert "line" not in text.toolTip()
        row = self._row(text)
        assert row.foreground(0).color() != DIAGNOSTIC_COLORS["error"]
        assert row.icon(0).isNull()
        assert "line" not in row.toolTip(0)

    def test_a_box_with_nothing_to_check_has_no_lint(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_mapping")
        assert getattr(text, "run_lint", None) is None


class TestTheEditorInside:
    """The pop-out as a code editor: lint, find, completion, closing."""

    @staticmethod
    def _dialog(qtbot, text="", **kwargs):
        dialog = TextPopOut("Node — Rules", text, **kwargs)
        # closed with done() at teardown: a plain close() is Esc, which asks
        # before throwing edits away — a modal nobody is there to answer
        qtbot.addWidget(dialog,
                        before_close_func=lambda d: d.done(QDialog.Rejected))
        return dialog

    def test_the_lint_marks_a_bad_line_and_says_why(self, qtbot):
        from flograph.core.text_assist import assist_for

        dialog = self._dialog(qtbot, "score > 1 => a\nscore north => b",
                              assist=assist_for(*CONDITIONAL))
        assert [d.line for d in dialog.editor._diagnostics] == [2]
        assert "line 2" in dialog.status.text()
        assert dialog.editor.diagnostic_at(2) is not None
        dialog.editor.setPlainText("score > 1 => a")
        dialog.run_lint()
        assert dialog.editor._diagnostics == []
        assert "No problems" in dialog.status.text()

    def test_a_box_with_no_lint_says_nothing(self, qtbot):
        assert self._dialog(qtbot, "anything").status.text() == ""

    def test_escape_shuts_the_find_bar_before_the_window(self, qtbot):
        dialog = self._dialog(qtbot, "abc")
        dialog.show()
        dialog.find_bar.open_bar()
        dialog.reject()
        assert dialog.find_bar.isHidden()
        assert dialog.isVisible()

    def test_escape_with_edits_asks_first(self, qtbot, monkeypatch):
        from PySide6.QtWidgets import QMessageBox

        from flograph.ui.properties import text_popout

        dialog = self._dialog(qtbot, "abc")
        dialog.show()
        dialog.editor.setPlainText("changed")
        answers = [QMessageBox.Cancel, QMessageBox.Discard]
        monkeypatch.setattr(text_popout.QMessageBox, "question",
                            lambda *args, **kwargs: answers.pop(0))
        dialog.reject()
        assert dialog.isVisible()
        dialog.reject()
        assert not dialog.isVisible()

    def test_unchanged_text_closes_without_asking(self, qtbot, monkeypatch):
        from flograph.ui.properties import text_popout

        def ask(*args, **kwargs):
            raise AssertionError("asked about unchanged text")

        monkeypatch.setattr(text_popout.QMessageBox, "question", ask)
        dialog = self._dialog(qtbot, "abc")
        dialog.show()
        dialog.reject()
        assert not dialog.isVisible()

    @staticmethod
    def _offered(dialog):
        model = dialog.completer._completer.completionModel()
        return [model.index(i, 0).data() for i in range(model.rowCount())]

    def test_completion_offers_columns_then_keywords(self, qtbot):
        from flograph.core.text_assist import assist_for

        dialog = self._dialog(qtbot, "", assist=assist_for(*CONDITIONAL),
                              columns=["unit price", "units", "region"])
        dialog.show()
        dialog.editor.insertPlainText("region = n and un")
        dialog.completer.show(force=True)
        assert self._offered(dialog) == ["unit price", "units"]
        dialog.completer._insert("unit price")
        assert dialog.editor.toPlainText() == "region = n and unit price"
        dialog.editor.insertPlainText(" > 5 o")
        dialog.completer.show(force=True)
        assert "or" in self._offered(dialog)

    def test_a_rules_box_quotes_the_column_it_completes(self, qtbot):
        from flograph.core.text_assist import assist_for

        dialog = self._dialog(
            qtbot, "", columns=["unit price"],
            assist=assist_for("flograph.viz.show_table", "rules", True))
        dialog.show()
        dialog.editor.insertPlainText("uni")
        dialog.completer.show(force=True)
        dialog.completer._insert("unit price")
        assert dialog.editor.toPlainText() == '"unit price"'

    def test_inside_a_backtick_the_name_is_finished_and_closed(self, qtbot):
        from flograph.core.text_assist import assist_for

        dialog = self._dialog(qtbot, "", columns=["price($)"],
                              assist=assist_for(*CONDITIONAL))
        dialog.show()
        dialog.editor.insertPlainText("`pri")
        dialog.completer.show(force=True)
        dialog.completer._insert("price($)")
        assert dialog.editor.toPlainText() == "`price($)`"

    def test_a_column_is_highlighted_as_one(self, qtbot):
        from flograph.ui.editor.rules_highlighter import COLUMN

        dialog = self._dialog(qtbot, "unit price > 5", columns=["unit price"])
        dialog.show()
        block = dialog.editor.document().firstBlock()
        spans = [(r.start, r.length) for r in block.layout().formats()
                 if r.format.foreground().color() == COLUMN.foreground().color()]
        assert (0, len("unit price")) in spans
