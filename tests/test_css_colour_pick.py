"""The CSS tab's colour picker: which text is a colour (core/css_colour.py),
how a picked colour is written back, and the editor gestures that open it
(ui/report/css_colour_pick.py)."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QUndoStack

from flograph.core import Graph, Page
from flograph.core.css_colour import colour_at, parse, write_like

CSS = """/* red note */
a:hover #add { color: #add; border: 1px solid red; }
.fg-red { background: rgba(14, 90, 97, 0.07); fill: hsl(120 50% 40% / .5); }
:root { --ink: #1D1B16; --chart-colors: #e30613, black; }"""


def at(word, inside=1):
    return colour_at(CSS, CSS.index(word) + inside)


class TestWhatIsAColour:
    def test_a_hex_in_a_value(self):
        assert at("#add;").text == "#add"
        assert at("#add;").rgba == (170, 221, 221, 255)

    def test_not_an_id_selector(self):
        assert at("#add {") is None

    def test_a_named_colour_in_a_value_but_not_in_a_class(self):
        assert at("red;", 0).text == "red"
        assert at(".fg-red", 4) is None

    def test_not_inside_a_comment(self):
        assert at("red note", 0) is None

    def test_functions_whole(self):
        assert at("rgba(").text == "rgba(14, 90, 97, 0.07)"
        assert at("hsl(", 6).rgba == (51, 153, 51, 128)

    def test_custom_properties_and_lists(self):
        assert at("#1D1B16").rgba == (29, 27, 22, 255)
        assert at("black;", 0).text == "black"

    def test_either_end_of_the_token_counts(self):
        start = CSS.index("#e30613")
        assert colour_at(CSS, start).text == "#e30613"
        assert colour_at(CSS, start + 7).text == "#e30613"

    def test_words_that_are_not_colours(self):
        assert at("solid", 2) is None
        assert parse("bold") is None and parse("#zzz") is None

    @pytest.mark.parametrize("token, rgba", [
        ("#abc", (170, 187, 204, 255)), ("#abcd", (170, 187, 204, 221)),
        ("#11223380", (17, 34, 51, 128)),
        ("rgb(100% 0% 0% / 50%)", (255, 0, 0, 128)),
        ("hsla(240, 100%, 50%, 0.5)", (0, 0, 255, 128)),
        ("RebeccaPurple", (102, 51, 153, 255)),
    ])
    def test_parse(self, token, rgba):
        assert parse(token) == rgba


class TestWrittenTheWayItWas:
    @pytest.mark.parametrize("token, rgba, out", [
        ("#1D1B16", (255, 0, 0, 255), "#FF0000"),
        ("#abc", (1, 2, 3, 128), "#01020380"),
        ("rgba(1, 2, 3, .5)", (10, 20, 30, 255), "rgb(10, 20, 30)"),
        ("rgb(1, 2, 3)", (10, 20, 30, 128), "rgba(10, 20, 30, 0.5)"),
        ("rgb(1 2 3)", (10, 20, 30, 128), "rgb(10 20 30 / 0.5)"),
        ("hsl(120, 50%, 40%)", (255, 0, 0, 255), "hsl(0, 100%, 50%)"),
        ("red", (0, 0, 255, 255), "#0000ff"),
    ])
    def test_write_like(self, token, rgba, out):
        assert write_like(token, rgba) == out

    @pytest.mark.parametrize("token", ["#e30613", "rgba(14, 90, 97, 0.5)",
                                       "rgb(14 90 97 / 0.5)"])
    def test_round_trip(self, token):
        assert parse(write_like(token, parse(token))) == parse(token)


class TestInTheCssTab:
    @pytest.fixture
    def page(self, qtbot, registry):
        from flograph.engine import ExecutionEngine
        from flograph.ui.report import ReportPage
        graph = Graph()
        graph.add_page(Page(id="p1", title="Q3", kind="report"))
        stack = QUndoStack()
        page = ReportPage(graph, ExecutionEngine(graph), stack, "p1")
        qtbot.addWidget(page)
        page.resize(900, 600)
        page.show()
        page._editor_tabs.setCurrentWidget(page.css_editor.parentWidget())
        page.css_editor.setPlainText("body { color: #112233; }")
        yield page, graph, stack
        page.dispose()

    def point_on(self, page, word):
        from PySide6.QtGui import QTextCursor
        cursor = QTextCursor(page.css_editor.document())
        cursor.setPosition(page.css_editor.toPlainText().index(word) + 2)
        return page.css_editor.cursorRect(cursor).center()

    def test_picking_rewrites_the_colour_in_one_undo_step(self, page,
                                                          monkeypatch):
        page, graph, stack = page
        picker = page._css_picker
        monkeypatch.setattr(picker, "_ask", lambda start: QColor(255, 0, 0))
        found = picker.colour_under(self.point_on(page, "#112233"))
        assert found.text == "#112233"
        assert picker.pick(found)
        assert graph.pages["p1"].custom_css == "body { color: #ff0000; }"
        stack.undo()
        assert graph.pages["p1"].custom_css == "body { color: #112233; }"

    def test_cancelling_changes_nothing(self, page, monkeypatch):
        page, graph, _stack = page
        picker = page._css_picker
        monkeypatch.setattr(picker, "_ask", lambda start: None)
        assert not picker.pick(picker.colour_under(self.point_on(page, "#11")))
        assert graph.pages["p1"].custom_css == "body { color: #112233; }"

    def test_the_menu_offers_it_on_a_colour_only(self, page):
        page = page[0]
        picker = page._css_picker
        on = picker.menu_for(self.point_on(page, "#112233"))
        assert on.actions()[0].text() == "Pick Colour…"
        off = picker.menu_for(self.point_on(page, "body"))
        assert "Pick Colour…" not in [a.text() for a in off.actions()]
        on.deleteLater()
        off.deleteLater()

    def test_a_double_click_opens_it(self, page, qtbot, monkeypatch):
        page, graph, _stack = page
        asked = []
        monkeypatch.setattr(page._css_picker, "_ask",
                            lambda start: asked.append(start.name()) or None)
        qtbot.mouseDClick(page.css_editor.viewport(), Qt.LeftButton,
                          pos=self.point_on(page, "#112233"))
        assert asked == ["#112233"]
