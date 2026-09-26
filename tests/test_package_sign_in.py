"""Signing in to a private package index (JFrog, Artifactory) from Manage
Packages: the login goes into the index URL, the log never shows the
password, and an install the index turned away asks and runs again."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QLineEdit, QWidget

from flograph import packages
from flograph.packages import IndexLogin, PackageIndex
from flograph.ui import packages_dialog
from flograph.ui.packages_dialog import PackagesDialog, SignInDialog

MIRROR = "https://mirror.example.com/artifactory/api/pypi/pypi/simple"
HOST = "mirror.example.com"


@pytest.fixture
def uv(monkeypatch):
    monkeypatch.setattr(packages, "installer_kind", lambda: "uv")
    monkeypatch.setattr(packages.shutil, "which", lambda _: "/usr/bin/uv")


@pytest.fixture
def pip(monkeypatch):
    monkeypatch.setattr(packages, "installer_kind", lambda: "pip")


class TestTheLoginInTheUrl:

    def test_it_is_percent_encoded(self):
        url = packages.url_with_login(
            MIRROR, IndexLogin("me@corp.com", "p@ss:w/rd"))
        assert url == ("https://me%40corp.com:p%40ss%3Aw%2Frd"
                       "@mirror.example.com/artifactory/api/pypi/pypi/simple")

    def test_it_replaces_one_already_there(self):
        url = packages.url_with_login("https://old:x@h.example:8081/simple",
                                      IndexLogin("new", "y"))
        assert url == "https://new:y@h.example:8081/simple"
        assert packages.index_host(url) == "h.example:8081"

    def test_no_login_or_no_url_leaves_it(self):
        assert packages.url_with_login(MIRROR, None) == MIRROR
        assert packages.url_with_login(MIRROR, IndexLogin("")) == MIRROR
        assert packages.url_with_login("", IndexLogin("a", "b")) == ""
        assert packages.url_with_login("file:///srv/simple",
                                       IndexLogin("a", "b")) \
            == "file:///srv/simple"

    def test_the_log_sees_stars(self):
        login = IndexLogin("bob", "s3cret/key")
        line = "$ uv pip install --index-url " + packages.url_with_login(
            MIRROR, login) + " requests"
        shown = packages.redact(line, login)
        assert "s3cret" not in shown
        assert "https://bob:****@mirror.example.com" in shown
        # and wherever else the password turns up
        assert packages.redact("oops s3cret/key", login) == "oops ****"


class TestBuildingTheCommand:

    def test_uv_gets_the_setting_with_the_login(self, uv):
        argv = packages.build_command(
            "install", ["requests"], index=PackageIndex(MIRROR),
            environ={}, files=[], login=IndexLogin("bob", "pw"))
        assert argv[argv.index("--index-url") + 1] == \
            packages.url_with_login(MIRROR, IndexLogin("bob", "pw"))

    def test_pip_is_told_its_own_index_to_carry_the_login(self, pip):
        """With no flograph setting pip reads pip.conf — but the login can
        only travel in a URL, so that URL goes on the command line."""
        argv = packages.build_command(
            "upgrade", ["requests"], environ={"PIP_INDEX_URL": MIRROR},
            files=[], login=IndexLogin("bob", "pw"))
        assert "https://bob:pw@mirror.example.com" in \
            argv[argv.index("--index-url") + 1]

    def test_uvs_own_index_gets_the_login(self, uv):
        argv = packages.build_command(
            "install", ["requests"], environ={"UV_INDEX_URL": MIRROR},
            files=[], login=IndexLogin("bob", "pw"))
        assert "https://bob:pw@" in argv[argv.index("--index-url") + 1]

    def test_uninstalling_sends_no_login(self, pip):
        argv = packages.build_command(
            "uninstall", ["requests"], index=PackageIndex(MIRROR),
            environ={}, files=[], login=IndexLogin("bob", "pw"))
        assert not any("pw" in a for a in argv[3:])


class TestReadingTheInstaller:

    def test_pips_prompt(self):
        out = "Looking in indexes: " + MIRROR + "\nUser for mirror.example.com: "
        assert packages.asks_for_login(out) == HOST
        assert packages.asks_for_login(
            "\x1b[0mUser for h.example:8081: ") == "h.example:8081"
        # only while it is the last thing said — waiting
        assert packages.asks_for_login(out + "\nERROR: gave up\n") == ""

    def test_refusals(self):
        assert packages.login_refused(
            "WARNING: 401 Error, Credentials not correct for https://h/x/")
        assert packages.login_refused(
            "hint: An index URL (https://h/simple) could not be queried due "
            "to a lack of valid authentication credentials "
            "(\x1b[31m401 Unauthorized\x1b[39m)")
        assert not packages.login_refused(
            "ERROR: No matching distribution found for nothing-here")


# ------------------------------------------------------------------ dialog

class _Window(QWidget):
    """Stands in for MainWindow: all the dialog wants of it is settings."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self.settings = QSettings(path, QSettings.IniFormat)


#: a fake installer: without a login it does what pip does (prompt, then
#: wait on stdin) or what uv does (say 401, fail); with one it succeeds
FAKE = r'''
import sys
kind, url = sys.argv[1], sys.argv[2]
if "@" in url:
    print("Successfully installed requests-2.0 with", url)
    sys.exit(0)
if kind == "pip":
    print("Looking in indexes:", url)
    print("User for mirror.example.com: ", end="", flush=True)
    sys.stdin.read()
    sys.exit(3)
print("error: (401 Unauthorized)", file=sys.stderr)
sys.exit(1)
'''


