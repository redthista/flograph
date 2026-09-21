"""Two flograph instances must not share a Chromium directory.

Qt's default web profile carries one storage path per *machine*, which Qt
hands to Chromium as its --user-data-dir. On Windows the second process to
reach it is locked out and its web views go blank while the rest of the app
works — "two apps open, only one shows plotly graphs". The cure is a profile
of this process's own, so the tests that matter are about what two processes
see, not about one.
"""
import os
import pathlib
import subprocess
import sys

import pytest

from flograph.ui import webprofile

pytest.importorskip("PySide6.QtWebEngineCore")


@pytest.fixture
def fresh(monkeypatch):
    """webprofile with its cache emptied, so a test builds its own."""
    monkeypatch.setattr(webprofile, "_profile", None)
    monkeypatch.setattr(webprofile, "_tmp", None)
    return webprofile


# What each of two processes reports about its own profile. It writes the
# answer to a file rather than to stdout, and its output goes to DEVNULL:
# Qt WebEngine starts helper processes that outlive the Python child and
# inherit whatever it was given, so a pipe here is not closed when the child
# exits and the parent waits on it for ever. That is a hang of the whole
# suite, and it is this file's own footgun to avoid.
REPORT = """
import sys
sys.path.insert(0, {src!r})
from PySide6.QtWidgets import QApplication
app = QApplication([])
app.setApplicationName("flograph"); app.setOrganizationName("flograph")
from flograph.ui.webprofile import profile
open({out!r}, "w").write(profile().persistentStoragePath())
"""


def _run_apart(script: str, tmp_path, name: str, **env_extra) -> str:
    """Run a snippet in a process of its own and hand back what it wrote."""
    out = tmp_path / name
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", **env_extra)
    result = subprocess.run(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=180, env=env)
    assert result.returncode == 0, f"the {name} process failed"
    return out.read_text() if out.exists() else ""


def _src_dir() -> str:
    import flograph

    return str(pathlib.Path(flograph.__file__).parent.parent)


def _storage_path_of_a_separate_process(tmp_path, name):
    """A real second process — the thing the bug is about — asked where its
    Chromium directory is."""
    out = tmp_path / name
    return _run_apart(REPORT.format(src=_src_dir(), out=str(out)),
                      tmp_path, name).strip()


class TestTwoInstances:
    def test_they_are_given_different_directories(self, tmp_path):
        """The whole bug in one assertion."""
        first = _storage_path_of_a_separate_process(tmp_path, "first")
        second = _storage_path_of_a_separate_process(tmp_path, "second")
        assert first and second
        assert first != second

    def test_neither_is_the_shared_one_qt_would_have_picked(self, qapp, fresh):
        from PySide6.QtWebEngineCore import QWebEngineProfile

        shared = QWebEngineProfile.defaultProfile().persistentStoragePath()
        assert fresh.profile().persistentStoragePath() != shared


class TestTheProfileItself:
    def test_it_is_still_off_the_record(self, qapp, fresh):
        """Moving where Chromium works must not start keeping history."""
        assert fresh.profile().isOffTheRecord()

    def test_it_belongs_to_the_application(self, qapp, fresh):
        """Which is what makes it outlive the widgets. Left to Python, it
        would be freed at interpreter shutdown in no particular order, and
        a profile freed under a live page takes Qt down with it."""
        assert fresh.profile().parent() is qapp

    def test_it_is_made_once_and_kept(self, qapp, fresh):
        """It has to outlive every page built on it — the cards destroy and
        rebuild their views freely, and a profile freed under a live page
        takes Qt down with it."""
        assert fresh.profile() is fresh.profile()

    def test_the_directory_it_uses_is_its_own(self, qapp, fresh):
        path = fresh.profile().persistentStoragePath()
        assert "flograph-web-" in path

    def test_the_temp_directory_is_held_alongside_it(self, qapp, fresh):
        """Nothing else refers to it: dropped, it would be swept up under a
        running Chromium."""
        fresh.profile()
        assert fresh._tmp is not None
        assert fresh._tmp.name in fresh.profile().persistentStoragePath()


