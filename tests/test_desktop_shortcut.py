"""File > Create Desktop Shortcut.

The point of the feature is that the shortcut relaunches *this* flograph:
the interpreter that already has PySide6 in it, and the same start-up route
(one-file bundle vs installed package vs checkout) the user is on now. These
tests pin the resolution of that command, the file each platform writes, and
the dialog that drives both.
"""
from __future__ import annotations

import shlex
import struct
import subprocess
import sys
import types
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from flograph.core import NodeRegistry
from flograph.ui import desktop_shortcut as ds
from flograph.ui import mainwindow as mod

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    """Point every writer at a throwaway Desktop."""
    folder = tmp_path / "Desktop"
    folder.mkdir()
    monkeypatch.setattr(ds, "desktop_dir", lambda: folder)
    return folder


@pytest.fixture(autouse=True)
def _fake_xdg_dirs(tmp_path, monkeypatch):
    """Never write to the real ~/.local/share — these are the user's own
    applications menu and icon theme."""
    apps = tmp_path / "xdg" / "applications"
    icons = tmp_path / "xdg" / "icons" / "hicolor"
    monkeypatch.setattr(ds, "applications_dir", lambda: apps)
    monkeypatch.setattr(ds, "icon_theme_dir", lambda: icons)
    return apps, icons


@pytest.fixture(autouse=True)
def _no_gio(monkeypatch):
    """The .desktop trust call is best-effort; don't touch the real session."""
    monkeypatch.setattr(ds.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))


class TestResolveLaunch:
    def test_onefile_points_at_the_bundle_not_the_temp_extraction(self, tmp_path):
        bundle = tmp_path / "flograph_onefile_9.9.9.py"
        bundle.write_text("# bundle\n")
        fake_main = types.SimpleNamespace(_BUNDLE_B64="…", __file__=str(bundle))

        launch = ds.resolve_launch(main_module=fake_main)

        assert launch.kind == "onefile"
        assert launch.argv == [ds.python_exe(), str(bundle)]
        assert launch.workdir == str(tmp_path)

    def test_installed_package_runs_dash_m(self):
        launch = ds.resolve_launch(main_module=types.SimpleNamespace(),
                                   probe=lambda _: True)

        assert launch.kind == "module"
        assert launch.argv == [ds.python_exe(), "-m", "flograph"]

    def test_uninstalled_checkout_falls_back_to_main_py(self):
        launch = ds.resolve_launch(main_module=types.SimpleNamespace(),
                                   probe=lambda _: False)

        assert launch.kind == "source"
        assert Path(launch.argv[1]).name == "main.py"
        assert Path(launch.argv[1]).exists()

    def test_the_command_names_an_interpreter_never_bare_python(self):
        launch = ds.resolve_launch(main_module=types.SimpleNamespace(),
                                   probe=lambda _: True)

        # the venv's own interpreter, by absolute path — a shortcut inherits
        # the desktop's PATH, not ours
        assert Path(launch.argv[0]).is_absolute()
        assert Path(launch.argv[0]).exists()

    def test_a_project_is_appended_and_sets_the_working_directory(self, tmp_path):
        project = tmp_path / "sales.flograph"
        project.write_text("{}")

        launch = ds.resolve_launch(str(project),
                                   main_module=types.SimpleNamespace(),
                                   probe=lambda _: True)

        assert launch.argv[-1] == str(project)
        assert launch.workdir == str(tmp_path)

    def test_probe_ignores_our_pythonpath(self, monkeypatch):
        """A fresh interpreter is what matters: importable only because of
        this process's PYTHONPATH is a false yes for a desktop launch."""
        seen = {}

        def fake_run(argv, **kwargs):
            seen.update(kwargs.get("env", {}))
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr(ds.subprocess, "run", fake_run)
        monkeypatch.setenv("PYTHONPATH", "/somewhere/odd")

        assert ds.module_importable() is True
        assert "PYTHONPATH" not in seen

    def test_the_bundle_marker_the_detection_relies_on_still_exists(self):
        """A one-file bundle is recognised by the `_BUNDLE_B64` blob it
        carries; rename it in the builder and every bundle silently gets a
        `-m flograph` shortcut that won't run where it was handed over."""
        builder = (REPO_ROOT / "scripts" / "build_onefile.py").read_text()

        assert "_BUNDLE_B64 = " in builder

    def test_a_broken_interpreter_is_not_importable(self, monkeypatch):
        monkeypatch.setattr(ds.subprocess, "run",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("no exe")))

        assert ds.module_importable() is False


