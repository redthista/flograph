"""Shape creation and editing wired through the main window: the Edit-menu
submenu, the trimmed right-click menu, the Properties panel, Select All."""
import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui.mainwindow import MainWindow


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
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
    yield win
    win._palette_popup.hide()


def test_right_click_does_not_offer_shapes(window):
    """Shapes muddied the node palette — they live in the Edit menu now."""
    window._show_add_node_menu(QPointF(0, 0), QPoint(0, 0))
    keys = {k for _, k in window._palette_popup._extras}
    assert not any(k.startswith("shape:") for k in keys)
    assert "frame" in keys


def test_edit_menu_has_an_insert_shape_submenu(window):
    menus = window._menu_root.findChildren(type(window._menu_root))
    titles = {m.title() for m in menus}
    assert "Insert Shape" in titles


def test_new_shape_is_selected_and_undoable(window):
    window._add_shape_at(QPointF(0, 0), "rect")
    sid = next(iter(window.graph.shapes))
    assert window.scene.shape_items[sid].isSelected()
    window.undo_stack.undo()
    assert not window.graph.shapes


def test_select_all_includes_visible_shapes(window):
    window._add_shape_at(QPointF(0, 0), "rect")
    window._add_shape_at(QPointF(200, 0), "ellipse")
    window.scene.clearSelection()
    window._select_all_nodes()
    assert len(window.scene.selected_shape_items()) == 2


def _menu_entries(window, monkeypatch, shape_id):
    from PySide6.QtWidgets import QMenu
    seen: dict = {}

    class _Peek(QMenu):
        def exec(self, *args):
            seen["labels"] = [a.text() for a in self.actions()]
            return None

    monkeypatch.setattr(mod, "QMenu", _Peek)
    window._show_shape_menu(shape_id, QPoint(0, 0))
    return seen.get("labels", [])


def test_shape_context_menu_is_only_order_and_delete(window, monkeypatch):
    window._add_shape_at(QPointF(0, 0), "rect")
    sid = next(iter(window.graph.shapes))
    labels = _menu_entries(window, monkeypatch, sid)
    assert "Edit text…" in labels
    assert "Layer" in labels
    assert "Delete" in labels
    # every style knob moved to the Properties panel
    assert "Line colour…" not in labels
    assert "Fill colour…" not in labels
    assert "Line width" not in labels
    assert "Dashed" not in labels
    assert "Hide" not in labels
    assert "Send behind nodes" not in labels


# --------------------------------------------------------- Properties panel

def _shape_panel(window, kind="rect"):
    window._add_shape_at(QPointF(0, 0), kind)
    sid = next(iter(window.graph.shapes))
    window._on_selection_changed()
    return sid, window.shape_panel


def test_selecting_a_shape_shows_the_shape_properties(window):
    sid, panel = _shape_panel(window)
    assert window._properties_stack.currentWidget() is panel
    assert panel._shape_id == sid
    assert not panel.tree.isHidden()


def test_properties_edits_reach_the_graph_as_undo_steps(window):
    sid, panel = _shape_panel(window)
    panel._push(stroke_width=4.0)
    assert window.graph.shapes[sid].stroke_width == 4.0
    panel._dashed.setChecked(True)
    assert window.graph.shapes[sid].dashed is True
    panel._visible.setChecked(False)
    assert window.graph.shapes[sid].hidden is True
    window.undo_stack.undo()                     # undo the hide
    assert window.graph.shapes[sid].hidden is False


def test_properties_text_field_commits(window):
    sid, panel = _shape_panel(window)
    panel._text.setText("hello")
    panel._commit_text()
    assert window.graph.shapes[sid].text == "hello"


def test_line_properties_hide_the_text_and_fill_rows(window):
    _sid, panel = _shape_panel(window, "arrow")
    assert panel._rows[1].isHidden()      # Text
    assert panel._rows[3].isHidden()      # Fill


def test_deselecting_returns_to_the_node_panel(window):
    _sid, panel = _shape_panel(window)
    window.scene.clearSelection()
    window._on_selection_changed()
    assert window._properties_stack.currentWidget() is window.params_panel


def test_duplicate_copies_a_shape_with_a_fresh_id(window):
    window._add_shape_at(QPointF(0, 0), "rect")
    window.scene.push_shape_style(next(iter(window.graph.shapes)),
                                  fill="#334455", text="label")
    original = dict(window.graph.shapes)
    window.scene.clearSelection()
    window.scene.shape_items[next(iter(original))].setSelected(True)
    window._duplicate()
    assert len(window.graph.shapes) == 2
    new_id = next(i for i in window.graph.shapes if i not in original)
    assert window.graph.shapes[new_id].fill == "#334455"
    assert window.graph.shapes[new_id].text == "label"
    window.undo_stack.undo()
    assert len(window.graph.shapes) == 1
