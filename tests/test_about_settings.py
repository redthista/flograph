"""ideas.md item 20: an About page in Settings showing the installed
flograph version (plus Python/Qt versions), so users can tell what build
they're running without checking pyproject.toml. Also covers the Settings
nav being sorted ascending (General/Canvas/About -> About/Canvas/General)
rather than insertion order.

Settings kept off the real store (avoid polluting the developer's actual
flograph.conf) -- see test_lod_settings.py's fixture of the same name."""
import importlib.metadata

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QLabel, QWidget

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui.settings_dialog import SettingsDialog, _flograph_version


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
    win = mod.MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def _all_labels(widget):
    return widget.findChildren(QLabel)


class TestAboutPage:
    def test_about_is_a_nav_entry(self, window):
        dialog = SettingsDialog(window)
        assert "About" in dialog.page_names()

    def test_about_page_shows_the_installed_version(self, window):
        dialog = SettingsDialog(window)
        page = dialog._pages.widget(dialog._page_index["About"])
        text = " ".join(label.text() for label in _all_labels(page))
        assert _flograph_version() in text

    def test_version_helper_matches_installed_metadata(self):
        assert _flograph_version() == importlib.metadata.version("flograph")


class TestTheSettingsGrid:
    """Reported 2026-07-26: "settings is a little cramped now, can we move to
    a table style like we have with properties?" Each page is now a
    two-column grid; the paragraph that used to sit under every control
    became the row's tooltip, so the risk this guards is losing the
    explanations entirely on the way."""

    def page(self, window, name):
        from flograph.ui.settings_dialog import SettingsGrid
        dialog = SettingsDialog(window)
        page = dialog._pages.widget(dialog._page_index[name])
        return dialog, page.findChild(SettingsGrid)

    def rows(self, grid):
        return [grid.topLevelItem(i) for i in range(grid.topLevelItemCount())]

    def test_every_settings_page_is_a_grid(self, window):
        for name in ("Canvas", "General", "Table Node"):
            _dialog, grid = self.page(window, name)
            assert grid is not None, name
            assert grid.columnCount() == 2

    def test_every_control_row_keeps_its_explanation(self, window):
        """The tooltip is now the only place the hint lives. A row with a
        control and no tooltip is a setting nobody can find out about."""
        for name in ("Canvas", "General", "Table Node"):
            _dialog, grid = self.page(window, name)
            for row in self.rows(grid):
                if grid.itemWidget(row, 1) is None:
                    continue                    # a group heading
                assert row.toolTip(0), f"{name}: {row.text(0)}"
                assert row.toolTip(0) != row.text(0), f"{name}: {row.text(0)}"

    def test_the_control_carries_the_tooltip_too(self, window):
        """Hovering the checkbox itself is at least as likely as hovering
        its name."""
        _dialog, grid = self.page(window, "Canvas")
        for row in self.rows(grid):
            widget = grid.itemWidget(row, 1)
            if widget is not None:
                assert widget.toolTip()

    def test_no_canvas_setting_was_dropped_in_the_rework(self, window):
        """Rebuilding the page by hand is exactly how a control goes
        missing — the GPU one did, briefly."""
        dialog, grid = self.page(window, "Canvas")
        for name in ("gpu_viewport_checkbox", "lod_enabled_checkbox",
                     "lod_threshold_spinbox", "minimap_enabled_checkbox",
                     "port_labels_checkbox", "snap_enabled_checkbox",
                     "grid_step_combo", "tint_soft_spinbox",
                     "tint_strong_spinbox"):
            assert dialog.findChild(QWidget, name) is not None, name

    def test_the_page_holds_only_settings_no_heading_rows(self, window):
        """Reported: "when i click display it should only show the display
        options. they we can remove the headers." The nav tree carries the
        structure now, so a heading inside the page said it twice."""
        _dialog, grid = self.page(window, "Canvas")
        assert all(grid.itemWidget(r, 1) is not None for r in self.rows(grid))
        assert grid.group_titles() == ["Display", "Drag-select", "Snapping",
                                       "Custom colour strength"]

    def test_tooltips_are_wrapped_over_several_lines(self, window):
        """Reported: "can we have a multi line tooltip? easier to read." Qt
        treats a plain string as one unbreakable line, so a paragraph ran
        off the edge of the screen."""
        from flograph.ui.settings_dialog import TOOLTIP_WRAP
        _dialog, grid = self.page(window, "Canvas")
        long_rows = [r for r in self.rows(grid)
                     if len(r.toolTip(0)) > TOOLTIP_WRAP + 20]
        assert long_rows
        for row in long_rows:
            tip = row.toolTip(0)
            assert tip.startswith("<qt>") and "<br>" in tip
            assert max(len(line) for line in tip.split("<br>")) \
                < TOOLTIP_WRAP + 30

    def test_it_opens_without_a_horizontal_scrollbar(self, window):
        """Reported: "default size of the settings window should be slightly
        wider, so it doesnt imediatly bring up the scroll horizontal bar".
        At 560 the view reckoned its content was 18px wider than its
        viewport — a scrollbar under a dialog with nothing to scroll to."""
        dialog = SettingsDialog(window)
        dialog.show()
        for name in ("Canvas", "General", "Table Node"):
            entry = dialog._nav.topLevelItem(dialog.page_names().index(name))
            dialog._nav.setCurrentItem(entry)
            grid = dialog._grids[name]
            assert grid.horizontalScrollBar().maximum() == 0, name

    def test_reset_still_reaches_the_controls_inside_the_grid(self, window):
        """findChild has to keep working through the tree, or a reset stops
        syncing the dialog."""
        from PySide6.QtWidgets import QCheckBox
        dialog = SettingsDialog(window)
        window.set_port_labels_enabled(True)
        check = dialog.findChild(QCheckBox, "port_labels_checkbox")
        check.setChecked(False)
        dialog.refresh_from(window)
        assert check.isChecked() is True


