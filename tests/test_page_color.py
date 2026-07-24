"""Per-page tab colours: the core field, the undo command, the tab bar's
tinted painting, and the round trip through MainWindow."""
import pytest
from PySide6.QtGui import QColor, QUndoStack

from flograph.core import Graph, NodeRegistry, Page
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.ui import mainwindow as mod
from flograph.ui.commands import (
    AddPageCommand, DuplicatePageCommand, RemovePageCommand,
    SetPageColorCommand,
)
from flograph.ui.dashboard.page_bar import (
    TAB_TINT_NORMAL, TAB_TINT_SELECTED, PageTabBar,
)
from flograph.ui.mainwindow import MainWindow

RED = "#c04040"


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture
def graph():
    g = Graph()
    for page_id in ("p1", "p2"):
        g.add_page(Page(id=page_id, title=page_id.upper()))
    return g


class TestCoreColor:
    def test_defaults_to_none(self, graph):
        assert graph.pages["p1"].color is None

    def test_set_and_emit(self, graph):
        seen = []
        graph.events.page_changed.connect(seen.append)
        graph.set_page_color("p1", RED)
        assert graph.pages["p1"].color == RED
        assert seen == [graph.pages["p1"]]

    def test_empty_string_resets_to_none(self, graph):
        graph.set_page_color("p1", RED)
        graph.set_page_color("p1", "")
        assert graph.pages["p1"].color is None

    def test_round_trips_through_serialization(self, graph):
        graph.set_page_color("p1", RED)
        loaded = graph_from_dict(graph_to_dict(graph), NodeRegistry())
        assert loaded.pages["p1"].color == RED
        assert loaded.pages["p2"].color is None

    def test_old_project_without_color_loads(self, graph):
        payload = graph_to_dict(graph)
        for entry in payload["graph"]["pages"]:
            del entry["color"]
        assert graph_from_dict(payload, NodeRegistry()).pages["p1"].color is None


class TestColorCommand:
    def test_undo_redo(self, qtbot, graph):
        stack = QUndoStack()
        before = graph_to_dict(graph)
        stack.push(SetPageColorCommand(graph, "p1", RED))
        after = graph_to_dict(graph)
        assert graph.pages["p1"].color == RED
        for _ in range(2):
            stack.undo()
            assert graph.pages["p1"].color is None
            assert graph_to_dict(graph) == before
            stack.redo()
            assert graph_to_dict(graph) == after
        stack.clear()

    def test_reset_is_undoable(self, qtbot, graph):
        stack = QUndoStack()
        stack.push(SetPageColorCommand(graph, "p1", RED))
        stack.push(SetPageColorCommand(graph, "p1", None))
        assert graph.pages["p1"].color is None
        stack.undo()
        assert graph.pages["p1"].color == RED
        stack.clear()

    def test_duplicate_carries_the_color(self, qtbot, graph):
        stack = QUndoStack()
        graph.set_page_color("p1", RED)
        stack.push(DuplicatePageCommand(graph, "p1"))
        copy = list(graph.pages.values())[-1]
        assert copy.color == RED
        stack.clear()

    def test_delete_undo_restores_the_color(self, qtbot, graph):
        stack = QUndoStack()
        graph.set_page_color("p1", RED)
        stack.push(RemovePageCommand(graph, "p1"))
        stack.undo()
        assert graph.pages["p1"].color == RED
        stack.clear()


@pytest.fixture
def bar(qtbot):
    widget = PageTabBar()
    qtbot.addWidget(widget)
    for page_id in ("p1", "p2"):
        widget.add_page_tab(Page(id=page_id, title=page_id.upper()))
    widget.resize(400, 30)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def tab_pixel(bar, page_id) -> QColor:
    """Background colour actually painted for a tab, via a real render.
    Sampled inside the tab's left padding — the centre lands on the label
    glyphs, whose antialiased pixels say nothing about the tab fill."""
    image = bar.grab().toImage()
    rect = bar.tabRect(bar._index_of_page(page_id))
    return QColor(image.pixel(rect.left() + 4, rect.center().y()))


