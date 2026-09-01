"""ideas.md (NEW list): "have flograph check for updates? settings -> check
for updates?"

A read-only version probe plus a once-a-day, opt-in, non-modal notice. The
constraints that matter and that these tests pin down:
  * off by default — no probe unless the user ticked the setting;
  * informative only — the helpers never build or run an install command;
  * quiet on failure — a blocked index or no network shows nothing;
  * never nags — the same new version is announced at most once.
"""
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QSettings

from flograph import packages
from flograph.ui import update_check


# --------------------------------------------------------------- packages

class TestPipIndexParsing:
    def test_pulls_the_version_list(self):
        out = ("flograph (0.1.14)\n"
               "Available versions: 0.1.14, 0.1.12, 0.1.11, 0.1.10\n"
               "  INSTALLED: 0.1.12\n")
        assert packages._parse_pip_index_output(out) == [
            "0.1.14", "0.1.12", "0.1.11", "0.1.10"]

    def test_empty_when_the_line_is_absent(self):
        assert packages._parse_pip_index_output("ERROR: nope") == []


class TestLatestAvailableVersion:
    def test_prefers_the_configured_index_over_pypi(self, monkeypatch):
        monkeypatch.setattr(packages, "_pip_index_versions",
                            lambda *a, **k: ["0.1.10", "0.2.0", "0.1.9"])
        monkeypatch.setattr(packages, "_pypi_latest_version",
                            lambda *a, **k: pytest.fail("PyPI was consulted"))
        assert packages.latest_available_version() == "0.2.0"

    def test_falls_back_to_pypi_when_the_index_is_silent(self, monkeypatch):
        monkeypatch.setattr(packages, "_pip_index_versions",
                            lambda *a, **k: [])
        monkeypatch.setattr(packages, "_pypi_latest_version",
                            lambda *a, **k: "9.9.9")
        assert packages.latest_available_version() == "9.9.9"

    def test_none_when_nothing_answers(self, monkeypatch):
        monkeypatch.setattr(packages, "_pip_index_versions",
                            lambda *a, **k: [])
        monkeypatch.setattr(packages, "_pypi_latest_version",
                            lambda *a, **k: None)
        assert packages.latest_available_version() is None


class TestUpdateStatus:
    def test_reports_a_newer_release(self, monkeypatch):
        monkeypatch.setattr(packages, "installed_version", lambda: "0.1.12")
        monkeypatch.setattr(packages, "latest_available_version",
                            lambda: "0.1.14")
        assert packages.update_status() == ("0.1.12", "0.1.14", True)

    def test_not_newer_when_level(self, monkeypatch):
        monkeypatch.setattr(packages, "installed_version", lambda: "0.1.14")
        monkeypatch.setattr(packages, "latest_available_version",
                            lambda: "0.1.14")
        assert packages.update_status() == ("0.1.14", "0.1.14", False)

    def test_not_newer_when_ahead(self, monkeypatch):
        """A dev build can be in front of the index — never cry update."""
        monkeypatch.setattr(packages, "installed_version", lambda: "0.2.0")
        monkeypatch.setattr(packages, "latest_available_version",
                            lambda: "0.1.14")
        assert packages.update_status()[2] is False

    def test_shrugs_when_the_check_cannot_run(self, monkeypatch):
        monkeypatch.setattr(packages, "installed_version", lambda: "0.1.12")
        monkeypatch.setattr(packages, "latest_available_version",
                            lambda: None)
        assert packages.update_status() == ("0.1.12", None, False)

    def test_never_raises(self, monkeypatch):
        def boom():
            raise RuntimeError("index on fire")
        monkeypatch.setattr(packages, "latest_available_version", boom)
        monkeypatch.setattr(packages, "installed_version", lambda: "0.1.12")
        assert packages.update_status() == ("0.1.12", None, False)


