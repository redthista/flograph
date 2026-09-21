"""Where this process's Qt WebEngine keeps its things: somewhere of its own.

Two copies of flograph open at once are two Chromium engines started from
one installation, and by default they agree on every path they use. The
default profile's storage path is `<app data>/flograph/QtWebEngine/
OffTheRecord` — the same string in both processes — and neither engine is
told to put its own working files anywhere in particular.

That is the shape of the "two apps open, only one shows plotly graphs"
report, which came from Windows. A file opened under a shared directory is
locked against the other process there, where on Linux both may hold it,
and Chromium fails the way it always fails: silently, leaving a blank
rectangle on a card while everything else in the app carries on.

Said plainly, because the file that fixes something should say how well it
knows what it is fixing: **this is a hypothesis about Windows, not a
diagnosis made here.** Measured on Linux, an off-the-record profile writes
nothing anywhere at all — the shared directory is never even created — so
the collision could not be reproduced on the machine this was written on.

What needs no hypothesis is that two processes have nothing to gain from
sharing a directory neither of them reads across runs. So this process
takes:

* **a profile of its own** — off-the-record exactly as before, nothing
  kept between runs — with its storage inside a temporary directory; and
* **its own `--user-data-dir`** (`claim_chromium_dirs`), which covers what
  Chromium writes without consulting a profile at all, the shader cache
  and the crash database among it. On Windows that is the half that would
  matter, since Direct3D is what every page there is drawn through.

Two instances then share nothing, by construction.

The profile is process-wide rather than per view because a
`QWebEngineProfile` must outlive every page built on it, and the cards
destroy and rebuild their views freely (`PlotlyView.set_content` drops the
whole view to give a big chart's memory back). One profile, parented to
the application, outlives all of them.
"""
from __future__ import annotations

import os
import sys
import tempfile

_profile = None   # the QWebEngineProfile, once built
_tmp = None       # its TemporaryDirectory, kept alive alongside it
_log_file = None  # the open web.log, while FLOGRAPH_WEB_LOG is on
_saved_stderr_fd = None   # descriptor 2 as it was, to give back


def _own_dir() -> str:
    """This process's web directory, made on first use.

    ignore_cleanup_errors: on Windows, Chromium may still hold a file in
    here when the interpreter tears the directory down. A temp directory
    that outlives the process is untidy; an exception on the way out is
    worse.
    """
    global _tmp
    if _tmp is None:
        _tmp = tempfile.TemporaryDirectory(prefix="flograph-web-",
                                           ignore_cleanup_errors=True)
    return _tmp.name


def claim_chromium_dirs() -> bool:
    """Give Chromium itself a directory of this process's own.

    The profile below moves what *Qt* keeps. This moves what Chromium keeps
    underneath it — the shader cache, the crash database, whatever the
    engine writes without consulting a profile — by handing it an explicit
    `--user-data-dir`. **Must run before the QApplication exists**, which is
    when the engine reads its flags.

    Returns False when it declines, which it does rather than risk a broken
    flag: Qt splits `QTWEBENGINE_CHROMIUM_FLAGS` on spaces and honours no
    quoting, so a temp path with a space in it — `C:\\Users\\Jo Bloggs\\…`,
    which is an ordinary Windows temp path — cannot be passed at all. On
    Windows the 8.3 short name is tried first, since that has no spaces by
    construction; where that is turned off too, a Chromium given half a path
    would be far worse than one sharing a directory, so it is left alone.
    """
    path = _own_dir()
    if " " in path and sys.platform == "win32":
        path = _short_path(path)
    if not path or " " in path:
        return False
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--user-data-dir" in flags:
        return False      # somebody has already said where; not ours to move
    ours = f"--user-data-dir={path} --disk-cache-dir={path}"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{flags} {ours}".strip()
    return True


