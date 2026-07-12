"""Inspector view for matplotlib Figures returned by nodes.

Figures are created worker-side with the OO API (matplotlib.figure.Figure);
the canvas that renders them is created here, on the GUI thread."""
from __future__ import annotations

from typing import Callable, Optional, Union

from PySide6.QtWidgets import QVBoxLayout, QWidget

DialogParent = Union[QWidget, Callable[[], Optional[QWidget]], None]

# NavigationToolbar2's matplotlib event hooks, by the attribute the base
# class stores each connection id under.
_TOOLBAR_CID_ATTRS = ("_id_press", "_id_release", "_id_drag")


def _disconnect_toolbar_cids(canvas, cids) -> None:
    """Unhook a toolbar's matplotlib event callbacks.

    matplotlib keeps the callback registry on the *Figure* (so it survives
    canvas swaps), which means a toolbar left connected outlives its Qt
    widgets: any later canvas showing the same figure keeps dispatching
    mouse events into the dead toolbar's deleted QLabel ("Internal C++
    object already deleted" spam, then a segfault). Registry disconnects
    are idempotent, so calling this twice for the same toolbar is fine."""
    for cid in cids:
        if cid is not None:
            canvas.mpl_disconnect(cid)


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
        self._render_ratio: float | None = None

    def set_render_ratio(self, ratio: float | None) -> None:
        """Absolute device pixels per logical pixel to render figures at
        (screen DPR × canvas zoom × card scale), or None to trust Qt's
        native ratio. The on-canvas figure card is magnified by transforms
        the embedded widget can't see; without a matching resolution boost
        those transforms stretch a raster drawn at logical size and the
        figure goes soft."""
        if ratio == self._render_ratio:
            return
        self._render_ratio = ratio
        if self._canvas is not None:
            self._canvas._render_ratio = ratio
            self._sync_pixel_ratio(self._canvas)

    def set_figure(self, figure) -> None:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.backends.backend_qtagg import (
            NavigationToolbar2QT as _Base,
        )

        class _Toolbar(_AnchoredToolbar, _Base):
            def set_message(self, s):
                # Last-ditch guard: an event already in flight when the
                # toolbar is torn down must not touch the deleted locLabel.
                import shiboken6
                if not shiboken6.isValid(self):
                    return
                super().set_message(s)

        class _ScaledCanvas(FigureCanvasQTAgg):
            """Reports its _render_ratio as the device pixel ratio so
            matplotlib sizes its Agg buffer (and stamps the painted QImage)
            to match the pixels actually landing on screen. Only matplotlib
            reads this override — Qt keeps its C++ value. Kept free of any
            closure over the view: a cycle through a live QWidget makes its
            teardown order depend on the garbage collector."""

            _render_ratio: float | None = None

            def devicePixelRatioF(self) -> float:
                if self._render_ratio is not None:
                    return self._render_ratio
                return super().devicePixelRatioF()

        self.clear()
        self._canvas = _ScaledCanvas(figure)
        self._canvas._render_ratio = self._render_ratio
        self._toolbar = _Toolbar(self._canvas, self, self._dialog_parent)
        # Safety net for teardown paths that never call clear() (scene
        # removeItem + GC, popup close, page dispose): the moment the
        # toolbar's C++ side dies, unhook its matplotlib callbacks. The
        # lambda captures only the canvas and the cids — never the view
        # (see _ScaledCanvas on why such a closure would be a hazard).
        canvas = self._canvas
        cids = tuple(getattr(self._toolbar, attr, None)
                     for attr in _TOOLBAR_CID_ATTRS)
        self._toolbar.destroyed.connect(
            lambda *_: _disconnect_toolbar_cids(canvas, cids))
        self._layout.addWidget(self._toolbar)
        self._layout.addWidget(self._canvas, 1)
        # Ends in a synchronous draw: embedded in a QGraphicsProxyWidget (the
        # on-canvas figure card) the canvas gets no real expose event, so
        # without it the card shows a blank/garbage buffer until a resize
        # forces a redraw.
        self._sync_pixel_ratio(self._canvas)

    @staticmethod
    def _sync_pixel_ratio(canvas) -> None:
        """Pull the (possibly overridden) pixel ratio into matplotlib and
        redraw synchronously. matplotlib only refreshes its ratio on
        showEvent/screen changes — neither fires for a widget embedded in a
        QGraphicsProxyWidget — and its refresh path schedules a draw_idle,
        which can fire after deletion when views are swapped quickly (same
        hazard as in set_figure). Cancel it and draw now instead."""
        canvas._update_pixel_ratio()
        canvas._draw_pending = False
        canvas.draw()

    def clear(self) -> None:
        if self._toolbar is not None and self._canvas is not None:
            # Unhook now rather than waiting for the deferred delete: the
            # caller may immediately attach a new canvas to the same figure
            # (set_figure on re-run) and start dispatching events.
            _disconnect_toolbar_cids(
                self._canvas,
                tuple(getattr(self._toolbar, attr, None)
                      for attr in _TOOLBAR_CID_ATTRS))
        for widget in (self._toolbar, self._canvas):
            if widget is not None:
                self._layout.removeWidget(widget)
                widget.deleteLater()
        self._canvas = None
        self._toolbar = None
