"""Where Is This Used? on a node's right-click menu — what it offers, and
where each answer takes you.

The lookup itself is `core.usage` and is tested Qt-free in
test_where_used.py; this is the menu and the jump.
"""
import pytest
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtWidgets import QMenu

from flograph.core import NodeRegistry, Page, Tile
from flograph.core.usage import NOWHERE
from flograph.ui import mainwindow as mw

CONST = "flograph.util.constant"
REPORT_CARD = "flograph.viz.report_card"
ENTRY = "Where Is This Used?"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry, tmp_path, monkeypatch):
    monkeypatch.setattr(
        mw, "QSettings",
        lambda *a, **k: QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
    win = mw.MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def add(window, label, type_id=CONST):
    node = window.graph.add_node(window.registry.instantiate(type_id))
    window.graph.set_label(node.id, label)
    return node


def record(monkeypatch):
    """What the menu would have shown: its top-level texts, and the
    contents of the Where Is This Used? submenu with each line's enabled
    state. See test_goto_links_ui for why a QMenu subclass rather than a
    patched exec."""
    seen = {"top": [], "where": None}

    class _Recorder(QMenu):
        def exec(self, *args):
            for action in self.actions():
                seen["top"].append(action.text())
                if action.menu() is not None and action.text() == ENTRY:
                    seen["where"] = [(a.text(), a.isEnabled())
                                     for a in action.menu().actions()]
            return None
    monkeypatch.setattr(mw, "QMenu", _Recorder)
    return seen


def pick(monkeypatch, text):
    """Choose the submenu line reading `text`."""
    def find(menu):
        for action in menu.actions():
            if action.text() == text:
                return action
            if action.menu() is not None:
                found = find(action.menu())
                if found is not None:
                    return found
        return None

    class _Picker(QMenu):
        def exec(self, *args):
            return find(self)
    monkeypatch.setattr(mw, "QMenu", _Picker)


class TestWhatTheMenuOffers:

    def test_one_node_is_asked_where_it_is_used(self, window, monkeypatch):
        node = add(window, "Revenue")
        seen = record(monkeypatch)
        window._show_node_menu(node.id, QPoint())
        assert ENTRY in seen["top"]

    def test_a_selection_is_not_asked(self, window, monkeypatch):
        """A selection has no one answer, and a menu entry that answered for
        whichever node happened to be clicked would say the wrong thing."""
        first, second = add(window, "Revenue"), add(window, "Detail")
        for node in (first, second):
            window.scene.node_items[node.id].setSelected(True)
        seen = record(monkeypatch)
        window._show_node_menu(first.id, QPoint())
        assert ENTRY not in seen["top"]

    def test_nowhere_is_an_answer_not_an_empty_menu(self, window,
                                                    monkeypatch):
        node = add(window, "Revenue")
        seen = record(monkeypatch)
        window._show_node_menu(node.id, QPoint())
        assert seen["where"] == [(NOWHERE, False)]

    def test_each_place_is_its_own_line(self, window, monkeypatch):
        node = add(window, "Revenue")
        window.graph.add_page(Page(id="p1", title="Today"))
        window.graph.add_tile("p1", Tile(id="t1", node_id=node.id))
        window.graph.add_page(Page(id="p2", title="Monthly", kind="report",
                                   body="![[Revenue]]"))
        seen = record(monkeypatch)
        window._show_node_menu(node.id, QPoint())
        assert seen["where"] == [("Dashboard page “Today”", True),
                                 ("Report page “Monthly”", True)]


class TestWhereAnAnswerTakesYou:

    def test_a_tile_opens_its_page_with_the_tile_selected(self, window,
                                                          monkeypatch):
        node = add(window, "Revenue")
        window.graph.add_page(Page(id="p1", title="Today"))
        window.graph.add_tile("p1", Tile(id="t1", node_id=node.id))

        pick(monkeypatch, "Dashboard page “Today”")
        window._show_node_menu(node.id, QPoint())

        assert window.page_bar.current_page_id() == "p1"
        page = window._dashboard_pages["p1"]
        assert page.scene.tile_items["t1"].isSelected()

    def test_of_two_tiles_the_one_picked_is_the_one_selected(
            self, window, monkeypatch):
        node = add(window, "Revenue")
        window.graph.add_page(Page(id="p1", title="Today"))
        window.graph.add_tile("p1", Tile(id="t1", node_id=node.id))
        window.graph.add_page(Page(id="p2", title="Later"))
        window.graph.add_tile("p2", Tile(id="t2", node_id=node.id))

        pick(monkeypatch, "Dashboard page “Later”")
        window._show_node_menu(node.id, QPoint())

        assert window.page_bar.current_page_id() == "p2"
        assert window._dashboard_pages["p2"].scene.tile_items["t2"] \
            .isSelected()

    def test_a_report_page_opens_with_the_embed_selected(self, window,
                                                         monkeypatch):
        """A page may name a dozen things; the jump lands on the one you
        asked about rather than leaving it to be found by eye."""
        node = add(window, "Revenue")
        add(window, "Detail")
        window.graph.add_page(Page(
            id="p1", title="Monthly", kind="report",
            body="# Sales\n\n![[Detail]]\n\nThen:\n\n![[Revenue|value]]\n"))

        pick(monkeypatch, "Report page “Monthly”")
        window._show_node_menu(node.id, QPoint())

        assert window.page_bar.current_page_id() == "p1"
        editor = window._dashboard_pages["p1"].editor
        assert editor.textCursor().selectedText() == "![[Revenue|value]]"

    def test_a_locked_report_just_opens(self, window, monkeypatch):
        """Its source is hidden, so a selection in it would show nobody
        anything — the open page is the answer."""
        node = add(window, "Revenue")
        window.graph.add_page(Page(id="p1", title="Monthly", kind="report",
                                   body="![[Revenue]]"))
        window._set_page_view_mode("p1", True)

        pick(monkeypatch, "Report page “Monthly”")
        window._show_node_menu(node.id, QPoint())

        assert window.page_bar.current_page_id() == "p1"
        assert not window._dashboard_pages["p1"].editor.textCursor() \
            .hasSelection()

    def test_a_report_card_brings_the_canvas_to_the_card(self, window,
                                                         monkeypatch):
        """A card lives on the model, so the jump leaves whatever page was
        open and selects the card — the same as every other jump."""
        source = add(window, "Feeder")
        card = add(window, "Summary", REPORT_CARD)
        window.graph.connect(source.id, "value", card.id, "a")
        window.graph.set_param(card.id, "text", "Total was ![[a]].")
        window.graph.add_page(Page(id="p1", title="Elsewhere"))
        window.page_bar.select_page("p1")

        pick(monkeypatch, "Report card “Summary”")
        window._show_node_menu(source.id, QPoint())

        assert window.page_bar.current_page_id() is None
        assert window.scene.node_items[card.id].isSelected()
        assert not window.scene.node_items[source.id].isSelected()
