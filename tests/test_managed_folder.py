"""Managed assets survive cache-free saves; node values remain immutable."""
import json
import zipfile

import pytest
from PySide6.QtGui import QUndoStack
from flograph.core import Graph, serialization
from flograph.core.managed_folder import ManagedFolder, FILES_PARAM
from flograph.engine.cache import OutputCache
from flograph.engine.cache_persistence import plan_project_save, write_project
from flograph.ui.canvas.scene import NodeGraphScene
from tests.test_stdlib_nodes import run_node


def test_folder_contract():
    folder = ManagedFolder().with_file("lookup.csv", b"id,value\n1,10\n")
    updated = folder.with_file("other.txt", b"hello")
    assert folder.names() == ("lookup.csv",)
    assert updated.open("other.txt", "r").read() == "hello"
    with pytest.raises(ValueError, match="already exists"):
        folder.with_file("lookup.csv", b"bad")
    with pytest.raises(ValueError):
        folder.with_file("../bad", b"bad")
    with pytest.raises(FileNotFoundError):
        folder.open("missing.csv")
    with pytest.raises(ValueError, match="read-only"):
        folder.open("lookup.csv", "wb")


def test_node_chain(registry, tmp_path):
    path = tmp_path / "lookup.csv"
    path.write_bytes(b"id,price\n1,12\n")
    upload = run_node(registry, "flograph.io.upload_managed_file", {"path": str(path)})
    output = run_node(registry, "flograph.io.managed_folder", incoming=upload["folder"])
    result = run_node(registry, "flograph.io.read_managed_file", {"filename": path.name}, folder=output["folder"])
    assert result["table"].iloc[0]["price"] == 12
    assert output["files"].iloc[0]["filename"] == path.name
    assert result["data"] == path.read_bytes()
    with pytest.raises(ValueError, match="Choose a filename"):
        run_node(registry, "flograph.io.read_managed_file", folder=output["folder"])
    with pytest.raises(ValueError, match="Choose a file"):
        run_node(registry, "flograph.io.upload_managed_file")
    with pytest.raises(FileNotFoundError):
        run_node(registry, "flograph.io.read_managed_file", folder=output["folder"], filename="no.csv")


def test_bundle_assets_and_workflow_export(registry, tmp_path):
    graph = Graph()
    node = graph.add_node(registry.instantiate("flograph.io.managed_folder"))
    folder = ManagedFolder().with_file("lookup.csv", b"id,price\n1,20\n\x00")
    graph.set_param(node.id, FILES_PARAM, folder.to_param())
    path = tmp_path / "original.flograph"
    write_project(path, plan_project_save(graph, OutputCache()))
    with zipfile.ZipFile(path) as archive:
        data = json.loads(archive.read("project.json"))
        assert FILES_PARAM not in data["graph"]["nodes"][0]["params"]
        member = next(iter(data["graph"]["nodes"][0]["managed_assets"].values()))
        assert archive.read(member) == folder.read_bytes("lookup.csv")
    loaded = serialization.load(path, registry)
    copy = tmp_path / "copy.flograph"
    write_project(copy, plan_project_save(loaded, OutputCache()), prev_path=path)
    path.unlink()
    restored = serialization.load(copy, registry)
    assert ManagedFolder.from_params(restored.node(node.id).params) == folder
    export = tmp_path / "portable.flowf"
    serialization.save(restored, export)
    assert ManagedFolder.from_params(serialization.load(export, registry).node(node.id).params) == folder


def test_visual_import_and_undo(qapp, registry, tmp_path):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry)
    node = graph.add_node(registry.instantiate("flograph.io.managed_folder"))
    widget = scene.node_items[node.id]._control_widget
    path = tmp_path / "lookup.csv"
    path.write_bytes(b"a,b\n1,2\n")
    widget.import_paths([str(path)])
    assert widget.tree.topLevelItemCount() == 1
    assert ManagedFolder.from_params(node.params).read_bytes(path.name) == path.read_bytes()
    stack.undo()
    assert widget.tree.topLevelItemCount() == 0
    stack.redo()
    assert widget.icons.count() == 1
    scene.clear()


