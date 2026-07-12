"""Application entry point: QApplication, theme, registry, main window."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    import matplotlib
    matplotlib.use("QtAgg")  # before any pyplot import, GUI-safe backend

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from flograph.core import NodeRegistry
    from flograph.ui.mainwindow import MainWindow
    from flograph.ui.theme import apply_theme

    # must be set before the QApplication exists: the Show Plotly card embeds
    # Qt WebEngine, which needs shared GL contexts to composite
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("flograph")
    app.setOrganizationName("flograph")
    apply_theme(app)

    registry = NodeRegistry()
    registry.load_builtins()

    window = MainWindow(registry)
    window.resize(1400, 900)
    window.show()

    args = app.arguments()[1:]
    project = next(
        (a for a in args if a.endswith((".flograph", ".flopy"))), None)
    if project:
        window.open_path(project, confirm=False)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
