"""Settings ▸ General ▸ Tables ▸ Data text size: one point size for every
read-only data table — the inspector's, the previews on cards and tiles,
the pop-out views — so a smaller one fits more rows and columns on screen."""
import pandas as pd
import pytest
from PySide6.QtCore import Qt

from flograph.ui import theme
from flograph.ui.data_table import (GRID_FONT_PT, DataTableView,
                                    set_table_text_size, table_text_size)
from flograph.ui.inspector.pandas_model import PandasModel


@pytest.fixture(autouse=True)
def default_size():
    """Every test starts and ends at "Default" — the size is a stored
    preference, and the file is shared by the whole module."""
    set_table_text_size(0.0)
    yield
    set_table_text_size(0.0)


def _table(qtbot, rows: int = 40):
    view = DataTableView()
    qtbot.addWidget(view)
    frame = pd.DataFrame({"name": [f"row {i}" for i in range(rows)],
                          "value": range(rows)})
    view.setModel(PandasModel(frame, parent=view))
    view.resize(400, 300)
    return view


class TestTextSize:
    def test_default_is_the_size_the_theme_picked(self, qtbot):
        view = _table(qtbot)
        assert table_text_size() == 0.0
        assert view.font().pointSizeF() == view._theme_font.pointSizeF()

    def test_a_smaller_size_fits_more_rows(self, qtbot):
        view = _table(qtbot)
        before = view.verticalHeader().defaultSectionSize()
        set_table_text_size(7.0)
        assert view.font().pointSizeF() == pytest.approx(7.0)
        assert view.horizontalHeader().font().pointSizeF() == pytest.approx(7.0)
        after = view.verticalHeader().defaultSectionSize()
        assert after < before, "rows have to tighten with the text"

    def test_columns_are_refitted_for_the_new_size(self, qtbot):
        view = _table(qtbot)
        wide_before = view.columnWidth(0)
        set_table_text_size(7.0)
        assert view.columnWidth(0) <= wide_before

    def test_going_back_to_default_restores_the_theme_font(self, qtbot):
        view = _table(qtbot)
        original = view._theme_font.pointSizeF()
        rows = view.verticalHeader().defaultSectionSize()
        set_table_text_size(7.0)
        set_table_text_size(0.0)
        assert view.font().pointSizeF() == pytest.approx(original)
        assert view.verticalHeader().defaultSectionSize() == rows

    def test_a_table_built_afterwards_opens_at_the_size(self, qtbot):
        set_table_text_size(6.5)
        view = _table(qtbot)
        assert view.font().pointSizeF() == pytest.approx(6.5)

    def test_a_wrapping_table_keeps_its_content_sized_rows(self, qtbot):
        """A `wrap` rule means each row is as tall as its own text; the
        text size must not put a fixed height back."""
        from PySide6.QtWidgets import QHeaderView

        class Wrapping(PandasModel):
            def wraps_text(self):
                return True

        view = DataTableView()
        qtbot.addWidget(view)
        view.setModel(Wrapping(pd.DataFrame({"a": ["x" * 80]}), parent=view))
        set_table_text_size(7.0)
        assert view.verticalHeader().sectionResizeMode(0) == \
            QHeaderView.ResizeToContents


class TestTableMenu:
    @staticmethod
    def _size_menu(view):
        """The Text Size submenu, with its parent kept alive — a menu built
        by build_menu() and dropped takes its submenus down with it."""
        menu = view.build_menu()
        sizes = next(action.menu() for action in menu.actions()
                     if action.text() == "Text Size")
        return menu, sizes

    def test_the_table_menu_steps_the_size(self, qtbot):
        view = _table(qtbot)
        menu, sizes = self._size_menu(view)
        assert [a.text() for a in sizes.actions() if not a.isSeparator()] == \
            ["Smaller", "Larger", "Default"]
        # nothing to go back to while the size is the default
        assert not sizes.actions()[-1].isEnabled()

        on_screen = view.font().pointSizeF()
        view.nudge_text_size(-0.5)
        assert table_text_size() == pytest.approx(on_screen - 0.5)
        assert view.font().pointSizeF() == pytest.approx(on_screen - 0.5)

        menu2, sizes2 = self._size_menu(view)
        assert sizes2.actions()[-1].isEnabled()     # Default now means something
        del menu, menu2

    def test_stepping_stops_at_the_ends(self, qtbot):
        from flograph.ui.data_table import MAX_TEXT_PT, MIN_TEXT_PT
        view = _table(qtbot)
        for _ in range(40):
            view.nudge_text_size(-1.0)
        assert table_text_size() == pytest.approx(MIN_TEXT_PT)
        for _ in range(60):
            view.nudge_text_size(1.0)
        assert table_text_size() == pytest.approx(MAX_TEXT_PT)


class TestSharedGridLook:
    def test_the_grid_stylesheet_carries_the_size(self):
        assert f"font-size: {GRID_FONT_PT:g}pt" in theme.grid_stylesheet()
        set_table_text_size(7.0)
        assert "font-size: 7pt" in theme.grid_stylesheet()

    def test_a_card_table_is_restyled_and_keeps_its_scroll_blitting(
            self, qtbot):
        """Cards and tiles carry the shared grid stylesheet, and a
        stylesheet's font-size beats any font set on the widget — so those
        get the sheet re-applied, through style_scroll_area, which is what
        keeps WA_OpaquePaintEvent on the viewport (a plain setStyleSheet
        loses it, and with it one-row scrolling)."""
        view = _table(qtbot)
        theme.style_scroll_area(view, theme.grid_stylesheet())
        assert f"font-size: {GRID_FONT_PT:g}pt" in view.styleSheet()

        set_table_text_size(7.0)
        assert "font-size: 7pt" in view.styleSheet()
        assert view.viewport().testAttribute(Qt.WA_OpaquePaintEvent)


class TestSettingsPage:
    def test_the_general_page_has_the_row_and_it_applies(self, qtbot):
        from PySide6.QtWidgets import QDoubleSpinBox

        from flograph.core import NodeRegistry
        from flograph.ui import mainwindow as mod
        from flograph.ui.settings_dialog import SettingsDialog

        registry = NodeRegistry()
        registry.load_builtins()
        window = mod.MainWindow(registry)      # never shown — see conftest
        window.confirm_close = False
        qtbot.addWidget(window)

        page = SettingsDialog._build_general_page(window)
        qtbot.addWidget(page)
        spin = page.findChild(QDoubleSpinBox, "table_text_size_spinbox")
        assert spin is not None
        assert spin.specialValueText() == "Default"
        assert spin.value() == 0.0

        spin.setValue(7.0)
        assert table_text_size() == pytest.approx(7.0)