def test_reader_action_and_dynamic_filename(qapp, registry):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry)
    node = graph.add_node(registry.instantiate("flograph.io.managed_folder"))
    folder = ManagedFolder().with_file("v1.csv", b"id,price\n1,10\n").with_file("v2.csv", b"id,price\n1,20\n")
    graph.set_param(node.id, FILES_PARAM, folder.to_param())
    widget = scene.node_items[node.id]._control_widget
    widget.use_in_flow("v1.csv")
    reader = next(n for n in graph.nodes.values() if n.spec.card == "managed_reader")
    assert graph.input_connection(reader.id, "folder").src_node == node.id
    out = run_node(registry, reader.type_id, reader.params, folder=folder, filename="v2.csv")
    assert out["table"]["price"].tolist() == [20]
    stack.undo()
    assert len(graph.nodes) == 1
    stack.redo()
    assert len(graph.nodes) == 2
    scene.clear()


def test_example_desktop_imports_result(qtbot, registry, tmp_path):
    from flograph.ui.mainwindow import MainWindow
    window = MainWindow(registry)
    window.confirm_close = False
    qtbot.addWidget(window)
    assert window.open_path("src/flograph/templates/42_managed_folder.flograph", confirm=False)
    folder = next(n for n in window.graph.nodes.values() if n.label == "Export files")
    source = next(n for n in window.graph.nodes.values() if n.label == "Lookup files")
    reader = next(n for n in window.graph.nodes.values() if n.label == "Read sales")
    picker = window.scene.node_items[reader.id]._control_widget.picker
    assert picker.findData("sales.csv") >= 0
    window.engine.run_all()
    qtbot.waitUntil(lambda: "joined_sales.csv" in ManagedFolder.from_params(folder.params).names(), timeout=20000)
    qtbot.waitUntil(lambda: not folder.dirty, timeout=20000)
    chooser = next(n for n in window.graph.nodes.values() if n.label == "Choose lookup per row")
    assert window.engine.cache.get(chooser.id).outputs["table"]["price"].tolist() == [10, 25, 12]
    result = ManagedFolder.from_params(folder.params)
    assert b"Apple,10" in result.read_bytes("joined_sales.csv")
    # Clearing caches must leave both imported and original project assets.
    window.engine.cache.clear()
    path = tmp_path / "example.flograph"
    write_project(path, plan_project_save(window.graph, window.engine.cache))
    loaded = serialization.load(path, registry)
    assert ManagedFolder.from_params(loaded.node(folder.id).params) == result
    assert {"sales.csv", "lookup_v1.csv", "lookup_v2.csv", "routed_sales.csv"} <= set(
        ManagedFolder.from_params(loaded.node(source.id).params).names())


def test_save_as_and_external_drag_copy_original_bytes(qapp, registry, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QDrag
    from PySide6.QtWidgets import QFileDialog, QMenu
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry)
    node = graph.add_node(registry.instantiate("flograph.io.managed_folder"))
    original = b"\x00\xfforiginal\r\nbytes"
    graph.set_param(node.id, FILES_PARAM, ManagedFolder().with_file("data.bin", original).to_param())
    widget = scene.node_items[node.id]._control_widget
    widget.tree.topLevelItem(0).setSelected(True)
    target = tmp_path / "export.bin"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    from flograph.ui import managed_folder as ui
    class TestMenu(QMenu):
        def exec(self, *args):
            return self.actions()[0]
    monkeypatch.setattr(ui, "QMenu", TestMenu)
    widget.menu(widget.tree, widget.tree.rect().center())
    assert target.read_bytes() == original
    captured = []
    def copy_drag(self, action):
        assert action == Qt.CopyAction
        captured.extend(self.mimeData().urls())
        return Qt.CopyAction
    class TestDrag(QDrag):
        exec = copy_drag
    monkeypatch.setattr(ui, "QDrag", TestDrag)
    widget.drag_out(["data.bin"])
    from pathlib import Path
    assert Path(captured[0].toLocalFile()).read_bytes() == original
    assert ManagedFolder.from_params(node.params).read_bytes("data.bin") == original
    scene.clear()


