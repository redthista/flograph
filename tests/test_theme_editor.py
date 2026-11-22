"""The theme customiser: writing a theme file, and the window that edits one."""
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui import theme, themes
from flograph.ui.theme_editor import ThemeCustomiser


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    ini = str(tmp_path / "s.ini")
    monkeypatch.setattr(
        mod, "QSettings", lambda *a, **k: QSettings(ini, QSettings.IniFormat))
    monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path / "user"))
    yield
    app = QApplication.instance()
    if app is not None:
        theme.apply_theme(app, "dark")


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


class TestFile:
    def test_slug(self):
        assert themes.slug("  My Theme!  ") == "my_theme"
        assert themes.slug("***") == "custom"

    def test_roundtrip_keeps_only_the_differences(self, tmp_path):
        name = themes.save_user(
            tmp_path, "Mine", "light", "light",
            {"canvas": {"CANVAS_BG": "#112233"},
             "style": {"node_shadow": False, "divider_width": 3,
                       "card_shadow": "dark"},
             "frame": {"FRAME_FILL": 0.5}})
        t = themes.load(name, tmp_path)
        assert t.label == "Mine" and t.kind == "light"
        assert t.get("canvas", "CANVAS_BG") == "#112233"
        assert t.get("style", "node_shadow") is False
        assert t.get("style", "divider_width") == 3
        assert t.get("frame", "FRAME_FILL") == 0.5
        # everything not listed still comes from the base
        light = themes.load("light")
        assert t.get("ui", "window") == light.get("ui", "window")

    def test_a_builtin_name_is_never_used(self, tmp_path):
        name = themes.save_user(tmp_path, "Dark", "dark", "dark", {})
        assert name == "dark_custom"
        assert not (tmp_path / "dark.toml").exists()

    def test_with_overrides_leaves_the_base_alone(self):
        base = themes.load("light")
        t = themes.with_overrides(base, {"ui": {"window": "#010203"}})
        assert t.get("ui", "window") == "#010203"
        assert base.get("ui", "window") != "#010203"


