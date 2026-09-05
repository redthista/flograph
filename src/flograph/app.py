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
    from flograph.paths import user_nodes_dir
    from flograph.ui import window_frame
    from flograph.ui.mainwindow import MainWindow
    from flograph.ui.theme import apply_theme

    # must be set before the QApplication exists: the Show Plotly card embeds
    # Qt WebEngine, which needs shared GL contexts to composite
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
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

    window = MainWindow(registry)
    window.resize(1400, 900)
    window.show()

    args = app.arguments()[1:]
    project = next((a for a in args if a.endswith(".flograph")), None)
    if project:
        window.open_path(project, confirm=False)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
