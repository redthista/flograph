"""Inspector view for matplotlib Figures returned by nodes.

Figures are created worker-side with the OO API (matplotlib.figure.Figure);
the canvas that renders them is created here, on the GUI thread."""
from __future__ import annotations

from typing import Callable, Optional, Union

from PySide6.QtWidgets import QVBoxLayout, QWidget

DialogParent = Union[QWidget, Callable[[], Optional[QWidget]], None]


class _AnchoredToolbar:
    """Mixin overriding NavigationToolbar2QT.save_figure to anchor its file
    dialog to an explicit top-level widget instead of self.canvas.parent().

    That default matters when the canvas is embedded via QGraphicsProxyWidget
    (the on-canvas figure card): setWidget() strips the embedded widget's
    Qt parent, leaving it a detached top-level that's never actually mapped
    to the screen. A native (GTK/portal) file chooser parented off that
    phantom window gets a bogus transient-for target — it renders with no
    sane size hints and crashes when it tries to interact with a window
    that was never really shown. Resolving the dialog's parent via the real
    QGraphicsView instead sidesteps that entirely.
    """

    def __init__(self, canvas, parent, dialog_parent: DialogParent = None) -> None:
        super().__init__(canvas, parent)
        self._dialog_parent = dialog_parent

    def save_figure(self, *args):
        parent = self._dialog_parent
        if callable(parent):
            parent = parent()
        if parent is None:
            return super().save_figure(*args)

        import os

        import matplotlib as mpl
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        filetypes = self.canvas.get_supported_filetypes_grouped()
        default_filetype = self.canvas.get_default_filetype()
        startpath = os.path.expanduser(mpl.rcParams["savefig.directory"])
        start = os.path.join(startpath, self.canvas.get_default_filename())

        filters = []
        selected_filter = None
        for name, exts in sorted(filetypes.items()):
            exts_list = " ".join(f"*.{ext}" for ext in exts)
            filt = f"{name} ({exts_list})"
            if default_filetype in exts:
                selected_filter = filt
            filters.append(filt)

        fname, _filt = QFileDialog.getSaveFileName(
            parent, "Choose a filename to save to", start,
            ";;".join(filters), selected_filter)
        if fname:
            if startpath != "":
                mpl.rcParams["savefig.directory"] = os.path.dirname(fname)
            try:
                self.canvas.figure.savefig(fname)
            except Exception as e:
                QMessageBox.critical(
                    self, "Error saving file", str(e),
                    QMessageBox.StandardButton.Ok,
                    QMessageBox.StandardButton.NoButton)
        return fname


class FigureView(QWidget):
    def __init__(self, parent=None, dialog_parent: DialogParent = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._canvas = None
        self._toolbar = None
        self._dialog_parent = dialog_parent

    def set_figure(self, figure) -> None:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.backends.backend_qtagg import (
            NavigationToolbar2QT as _Base,
        )

        class _Toolbar(_AnchoredToolbar, _Base):
            pass

        self.clear()
        self._canvas = FigureCanvasQTAgg(figure)
        self._toolbar = _Toolbar(self._canvas, self, self._dialog_parent)
        self._layout.addWidget(self._toolbar)
        self._layout.addWidget(self._canvas, 1)
        # no explicit draw_idle: the canvas draws on expose, and a scheduled
        # draw can fire after deletion when views are swapped quickly

    def clear(self) -> None:
        for widget in (self._toolbar, self._canvas):
            if widget is not None:
                self._layout.removeWidget(widget)
                widget.deleteLater()
        self._canvas = None
        self._toolbar = None
