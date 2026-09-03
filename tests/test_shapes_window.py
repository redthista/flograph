"""Shape creation wired through the main window: the Edit-menu submenu, the
right-click palette rows, and Select All."""
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


def test_right_click_offers_every_shape(window):
    window._show_add_node_menu(QPointF(0, 0), QPoint(0, 0))
    keys = {k for _, k in window._palette_popup._extras}
    assert {"shape:rect", "shape:arrow", "shape:text",
            "shape:diamond"} <= keys


def test_palette_row_drops_a_shape_where_it_opened(window):
    window._show_add_node_menu(QPointF(400, 300), QPoint(0, 0))
    window._palette_popup.hide()
    window._palette_extra_chosen("shape:ellipse")
    shape = next(iter(window.graph.shapes.values()))
    assert shape.kind == "ellipse"
    cx = shape.rect[0] + shape.rect[2] / 2
    cy = shape.rect[1] + shape.rect[3] / 2
    assert abs(cx - 400) < 1 and abs(cy - 300) < 1


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


def test_shape_context_menu_offers_the_expected_entries(window, monkeypatch):
    window._add_shape_at(QPointF(0, 0), "rect")
    sid = next(iter(window.graph.shapes))
    labels = _menu_entries(window, monkeypatch, sid)
    assert "Edit text…" in labels
    assert "Line colour…" in labels and "Fill colour…" in labels
    assert "Send behind nodes" in labels
    assert "Hide" in labels and "Delete" in labels


def test_line_context_menu_has_no_fill_entries(window, monkeypatch):
    window._add_shape_at(QPointF(0, 0), "arrow")
    sid = next(iter(window.graph.shapes))
    labels = _menu_entries(window, monkeypatch, sid)
    assert "Fill colour…" not in labels
    assert "Edit text…" not in labels


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