def test_reader_height_follows_description(qapp, registry):
    graph = Graph()
    scene = NodeGraphScene(graph, QUndoStack(), registry)
    node = graph.add_node(registry.instantiate("flograph.io.read_managed_file"))
    item = scene.node_items[node.id]
    graph.set_param(node.id, "description", "Choose lookup")
    short = item.body_height
    assert short < 140
    graph.set_param(node.id, "height", 900)
    assert item.body_height == short
    graph.set_param(node.id, "description", "An explanatory sentence about which lookup to choose. " * 5)
    assert item.body_height > short
    assert item._control_widget.hint.text() == node.params["description"]
    scene.clear()


def test_metadata_roundtrip_rename_and_merge(registry, tmp_path):
    from flograph.core.managed_folder import METADATA_PARAM
    folder = ManagedFolder().with_file("a.csv", b"a\n1\n", metadata={"source_modified": "2026-11-01T12:00:00+00:00", "owner": "Team A"})
    renamed = folder.renamed("a.csv", "b.csv")
    assert renamed.metadata_for("b.csv")["owner"] == "Team A"
    assert folder.metadata_for("a.csv")["owner"] == "Team A"
    incoming = ManagedFolder().with_file("b.csv", b"new", metadata={"imported_at": "2026-11-03T12:00:00+00:00"})
    merged = renamed.merged(incoming)
    assert merged.metadata_for("b.csv")["owner"] == "Team A"
    assert merged.metadata_for("b.csv")["imported_at"].startswith("2026-11-03")
    assert not merged.without(["b.csv"]).metadata
    graph = Graph()
    node = graph.add_node(registry.instantiate("flograph.io.managed_folder"))
    graph.set_param(node.id, FILES_PARAM, merged.to_param())
    graph.set_param(node.id, METADATA_PARAM, merged.metadata_param())
    path = tmp_path / "metadata.flograph"
    write_project(path, plan_project_save(graph, OutputCache()))
    loaded = serialization.load(path, registry)
    assert ManagedFolder.from_params(loaded.node(node.id).params) == merged
    assert merged.file_table(["status"])["owner"].tolist() == ["Team A"]
    assert "status" in merged.file_table(["status"])


def test_custom_metadata_ui_and_column_visibility(qapp, registry, tmp_path):
    from flograph.core.managed_folder import METADATA_PARAM
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry)
    node = graph.add_node(registry.instantiate("flograph.io.managed_folder"))
    widget = scene.node_items[node.id]._control_widget
    path = tmp_path / "a.csv"
    path.write_text("a\n1\n")
    widget.import_paths([str(path)])
    assert "source_modified" in node.params[METADATA_PARAM]["a.csv"]
    assert "imported_at" in node.params[METADATA_PARAM]["a.csv"]
    widget.add_metadata_column("owner")
    assert "owner" in widget.columns
    widget.commit_folder(widget.folder.with_metadata("a.csv", {"owner": "Team A"}))
    assert widget.tree.topLevelItem(0).text(widget.columns.index("owner")) == "Team A"
    stack.undo()
    assert "owner" not in node.params[METADATA_PARAM]["a.csv"]
    stack.redo()
    assert node.params[METADATA_PARAM]["a.csv"]["owner"] == "Team A"
    widget.toggle_column("owner", False)
    assert "owner" not in widget.columns
    assert widget.folder.file_table()["owner"].tolist() == ["Team A"]
    scene.clear()


