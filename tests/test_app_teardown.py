"""The window is destroyed by `app.main()`, not by PySide's exit sweep.

Left to the sweep, a web view could be deleted after the GL state it needs
had gone and Qt WebEngine aborted the process on close ("Failed to restore
OpenGL context after clean-up."). What can be checked headlessly is the
order: web views and the window are gone before `main()` returns.
"""
import pytest
import shiboken6
from PySide6.QtWidgets import (
    QGraphicsProxyWidget, QGraphicsScene, QGraphicsView, QVBoxLayout, QWidget,
)

from flograph.app import _tear_down

pytest.importorskip("PySide6.QtWebEngineWidgets")


def _window_with_card(qapp):
    """A window whose canvas holds a web view the way a Plotly card does:
    inside a QGraphicsProxyWidget, inside a scene the window owns."""
    from flograph.ui.webprofile import new_view

    window = QWidget()
    scene = QGraphicsScene(window)
    QVBoxLayout(window).addWidget(QGraphicsView(scene))
    card = QWidget()
    view = new_view(card)
    proxy = QGraphicsProxyWidget()
    proxy.setWidget(card)
    scene.addItem(proxy)
    return window, view


def test_tear_down_destroys_the_web_view_and_the_window(qapp):
    window, view = _window_with_card(qapp)
    _tear_down(window)
    assert not shiboken6.isValid(view)
    assert not shiboken6.isValid(window)


def test_a_view_already_handed_to_delete_later_is_not_deleted_twice(qapp):
    window, view = _window_with_card(qapp)
    view.deleteLater()
    _tear_down(window)
    assert not shiboken6.isValid(view)
    assert not shiboken6.isValid(window)


def test_a_window_already_gone_is_left_alone(qapp):
    window = QWidget()
    shiboken6.delete(window)
    _tear_down(window)    # must not raise
