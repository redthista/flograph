"""A theme's node shape and size reach the canvas, live."""
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui import theme, themes
from flograph.ui.canvas import node_item


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    ini = str(tmp_path / "s.ini")
    monkeypatch.setattr(
        mod, "QSettings", lambda *a, **k: QSettings(ini, QSettings.IniFormat))
    yield
    app = QApplication.instance()
    if app is not None:
        theme.apply_theme(app, "dark")


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def _apply(**style):
    app = QApplication.instance()
    base = themes.load("dark")
    theme.apply_theme(app, "dark",
                      custom=themes.with_overrides(base, {"style": style}))


def test_the_reference_values_are_what_the_code_used_to_hardcode():
    style = themes.load("dark").section("style")
    assert (style["node_corner_radius"], style["node_width"],
            style["node_header_height"], style["node_row_height"],
            style["node_compact_size"]) == (7, 170, 26, 20, 60)


def test_a_theme_sets_the_node_constants(qapp):
    _apply(node_corner_radius=0, node_width=240, node_header_height=34,
           node_row_height=26, node_compact_size=80)
    assert node_item.NODE_RADIUS == 0.0
    assert node_item.NODE_WIDTH == 240.0
    assert node_item.HEADER_H == 34.0
    assert node_item.ROW_H == 26.0
    assert node_item.COMPACT_W == node_item.COMPACT_MIN_H == 80.0
    assert node_item.GEOMETRY_CHANGED
    # a colour-only change is not a size change: nothing to re-lay-out
    _apply(node_corner_radius=0, node_width=240, node_header_height=34,
           node_row_height=26, node_compact_size=80, node_shadow=True)
    assert not node_item.GEOMETRY_CHANGED


def test_existing_nodes_take_the_new_size(qtbot, registry):
    win = mod.MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    from pathlib import Path
    import flograph.templates as T
    win.open_example(Path(T.__file__).parent / "01_load_filter_visualize.flograph")
    plain = [i for i in win.scene.node_items.values() if i.plain]
    assert plain
    _apply(node_compact_size=90, node_width=250)
    win._on_app_theme_changed()
    for item in plain:
        assert item.width == (90.0 if item._square else 250.0)
    _apply()                                  # back to the reference
    win._on_app_theme_changed()
    for item in plain:
        assert item.width == (60.0 if item._square else 170.0)