def test_duplicate_and_edit_csv_undo(qapp, registry):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry)
    node = graph.add_node(registry.instantiate("flograph.io.managed_folder"))
    widget = scene.node_items[node.id]._control_widget
    widget.commit_folder(ManagedFolder().with_file("lookup.csv", b"id,name\n001,Apple\n", metadata={"owner": "Team"}))
    widget.duplicate_file("lookup.csv", "lookup copy.csv")
    assert widget.folder.read_bytes("lookup copy.csv") == widget.folder.read_bytes("lookup.csv")
    assert widget.folder.metadata_for("lookup copy.csv")["owner"] == "Team"
    with pytest.raises(ValueError, match="already exists"):
        widget.duplicate_file("lookup.csv", "lookup copy.csv")
    widget.save_csv("lookup copy.csv", b"id,name\n001,Pear\n", "utf-8", ",")
    assert b"Apple" in widget.folder.read_bytes("lookup.csv")
    assert "edited_at" in widget.folder.metadata_for("lookup copy.csv")
    stack.undo()
    assert b"Apple" in widget.folder.read_bytes("lookup copy.csv")
    stack.undo()
    assert widget.folder.names() == ("lookup.csv",)
    stack.redo()
    stack.redo()
    assert b"Pear" in widget.folder.read_bytes("lookup copy.csv")
    scene.clear()


def test_csv_editor_preserves_text_encoding_quotes_and_newlines(qapp):
    from flograph.ui.managed_csv_editor import ManagedCsvEditor
    from PySide6.QtWidgets import QTableWidgetItem
    original = 'id;name;note\r\n001;café;"first\nsecond"\r\n'.encode("latin-1")
    dialog = ManagedCsvEditor("a.csv", original, {"encoding": "latin-1"})
    assert dialog.separator.text() == ";"
    assert dialog.grid.item(0, 0).text() == "001"
    assert dialog.grid.item(0, 2).text() == "first\nsecond"
    dialog.save()
    assert dialog.data == original
    dialog.grid.setItem(0, 1, QTableWidgetItem("thé"))
    dialog.save()
    assert '001;thé;"first\nsecond"\r\n'.encode("latin-1") in dialog.data
    dialog.deleteLater()


def test_csv_editor_invalid_utf8_requires_encoding_choice(qapp):
    from flograph.ui.managed_csv_editor import ManagedCsvEditor
    from PySide6.QtWidgets import QDialogButtonBox
    dialog = ManagedCsvEditor("a.csv", "id,name\n1,café\n".encode("latin-1"))
    assert not dialog.buttons.button(QDialogButtonBox.Save).isEnabled()
    dialog.encoding.setCurrentText("latin-1")
    dialog.load()
    assert dialog.grid.item(0, 1).text() == "café"
    assert dialog.buttons.button(QDialogButtonBox.Save).isEnabled()
    dialog.deleteLater()


def test_csv_find_replace_literal_case_whole_cell_and_wrap(qapp):
    from flograph.ui.managed_csv_editor import ManagedCsvEditor
    dialog = ManagedCsvEditor("a.csv", b"name,note\nApple,apple apple\nPineapple,a.b\n")
    dialog.find_text.setText("apple")
    dialog.whole_cell.setChecked(True)
    assert dialog.find_next()
    assert (dialog.grid.currentRow(), dialog.grid.currentColumn()) == (0, 0)
    assert dialog.find_next()
    assert "wrapped" in dialog.search_status.text()
    dialog.replace_text.setText("Pear")
    dialog.replace_current()
    assert dialog.grid.item(0, 0).text() == "Pear"
    dialog.whole_cell.setChecked(False)
    dialog.match_case.setChecked(True)
    dialog.replace_all()
    assert dialog.grid.item(0, 1).text() == "Pear Pear"
    assert dialog.grid.item(1, 0).text() == "PinePear"
    assert dialog.search_status.text() == "3 replacements"
    dialog.find_text.setText("a.b")
    dialog.replace_text.setText(r"\1")
    dialog.replace_all()
    assert dialog.grid.item(1, 1).text() == r"\1"
    before = dialog.rows()
    dialog.find_text.clear()
    dialog.replace_all()
    assert dialog.rows() == before
    dialog.deleteLater()


