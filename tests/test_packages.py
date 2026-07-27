"""Package-management helpers and the Packages dialog."""
import sys

import pytest

from flograph import packages


class TestParquetProblem:
    def test_silent_when_pyarrow_is_usable(self):
        pytest.importorskip("pyarrow")
        assert packages.parquet_problem("auto") == ""
        assert packages.parquet_problem("pyarrow") == ""

    def test_silent_for_installed_fastparquet(self):
        pytest.importorskip("fastparquet")
        assert packages.parquet_problem("fastparquet") == ""

    def test_named_engine_reports_only_its_own_package(self, monkeypatch):
        """Choosing fastparquet must not be blocked by a missing pyarrow."""
        monkeypatch.setattr(packages.importlib.util, "find_spec",
                            lambda name: None if name == "pyarrow" else object())
        assert packages.parquet_problem("fastparquet") == ""
        assert "pyarrow package" in packages.parquet_problem("pyarrow")

    def test_auto_falls_back_to_fastparquet(self, monkeypatch):
        monkeypatch.setattr(packages.importlib.util, "find_spec",
                            lambda name: None if name == "pyarrow" else object())
        assert packages.parquet_problem("auto") == ""

    def test_auto_reports_when_neither_engine_exists(self, monkeypatch):
        monkeypatch.setattr(packages.importlib.util, "find_spec",
                            lambda name: None)
        assert "either" in packages.parquet_problem("auto")

    def test_reports_pandas_stale_after_late_install(self, monkeypatch):
        """pandas thinks pyarrow is absent, pyarrow says it is modern: the
        state that makes to_parquet die on an unrelated ArrowKeyError."""
        pytest.importorskip("pyarrow")
        import pandas.compat.pyarrow as compat
        monkeypatch.setattr(compat, "pa_version_under14p1", True)
        assert "Restart flograph" in packages.parquet_problem("auto")

    def test_stale_check_skipped_for_fastparquet(self, monkeypatch):
        """fastparquet does not go through pandas' pyarrow compat flags."""
        pytest.importorskip("fastparquet")
        import pandas.compat.pyarrow as compat
        monkeypatch.setattr(compat, "pa_version_under14p1", True)
        assert packages.parquet_problem("fastparquet") == ""

    def test_quiet_for_a_genuinely_old_pyarrow(self, monkeypatch):
        """A real pre-14.0.1 pyarrow sets the same flag legitimately, and
        pandas' own patching handles it — do not cry restart at it."""
        pyarrow = pytest.importorskip("pyarrow")
        import pandas.compat.pyarrow as compat
        monkeypatch.setattr(compat, "pa_version_under14p1", True)
        monkeypatch.setattr(pyarrow, "__version__", "13.0.0")
        assert packages.parquet_problem("auto") == ""


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
        from flograph.ui.packages_dialog import PackagesDialog
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

        from flograph.ui.packages_dialog import PackagesDialog
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

    def test_install_invalidates_import_caches(self, qtbot, monkeypatch):
        """A package installed mid-session must become importable, and the
        user must be told a restart is still needed — pandas caches
        pyarrow's absence at import time and cannot be told otherwise."""
        import importlib

        from flograph.ui.packages_dialog import PackagesDialog
        dialog = PackagesDialog()
        qtbot.addWidget(dialog)
        called = []
        monkeypatch.setattr(importlib, "invalidate_caches",
                            lambda: called.append(True))
        dialog._on_finished("install", 0)
        assert called, "import caches were not invalidated after an install"
        assert "restart" in dialog._log.toPlainText().lower()

    def test_not_busy_initially(self, qtbot):
        from flograph.ui.packages_dialog import PackagesDialog
        dialog = PackagesDialog()
        qtbot.addWidget(dialog)
        assert not dialog.busy
