"""Application entry point: QApplication, theme, registry, main window."""
from __future__ import annotations

import sys


def _matplotlib_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("matplotlib") is not None


def _claim_windows_identity() -> None:
    """Tell Windows this process is flograph, not the interpreter running it.

    Until a process declares an explicit AppUserModelID, the taskbar reads
    its identity — and therefore its icon and its grouping — off the .exe
    that started it, which for us is python.exe. Declaring one makes the
    taskbar button use the window icon we set. Must happen before the first
    window exists.
    """
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "flograph.flograph")
    except (AttributeError, OSError):
        pass  # an icon is not worth failing a launch over


def main(argv: list[str] | None = None) -> int:
    if _matplotlib_available():
        import matplotlib
        matplotlib.use("QtAgg")  # before any pyplot import, GUI-safe backend

    from PySide6.QtCore import Qt
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from flograph.core import NodeRegistry
    from flograph.paths import user_data_dir, user_nodes_dir
    from flograph.ui import window_frame
    from flograph.ui.mainwindow import MainWindow
    from flograph.ui.theme import apply_theme

    # must be set before the QApplication exists: the Show Plotly card embeds
    # Qt WebEngine, which needs shared GL contexts to composite
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    # also before it, and for the same reason — the engine reads its flags
    # once. Two copies of flograph open at once must not be two Chromiums
    # working in one directory; see ui/webprofile.
    from flograph.ui.webprofile import (
        claim_chromium_dirs, claim_engine_logging,
    )
    claim_chromium_dirs()
    claim_engine_logging()
    app = QApplication.instance() or QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("flograph")
    app.setOrganizationName("flograph")
    # the desktop-file name is what a Linux dock matches a window against, so
    # the running app sits under its own launcher rather than beside it
    app.setDesktopFileName("flograph")
    _claim_windows_identity()
    app.setWindowIcon(window_frame.app_icon())
    theme_pref = QSettings("flograph", "flograph").value(
        "appearance/theme", "dark", type=str)
    apply_theme(app, theme_pref)

    registry = NodeRegistry()
    registry.load_builtins()
    registry.load_user_nodes(user_nodes_dir())
    registry.load_installed_packs(user_data_dir())

    window = MainWindow(registry)
    window.resize(1400, 900)
    window.show()
    window.watch_for_stalls()

    args = app.arguments()[1:]
    project = next((a for a in args if a.endswith(".flograph")), None)
    if project:
        window.open_path(project, confirm=False)
    elif window.start_screen_on_launch:
        # nothing named to open: offer what was open last rather than an
        # empty canvas (O1)
        window.show_start_screen()
    code = app.exec()
    _tear_down(window)
    return code


def _tear_down(window) -> None:
    """Destroy the window while the application is still whole.

    Left alone, the window outlives `app.exec()` and is deleted by PySide's
    exit-time sweep, which visits every Python-owned object in no particular
    order. A web view (a Plotly card, a Web View card, a report renderer)
    frees GPU resources as it dies, and when the sweep reaches it after the
    GL state it leans on has gone, Qt WebEngine aborts the process with
    "Failed to restore OpenGL context after clean-up." — a crash on every
    close that hits it, after the user's work is saved but loud all the same
    (notes/issues.md). So the web views go first, then the window, and both
    before Python starts finalizing.

    Deleting them early is not enough on its own. To free a texture, Qt
    WebEngine saves whichever GL context is current, switches to its own,
    and afterwards makes the saved one current again on its saved surface.
    By now the window is closed and that surface is gone, so the switch back
    fails and *that* is the qFatal. With no context current there is nothing
    to switch back to and the step is skipped, so the current context is
    released before every deletion: deleting one view can leave its own
    context current for the next.
    """
    import shiboken6
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    # views already handed to deleteLater die the ordinary way first
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except ImportError:
        QWebEngineView = None
    if QWebEngineView is not None:
        views = [w for w in QApplication.allWidgets()
                 if isinstance(w, QWebEngineView)]
        for view in views:
            # deleting one can take another with it (a parent view's page)
            if shiboken6.isValid(view):
                _release_gl_context()
                shiboken6.delete(view)
    if shiboken6.isValid(window):
        _release_gl_context()
        shiboken6.delete(window)
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _release_gl_context() -> None:
    """Leave no GL context current (see `_tear_down`)."""
    from PySide6.QtGui import QOpenGLContext

    context = QOpenGLContext.currentContext()
    if context is not None:
        context.doneCurrent()


if __name__ == "__main__":
    raise SystemExit(main())