class TestWindow:
    def test_editing_previews_live_and_close_restores(self, window, qtbot):
        dlg = ThemeCustomiser(window)
        qtbot.addWidget(dlg)
        before = theme.CANVAS_BG.name()
        _, row = dlg._rows[("canvas", "CANVAS_BG")]
        row.set_value("#123456")
        row._emit("#123456")
        qtbot.waitUntil(lambda: theme.CANVAS_BG.name() == "#123456",
                        timeout=2000)
        dlg.close()
        assert theme.CANVAS_BG.name() == before

    def test_save_writes_a_file_with_just_the_change_and_uses_it(
            self, window, qtbot, tmp_path):
        dlg = ThemeCustomiser(window)
        qtbot.addWidget(dlg)
        dlg.label.setText("Steel Blue")
        _, row = dlg._rows[("canvas", "CANVAS_BG")]
        row._emit("#123456")
        dlg._save()
        path = tmp_path / "user" / "themes" / "steel_blue.toml"
        assert path.exists()
        text = path.read_text()
        assert "CANVAS_BG" in text and "NODE_BODY" not in text
        assert window.theme_pref == "steel_blue"
        assert theme.CANVAS_BG.name() == "#123456"

    def test_resaving_a_user_theme_keeps_its_earlier_changes(
            self, window, qtbot, tmp_path):
        dlg = ThemeCustomiser(window)
        qtbot.addWidget(dlg)
        dlg.label.setText("Mine")
        dlg._rows[("canvas", "CANVAS_BG")][1]._emit("#111111")
        dlg._save()
        dlg._rows[("canvas", "NODE_BODY")][1]._emit("#222222")
        dlg._save()                      # same name: overwrite, no prompt
        t = themes.load("mine", tmp_path / "user" / "themes")
        assert t.get("canvas", "CANVAS_BG") == "#111111"
        assert t.get("canvas", "NODE_BODY") == "#222222"

    def test_text_mode_edits_preview_live_and_save(self, window, qtbot,
                                                   tmp_path):
        dlg = ThemeCustomiser(window)
        qtbot.addWidget(dlg)
        dlg.tabs.setCurrentIndex(1)
        text = dlg.text.toPlainText()
        assert "[canvas]" in text and "CANVAS_BG" in text
        old = theme.CANVAS_BG.name()
        dlg.text.setPlainText(text.replace(f'CANVAS_BG = "{old}"',
                                           'CANVAS_BG = "#0a0b0c"'))
        qtbot.waitUntil(lambda: theme.CANVAS_BG.name() == "#0a0b0c",
                        timeout=2000)
        assert dlg._over == {"canvas": {"CANVAS_BG": "#0a0b0c"}}
        # the colour list follows when you go back to it
        dlg.tabs.setCurrentIndex(0)
        assert dlg._rows[("canvas", "CANVAS_BG")][1].hex.text() == "#0a0b0c"
        dlg.tabs.setCurrentIndex(1)
        dlg.label.setText("From Text")
        dlg._save()
        saved = (tmp_path / "user" / "themes" / "from_text.toml").read_text()
        assert "#0a0b0c" in saved and "NODE_BODY" not in saved

    def test_a_bad_line_keeps_the_last_good_preview(self, window, qtbot):
        dlg = ThemeCustomiser(window)
        qtbot.addWidget(dlg)
        dlg.tabs.setCurrentIndex(1)
        text = dlg.text.toPlainText()
        old = theme.CANVAS_BG.name()
        dlg.text.setPlainText(text.replace(f'CANVAS_BG = "{old}"',
                                           'CANVAS_BG = "nope"'))
        qtbot.waitUntil(lambda: bool(dlg.text._diagnostics), timeout=2000)
        assert dlg.text._diagnostics[0].message.startswith("CANVAS_BG")
        assert theme.CANVAS_BG.name() == old
        assert "Line" in dlg.note.text()

    def test_selecting_an_element_cuts_the_list_to_its_settings(
            self, window, qtbot):
        from flograph.ui.theme_editor import Element
        dlg = ThemeCustomiser(window)
        qtbot.addWidget(dlg)
        dlg.show()
        keys = [("canvas", "NODE_BODY"), ("canvas", "NODE_HEADER")]
        dlg.select_element(Element("Node", [("Node", None, keys)]))
        shown = [(s, k) for (s, k), (item, _) in dlg._rows.items()
                 if not item.isHidden()]
        assert sorted(shown) == sorted(keys)
        assert dlg.banner.isVisible() and "Node" in dlg.banner_text.text()
        dlg._clear_pick()
        assert not dlg.banner.isVisible()
        assert all(not item.isHidden() for item, _ in dlg._rows.values())

    def test_clicking_the_empty_canvas_finds_the_canvas_settings(
            self, window, qtbot):
        from flograph.ui.theme_editor import element_at
        window.resize(1200, 800)
        window.show()
        qtbot.waitExposed(window)
        view = window.view.viewport()
        element = element_at(view.mapToGlobal(view.rect().center()),
                             theme.current())
        assert element is not None
        assert ("canvas", "CANVAS_BG") in element.keys

    def test_clicking_a_panel_ranks_settings_named_like_it(self, window,
                                                           qtbot):
        from flograph.ui.theme_editor import element_at
        window.resize(1200, 800)
        window.show()
        qtbot.waitExposed(window)
        status = window.statusBar()
        element = element_at(status.mapToGlobal(status.rect().center()),
                             theme.current())
        assert element is not None and element.keys

    def test_a_change_applies_once_and_stays(self, window, qtbot,
                                             monkeypatch):
        """Re-theming re-colours the text editor, which reports 'text
        changed'. That once read the stale text back over the colour just
        picked and re-themed again, forever: lag, and the value reverting."""
        dlg = ThemeCustomiser(window)
        qtbot.addWidget(dlg)
        dlg.show()
        calls = []
        real = theme.apply_theme
        monkeypatch.setattr(theme, "apply_theme",
                            lambda *a, **k: (calls.append(1), real(*a, **k)))
        dlg._rows[("canvas", "CANVAS_BG")][1]._emit("#ff0000")
        qtbot.wait(1500)
        assert len(calls) == 1
        assert theme.CANVAS_BG.name() == "#ff0000"
        assert dlg._over == {"canvas": {"CANVAS_BG": "#ff0000"}}

    def test_the_gutter_fits_the_text_and_the_caret_line_keeps_its_swatch(
            self, window, qtbot):
        from PySide6.QtGui import QTextCursor
        dlg = ThemeCustomiser(window)
        qtbot.addWidget(dlg)
        dlg.show()
        dlg.tabs.setCurrentIndex(1)
        # the gutter is as wide as the box's left margin, or it covers text
        assert (dlg.text.viewportMargins().left()
                == dlg.text.gutter_width())
        # the line the caret is on still gets its colours drawn
        cursor = dlg.text.textCursor()
        cursor.movePosition(QTextCursor.Start)
        cursor.movePosition(QTextCursor.Down, QTextCursor.MoveAnchor, 3)
        dlg.text.setTextCursor(cursor)
        text = cursor.block().text()
        assert '"#' in text
        swatches = dlg.text.extra_selections_hook()
        assert len(swatches) == 1
        assert swatches[0].format.background().color().name() in text

    def test_selected_setting_says_what_it_does(self, window, qtbot):
        dlg = ThemeCustomiser(window)
        qtbot.addWidget(dlg)
        item = dlg._rows[("ui", "mid")][0]
        dlg.tree.setCurrentItem(item)
        assert "DIM TEXT" in dlg.help.text() and "ui.mid" in dlg.help.text()
        assert item.toolTip(0)

    def test_checks_list_follows_the_edit_and_leads_to_the_settings(
            self, window, qtbot):
        dlg = ThemeCustomiser(window)
        qtbot.addWidget(dlg)
        dlg.show()
        dlg._load_base("light")
        assert dlg.checks_list.count() == 0
        assert not dlg.checks_toggle.isEnabled()
        dlg._rows[("wires", "dataframe")][1]._emit("#e0e0e0")
        dlg._refresh_checks()
        assert dlg.checks_list.count() >= 1
        assert dlg.checks_toggle.isEnabled()
        dlg.checks_toggle.setChecked(True)
        dlg._check_clicked(dlg.checks_list.item(0))
        assert dlg.tabs.currentIndex() == 0
        assert ("wires", "dataframe") in dlg._picked_keys

    def test_preview_tab_draws_in_every_theme(self, window, qtbot):
        dlg = ThemeCustomiser(window)
        qtbot.addWidget(dlg)
        dlg.show()
        for name in ("dark", "light", "light_steel"):
            dlg._load_base(name)
            dlg._preview()
            dlg.tabs.setCurrentIndex(2)
            image = dlg.tabs.currentWidget().grab().toImage()
            assert image.width() > 100
        # the canvas sample takes the theme's node shape
        from flograph.ui.theme_preview import MiniCanvas
        canvas = dlg.tabs.currentWidget().findChild(MiniCanvas)
        assert canvas.grab().toImage().pixelColor(2, 2) == theme.CANVAS_BG

    def test_menu_opens_it(self, window, qtbot):
        window._show_theme_editor()
        qtbot.addWidget(window._theme_editor)
        assert window._theme_editor.isVisible()
        window._theme_editor.close()