def test_csv_headers_roundtrip_and_rename(qapp, monkeypatch):
    from flograph.ui.managed_csv_editor import ManagedCsvEditor
    from PySide6.QtWidgets import QInputDialog, QPushButton
    original = b"id,name\r\n001,Apple\r\n"
    dialog = ManagedCsvEditor("a.csv", original)
    assert dialog.grid.horizontalHeaderItem(0).text() == "id"
    assert dialog.grid.horizontalHeaderItem(1).text() == "name"
    assert dialog.grid.rowCount() == 1
    assert dialog.grid.item(0, 0).text() == "001"
    assert not any(button.text() in ("Add row", "Replace all", "Remove selected columns")
                   for button in dialog.findChildren(QPushButton) if button.window() is dialog)
    dialog.save()
    assert dialog.data == original
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("description", True))
    dialog._context_column = 1
    dialog.rename_column()
    dialog.save()
    assert dialog.data == b"id,description\r\n001,Apple\r\n"
    dialog.deleteLater()


@pytest.mark.parametrize("original", [b"", b"\n", b"id,name\n"])
def test_csv_empty_and_header_only_preserve_original(qapp, original):
    from flograph.ui.managed_csv_editor import ManagedCsvEditor
    dialog = ManagedCsvEditor("a.csv", original)
    dialog.save()
    assert dialog.data == original
    dialog.deleteLater()


def test_csv_find_replace_uses_separate_dialog(qapp):
    from flograph.ui.managed_csv_editor import ManagedCsvEditor
    dialog = ManagedCsvEditor("a.csv", b"id,name\n1,Apple\n")
    assert dialog.find_text.window() is dialog.search_dialog
    assert dialog.replace_text.window() is dialog.search_dialog
    assert not dialog.search_dialog.isVisible()
    dialog.show_find()
    assert dialog.search_dialog.isVisible()
    dialog.find_text.setText("Apple")
    dialog.replace_text.setText("Pear")
    dialog.commands["replace_all"].trigger()
    assert dialog.grid.item(0, 1).text() == "Pear"
    dialog.reject()
    assert not dialog.search_dialog.isVisible()
    dialog.deleteLater()


def test_csv_columns_fit_content_and_wrap_resizes_rows(qapp, qtbot):
    from flograph.ui.managed_csv_editor import ManagedCsvEditor
    from PySide6.QtWidgets import QTableWidgetItem
    text = "A long explanation with several words that should wrap. " * 8
    dialog = ManagedCsvEditor("a.csv", ("id,description\n001," + text + "\n").encode())
    assert dialog.grid.columnWidth(1) > dialog.grid.columnWidth(0)
    assert dialog.grid.columnWidth(1) <= 480
    base = dialog.grid.rowHeight(0)
    dialog.wrap_text.setChecked(True)
    assert dialog.grid.wordWrap()
    assert dialog.grid.rowHeight(0) > base
    wrapped_height = dialog.grid.rowHeight(0)
    dialog.grid.setColumnWidth(1, 150)
    qtbot.waitUntil(lambda: dialog.grid.rowHeight(0) > wrapped_height)
    dialog.wrap_text.setChecked(False)
    assert not dialog.grid.wordWrap()
    assert dialog.grid.rowHeight(0) == base
    before = dialog.grid.columnWidth(0)
    dialog.grid.setItem(0, 0, QTableWidgetItem("a considerably longer identifier"))
    qtbot.waitUntil(lambda: dialog.grid.columnWidth(0) > before)
    dialog.deleteLater()


def test_csv_wrap_breaks_long_unbroken_values_and_starts_compact(qapp):
    from flograph.ui.managed_csv_editor import ManagedCsvEditor
    from PySide6.QtWidgets import QStyleOptionViewItem
    token = "https://example.test/" + "long_identifier_" * 40
    dialog = ManagedCsvEditor("a.csv", ("id,value\n1," + token + "\n").encode())
    compact = dialog.grid.rowHeight(0)
    assert compact == dialog.compact_row_height
    dialog.wrap_text.setChecked(True)
    assert dialog.grid.rowHeight(0) > compact * 2
    delegate = dialog.grid.itemDelegate()
    option = QStyleOptionViewItem()
    delegate.initStyleOption(option, dialog.grid.model().index(0, 1))
    document = delegate.document(option, dialog.grid.columnWidth(1) - 9)
    document.size()
    assert document.begin().layout().lineCount() > 2
    dialog.wrap_text.setChecked(False)
    assert dialog.grid.rowHeight(0) == compact
    dialog.deleteLater()
