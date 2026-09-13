"""Autocomplete in the report editors: what fits at the caret, and the
popup that offers it."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry, Page
from flograph.core.report import EMBED_FLAGS, EMBED_OPTIONS
from flograph.core.report_assist import (
    FLAG_HINTS, OPTION_HINTS, Name, Vocabulary, suggest)


@pytest.fixture
def vocab():
    return Vocabulary(
        names=[Name("Sales Chart", "", ("figure", "table")),
               Name("Sales Table", "", ("table",)),
               Name("Total", "not run yet", ("value",))],
        pages=["Costs", "Sales North"])


def texts(completion):
    return [item.text for item in completion.items]


class TestWhatFits:
    def test_labels_after_an_open_embed(self, vocab):
        done = suggest("See ![[Sa", "", vocab)
        assert texts(done) == ["Sales Chart", "Sales Table"]
        assert done.prefix == "Sa" and done.start == len("See ![[")
        assert done.items[0].close == "]]"

    def test_every_label_on_an_empty_embed(self, vocab):
        assert len(suggest("![[", "", vocab).items) == 3

    def test_contains_matches_after_starts_with(self, vocab):
        assert texts(suggest("![[tab", "", vocab)) == ["Sales Table"]

    def test_no_closing_brackets_when_they_are_already_there(self, vocab):
        assert suggest("![[Sa", "]]", vocab).items[0].close == ""
        assert suggest("![[Sa", "|width=50%]]", vocab).items[0].close == ""

    def test_ports_options_and_flags_after_a_bar(self, vocab):
        offered = texts(suggest("![[Sales Chart|", "]]", vocab))
        assert offered[:2] == ["figure", "table"]
        assert "width=" in offered and "ratio=" in offered and "fit" in offered

    def test_options_already_used_are_not_offered_again(self, vocab):
        offered = texts(suggest("![[Sales Chart|table|width=50%|", "", vocab))
        assert "width=" not in offered
        assert "figure" not in offered   # a port is already named
        assert "fit" in offered

    def test_values_after_an_option_key(self, vocab):
        done = suggest("![[Sales Chart|ratio=16", "]]", vocab)
        assert texts(done) == ["16:9"]
        assert done.start == len("![[Sales Chart|ratio=")

    def test_page_titles_in_a_link_are_url_encoded(self, vocab):
        done = suggest("[north](page:Sales", "", vocab)
        assert texts(done) == ["Sales%20North"]
        assert done.items[0].label == "Sales North"
        assert done.items[0].close == ")"
        # typed the encoded way, still matched
        assert texts(suggest("[n](page:Sales%20N", "", vocab)) == \
            ["Sales%20North"]

    def test_page_titles_in_angle_brackets_stay_as_written(self, vocab):
        assert texts(suggest("<page:sal", "", vocab)) == ["Sales North"]

    def test_columns_fence_waits_for_a_letter(self, vocab):
        done = suggest("```", "", vocab)
        assert texts(done) == ["columns"] and not done.eager
        assert texts(suggest("```co", "", vocab)) == ["columns"]
        assert suggest("```python", "", vocab) is None

    def test_page_break_commands(self, vocab):
        # starts-with first, then contains
        assert texts(suggest("\\p", "", vocab)) == ["pagebreak", "newpage"]
        assert texts(suggest("\\new", "", vocab)) == ["newpage"]

    def test_nothing_in_ordinary_prose(self, vocab):
        assert suggest("Revenue rose 12% on the", "", vocab) is None

    def test_nothing_inside_backticks(self, vocab):
        """`![[Sales]]` in code is a page documenting its own syntax."""
        assert suggest("write `![[Sa", "", vocab) is None

    def test_a_finished_word_offers_nothing(self, vocab):
        assert suggest("![[Sales Chart|fit", "]]", vocab) is None

    def test_every_option_and_flag_has_a_hint(self):
        """The closed option set lives in core.report; a new option must
        arrive with its explanation here, or the list shows it bare."""
        assert set(OPTION_HINTS) == set(EMBED_OPTIONS)
        assert set(FLAG_HINTS) == set(EMBED_FLAGS)


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


class TestVocabulary:
    def test_page_vocabulary_ran_first_duplicates_and_canvas_tabs_out(
            self, registry):
        from flograph.engine.cache import OutputCache
        from flograph.ui.report.completion import page_vocabulary

        graph = Graph()
        cache = OutputCache()
        for label, value in (("Zeta", 1), ("Alpha", None), ("Twin", 1),
                             ("twin", 1)):
            node = graph.add_node(registry.instantiate("flograph.util.constant"))
            graph.set_label(node.id, label)
            if value is not None:
                cache.set(node.id, {"value": value}, 0.0)
        graph.add_page(Page(id="r", title="Report", kind="report"))
        graph.add_page(Page(id="c", title="Model", kind="canvas"))

        vocab = page_vocabulary(graph, cache)
        assert [n.label for n in vocab.names] == ["Zeta", "Alpha"]
        assert vocab.names[1].hint == "not run yet"
        assert vocab.names[0].ports == ("value",)
        assert vocab.pages == ["Report"]


class TestThePopup:

    @pytest.fixture
    def page(self, qtbot, registry):
        from flograph.engine import ExecutionEngine
        from flograph.ui.report import ReportPage

        graph = Graph()
        graph.add_page(Page(id="p1", title="Q3", kind="report"))
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, "Total Sales")
        engine = ExecutionEngine(graph)
        engine.cache.set(node.id, {"value": 42}, 0.0)
        page = ReportPage(graph, engine, QUndoStack(), "p1")
        qtbot.addWidget(page)
        page.show()
        page.editor.setFocus()
        yield page
        page.completer.popup.hide()
        page.dispose()

    def type_(self, qtbot, page, text):
        qtbot.keyClicks(page.editor, text)
        qtbot.wait(20)

    def test_typing_an_embed_opens_the_list_and_enter_takes_it(
            self, qtbot, page):
        self.type_(qtbot, page, "![[tot")
        popup = page.completer.popup
        assert popup.isVisible()
        assert popup.currentIndex().data().startswith("Total Sales")
        qtbot.keyClick(popup, Qt.Key_Return)
        assert page.editor.toPlainText() == "![[Total Sales]]"
        assert not popup.isVisible()

    def test_a_bar_offers_the_options(self, qtbot, page):
        page.editor.setPlainText("![[Total Sales]]")
        cursor = page.editor.textCursor()
        cursor.setPosition(len("![[Total Sales"))
        page.editor.setTextCursor(cursor)
        self.type_(qtbot, page, "|wi")
        assert page.completer.popup.isVisible()
        qtbot.keyClick(page.completer.popup, Qt.Key_Tab)
        assert page.editor.toPlainText() == "![[Total Sales|width=]]"
        # and the values follow straight on
        qtbot.wait(20)
        assert page.completer.popup.isVisible()

    def test_escape_puts_it_away_and_leaves_the_text(self, qtbot, page):
        self.type_(qtbot, page, "![[")
        qtbot.keyClick(page.completer.popup, Qt.Key_Escape)
        assert not page.completer.popup.isVisible()
        assert page.editor.toPlainText() == "![["

    def test_an_undo_does_not_pop_the_list(self, qtbot, page):
        page.editor.clearFocus()
        page.editor.setPlainText("![[")
        qtbot.wait(20)
        assert not page.completer.popup.isVisible()

    def test_ctrl_space_opens_it_for_a_fence(self, qtbot, page):
        self.type_(qtbot, page, "```")
        assert not page.completer.popup.isVisible()
        qtbot.keyClick(page.editor, Qt.Key_Space, Qt.ControlModifier)
        assert page.completer.popup.isVisible()
