"""Node library favourites: the Favorites section, the favorites-only
toggle, and the Tab popup's favorites-first ordering.

Settings kept off the real store (avoid polluting the developer's actual
flograph.conf) -- same isolation as test_dashboard_ui.py."""
import os
import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from flograph.ui import mainwindow as mod
from flograph.ui.canvas.palette import FAVORITE_SECTION, STAR
from flograph.ui.favorites import Favorites
from flograph.ui.mainwindow import MainWindow


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture(scope="module")
def registry():
    from flograph.core import NodeRegistry
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def _roots(tree):
    return [tree.topLevelItem(i).text(0)
            for i in range(tree.topLevelItemCount())]


def _find_section(tree, title):
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        if top.text(0).endswith(title):
            return top
    return None


def _node_labels(section):
    return [section.child(i).text(0) for i in range(section.childCount())]


class TestFavoritesSection:
    def test_empty_stored_value_does_not_crash(self):
        # an empty list round-trips through QSettings as @Invalid() and comes
        # back as None — a fresh store must not crash on that
        from PySide6.QtCore import QCoreApplication, QSettings
        import tempfile
        ini = os.path.join(tempfile.mkdtemp(), "empty.ini")
        st = QSettings(ini, QSettings.IniFormat)
        st.setValue("library/favorites", [])
        st.sync()
        st2 = QSettings(ini, QSettings.IniFormat)
        favs = Favorites(st2)
        assert favs.ids() == []
        favs.toggle("flograph.io.read_csv")
        assert favs.contains("flograph.io.read_csv")

    def test_hidden_when_empty(self, window):
        tree = window.library_tree
        assert _find_section(tree, FAVORITE_SECTION) is None

    def test_toggle_adds_section_and_stars_home_row(self, window):
        tree = window.library_tree
        window.favorites.toggle("flograph.io.read_csv")

        fav = _find_section(tree, FAVORITE_SECTION)
        assert fav is not None
        assert "Read CSV" in _node_labels(fav)

        # the same node in its home category carries the star prefix
        io = _find_section(tree, "IO")
        starred = [lbl for lbl in _node_labels(io) if lbl.startswith(STAR)]
        assert any("Read CSV" in lbl for lbl in starred)

    def test_favorite_section_survives_reload_and_restart(self, window, qtbot):
        tree = window.library_tree
        window.favorites.toggle("flograph.io.read_csv")
        tree.reload()
        assert _find_section(tree, FAVORITE_SECTION) is not None

        # a fresh store over the same QSettings keeps the favorite
        fresh = Favorites(window.settings)
        assert fresh.contains("flograph.io.read_csv")

    def test_stale_favorite_is_ignored_not_kept(self, window):
        tree = window.library_tree
        window.favorites.toggle("user.nonexistent.node")
        assert _find_section(tree, FAVORITE_SECTION) is None

    def test_toggle_removes_section(self, window):
        tree = window.library_tree
        window.favorites.toggle("flograph.io.read_csv")
        assert _find_section(tree, FAVORITE_SECTION) is not None
        window.favorites.toggle("flograph.io.read_csv")
        assert _find_section(tree, FAVORITE_SECTION) is None


class TestFavoritesOnlyToggle:
    def test_hides_every_section_but_favorites(self, window):
        tree = window.library_tree
        window.favorites.toggle("flograph.io.read_csv")
        tree.set_favorites_only(True)
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            if top.text(0).endswith(FAVORITE_SECTION):
                assert not top.isHidden()
            else:
                assert top.isHidden()

    def test_empty_favorites_alone_stays_hidden(self, window):
        tree = window.library_tree
        tree.set_favorites_only(True)
        assert _find_section(tree, FAVORITE_SECTION) is None

    def test_still_respects_search(self, window):
        tree = window.library_tree
        window.favorites.toggle("flograph.io.read_csv")
        tree.set_favorites_only(True)
        tree.filter("no such node")
        fav = _find_section(tree, FAVORITE_SECTION)
        assert all(fav.child(i).isHidden() for i in range(fav.childCount()))

    def test_off_restores_categories(self, window):
        tree = window.library_tree
        window.favorites.toggle("flograph.io.read_csv")
        tree.set_favorites_only(True)
        tree.set_favorites_only(False)
        io = _find_section(tree, "IO")
        assert io is not None and not io.isHidden()


class TestPalettePopup:
    def test_favorites_first_with_star(self, window, qtbot):
        window.favorites.toggle("flograph.io.read_csv")
        popup = window._palette_popup
        popup.popup_at(QPoint(0, 0))
        try:
            first = popup._list.item(0).text()
            assert first.startswith(STAR)
            assert "Read CSV" in first
        finally:
            popup.hide()

    def test_wire_drop_predicate_still_filters(self, window):
        src = window.registry.instantiate("flograph.io.read_csv", pos=(0, 0))
        window.graph.add_node(src)
        port_item = window.scene.node_items[src.id].output_ports["table"]
        window._on_wire_dropped(port_item, QPoint(300, 0))
        try:
            labels = [window._palette_popup._list.item(i).text()
                      for i in range(window._palette_popup._list.count())]
            assert any("Filter Rows" in l for l in labels)
            assert not any("Read CSV" in l for l in labels)
        finally:
            window._palette_popup.hide()


class TestShortcut:
    def test_ctrl_shift_f_toggles_favorite(self, window, qtbot):
        tree = window.library_tree
        io = _find_section(tree, "IO")
        row = next(io.child(i) for i in range(io.childCount())
                   if io.child(i).data(0, 256) == "flograph.io.read_csv")
        tree.setCurrentItem(row)
        QTest.keyClick(tree, "F",
                       Qt.ControlModifier | Qt.ShiftModifier)
        assert window.favorites.contains("flograph.io.read_csv")
