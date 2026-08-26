"""Right-clicking inside a multi-selection acts on the whole selection.

Selecting five nodes and picking Freeze used to freeze the one under the
cursor, which is the least useful of the six things it could have meant. The
rule this file pins down is: the menu is about the selection, the clicked
node only decides what the labels *say*, and everything that can only be
true of one node (its code, its name, its cached output) leaves the menu
rather than quietly acting on whichever one was clicked.
"""
import pytest
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMenu

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mw
from flograph.ui.mainwindow import MainWindow

CONST = "flograph.util.constant"
TABLE = "flograph.viz.show_table"


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mw, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


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
    return win


def _find(menu, text):
    for action in menu.actions():
        if action.text() == text:
            return action
        if action.menu() is not None:
            found = _find(action.menu(), text)
            if found is not None:
                return found
    return None


def pick(monkeypatch, text):
    """Drive the context menu without popping a real one — a genuine QMenu
    subclass rather than a patched exec, for the reason spelled out in
    test_goto_links_ui."""
    class _Picker(QMenu):
        def exec(self, *args):
            return _find(self, text)
    monkeypatch.setattr(mw, "QMenu", _Picker)


def menu_texts(monkeypatch):
    """Every action text the menu would have shown, submenu titles included
    but not their contents."""
    seen: list = []

    class _Recorder(QMenu):
        def exec(self, *args):
            seen.extend(a.text() for a in self.actions())
            return None
    monkeypatch.setattr(mw, "QMenu", _Recorder)
    return seen


def add_nodes(window, count=3, type_id=CONST):
    """`count` nodes, all selected, returned in the order they were made."""
    nodes = []
    for i in range(count):
        node = window.registry.instantiate(type_id, pos=(i * 200.0, 0.0))
        window.graph.add_node(node)
        nodes.append(node)
    for node in nodes:
        window.scene.node_items[node.id].setSelected(True)
    return nodes


# ------------------------------------------------------------- the menu

class TestWhatTheMenuOffers:
    def test_one_node_still_gets_the_single_node_menu(self, window,
                                                      monkeypatch):
        node = add_nodes(window, 1)[0]
        texts = menu_texts(monkeypatch)
        window._show_node_menu(node.id, QPoint())
        assert "Run To This Node" in texts
        assert "Edit Code" in texts
        assert "Rename" in texts
        assert not any("selected" in t for t in texts)

    def test_a_selection_says_how_many_it_means(self, window, monkeypatch):
        nodes = add_nodes(window, 3)
        texts = menu_texts(monkeypatch)
        window._show_node_menu(nodes[0].id, QPoint())
        assert "3 nodes selected" in texts

    def test_it_runs_the_selection_rather_than_a_path_to_one(self, window,
                                                            monkeypatch):
        nodes = add_nodes(window, 3)
        texts = menu_texts(monkeypatch)
        window._show_node_menu(nodes[0].id, QPoint())
        assert "Run These Nodes" in texts
        assert "Run To This Node" not in texts

    def test_the_one_node_entries_step_aside(self, window, monkeypatch):
        """Not greyed out — gone. An entry that could only mean the node
        under the cursor has no honest reading on a selection."""
        nodes = add_nodes(window, 3)
        texts = menu_texts(monkeypatch)
        window._show_node_menu(nodes[0].id, QPoint())
        for text in ("Edit Code", "Open in Window", "Rename"):
            assert text not in texts

    def test_everything_that_can_mean_several_stays(self, window,
                                                    monkeypatch):
        nodes = add_nodes(window, 3)
        texts = menu_texts(monkeypatch)
        window._show_node_menu(nodes[0].id, QPoint())
        for text in ("Appearance…", "Mark Dirty", "Freeze", "Lock",
                     "Deactivate", "Run only when asked", "Copy", "Delete"):
            assert text in texts

    def test_dismissing_the_menu_does_nothing_at_all(self, window,
                                                     monkeypatch):
        """The entries a selection does not get are None, and so is a
        dismissed menu — so "did they pick Edit Code?" has to be asked after
        "did they pick anything?", not instead of it."""
        nodes = add_nodes(window, 3)
        pick(monkeypatch, "nothing of the sort")
        before = window.undo_stack.count()
        window._show_node_menu(nodes[0].id, QPoint())
        assert window.undo_stack.count() == before
        assert window.editor_panel._node_id is None

    def test_right_clicking_outside_the_selection_takes_the_node_alone(
            self, window, monkeypatch):
        """The old behaviour, still: a right-click on an unselected node
        selects it and means it."""
        nodes = add_nodes(window, 3)
        window.scene.clearSelection()
        window.scene.node_items[nodes[0].id].setSelected(True)
        texts = menu_texts(monkeypatch)
        window._show_node_menu(nodes[1].id, QPoint())
        assert "Rename" in texts
        assert window.scene.node_items[nodes[1].id].isSelected()
        assert not window.scene.node_items[nodes[0].id].isSelected()


