"""The Node Library follows a live theme switch: row marks recolour in
place (a cache keyed on the mark alone kept the first theme's colour), and
category headings carry their mark in the accent colour (#119)."""
import pytest
from PySide6.QtCore import QSettings

from flograph.core import NodeRegistry
from flograph.ui import theme
from flograph.ui.canvas import palette
from flograph.ui.favorites import Favorites


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def tree(qtbot, registry, tmp_path, monkeypatch, qapp):
    monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path))
    theme.apply_theme(qapp, "dark")
    settings = QSettings(str(tmp_path / "fav.ini"), QSettings.IniFormat)
    t = palette.LibraryTree(registry, Favorites(settings))
    qtbot.addWidget(t)
    yield t
    theme.apply_theme(qapp, "dark")


def _first_row(tree):
    top = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
               if tree.topLevelItem(i).childCount())
    return top, top.child(0)


def _colour_of(icon):
    image = icon.pixmap(16, 16).toImage()
    seen = {image.pixelColor(x, y).name()
            for x in range(image.width()) for y in range(image.height())
            if image.pixelColor(x, y).alpha() > 200}
    return seen


def test_marks_recolour_on_a_theme_switch(tree, qapp):
    _top, row = _first_row(tree)
    dark = _colour_of(row.icon(0))
    theme.apply_theme(qapp, "light")
    light = _colour_of(row.icon(0))
    assert dark and light and dark != light


def test_category_headings_have_an_accent_mark(tree):
    headings = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    marked = [h for h in headings if not h.icon(0).isNull()]
    assert marked
    assert marked[0].font(0).weight() > 400