class TestViews:
    def test_a_view_is_built_on_it(self, fresh, qtbot):
        view = fresh.new_view()
        qtbot.addWidget(view)
        assert view.page().profile() is fresh.profile()

    def test_a_parent_is_still_honoured(self, fresh, qtbot):
        from PySide6.QtWidgets import QWidget

        holder = QWidget()
        qtbot.addWidget(holder)
        view = fresh.new_view(holder)
        assert view.parent() is holder

    def test_no_webengine_leaves_the_caller_its_import_error(
            self, monkeypatch, fresh):
        """A trimmed PySide6 install has no WebEngine, and every call site
        already catches that — so it must still arrive as ImportError."""
        monkeypatch.setitem(sys.modules, "PySide6.QtWebEngineWidgets", None)
        with pytest.raises(ImportError):
            fresh.new_view()

    def test_a_missing_profile_is_not_an_error_of_its_own(
            self, monkeypatch, fresh):
        monkeypatch.setitem(sys.modules, "PySide6.QtWebEngineCore", None)
        assert fresh.profile() is None


class TestTheEngineItselfIsMoved:
    """A profile moves what Qt keeps; `--user-data-dir` moves what Chromium
    keeps underneath it, which is the half a shader cache lands in."""

    @pytest.fixture(autouse=True)
    def _no_inherited_flags(self, monkeypatch):
        monkeypatch.delenv("QTWEBENGINE_CHROMIUM_FLAGS", raising=False)

    def test_the_engine_is_given_this_process_s_directory(self, fresh):
        assert fresh.claim_chromium_dirs() is True
        flags = os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]
        assert f"--user-data-dir={fresh._own_dir()}" in flags
        assert f"--disk-cache-dir={fresh._own_dir()}" in flags

    def test_it_is_the_same_directory_the_profile_uses(self, qapp, fresh):
        fresh.claim_chromium_dirs()
        assert fresh._own_dir() in os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]
        assert fresh.profile().persistentStoragePath() == fresh._own_dir()

    def test_flags_already_set_are_kept(self, monkeypatch, fresh):
        monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
        fresh.claim_chromium_dirs()
        assert os.environ["QTWEBENGINE_CHROMIUM_FLAGS"].startswith(
            "--disable-gpu ")

    def test_somebody_else_s_choice_of_directory_is_left_alone(
            self, monkeypatch, fresh):
        monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS",
                           "--user-data-dir=/somewhere/chosen")
        assert fresh.claim_chromium_dirs() is False
        assert os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] == (
            "--user-data-dir=/somewhere/chosen")

    def test_a_path_with_a_space_is_declined_rather_than_mangled(
            self, monkeypatch, fresh):
        """Qt splits this variable on spaces and honours no quoting, and
        `C:\\Users\\Jo Bloggs\\AppData\\Local\\Temp\\…` is an ordinary Windows
        temp path. Half a path would take Chromium down altogether, which is
        much worse than two of them sharing a directory."""
        monkeypatch.setattr(fresh, "_own_dir", lambda: "/tmp/jo bloggs/web")
        assert fresh.claim_chromium_dirs() is False
        assert "QTWEBENGINE_CHROMIUM_FLAGS" not in os.environ

    def test_on_windows_a_spaced_path_tries_its_short_name_first(
            self, monkeypatch, fresh):
        monkeypatch.setattr(fresh, "_own_dir", lambda: "C:\\Jo Bloggs\\web")
        monkeypatch.setattr(fresh.sys, "platform", "win32")
        monkeypatch.setattr(fresh, "_short_path", lambda p: "C:\\JOBLOG~1\\web")
        assert fresh.claim_chromium_dirs() is True
        assert ("--user-data-dir=C:\\JOBLOG~1\\web"
                in os.environ["QTWEBENGINE_CHROMIUM_FLAGS"])

    def test_and_declines_when_windows_has_no_short_name_either(
            self, monkeypatch, fresh):
        monkeypatch.setattr(fresh, "_own_dir", lambda: "C:\\Jo Bloggs\\web")
        monkeypatch.setattr(fresh.sys, "platform", "win32")
        monkeypatch.setattr(fresh, "_short_path", lambda p: "")
        assert fresh.claim_chromium_dirs() is False
        assert "QTWEBENGINE_CHROMIUM_FLAGS" not in os.environ