class TestTheNavTreeAndSearch:
    """Reported 2026-07-26: "could maybe add a treeview where the left list is
    and seperate it out that way, may need a search box also to search for
    settings"."""

    def nav_rows(self, dialog):
        """(page, [group, ...]) for every visible nav entry."""
        out = []
        for i in range(dialog._nav.topLevelItemCount()):
            entry = dialog._nav.topLevelItem(i)
            if entry.isHidden():
                continue
            out.append((entry.text(0),
                        [entry.child(c).text(0) for c in range(entry.childCount())
                         if not entry.child(c).isHidden()]))
        return out

    def select(self, dialog, page, group=None):
        entry = dialog._nav.topLevelItem(dialog.page_names().index(page))
        if group is None:
            dialog._nav.setCurrentItem(entry)
            return
        child = next(entry.child(c) for c in range(entry.childCount())
                     if entry.child(c).text(0) == group)
        dialog._nav.setCurrentItem(child)

    def test_groups_hang_under_their_page(self, window):
        dialog = SettingsDialog(window)
        rows = dict(self.nav_rows(dialog))
        assert rows["Canvas"] == ["Display", "Drag-select", "Snapping",
                                  "Custom colour strength"]
        assert rows["General"] == ["Window", "Execution", "Saving",
                                   "Updates", "Reset"]
        assert rows["About"] == []          # prose, no settings

    def test_clicking_a_group_switches_to_its_page(self, window):
        dialog = SettingsDialog(window)
        canvas = dialog._nav.topLevelItem(dialog.page_names().index("Canvas"))
        snapping = next(canvas.child(c) for c in range(canvas.childCount())
                        if canvas.child(c).text(0) == "Snapping")
        dialog._nav.setCurrentItem(snapping)
        assert dialog._pages.currentIndex() == dialog._page_index["Canvas"]

    def test_search_narrows_to_the_matching_settings(self, window):
        dialog = SettingsDialog(window)
        grid = dialog._grids["Canvas"]
        dialog._search.setText("minimap")
        shown = [item.text(0) for item, _g, _h in grid.settings
                 if not item.isHidden()]
        assert shown == ["Show minimap"]

    def test_it_searches_what_a_setting_does_not_just_its_name(self, window):
        """What a setting *does* is far more memorable than what it's
        called — "muted" appears only in an explanation, never in a name."""
        dialog = SettingsDialog(window)
        grid = dialog._grids["Canvas"]
        dialog._search.setText("muted")
        shown = [item.text(0) for item, _g, _h in grid.settings
                 if not item.isHidden()]
        assert shown == ["Card body, unselected tab"]

    def test_it_searches_the_group_title_too(self, window):
        """So a whole section can be summoned by name, and a pair of
        settings under one heading comes back together."""
        dialog = SettingsDialog(window)
        grid = dialog._grids["Canvas"]
        dialog._search.setText("colour strength")
        shown = [item.text(0) for item, _g, _h in grid.settings
                 if not item.isHidden()]
        assert shown == ["Card body, unselected tab",
                         "Node header, selected tab"]

    def test_groups_with_no_match_leave_the_tree(self, window):
        dialog = SettingsDialog(window)
        rows = dict(self.nav_rows(dialog))
        dialog._search.setText("minimap")
        assert dict(self.nav_rows(dialog))["Canvas"] == ["Display"]
        dialog._search.setText("")
        assert dict(self.nav_rows(dialog)) == rows

    def test_pages_with_no_match_leave_the_nav(self, window):
        """A category still listed but empty when you click it is worse
        than no result at all."""
        dialog = SettingsDialog(window)
        dialog._search.setText("minimap")
        assert [page for page, _groups in self.nav_rows(dialog)] == ["Canvas"]

    def test_the_search_jumps_to_the_first_hit(self, window):
        dialog = SettingsDialog(window)
        dialog._search.setText("date formats")
        assert dialog._pages.currentIndex() == dialog._page_index["Table Node"]

    def test_clearing_the_search_restores_everything(self, window):
        dialog = SettingsDialog(window)
        before = self.nav_rows(dialog)
        dialog._search.setText("minimap")
        dialog._search.setText("")
        assert self.nav_rows(dialog) == before
        grid = dialog._grids["Canvas"]
        assert not any(item.isHidden() for item, _g, _h in grid.settings)

    def test_a_search_matching_nothing_empties_the_nav(self, window):
        dialog = SettingsDialog(window)
        dialog._search.setText("zzzznope")
        assert self.nav_rows(dialog) == []

    def test_selecting_a_group_shows_only_that_group(self, window):
        """The ask: clicking Display shows the display options and nothing
        else."""
        dialog = SettingsDialog(window)
        grid = dialog._grids["Canvas"]
        self.select(dialog, "Canvas", "Display")
        shown = [item.text(0) for item, _g, _h in grid.settings
                 if not item.isHidden()]
        assert shown == ["GPU-accelerated canvas (experimental)",
                         "Simplify nodes when zoomed out", "Zoom threshold",
                         "Show minimap", "Compact nodes", "Show port names",
                         "Show flow pins", "Show scroll bars",
                         "Double-click a node opens",
                         "Hold to show port names"]

    def test_selecting_the_page_shows_all_of_it(self, window):
        dialog = SettingsDialog(window)
        grid = dialog._grids["Canvas"]
        self.select(dialog, "Canvas", "Snapping")
        self.select(dialog, "Canvas", None)
        assert not any(item.isHidden() for item, _g, _h in grid.settings)

    def test_moving_between_groups_does_not_leak_rows(self, window):
        dialog = SettingsDialog(window)
        grid = dialog._grids["Canvas"]
        self.select(dialog, "Canvas", "Display")
        self.select(dialog, "Canvas", "Snapping")
        shown = [item.text(0) for item, _g, _h in grid.settings
                 if not item.isHidden()]
        assert shown == ["Show grid", "Snap to grid", "Grid resolution"]

    def test_a_search_reaches_groups_other_than_the_selected_one(self, window):
        """The case the explicit jump-to-first-hit exists for: the selected
        group still has matches, so nothing forces the selection to move,
        and matches in a *sibling* group would stay hidden behind it."""
        dialog = SettingsDialog(window)
        grid = dialog._grids["Canvas"]
        self.select(dialog, "Canvas", "Display")
        dialog._search.setText("canvas")
        groups = {g for item, g, _h in grid.settings if not item.isHidden()}
        assert groups == {"Display", "Drag-select", "Snapping"}

    def test_a_search_is_page_wide_despite_a_group_selection(self, window):
        """A match under a group you had not selected would otherwise be
        hidden by that selection, and the search would appear to fail."""
        dialog = SettingsDialog(window)
        grid = dialog._grids["Canvas"]
        self.select(dialog, "Canvas", "Snapping")
        dialog._search.setText("minimap")
        shown = [item.text(0) for item, _g, _h in grid.settings
                 if not item.isHidden()]
        assert shown == ["Show minimap"]


class TestNavSortOrder:
    def test_nav_entries_are_sorted_ascending(self, window):
        dialog = SettingsDialog(window)
        names = dialog.page_names()
        assert names == sorted(names)
