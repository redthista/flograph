"""Drag-drop of csv/xlsx/parquet files from the OS file explorer onto the canvas."""
import pytest
from PySide6.QtCore import QMimeData, QPointF, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent, Qt

from flograph.core import NodeRegistry
from flograph.ui.canvas.file_drop import resolve_dropped_file
from flograph.ui.mainwindow import MainWindow


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


class TestResolveDroppedFile:
    def test_known_extensions(self):
        assert resolve_dropped_file("/x/data.csv") == ("flograph.io.read_csv", "path")
        assert resolve_dropped_file("/x/data.XLSX") == ("flograph.io.read_excel", "path")
        assert resolve_dropped_file("/x/data.parquet") == ("flograph.io.read_parquet", "path")

    def test_unknown_extension(self):
        assert resolve_dropped_file("/x/data.txt") is None


class TestAddReaderNodesForFiles:
    def test_single_file_creates_node_with_path(self, window):
        window._add_reader_nodes_for_files(["/fake/data.csv"], QPointF(100, 100))
        assert len(window.graph.nodes) == 1
        node = next(iter(window.graph.nodes.values()))
        assert node.type_id == "flograph.io.read_csv"
        assert node.params["path"] == "/fake/data.csv"

        window.undo_stack.undo()
        assert len(window.graph.nodes) == 0

    def test_multiple_files_offset_and_undo_together(self, window):
        window._add_reader_nodes_for_files(
            ["/fake/a.csv", "/fake/b.xlsx"], QPointF(0, 0))
        assert len(window.graph.nodes) == 2
        positions = sorted(n.pos for n in window.graph.nodes.values())
        assert positions[0] != positions[1]

        window.undo_stack.undo()
        assert len(window.graph.nodes) == 0

    def test_unsupported_file_is_ignored(self, window):
        window._add_reader_nodes_for_files(["/fake/image.png"], QPointF(0, 0))
        assert len(window.graph.nodes) == 0


class TestViewDragDrop:
    def _mime_with_urls(self, *paths):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        return mime

    def test_drag_enter_accepts_supported_file(self, window):
        mime = self._mime_with_urls("/fake/data.csv")
        event = QDragEnterEvent(
            window.view.viewport().rect().center(), Qt.CopyAction, mime,
            Qt.LeftButton, Qt.NoModifier)
        window.view.dragEnterEvent(event)
        assert event.isAccepted()

    def test_drag_enter_rejects_unsupported_file(self, window):
        mime = self._mime_with_urls("/fake/image.png")
        event = QDragEnterEvent(
            window.view.viewport().rect().center(), Qt.CopyAction, mime,
            Qt.LeftButton, Qt.NoModifier)
        window.view.dragEnterEvent(event)
        assert not event.isAccepted()

    def test_drop_emits_files_dropped(self, window, qtbot):
        mime = self._mime_with_urls("/fake/data.csv")
        pos = window.view.viewport().rect().center()
        event = QDropEvent(
            pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        with qtbot.waitSignal(window.view.files_dropped, timeout=1000) as blocker:
            window.view.dropEvent(event)
        paths, scene_pos = blocker.args
        assert paths == ["/fake/data.csv"]
        assert isinstance(scene_pos, QPointF)
