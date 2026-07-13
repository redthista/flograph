"""Wheel over a scrollable in-canvas widget (table card) must scroll that
widget; wheel over empty canvas (or a card whose content fits) keeps
zoom-to-cursor. Covers ZoomPanGraphicsView, shared by canvas and dashboard."""
import json

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QUndoStack, QWheelEvent
from PySide6.QtWidgets import QApplication

from flograph.core import Graph, NodeRegistry
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.view import NodeGraphView


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def env(qtbot, registry):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry=registry)
    view = NodeGraphView(scene)
    view.resize(800, 600)
    qtbot.addWidget(view)
    view.show()
    return graph, stack, scene, view


def send_wheel(view, pos: QPoint, delta: int = -120) -> None:
    event = QWheelEvent(
        QPointF(pos), QPointF(view.viewport().mapToGlobal(pos)),
        QPoint(0, 0), QPoint(0, delta),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(view.viewport(), event)


def add_table_node(graph, registry, rows: int):
    node = registry.instantiate("flograph.io.table")
    node.params["data"] = json.dumps(
        {"columns": ["A"], "rows": [[str(i)] for i in range(rows)]})
    graph.add_node(node)
    QApplication.processEvents()  # let the proxy widget's layout run
    return node


def point_over_grid(view, item) -> QPoint:
    """Viewport point in the middle of the table card's grid viewport."""
    grid = item._table_widget
    local = grid.viewport().mapTo(item._table_proxy.widget(),
                                  grid.viewport().rect().center())
    scene_pos = item._table_proxy.mapToScene(QPointF(local))
    return view.mapFromScene(scene_pos)


def test_wheel_on_empty_canvas_zooms(env):
    *_, view = env
    before = view.zoom
    send_wheel(view, QPoint(400, 300))
    assert view.zoom != before


def test_wheel_over_scrollable_table_scrolls_not_zooms(env, registry):
    graph, _, scene, view = env
    node = add_table_node(graph, registry, rows=60)
    item = scene.node_items[node.id]
    view.centerOn(item)
    bar = item._table_widget.verticalScrollBar()
    assert bar.maximum() > bar.minimum()  # setup: content must overflow

    before_zoom = view.zoom
    before_scroll = bar.value()
    send_wheel(view, point_over_grid(view, item))

    assert view.zoom == before_zoom
    assert bar.value() > before_scroll


def test_wheel_past_scroll_end_neither_zooms_nor_pans(env, registry):
    graph, _, scene, view = env
    node = add_table_node(graph, registry, rows=60)
    item = scene.node_items[node.id]
    view.centerOn(item)
    bar = item._table_widget.verticalScrollBar()
    bar.setValue(bar.maximum())
    pos = point_over_grid(view, item)

    before_zoom = view.zoom
    before_transform = view.transform()
    before_scroll = (view.horizontalScrollBar().value(),
                     view.verticalScrollBar().value())
    send_wheel(view, pos)  # wheel down with the table already at the bottom

    assert view.zoom == before_zoom
    assert view.transform() == before_transform
    assert (view.horizontalScrollBar().value(),
            view.verticalScrollBar().value()) == before_scroll

    send_wheel(view, pos, delta=120)  # reversing still scrolls the table
    assert bar.value() < bar.maximum()
    assert view.zoom == before_zoom


def test_wheel_over_table_without_overflow_still_zooms(env, registry):
    graph, _, scene, view = env
    node = add_table_node(graph, registry, rows=1)
    item = scene.node_items[node.id]
    view.centerOn(item)
    grid = item._table_widget
    assert grid.verticalScrollBar().maximum() == 0
    assert grid.horizontalScrollBar().maximum() == 0

    before = view.zoom
    send_wheel(view, point_over_grid(view, item))

    assert view.zoom != before