class TestNamesAndPaths:
    @pytest.mark.parametrize("raw, expected", [
        ("sales report", "sales report"),
        ("../../etc/passwd", ".. .. etc passwd"),
        ("a/b\\c:d*e?", "a b c d e"),
        ("trailing.", "trailing"),
        ("   ", ""),
    ])
    def test_names_cannot_escape_the_desktop(self, raw, expected):
        assert ds.clean_name(raw) == expected

    def test_shortcut_path_uses_the_platform_suffix(self, desktop):
        path = ds.shortcut_path("Sales")

        assert path.parent == desktop
        assert path.suffix == ds.shortcut_suffix()

    @pytest.mark.skipif(not sys.platform.startswith("linux"),
                        reason="XDG user-dirs is a Linux thing")
    def test_desktop_dir_honours_xdg_user_dirs(self, tmp_path, monkeypatch):
        config = tmp_path / "config"
        config.mkdir()
        (config / "user-dirs.dirs").write_text(
            '# generated\nXDG_DESKTOP_DIR="$HOME/Skrivbord"\n')
        monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
        ds.desktop_dir.cache_clear()

        try:
            assert ds.desktop_dir() == Path.home() / "Skrivbord"
        finally:
            ds.desktop_dir.cache_clear()


@pytest.mark.skipif(sys.platform == "win32" or sys.platform == "darwin",
                    reason="the .desktop writer")
class TestLinuxEntry:
    def test_it_writes_a_launchable_desktop_entry(self, desktop, tmp_path):
        launch = ds.resolve_launch(main_module=types.SimpleNamespace(),
                                   probe=lambda _: True)

        path = ds.create_shortcut("Sales flow", launch, icon=None)

        text = path.read_text()
        assert path == desktop / "Sales flow.desktop"
        assert "Type=Application" in text
        assert "Name=Sales flow" in text
        assert f"Exec={launch.argv[0]} -m flograph" in text
        assert "Terminal=false" in text
        assert path.stat().st_mode & 0o111  # executable, or nothing launches it

    def test_a_project_path_with_spaces_survives_the_exec_line(self, desktop, tmp_path):
        project = tmp_path / "quarterly report.flograph"
        project.write_text("{}")
        launch = ds.resolve_launch(str(project),
                                   main_module=types.SimpleNamespace(),
                                   probe=lambda _: True)

        text = ds.create_shortcut("Quarterly", launch, icon=None).read_text()

        exec_line = next(l for l in text.splitlines() if l.startswith("Exec="))
        # a launcher parses Exec= itself, so the path has to come back whole
        assert shlex.split(exec_line[len("Exec="):]) == launch.argv

    def test_the_icon_is_referenced_when_there_is_one(self, desktop, tmp_path):
        icon = ds.ensure_icon(tmp_path)
        launch = ds.resolve_launch(main_module=types.SimpleNamespace(),
                                   probe=lambda _: True)

        text = ds.create_shortcut("Iconned", launch, icon=icon).read_text()

        assert f"Icon={icon}" in text

    def test_it_claims_the_running_window_for_the_launcher(self, desktop):
        launch = ds.resolve_launch(main_module=types.SimpleNamespace(),
                                   probe=lambda _: True)

        text = ds.create_shortcut("Docked", launch, icon=None).read_text()

        # has to match QApplication.setDesktopFileName, or a dock shows the
        # running window as a second, iconless entry
        assert "StartupWMClass=flograph" in text


class TestIcon:
    def test_it_paints_a_real_image_file(self, tmp_path):
        path = ds.ensure_icon(tmp_path)

        assert path is not None and path.exists()
        head = path.read_bytes()[:8]
        if path.suffix == ".ico":
            assert head[:4] == b"\x00\x00\x01\x00"
        else:
            assert head == b"\x89PNG\r\n\x1a\n"

    def test_the_ico_directory_points_at_every_image_it_holds(self):
        entries = [(16, b"small"), (256, b"large" * 3)]

        ico = ds._ico_bytes(entries)

        assert ico[:4] == b"\x00\x00\x01\x00"
        assert struct.unpack("<H", ico[4:6])[0] == 2
        for index, (size, payload) in enumerate(entries):
            row = ico[6 + 16 * index:22 + 16 * index]
            width, height = row[0], row[1]
            length, offset = struct.unpack("<II", row[8:16])
            # 256 is spelled 0 in a directory row
            assert (width, height) == ((0, 0) if size == 256 else (size, size))
            assert ico[offset:offset + length] == payload

    def test_the_windows_icon_carries_the_small_sizes_as_bitmaps(self, monkeypatch):
        monkeypatch.setattr(ds.sys, "platform", "win32")

        ico = ds._icon_bytes()

        count = struct.unpack("<H", ico[4:6])[0]
        assert count == len(ds._ICON_SIZES)
        payloads = []
        for index in range(count):
            row = ico[6 + 16 * index:22 + 16 * index]
            length, offset = struct.unpack("<II", row[8:16])
            payloads.append((row[0], ico[offset:offset + length]))
        # a PNG-only .ico is the form parts of the Windows shell decline to
        # read, so everything under 256 has to be a BITMAPINFOHEADER
        for width, payload in payloads:
            if width == 0:
                assert payload[:8] == b"\x89PNG\r\n\x1a\n"
            else:
                assert struct.unpack("<I", payload[:4])[0] == 40

    def test_the_name_changes_when_the_picture_does(self, tmp_path, monkeypatch):
        first = ds.ensure_icon(tmp_path)

        monkeypatch.setattr(ds, "_icon_bytes", lambda: b"a different mark")
        second = ds.ensure_icon(tmp_path)

        # Windows caches shell icons by path, so a redrawn mark has to land
        # at a new name or existing shortcuts keep the old picture
        assert first is not None and second is not None
        assert first.name != second.name
        assert not first.exists(), "the superseded icon should be swept up"

    def test_it_leaves_the_unversioned_icon_older_releases_wrote(self, tmp_path):
        legacy = tmp_path / "flograph.ico"
        legacy.write_bytes(b"an icon a live shortcut still points at")

        ds.ensure_icon(tmp_path)

        assert legacy.exists()