class TestAskingChromiumToSpeak:
    """FLOGRAPH_WEB_LOG=1 — for the machine with the fault on it, which is
    not the machine this is written on."""

    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch, tmp_path):
        monkeypatch.delenv("QTWEBENGINE_CHROMIUM_FLAGS", raising=False)
        monkeypatch.delenv("FLOGRAPH_WEB_LOG", raising=False)
        monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path))
        yield
        webprofile._stop_engine_log()

    def test_off_unless_asked_for(self, fresh):
        assert fresh.claim_engine_logging() == ""
        assert "QTWEBENGINE_CHROMIUM_FLAGS" not in os.environ

    def test_asked_for_it_turns_chromium_s_logging_on(self, monkeypatch,
                                                      fresh, tmp_path):
        monkeypatch.setenv("FLOGRAPH_WEB_LOG", "1")
        assert fresh.claim_engine_logging() == str(tmp_path / "web.log")
        assert "--enable-logging" in os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]

    def test_what_chromium_writes_to_descriptor_2_lands_in_it(
            self, monkeypatch, fresh):
        """The engine's C++ writes its log straight to the descriptor,
        through Qt and through Python both. Catching it means catching it
        there."""
        monkeypatch.setenv("FLOGRAPH_WEB_LOG", "1")
        path = pathlib.Path(fresh.claim_engine_logging())
        os.write(2, b"[INFO:gpu_process_host.cc] renderer went away\n")
        webprofile._stop_engine_log()
        assert "renderer went away" in path.read_text()

    def test_what_qt_says_lands_in_it_too(self, tmp_path):
        """In a process of its own: pytest-qt installs a message handler of
        its own, so Qt's messages never reach a descriptor to be caught
        here — and it is Qt's *default* handler, writing to stderr, that
        this relies on."""
        script = f"""
import sys
sys.path.insert(0, {_src_dir()!r})
from PySide6.QtCore import qWarning
from flograph.ui.webprofile import claim_engine_logging
claim_engine_logging()
qWarning("a qt warning")
"""
        _run_apart(script, tmp_path, "unused", FLOGRAPH_WEB_LOG="1",
                   FLOGRAPH_USER_DIR=str(tmp_path))
        assert "a qt warning" in (tmp_path / "web.log").read_text()

    def test_the_log_survives_a_launch_with_no_stderr(self, monkeypatch,
                                                      fresh):
        """The Windows shortcut runs under pythonw, which has none — and
        that is the launch the report came from."""
        monkeypatch.setattr(fresh.sys, "stderr", None)
        monkeypatch.setenv("FLOGRAPH_WEB_LOG", "1")
        path = pathlib.Path(fresh.claim_engine_logging())
        os.write(2, b"still written\n")
        webprofile._stop_engine_log()
        assert "still written" in path.read_text()

    def test_descriptor_2_is_handed_back(self, monkeypatch, fresh):
        """Left redirected, the rest of the suite would write into a closed
        file."""
        monkeypatch.setenv("FLOGRAPH_WEB_LOG", "1")
        path = pathlib.Path(fresh.claim_engine_logging())
        webprofile._stop_engine_log()
        os.write(2, b"")
        before = path.stat().st_size
        os.write(2, b"")
        assert path.stat().st_size == before

    def test_it_says_which_process_wrote_it(self, monkeypatch, fresh):
        """Two instances is the whole subject; one log must not be mistaken
        for the other's."""
        monkeypatch.setenv("FLOGRAPH_WEB_LOG", "1")
        path = pathlib.Path(fresh.claim_engine_logging())
        assert str(os.getpid()) in path.read_text()

    def test_it_sits_beside_the_directories_rather_than_over_them(
            self, monkeypatch, fresh, tmp_path):
        monkeypatch.setenv("FLOGRAPH_WEB_LOG", "1")
        fresh.claim_chromium_dirs()
        fresh.claim_engine_logging()
        flags = os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]
        assert "--user-data-dir=" in flags and "--enable-logging" in flags