class TestUpgradeHint:
    def test_plain_pip_by_default(self, monkeypatch):
        monkeypatch.setattr(packages.sys, "frozen", False, raising=False)
        monkeypatch.setattr(packages, "installer_kind", lambda: "pip")
        assert packages.upgrade_hint() == "pip install --upgrade flograph"

    def test_uv_form_in_a_uv_venv(self, monkeypatch):
        monkeypatch.setattr(packages.sys, "frozen", False, raising=False)
        monkeypatch.setattr(packages, "installer_kind", lambda: "uv")
        assert packages.upgrade_hint() == "uv pip install --upgrade flograph"

    def test_points_at_releases_when_frozen(self, monkeypatch):
        monkeypatch.setattr(packages.sys, "frozen", True, raising=False)
        assert "releases" in packages.upgrade_hint()

    def test_hint_is_never_a_runnable_argv(self, monkeypatch):
        """It is copy-and-paste text for the user, not something flograph
        feeds to a subprocess — a list would mean someone wired it up."""
        monkeypatch.setattr(packages.sys, "frozen", False, raising=False)
        monkeypatch.setattr(packages, "installer_kind", lambda: "pip")
        assert isinstance(packages.upgrade_hint(), str)


# ------------------------------------------------------------- throttle

class TestDueForCheck:
    NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    def test_due_when_never_checked(self):
        assert update_check.due_for_check(None, self.NOW) is True
        assert update_check.due_for_check("", self.NOW) is True

    def test_due_when_the_stamp_is_unreadable(self):
        assert update_check.due_for_check("not-a-date", self.NOW) is True

    def test_not_due_within_the_day(self):
        recent = (self.NOW - timedelta(hours=3)).isoformat()
        assert update_check.due_for_check(recent, self.NOW) is False

    def test_due_again_after_a_day(self):
        old = (self.NOW - timedelta(hours=25)).isoformat()
        assert update_check.due_for_check(old, self.NOW) is True


# ------------------------------------------------------- startup check

@pytest.fixture
def fake_window(tmp_path):
    class _Win:
        def __init__(self):
            self.settings = QSettings(str(tmp_path / "s.ini"),
                                      QSettings.IniFormat)
        def isVisible(self):
            return True
    return _Win()


@pytest.fixture
def captured_probe(monkeypatch):
    """Replace the background probe with a hook that fires a chosen result
    synchronously, and record every toast raised."""
    state = {"calls": 0, "result": ("0.1.12", "0.1.14", True), "toasts": []}

    def fake_run_probe(on_done):
        state["calls"] += 1
        on_done(*state["result"])

    monkeypatch.setattr(update_check, "run_probe", fake_run_probe)
    monkeypatch.setattr(update_check, "UpdateToast",
                        lambda window, latest: state["toasts"].append(latest)
                        or _NoToast())
    return state


class _NoToast:
    def show_in_corner(self):
        pass


class TestMaybeCheckOnStartup:
    def test_does_nothing_unless_opted_in(self, fake_window, captured_probe):
        update_check.maybe_check_on_startup(fake_window)
        assert captured_probe["calls"] == 0

    def test_checks_and_notifies_when_enabled(self, fake_window, captured_probe):
        fake_window.settings.setValue("updates/notify", True)
        update_check.maybe_check_on_startup(fake_window)
        assert captured_probe["calls"] == 1
        assert captured_probe["toasts"] == ["0.1.14"]
        assert fake_window.settings.value("updates/last_check", "", type=str)

    def test_second_launch_same_day_does_not_recheck(self, fake_window,
                                                     captured_probe):
        fake_window.settings.setValue("updates/notify", True)
        update_check.maybe_check_on_startup(fake_window)
        update_check.maybe_check_on_startup(fake_window)
        assert captured_probe["calls"] == 1

    def test_same_version_is_announced_only_once(self, fake_window,
                                                 captured_probe, monkeypatch):
        fake_window.settings.setValue("updates/notify", True)
        update_check.maybe_check_on_startup(fake_window)
        # force the throttle open again, same available version
        fake_window.settings.setValue("updates/last_check", "2000-01-01T00:00")
        update_check.maybe_check_on_startup(fake_window)
        assert captured_probe["toasts"] == ["0.1.14"]       # not twice

    def test_no_toast_when_up_to_date(self, fake_window, captured_probe):
        captured_probe["result"] = ("0.1.14", "0.1.14", False)
        fake_window.settings.setValue("updates/notify", True)
        update_check.maybe_check_on_startup(fake_window)
        assert captured_probe["toasts"] == []
        assert fake_window.settings.value("updates/last_check", "", type=str)

    def test_stamps_the_check_even_when_offline(self, fake_window,
                                                captured_probe):
        captured_probe["result"] = ("0.1.12", None, False)
        fake_window.settings.setValue("updates/notify", True)
        update_check.maybe_check_on_startup(fake_window)
        assert captured_probe["toasts"] == []
        assert fake_window.settings.value("updates/last_check", "", type=str)


