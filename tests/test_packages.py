"""Package-management helpers and the Packages dialog."""
import sys

import pytest

from flopy import packages


class TestHelpers:
    def test_list_installed_contains_deps(self):
        names = [name for name, _version in packages.list_installed()]
        assert "pandas" in names
        assert names == sorted(names)

    def test_installer_is_available_here(self):
        # dev envs always have pip or uv; the dialog depends on this signal
        assert packages.installer_kind() in ("pip", "uv")

    def test_validate_rejects_options(self):
        with pytest.raises(ValueError, match="not a package"):
            packages.validate_requirements(["-r", "evil.txt"])

    def test_validate_rejects_empty(self):
        with pytest.raises(ValueError, match="no packages"):
            packages.validate_requirements(["  ", ""])

    def test_build_command_shapes(self, monkeypatch):
        monkeypatch.setattr(packages, "installer_kind", lambda: "pip")
        argv = packages.build_command("install", ["requests==2.31"])
        assert argv[:3] == [sys.executable, "-m", "pip"]
        assert argv[3:] == ["install", "requests==2.31"]
        assert "--upgrade" in packages.build_command("upgrade", ["requests"])
        assert "-y" in packages.build_command("uninstall", ["requests"])

    def test_build_command_uv_targets_this_interpreter(self, monkeypatch):
        monkeypatch.setattr(packages, "installer_kind", lambda: "uv")
        monkeypatch.setattr(packages.shutil, "which", lambda _: "/usr/bin/uv")
        argv = packages.build_command("install", ["requests"])
        assert argv[:2] == ["/usr/bin/uv", "pip"]
        assert sys.executable in argv

    def test_build_command_no_installer(self, monkeypatch):
        monkeypatch.setattr(packages, "installer_kind", lambda: None)
        with pytest.raises(RuntimeError, match="no installer"):
            packages.build_command("install", ["requests"])

    def test_build_command_unknown_action(self):
        with pytest.raises(ValueError, match="unknown action"):
            packages.build_command("explode", ["requests"])


class TestDialog:
    def test_lists_and_filters(self, qtbot):
        from flopy.ui.packages_dialog import PackagesDialog
        dialog = PackagesDialog()
        qtbot.addWidget(dialog)
        table = dialog._table
        assert table.rowCount() > 0
        dialog._filter.setText("pandas")
        visible = [table.item(r, 0).text() for r in range(table.rowCount())
                   if not table.isRowHidden(r)]
        assert visible and all("pandas" in name for name in visible)
        dialog._filter.setText("")
        assert not table.isRowHidden(0)

    def test_uninstall_refuses_core_packages(self, qtbot, monkeypatch):
        from PySide6.QtWidgets import QMessageBox

        from flopy.ui.packages_dialog import PackagesDialog
        dialog = PackagesDialog()
        qtbot.addWidget(dialog)
        warned = []
        monkeypatch.setattr(QMessageBox, "warning",
                            lambda *a, **k: warned.append(a))
        monkeypatch.setattr(dialog, "_selected_packages", lambda: ["pandas"])
        started = []
        monkeypatch.setattr(dialog, "_run_installer",
                            lambda *a: started.append(a))
        dialog._uninstall()
        assert warned and not started

    def test_not_busy_initially(self, qtbot):
        from flopy.ui.packages_dialog import PackagesDialog
        dialog = PackagesDialog()
        qtbot.addWidget(dialog)
        assert not dialog.busy