@pytest.mark.skipif(sys.platform == "win32" or sys.platform == "darwin",
                    reason="there is no applications directory to register with")
class TestApplicationsMenu:
    def test_the_entry_is_named_for_the_app_id_not_the_shortcut(self, _fake_xdg_dirs):
        apps, _ = _fake_xdg_dirs

        path = ds.install_menu_entry()

        # the running window's app id is setDesktopFileName's value, and the
        # file name is how a desktop matches window to launcher
        assert path == apps / "flograph.desktop"
        assert "Name=flograph" in path.read_text()

    def test_it_registers_the_app_not_the_project_being_shortcutted(
            self, _fake_xdg_dirs, tmp_path):
        project = tmp_path / "sales.flograph"
        project.write_text("{}")

        text = ds.install_menu_entry().read_text()

        exec_line = next(l for l in text.splitlines() if l.startswith("Exec="))
        assert "sales.flograph" not in exec_line
        assert "StartupWMClass=flograph" in text

    def test_the_icon_is_a_theme_name_not_the_shortcut_s_file(self, _fake_xdg_dirs):
        apps, icons = _fake_xdg_dirs

        text = ds.install_menu_entry().read_text()

        # a digest-named file gets swept when the mark is redrawn; the theme
        # name never moves, so the menu entry cannot go blank
        assert "Icon=flograph\n" in text
        assert (icons / "256x256" / "apps" / "flograph.png").exists()
        assert (icons / "48x48" / "apps" / "flograph.png").exists()

    def test_every_painted_size_reaches_the_theme(self, _fake_xdg_dirs):
        _, icons = _fake_xdg_dirs

        ds.install_theme_icon()

        for size in ds._ICON_SIZES:
            written = icons / f"{size}x{size}" / "apps" / "flograph.png"
            assert written.exists(), f"{size}px missing from the icon theme"
            assert written.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    def test_applications_dir_follows_xdg_data_home(self, tmp_path, monkeypatch):
        monkeypatch.undo()  # the autouse fixture stubs the function itself
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))

        assert ds.applications_dir() == tmp_path / "share" / "applications"
        assert ds.icon_theme_dir() == tmp_path / "share" / "icons" / "hicolor"

    def test_a_read_only_theme_loses_the_icon_not_the_entry(
            self, _fake_xdg_dirs, monkeypatch):
        monkeypatch.setattr(ds, "install_theme_icon", lambda root=None: False)

        text = ds.install_menu_entry().read_text()

        assert "Icon=" not in text
        assert "Exec=" in text

    def test_a_read_only_directory_loses_the_icon_not_the_shortcut(self, tmp_path):
        blocked = tmp_path / "nope"
        blocked.write_text("I am a file, not a directory")

        assert ds.ensure_icon(blocked) is None


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