# ------------------------------------------------------------- the flags

class TestBatchFlags:
    def test_freeze_takes_the_whole_selection(self, window, monkeypatch):
        nodes = add_nodes(window, 3)
        pick(monkeypatch, "Freeze")
        window._show_node_menu(nodes[0].id, QPoint())
        assert all(window.graph.nodes[n.id].frozen for n in nodes)

    def test_the_clicked_node_decides_the_direction(self, window,
                                                    monkeypatch):
        """A selection of some frozen and some not is exactly where a
        per-node toggle goes wrong: the label said Unfreeze, so everything
        ends up thawed rather than swapped over."""
        nodes = add_nodes(window, 3)
        window.graph.set_frozen(nodes[0].id, True)
        pick(monkeypatch, "Unfreeze")
        window._show_node_menu(nodes[0].id, QPoint())
        assert not any(window.graph.nodes[n.id].frozen for n in nodes)

    def test_it_is_one_step_on_the_undo_stack(self, window, monkeypatch):
        nodes = add_nodes(window, 3)
        before = window.undo_stack.count()
        pick(monkeypatch, "Lock")
        window._show_node_menu(nodes[0].id, QPoint())
        assert window.undo_stack.count() == before + 1
        window.undo_stack.undo()
        assert not any(window.graph.nodes[n.id].locked for n in nodes)

    def test_the_undo_entry_counts_what_it_did(self, window, monkeypatch):
        nodes = add_nodes(window, 3)
        pick(monkeypatch, "Lock")
        window._show_node_menu(nodes[0].id, QPoint())
        assert window.undo_stack.text(window.undo_stack.count() - 1) == \
            "lock nodes (3)"

    def test_nodes_already_that_way_are_left_out_of_the_step(
            self, window, monkeypatch):
        """Two of the three are already locked, so the step is about one —
        and says so, instead of carrying two commands that do nothing."""
        nodes = add_nodes(window, 3)
        window.graph.set_locked(nodes[1].id, True)
        window.graph.set_locked(nodes[2].id, True)
        pick(monkeypatch, "Lock")
        window._show_node_menu(nodes[0].id, QPoint())
        assert window.undo_stack.text(window.undo_stack.count() - 1) == \
            "lock node"
        assert all(window.graph.nodes[n.id].locked for n in nodes)

    def test_a_selection_already_that_way_adds_no_step(self, window,
                                                       monkeypatch):
        nodes = add_nodes(window, 3)
        for node in nodes:
            window.graph.set_active(node.id, False)
        before = window.undo_stack.count()
        pick(monkeypatch, "Activate")
        window._show_node_menu(nodes[0].id, QPoint())
        # every node wanted active; they were the other way, so this *is* a
        # step — the no-op case is asking for what they already are
        assert window.undo_stack.count() == before + 1
        before = window.undo_stack.count()
        pick(monkeypatch, "Deactivate")
        window._show_node_menu(nodes[0].id, QPoint())
        window.undo_stack.undo()
        assert window.undo_stack.count() == before + 1

    def test_deactivate(self, window, monkeypatch):
        nodes = add_nodes(window, 3)
        pick(monkeypatch, "Deactivate")
        window._show_node_menu(nodes[0].id, QPoint())
        assert not any(window.graph.nodes[n.id].active for n in nodes)

    def test_run_only_when_asked(self, window, monkeypatch):
        nodes = add_nodes(window, 3)
        pick(monkeypatch, "Run only when asked")
        window._show_node_menu(nodes[0].id, QPoint())
        assert all(window.graph.nodes[n.id].manual for n in nodes)

    def test_run_on_its_own(self, window, monkeypatch):
        nodes = add_nodes(window, 3)
        pick(monkeypatch, "Run on its own")
        window._show_node_menu(nodes[0].id, QPoint())
        assert all(window.graph.nodes[n.id].exclusive_override is True
                   for n in nodes)

    def test_mark_dirty_marks_them_all(self, window, monkeypatch):
        nodes = add_nodes(window, 3)
        for node in nodes:
            window.graph.nodes[node.id].dirty = False
        pick(monkeypatch, "Mark Dirty")
        window._show_node_menu(nodes[0].id, QPoint())
        assert all(window.graph.nodes[n.id].dirty for n in nodes)

    def test_run_asks_the_engine_for_the_selection(self, window, monkeypatch):
        nodes = add_nodes(window, 3)
        asked: list = []
        monkeypatch.setattr(window.engine, "run_targets",
                            lambda targets: asked.append(list(targets)))
        pick(monkeypatch, "Run These Nodes")
        window._show_node_menu(nodes[0].id, QPoint())
        assert asked and sorted(asked[0]) == sorted(n.id for n in nodes)