def claim_engine_logging() -> str:
    """Write down what Chromium says, when FLOGRAPH_WEB_LOG is set.

    Chromium keeps its reasons to itself: a page that will not draw prints
    nothing and the card is left blank — the view says *that* much now (see
    `inspector/plotly_view`), but never why. When the machine showing the
    fault is one nobody can attach a debugger to, an environment variable
    that makes the engine talk is the difference between a bug report and a
    guess.

        Windows:    set FLOGRAPH_WEB_LOG=1 && flograph
        Linux/Mac:  FLOGRAPH_WEB_LOG=1 flograph

    Taking it down is the awkward half. Chromium's `--log-file` is not
    honoured under QtWebEngine, and its messages do not come through Qt's
    message handler either — the engine's C++ writes them straight to file
    descriptor 2. So descriptor 2 is what gets redirected, which catches
    Chromium's log, Qt's own warnings and any Python traceback in one file,
    and works where it is needed most: the Windows Start Menu shortcut runs
    under `pythonw`, which has no stderr at all, so the run that fails is
    otherwise the one run nobody can read.

    Returns the log's path, or "" when it is switched off. Must run before
    the QApplication, which is when the engine reads its flags.
    """
    global _log_file, _saved_stderr_fd
    if not os.environ.get("FLOGRAPH_WEB_LOG"):
        return ""
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--enable-logging" not in flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
            f"{flags} --enable-logging --v=1").strip()

    from flograph.paths import user_data_dir

    path = user_data_dir() / "web.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    # line-buffered: the run this is meant to explain is one that may not
    # exit tidily, and an unflushed buffer explains nothing
    _log_file = open(path, "a", encoding="utf-8", errors="replace",
                     buffering=1)
    _log_file.write(f"--- flograph {os.getpid()} ---\n")
    _log_file.flush()
    try:
        _saved_stderr_fd = os.dup(2)
        os.dup2(_log_file.fileno(), 2)
    except OSError:
        _saved_stderr_fd = None     # no descriptor 2 to take over
    sys.stderr = _log_file
    return str(path)


def _stop_engine_log() -> None:
    """Give descriptor 2 back. For tests — the redirect is process-wide,
    and a suite whose stderr is a closed file is a suite with no output."""
    global _log_file, _saved_stderr_fd
    if _saved_stderr_fd is not None:
        os.dup2(_saved_stderr_fd, 2)
        os.close(_saved_stderr_fd)
        _saved_stderr_fd = None
    sys.stderr = sys.__stderr__
    if _log_file is not None:
        _log_file.close()
        _log_file = None


def _short_path(path: str) -> str:
    """The 8.3 name for a Windows path, or "" if there isn't one."""
    import ctypes

    buf = ctypes.create_unicode_buffer(512)
    got = ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf))
    return buf.value if got else ""


def profile():
    """This process's web profile, or None if Qt WebEngine is missing.

    Built on first use — Chromium is heavy, and a trimmed PySide6 install
    has no WebEngine at all, which is a thing to say in a placeholder
    rather than an error to raise.
    """
    global _profile
    if _profile is not None:
        return _profile
    try:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtWebEngineCore import QWebEngineProfile
    except ImportError:
        return None
    path = _own_dir()
    # An unnamed profile is off-the-record, which is what the default
    # profile was too — this changes where Chromium works, not whether it
    # remembers anything.
    #
    # Parented to the application, not left to Python: a profile freed while
    # a page still stands on it earns "Release of profile requested but
    # WebEnginePage still not deleted. Expect troubles!" from Qt, and the
    # troubles are real. Module globals are cleared at interpreter shutdown
    # in no useful order, whereas Qt destroys the application's own children
    # after it has destroyed its widgets.
    prof = QWebEngineProfile(QCoreApplication.instance())
    prof.setPersistentStoragePath(path)
    prof.setCachePath(path)
    _profile = prof
    return _profile


def new_view(parent=None):
    """A QWebEngineView on this process's own profile.

    Raises ImportError when WebEngine is not installed, so the callers that
    already catch that keep catching it.
    """
    from PySide6.QtWebEngineWidgets import QWebEngineView

    prof = profile()
    if prof is None:
        return QWebEngineView(parent)
    return QWebEngineView(prof, parent)