class TestDialog:
    def test_the_file_menu_offers_it(self, window):
        # the QAction has to stay referenced or PySide takes its menu with it
        menu_actions = window._menu_root.actions()
        file_action = next(a for a in menu_actions if a.text() == "&File")

        entries = [a.text() for a in file_action.menu().actions()]

        assert any("Desktop Shortcut" in text for text in entries)

    def test_it_defaults_to_the_open_project_and_offers_to_open_it(
            self, qtbot, window, tmp_path):
        project = str(tmp_path / "sales.flograph")

        dialog = ds.ShortcutDialog(window, project)
        qtbot.addWidget(dialog)

        assert dialog.name_edit.text() == "sales"
        assert dialog.open_project.isChecked()
        assert dialog.launch().argv[-1] == project

    def test_unticking_drops_the_project_from_the_command(
            self, qtbot, window, tmp_path):
        dialog = ds.ShortcutDialog(window, str(tmp_path / "sales.flograph"))
        qtbot.addWidget(dialog)

        dialog.open_project.setChecked(False)

        assert not dialog.launch().argv[-1].endswith(".flograph")
        assert "sales.flograph" not in dialog.summary.text()

    def test_an_unsaved_project_cannot_be_pointed_at(self, qtbot, window):
        dialog = ds.ShortcutDialog(window, None)
        qtbot.addWidget(dialog)

        assert not dialog.open_project.isEnabled()
        assert not dialog.open_project.isChecked()
        assert dialog.name_edit.text() == "flograph"

    def test_the_summary_shows_the_command_and_the_destination(
            self, qtbot, window, desktop):
        dialog = ds.ShortcutDialog(window, None)
        qtbot.addWidget(dialog)

        text = dialog.summary.text()

        assert ds.python_exe() in text
        assert str(desktop) in text

    def test_a_nameless_shortcut_cannot_be_created(self, qtbot, window):
        dialog = ds.ShortcutDialog(window, None)
        qtbot.addWidget(dialog)

        dialog.name_edit.setText("   ")

        assert not dialog.create_button.isEnabled()

    def test_creating_writes_the_file_and_reports_where(
            self, qtbot, window, desktop, monkeypatch):
        monkeypatch.setattr(QMessageBox, "information",
                            lambda *a, **k: QMessageBox.Ok)
        dialog = ds.ShortcutDialog(window, None)
        qtbot.addWidget(dialog)
        dialog.name_edit.setText("flograph")

        dialog._create()

        assert dialog.created_path is not None
        assert dialog.created_path.exists()
        assert dialog.created_path.parent == desktop

    def test_an_existing_shortcut_is_only_replaced_on_a_yes(
            self, qtbot, window, desktop, monkeypatch):
        existing = desktop / ("keep me" + ds.shortcut_suffix())
        existing.write_text("original")
        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: QMessageBox.No)
        dialog = ds.ShortcutDialog(window, None)
        qtbot.addWidget(dialog)
        dialog.name_edit.setText("keep me")

        dialog._create()

        assert existing.read_text() == "original"
        assert dialog.created_path is None

    @pytest.mark.skipif(not sys.platform.startswith("linux"),
                        reason="the applications menu is a Linux thing")
    def test_ticking_the_menu_box_registers_the_app(
            self, qtbot, window, desktop, monkeypatch, _fake_xdg_dirs):
        apps, _ = _fake_xdg_dirs
        monkeypatch.setattr(QMessageBox, "information",
                            lambda *a, **k: QMessageBox.Ok)
        dialog = ds.ShortcutDialog(window, None)
        qtbot.addWidget(dialog)

        assert dialog.add_to_menu.isChecked()
        dialog._create()

        assert dialog.menu_entry_path == apps / "flograph.desktop"
        assert (apps / "flograph.desktop").exists()

    @pytest.mark.skipif(not sys.platform.startswith("linux"),
                        reason="the applications menu is a Linux thing")
    def test_unticking_it_writes_only_the_desktop_shortcut(
            self, qtbot, window, desktop, monkeypatch, _fake_xdg_dirs):
        apps, _ = _fake_xdg_dirs
        monkeypatch.setattr(QMessageBox, "information",
                            lambda *a, **k: QMessageBox.Ok)
        dialog = ds.ShortcutDialog(window, None)
        qtbot.addWidget(dialog)

        dialog.add_to_menu.setChecked(False)
        dialog._create()

        assert dialog.created_path.exists()
        assert dialog.menu_entry_path is None
        assert not (apps / "flograph.desktop").exists()

    @pytest.mark.skipif(not sys.platform.startswith("linux"),
                        reason="the applications menu is a Linux thing")
    def test_a_failed_menu_entry_still_leaves_the_shortcut(
            self, qtbot, window, desktop, monkeypatch):
        said = []
        monkeypatch.setattr(QMessageBox, "information",
                            lambda *a, **k: said.append(a[2]))
        monkeypatch.setattr(ds, "install_menu_entry", _explode)
        dialog = ds.ShortcutDialog(window, None)
        qtbot.addWidget(dialog)

        dialog._create()

        assert dialog.created_path is not None and dialog.created_path.exists()
        assert said and "couldn't be written" in said[0]

    def test_a_failed_write_is_reported_not_raised(
            self, qtbot, window, desktop, monkeypatch):
        warned = []
        monkeypatch.setattr(QMessageBox, "warning",
                            lambda *a, **k: warned.append(a[2]))
        monkeypatch.setattr(ds, "create_shortcut", _explode)
        dialog = ds.ShortcutDialog(window, None)
        qtbot.addWidget(dialog)

        dialog._create()

        assert warned and "read-only" in warned[0]
        assert dialog.created_path is None


def _explode(*args, **kwargs):
    raise RuntimeError("couldn't write /Desktop/flograph.desktop: read-only")