# -------------------------------------------------------- the appearance

class TestBatchAppearance:
    def _dialog(self, window, node_ids):
        from flograph.ui.canvas.appearance_dialog import AppearanceDialog
        return AppearanceDialog(window.scene, node_ids, window)

    def test_the_title_says_how_many(self, window):
        nodes = add_nodes(window, 3)
        dialog = self._dialog(window, [n.id for n in nodes])
        assert "3 nodes" in dialog.windowTitle()

    def test_one_node_still_names_it(self, window):
        node = add_nodes(window, 1)[0]
        assert node.label in self._dialog(window, node.id).windowTitle()

    def test_a_colour_reaches_every_node(self, window, monkeypatch):
        nodes = add_nodes(window, 3)
        dialog = self._dialog(window, [n.id for n in nodes])
        from flograph.ui.canvas import appearance_dialog as mod
        monkeypatch.setattr(mod.QColorDialog, "getColor",
                            staticmethod(lambda *a, **k: QColor("#ff0055")))
        before = window.undo_stack.count()
        dialog._choose_colour()
        assert [window.graph.nodes[n.id].color for n in nodes] == \
            ["#ff0055"] * 3
        assert window.undo_stack.count() == before + 1   # one step, not three

    def test_undo_puts_all_three_back(self, window, monkeypatch):
        nodes = add_nodes(window, 3)
        dialog = self._dialog(window, [n.id for n in nodes])
        from flograph.ui.canvas import appearance_dialog as mod
        monkeypatch.setattr(mod.QColorDialog, "getColor",
                            staticmethod(lambda *a, **k: QColor("#ff0055")))
        dialog._choose_colour()
        window.undo_stack.undo()
        assert not any(window.graph.nodes[n.id].color for n in nodes)

    def test_port_names_reach_every_node(self, window):
        nodes = add_nodes(window, 3)
        dialog = self._dialog(window, [n.id for n in nodes])
        dialog._labels_combo.setCurrentIndex(
            dialog._labels_combo.findData(False))
        assert all(window.graph.nodes[n.id].port_labels is False
                   for n in nodes)

    def test_a_mark_reaches_every_node(self, window):
        nodes = add_nodes(window, 3)
        dialog = self._dialog(window, [n.id for n in nodes])
        swatch = dialog._swatches.buttons()[3]
        swatch.setChecked(True)      # the group does this before it emits
        dialog._on_swatch_clicked(swatch)
        assert all(window.graph.nodes[n.id].mark == swatch.name
                   for n in nodes)

    def test_a_card_in_the_selection_keeps_its_shape(self, window):
        """A card is drawn at its content's size and has no square to mark,
        so the two sections that mean nothing for it skip it — while the
        colour and the port names still land."""
        plain = add_nodes(window, 2)
        card = add_nodes(window, 1, type_id=TABLE)[0]
        dialog = self._dialog(window, [n.id for n in plain] + [card.id])
        dialog._shape_combo.setCurrentIndex(dialog._shape_combo.findData(True))
        assert all(window.graph.nodes[n.id].compact_view is True
                   for n in plain)
        assert window.graph.nodes[card.id].compact_view is None

    def test_the_canvas_preview_skips_nodes_that_have_none(self, window):
        cards = add_nodes(window, 2, type_id=TABLE)
        plain = add_nodes(window, 1)[0]
        dialog = self._dialog(window, [c.id for c in cards] + [plain.id])
        assert dialog._preview_check is not None
        dialog._preview_check.setChecked(False)
        assert all(window.graph.nodes[c.id].canvas_preview_enabled is False
                   for c in cards)
        assert window.graph.nodes[plain.id].canvas_preview_enabled is True

    def test_one_node_keeps_its_merging(self, window):
        """The single-node path is untouched, so browsing sixteen marks is
        still one step back rather than sixteen."""
        node = add_nodes(window, 1)[0]
        dialog = self._dialog(window, node.id)
        before = window.undo_stack.count()
        for swatch in dialog._swatches.buttons()[:4]:
            dialog._on_swatch_clicked(swatch)
        assert window.undo_stack.count() == before + 1