# ------------------------------------------------------------- the toast

class TestUpdateToast:
    def test_shows_and_dismisses(self, qtbot):
        from PySide6.QtWidgets import QLabel, QMainWindow
        host = QMainWindow()
        qtbot.addWidget(host)
        host.resize(800, 600)
        toast = update_check.UpdateToast(host, "0.1.14")
        toast.show_in_corner()
        assert not toast.isHidden()          # parent isn't shown in tests
        labels = " ".join(w.text() for w in toast.findChildren(QLabel))
        assert "0.1.14" in labels
        toast.close()
        assert toast.isHidden()

    def test_click_opens_the_details(self, qtbot):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QMainWindow

        opened = []

        class _Host(QMainWindow):
            def show_update_details(self):
                opened.append(True)

        host = _Host()
        qtbot.addWidget(host)
        toast = update_check.UpdateToast(host, "0.1.14")
        toast.show_in_corner()
        press = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(5, 5),
                            QPointF(5, 5), Qt.LeftButton, Qt.LeftButton,
                            Qt.NoModifier)
        toast.mouseReleaseEvent(press)
        assert opened == [True]


# ----------------------------------------------------- settings surface

@pytest.fixture(scope="module")
def registry():
    from flograph.core import NodeRegistry
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings as _QS

    from flograph.ui import mainwindow as mod
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: _QS(str(tmp_path / "w.ini"), _QS.IniFormat))
    win = mod.MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


class TestSettingsSurface:
    def _dialog(self, window):
        from flograph.ui.settings_dialog import SettingsDialog
        return SettingsDialog(window)

    def test_notify_toggle_defaults_off_and_persists(self, window):
        from PySide6.QtWidgets import QCheckBox
        dialog = self._dialog(window)
        check = dialog.findChild(QCheckBox, "update_notify_checkbox")
        assert check is not None
        assert check.isChecked() is False
        check.setChecked(True)
        assert window.settings.value("updates/notify", False, type=bool) is True

    def test_about_page_has_a_check_button(self, window, monkeypatch):
        from PySide6.QtWidgets import QLabel, QPushButton

        from flograph.ui import update_check as uc
        dialog = self._dialog(window)
        btn = dialog.findChild(QPushButton, "check_updates_button")
        result = dialog.findChild(QLabel, "update_result_label")
        assert btn is not None and result is not None

        monkeypatch.setattr(uc, "run_probe",
                            lambda cb: cb("0.1.12", "0.1.14", True))
        btn.click()
        assert "0.1.14" in result.text()

    def test_check_button_reports_up_to_date(self, window, monkeypatch):
        from PySide6.QtWidgets import QLabel, QPushButton

        from flograph.ui import update_check as uc
        dialog = self._dialog(window)
        btn = dialog.findChild(QPushButton, "check_updates_button")
        result = dialog.findChild(QLabel, "update_result_label")
        monkeypatch.setattr(uc, "run_probe",
                            lambda cb: cb("0.1.14", "0.1.14", False))
        btn.click()
        assert "latest" in result.text().lower()

    def test_check_button_handles_a_failed_probe(self, window, monkeypatch):
        from PySide6.QtWidgets import QLabel, QPushButton

        from flograph.ui import update_check as uc
        dialog = self._dialog(window)
        btn = dialog.findChild(QPushButton, "check_updates_button")
        result = dialog.findChild(QLabel, "update_result_label")
        monkeypatch.setattr(uc, "run_probe",
                            lambda cb: cb("0.1.12", None, False))
        btn.click()
        assert "couldn't" in result.text().lower()

    def test_update_details_opens_about(self, window):
        window.show_update_details()
        assert window._settings_dialog is not None
        assert window._settings_dialog._scope()[0] == "About"