@pytest.fixture(autouse=True)
def _no_logins_kept(monkeypatch):
    monkeypatch.setattr(packages_dialog, "_LOGINS", {})


@pytest.fixture
def dialog(qtbot, tmp_path, monkeypatch):
    window = _Window(str(tmp_path / "settings.ini"))
    window.settings.setValue("packages/index_url", MIRROR)
    qtbot.addWidget(window)
    monkeypatch.setattr(packages, "installer_kind", lambda: "uv")
    monkeypatch.setattr(packages, "list_installed", lambda: [])
    dlg = PackagesDialog(window)
    qtbot.addWidget(dlg)
    dlg.runs = []
    dlg.asked = []

    def fake(kind):
        def build(action, specs, index=None, login=None, **_):
            dlg.runs.append(login)
            url = packages.url_with_login(index.url, login)
            return [sys.executable, "-c", FAKE, kind, url]
        monkeypatch.setattr(packages, "build_command", build)

    def answer(*logins):
        queue = list(logins)

        def ask(host, username, refused):
            dlg.asked.append((host, username, refused))
            return queue.pop(0) if queue else None
        monkeypatch.setattr(dlg, "_ask_login", ask)

    dlg.fake, dlg.answer = fake, answer
    yield dlg
    if dlg.busy:
        dlg._process.kill()
        dlg._process.waitForFinished(2000)


def _log(dlg) -> str:
    return dlg._log.toPlainText()


class TestSigningInWhenAsked:

    def test_pips_prompt_is_stopped_and_asked_for(self, dialog, qtbot):
        dialog.fake("pip")
        dialog.answer(IndexLogin("bob", "hunter22"))
        dialog.prefill(["requests"])
        dialog._install()
        qtbot.waitUntil(lambda: len(dialog.runs) == 2 and not dialog.busy,
                        timeout=10000)
        assert dialog.asked == [(HOST, "", False)]
        assert dialog.runs == [None, IndexLogin("bob", "hunter22")]
        log = _log(dialog)
        assert "the index asks for a user name and password" in log
        assert "— install finished —" in log
        assert "hunter22" not in log
        assert "https://bob:****@" in log
        assert "signed in as bob" in dialog._index_label.text()

    def test_uvs_401_is_asked_for(self, dialog, qtbot):
        dialog.fake("uv")
        dialog.answer(IndexLogin("bob", "hunter22"))
        dialog.prefill(["requests"])
        dialog._install()
        qtbot.waitUntil(lambda: len(dialog.runs) == 2 and not dialog.busy,
                        timeout=10000)
        assert "— install finished —" in _log(dialog)

    def test_a_refused_login_says_so_and_asks_again(self, dialog, qtbot,
                                                    monkeypatch):
        packages_dialog._LOGINS[HOST] = IndexLogin("bob", "wrong")

        def build(action, specs, index=None, login=None, **_):
            dialog.runs.append(login)      # always refused
            return [sys.executable, "-c", FAKE, "uv", index.url]
        monkeypatch.setattr(packages, "build_command", build)
        dialog.answer()                    # then the user cancels
        dialog._install_edit.setText("requests")
        dialog._install()
        qtbot.waitUntil(lambda: bool(dialog.asked) and not dialog.busy,
                        timeout=10000)
        assert dialog.asked == [(HOST, "bob", True)]
        qtbot.waitUntil(lambda: "not signed in" in _log(dialog))
        assert len(dialog.runs) == 1

    def test_cancelling_the_sign_in_installs_nothing(self, dialog, qtbot):
        dialog.fake("pip")
        dialog.answer()
        dialog._install_edit.setText("requests")
        dialog._install()
        qtbot.waitUntil(lambda: "not signed in" in _log(dialog),
                        timeout=10000)
        assert dialog.runs == [None]
        assert not packages_dialog._LOGINS


class TestTheButton:

    def test_sign_in_then_out(self, dialog):
        dialog.answer(IndexLogin("bob", "pw"))
        assert dialog._sign_in_btn.text() == "Sign In…"
        dialog._sign_in_btn.click()
        assert packages_dialog._LOGINS == {HOST: IndexLogin("bob", "pw")}
        assert dialog._sign_in_btn.text() == "Sign Out"
        dialog._sign_in_btn.click()
        assert not packages_dialog._LOGINS
        assert dialog._sign_in_btn.text() == "Sign In…"

    def test_no_private_index_nothing_to_sign_in_to(self, dialog,
                                                     monkeypatch):
        dialog._settings.setValue("packages/index_url", "")
        monkeypatch.setattr(packages, "pip_config_index",
                            lambda *a, **k: PackageIndex())
        dialog._show_index()
        assert not dialog._sign_in_btn.isEnabled()

    def test_the_window_hides_the_password(self, qtbot):
        win = SignInDialog(HOST, "bob", refused=True)
        qtbot.addWidget(win)
        win.password_edit.setText("pw")
        assert win.password_edit.echoMode() == QLineEdit.Password
        assert win.login() == IndexLogin("bob", "pw")
