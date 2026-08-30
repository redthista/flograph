"""Drag-drop of csv/xlsx/parquet files from the OS file explorer onto the canvas."""
import pytest
from PySide6.QtCore import QMimeData, QPointF, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent, Qt

from flograph.core import NodeRegistry
from flograph.ui.canvas.file_drop import (
    resolve_dropped_file, resolve_dropped_folder, resolve_dropped_path,
)
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

    def test_image_extensions_make_image_nodes(self):
        for name in ("shot.png", "photo.JPG", "loop.gif", "logo.svg",
                     "icon.webp"):
            assert resolve_dropped_file(f"/x/{name}") == (
                "flograph.viz.image", "path")

    def test_unknown_extension(self):
        assert resolve_dropped_file("/x/data.txt") is None


class TestResolveDroppedFolder:
    def test_a_folder_of_markdown_makes_a_wiki(self, tmp_path):
        (tmp_path / "Home.md").write_text("# Home\n", encoding="utf-8")
        assert resolve_dropped_folder(str(tmp_path)) == (
            "flograph.viz.markdown_wiki", "folder")
        assert resolve_dropped_path(str(tmp_path)) == (
            "flograph.viz.markdown_wiki", "folder")

    def test_a_folder_without_markdown_is_left_alone(self, tmp_path):
        (tmp_path / "data.csv").write_text("a,b\n", encoding="utf-8")
        assert resolve_dropped_folder(str(tmp_path)) is None
        assert resolve_dropped_path(str(tmp_path)) is None

    def test_a_file_is_not_a_folder(self, tmp_path):
        f = tmp_path / "notes.md"
        f.write_text("# hi\n", encoding="utf-8")
        assert resolve_dropped_folder(str(f)) is None

    def test_resolve_dropped_path_still_handles_files(self):
        assert resolve_dropped_path("/x/data.csv") == ("flograph.io.read_csv", "path")


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
        window._add_reader_nodes_for_files(["/fake/notes.txt"], QPointF(0, 0))
        assert len(window.graph.nodes) == 0

    def test_a_markdown_folder_creates_a_wiki_node(self, window, tmp_path):
        (tmp_path / "Home.md").write_text("# Home\n", encoding="utf-8")
        window._add_reader_nodes_for_files([str(tmp_path)], QPointF(0, 0))
        assert len(window.graph.nodes) == 1
        node = next(iter(window.graph.nodes.values()))
        assert node.type_id == "flograph.viz.markdown_wiki"
        assert node.params["folder"] == str(tmp_path)
        window.undo_stack.undo()
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
        mime = self._mime_with_urls("/fake/notes.txt")
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