def redness(color: QColor) -> int:
    """How far a pixel leans red. Compared against the untinted tab rather
    than an absolute value, since the base tab colour depends on the theme
    (the dark stylesheet is applied by the app, not by a bare widget)."""
    return color.red() - color.blue()


class TestTabPainting:
    def test_uncolored_tabs_paint_the_theme_background(self, bar):
        assert tab_pixel(bar, "p1") == tab_pixel(bar, "p2")

    def test_color_tints_the_tab(self, bar):
        plain = tab_pixel(bar, "p1")
        bar.set_page_color("p1", RED)
        tinted = tab_pixel(bar, "p1")
        assert tinted != plain
        # muted, not the raw colour: the tint is laid over the themed tab
        assert tinted != QColor(RED)
        assert redness(tinted) > redness(plain)
        # the untouched tab is unaffected
        assert tab_pixel(bar, "p2") == plain

    def test_selected_tab_is_tinted_more_strongly(self, bar):
        bar.set_page_color("p1", RED)
        bar.select_page("p2")
        unselected = tab_pixel(bar, "p1")
        bar.select_page("p1")
        selected = tab_pixel(bar, "p1")
        assert TAB_TINT_SELECTED > TAB_TINT_NORMAL
        assert redness(selected) > redness(unselected)

    def test_reset_returns_to_the_theme_background(self, bar):
        plain = tab_pixel(bar, "p1")
        bar.set_page_color("p1", RED)
        bar.set_page_color("p1", None)
        assert bar.page_color("p1") is None
        assert tab_pixel(bar, "p1") == plain

    def test_label_still_readable_over_the_tint(self, bar):
        """The label is drawn after the tint, so a coloured tab must not be
        one flat colour across its whole width."""
        bar.set_page_color("p1", RED)
        image = bar.grab().toImage()
        rect = bar.tabRect(bar._index_of_page("p1"))
        row = rect.center().y()
        seen = {image.pixel(x, row)
                for x in range(rect.left() + 2, rect.right() - 2)}
        assert len(seen) > 1

    def test_color_survives_a_reorder(self, bar):
        bar.set_page_color("p1", RED)
        bar.set_page_order(["p2", "p1"])
        assert bar.page_order() == ["p2", "p1"]
        assert bar.page_color("p1") == RED
        assert tab_pixel(bar, "p1") != tab_pixel(bar, "p2")

    def test_removing_a_page_drops_its_color(self, bar):
        bar.set_page_color("p1", RED)
        bar.remove_page_tab("p1")
        assert bar.page_color("p1") is None

    def test_add_page_tab_picks_up_an_existing_color(self, bar):
        bar.add_page_tab(Page(id="p3", title="P3", color=RED))
        assert bar.page_color("p3") == RED


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    win.undo_stack.push(AddPageCommand(win.graph, Page(id="p1", title="P1")))
    return win


class TestWindowRoundTrip:
    def test_request_colors_the_page_undoably(self, window):
        window.page_bar.recolor_page_requested.emit("p1", RED)
        assert window.graph.pages["p1"].color == RED
        assert window.page_bar.page_color("p1") == RED
        window.undo_stack.undo()
        assert window.graph.pages["p1"].color is None
        assert window.page_bar.page_color("p1") is None

    def test_reset_request(self, window):
        window.page_bar.recolor_page_requested.emit("p1", RED)
        window.page_bar.recolor_page_requested.emit("p1", None)
        assert window.graph.pages["p1"].color is None
        assert window.page_bar.page_color("p1") is None

    def test_no_command_when_color_unchanged(self, window):
        window.page_bar.recolor_page_requested.emit("p1", RED)
        depth = window.undo_stack.count()
        window.page_bar.recolor_page_requested.emit("p1", RED)
        assert window.undo_stack.count() == depth

    def test_unknown_page_is_ignored(self, window):
        window.page_bar.recolor_page_requested.emit("nope", RED)
        assert list(window.graph.pages) == ["p1"]