# ------------------------------------------------------------- the pages

class TestAddSelectionToPage:
    def test_every_selected_node_becomes_a_tile(self, window, monkeypatch):
        from flograph.core import Page
        from flograph.ui.commands import AddPageCommand
        window.undo_stack.push(AddPageCommand(
            window.graph, Page(id="p1", title="Board")))
        nodes = add_nodes(window, 3, type_id=TABLE)
        before = window.undo_stack.count()
        pick(monkeypatch, "Board")
        window._show_node_menu(nodes[0].id, QPoint())
        tiles = window.graph.pages["p1"].tiles.values()
        assert sorted(t.node_id for t in tiles) == sorted(n.id for n in nodes)
        assert window.undo_stack.count() == before + 1   # one step for three

    def test_they_do_not_land_in_one_pile(self, window, monkeypatch):
        from flograph.core import Page
        from flograph.ui.commands import AddPageCommand
        window.undo_stack.push(AddPageCommand(
            window.graph, Page(id="p1", title="Board")))
        nodes = add_nodes(window, 3, type_id=TABLE)
        pick(monkeypatch, "Board")
        window._show_node_menu(nodes[0].id, QPoint())
        corners = {(t.rect[0], t.rect[1])
                   for t in window.graph.pages["p1"].tiles.values()}
        assert len(corners) == 3

    def test_a_new_page_takes_the_whole_selection(self, window, monkeypatch):
        nodes = add_nodes(window, 3, type_id=TABLE)
        pick(monkeypatch, "New Page…")
        window._show_node_menu(nodes[0].id, QPoint())
        pages = [p for p in window.graph.pages.values()
                 if p.kind == "dashboard"]
        assert len(pages) == 1
        assert len(pages[0].tiles) == 3

    def test_a_node_that_cannot_be_a_tile_is_left_behind(self, window,
                                                         monkeypatch):
        from flograph.core import Page
        from flograph.ui.commands import AddPageCommand
        window.undo_stack.push(AddPageCommand(
            window.graph, Page(id="p1", title="Board")))
        cards = add_nodes(window, 2, type_id=TABLE)
        note = window.registry.instantiate("flograph.util.note", pos=(0, 400))
        window.graph.add_node(note)
        window.scene.node_items[note.id].setSelected(True)
        pick(monkeypatch, "Board")
        window._show_node_menu(cards[0].id, QPoint())
        tiles = window.graph.pages["p1"].tiles.values()
        assert sorted(t.node_id for t in tiles) == sorted(c.id for c in cards)
