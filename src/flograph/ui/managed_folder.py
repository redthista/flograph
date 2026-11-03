"""Canvas file manager and filename picker for managed-folder nodes."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QMimeData, QUrl, QSize, QRect
from PySide6.QtGui import QDrag, QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QTreeWidget, QTreeWidgetItem, QListWidget, QListWidgetItem, QStackedWidget,
    QAbstractItemView, QFileDialog, QMessageBox, QInputDialog, QMenu, QApplication,
    QStyle,
)
from flograph.core.managed_folder import ManagedFolder, FILES_PARAM, METADATA_PARAM, SYSTEM_COLUMNS, import_metadata, valid_name
from .commands import SetParamCommand
from .canvas.popup_lift import CardComboBox

# A desktop may read the URLs after QDrag.exec returns. Retain exported
# copies until application exit, rather than deleting them at drag end.
_exports = tempfile.TemporaryDirectory(prefix="flograph-drag-")


READER_DESCRIPTION = "Choose a file, or wire a filename to select it dynamically."


def reader_content_height(params, width):
    text = params.get("description", READER_DESCRIPTION)
    metrics = QFontMetrics(QApplication.font())
    text_height = metrics.boundingRect(QRect(0, 0, max(1, int(width) - 16), 10000),
                                      Qt.TextWordWrap, text).height() if text else 0
    return 16 + text_height + (6 if text else 0) + max(26, metrics.height() + 10)


class FileTree(QTreeWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setHeaderLabels(["Name", "Type", "Size"])
        self.header().setContextMenuPolicy(Qt.CustomContextMenu)
        self.header().customContextMenuRequested.connect(
            lambda point: owner.columns_menu(self.header().mapToGlobal(point)))
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda p: owner.menu(self, p))

    def dragEnterEvent(self, event):
        self.owner.dragEnterEvent(event)

    def dragMoveEvent(self, event):
        self.owner.dragMoveEvent(event)

    def dropEvent(self, event):
        self.owner.dropEvent(event)

    def startDrag(self, actions):
        self.owner.drag_out([i.text(0) for i in self.selectedItems()])


class FileIcons(QListWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setViewMode(QListWidget.IconMode)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setIconSize(QSize(48, 48))
        self.setGridSize(QSize(130, 90))
        self.setWordWrap(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda p: owner.menu(self, p))

    def dragEnterEvent(self, event):
        self.owner.dragEnterEvent(event)

    def dragMoveEvent(self, event):
        self.owner.dragMoveEvent(event)

    def dropEvent(self, event):
        self.owner.dropEvent(event)

    def startDrag(self, actions):
        self.owner.drag_out([i.text() for i in self.selectedItems()])


class ManagedFilesWidget(QWidget):
    def __init__(self, item):
        super().__init__()
        self.item = item
        self.folder = ManagedFolder.from_params(item.node.params)
        self._encoded_files = item.node.params.get(FILES_PARAM)
        self.reader = item.node.spec.card == "managed_reader"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.hint = QLabel(self)
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        if self.reader:
            self.picker = CardComboBox(self)
            self.picker.setEditable(False)
            self.picker.activated.connect(self.choose)
            layout.addWidget(self.picker)
            self.set_folder(self.folder)
            return
        self.setAcceptDrops(True)
        bar = QHBoxLayout()
        upload = QPushButton("Upload…", self)
        upload.clicked.connect(self.upload)
        bar.addWidget(upload)
        view = CardComboBox(self)
        view.addItems(["Details", "Large icons"])
        bar.addWidget(view)
        layout.addLayout(bar)
        self.views = QStackedWidget(self)
        self.tree = FileTree(self)
        self.icons = FileIcons(self)
        self.tree.itemDoubleClicked.connect(self.edit_cell)
        self.views.addWidget(self.tree)
        self.views.addWidget(self.icons)
        view.currentIndexChanged.connect(self.views.setCurrentIndex)
        layout.addWidget(self.views)
        self.set_folder(self.folder)

    def window_parent(self):
        scene = self.item.scene()
        return scene.views()[0].window() if scene and scene.views() else QApplication.activeWindow()

    def set_param(self, name, value):
        scene = self.item.scene()
        if scene is None:
            return
        scene.undo_stack.push(SetParamCommand(scene.graph, self.item.node.id, name, value, merge=False))

    def sync(self, params):
        if self.reader:
            self.set_folder(self.folder)
        else:
            if params.get(FILES_PARAM) is self._encoded_files:
                names = set(self.folder.names())
                folder = ManagedFolder(self.folder.entries, tuple(
                    (n, tuple(values.items())) for n, values in (params.get(METADATA_PARAM) or {}).items()
                    if n in names))
            else:
                folder = ManagedFolder.from_params(params)
                self._encoded_files = params.get(FILES_PARAM)
            self.set_folder(folder)

    def set_upstream(self, values):
        folder = values.get("folder")
        if isinstance(folder, ManagedFolder):
            self.set_folder(folder)

    def set_folder(self, folder):
        self.folder = folder
        if self.reader:
            self.picker.blockSignals(True)
            self.picker.clear()
            self.picker.addItem("Choose a file…", "")
            for name in folder.names():
                self.picker.addItem(name, name)
            selected = self.item.node.params.get("filename", "")
            index = self.picker.findData(selected)
            if selected and index < 0:
                self.picker.addItem(selected + " (missing)", selected)
                index = self.picker.count() - 1
            self.picker.setCurrentIndex(max(0, index))
            self.picker.blockSignals(False)
            description = self.item.node.params.get("description", READER_DESCRIPTION)
            self.hint.setText(description)
            self.hint.setVisible(bool(description))
            return
        self.tree.clear()
        self.icons.clear()
        fields = self.item.node.params.get("metadata_fields", [])
        table = folder.file_table(fields)
        requested = self.item.node.params.get("visible_columns", "filename, extension, size_bytes, source_modified")
        self.columns = list(dict.fromkeys(["filename", *(c.strip() for c in requested.split(",") if c.strip() in table.columns)]))
        labels = {"filename": "Name", "extension": "Type", "size_bytes": "Size (bytes)",
                  "source_modified": "Source modified (UTC)", "imported_at": "Imported (UTC)",
                  "edited_at": "Edited (UTC)"}
        self.tree.setColumnCount(len(self.columns))
        self.tree.setHeaderLabels([labels.get(c, c) for c in self.columns])
        icon = self.style().standardIcon(QStyle.SP_FileIcon)
        import pandas as pd
        for record in table.to_dict("records"):
            name = record["filename"]
            row = QTreeWidgetItem(["" if pd.isna(record[c]) else str(record[c]) for c in self.columns])
            row.setIcon(0, icon)
            self.tree.addTopLevelItem(row)
            self.icons.addItem(QListWidgetItem(icon, name))
        self.tree.resizeColumnToContents(0)
        self.hint.setText(f"{len(folder.entries)} files · Drop files here to import")

    def choose(self, index):
        name = self.picker.itemData(index)
        if name:
            self.set_param("filename", name)

    def upload(self):
        paths, _ = QFileDialog.getOpenFileNames(self.window_parent(), "Upload to Managed Folder")
        self.import_paths(paths)

    def import_paths(self, paths):
        folder = self.folder
        try:
            for raw in paths:
                path = Path(raw)
                if not path.is_file():
                    raise ValueError("Drop files, rather than directories")
                replace = path.name in folder.names()
                if replace and QMessageBox.question(self.window_parent(), "Replace file?",
                        f"Replace {path.name} in this managed folder?") != QMessageBox.Yes:
                    continue
                folder = folder.with_file(path.name, path.read_bytes(), replace=replace, metadata=import_metadata(path))
            if folder != self.folder:
                self.commit_folder(folder)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.window_parent(), "Cannot upload files", str(exc))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and all(u.isLocalFile() for u in event.mimeData().urls()):
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        self.import_paths([u.toLocalFile() for u in event.mimeData().urls()])
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def drag_out(self, names):
        if not names:
            return
        import uuid
        root = Path(_exports.name) / uuid.uuid4().hex
        root.mkdir()
        try:
            urls = []
            for name in names:
                path = root / valid_name(name)
                path.write_bytes(self.folder.read_bytes(name))
                urls.append(QUrl.fromLocalFile(str(path)))
            mime = QMimeData()
            mime.setUrls(urls)
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.exec(Qt.CopyAction)
        except OSError as exc:
            QMessageBox.warning(self.window_parent(), "Cannot export files", str(exc))

    def menu(self, view, point):
        selected = view.selectedItems()
        if not selected:
            return
        names = [i.text(0) if view is self.tree else i.text() for i in selected]
        menu = QMenu(self.window_parent())
        save = menu.addAction("Save As…")
        rename = menu.addAction("Rename…")
        rename.setEnabled(len(names) == 1)
        remove = menu.addAction("Remove")
        use = menu.addAction("Use in Flow")
        use.setEnabled(len(names) == 1)
        duplicate = menu.addAction("Duplicate…")
        duplicate.setEnabled(len(names) == 1)
        edit = menu.addAction("Edit CSV…")
        edit.setEnabled(len(names) == 1 and Path(names[0]).suffix.lower() in (".csv", ".tsv"))
        action = menu.exec(view.mapToGlobal(point))
        try:
            if action == duplicate:
                path = Path(names[0])
                number = 1
                proposed = f"{path.stem} copy{path.suffix}"
                while proposed in self.folder.names():
                    number += 1
                    proposed = f"{path.stem} copy {number}{path.suffix}"
                name, ok = QInputDialog.getText(self.window_parent(), "Duplicate file", "New filename", text=proposed)
                if ok:
                    self.duplicate_file(names[0], name)
            elif action == edit:
                self.edit_csv(names[0])
            elif action == use:
                self.use_in_flow(names[0])
            elif action == save:
                for name in names:
                    target, _ = QFileDialog.getSaveFileName(self.window_parent(), "Save managed file as", name)
                    if target:
                        Path(target).write_bytes(self.folder.read_bytes(name))
            elif action == remove:
                self.commit_folder(self.folder.without(names))
            elif action == rename:
                name, ok = QInputDialog.getText(self.window_parent(), "Rename file", "Filename", text=names[0])
                if ok and name != names[0]:
                    valid_name(name)
                    if name in self.folder.names():
                        raise ValueError("A file with that name already exists")
                    self.commit_folder(self.folder.renamed(names[0], name))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self.window_parent(), "Cannot change file", str(exc))
        finally:
            menu.deleteLater()

    def use_in_flow(self, name):
        from .commands import AddNodeCommand, ConnectCommand
        scene = self.item.scene()
        if scene is None or scene.registry is None:
            return
        node = scene.registry.instantiate("flograph.io.read_managed_file",
                         pos=(self.item.node.pos[0] + self.item.width + 100,
                              self.item.node.pos[1]))
        node.params["filename"] = name
        node.canvas = self.item.node.canvas
        scene.undo_stack.beginMacro("Read managed file")
        try:
            scene.undo_stack.push(AddNodeCommand(scene.graph, node))
            scene.undo_stack.push(ConnectCommand(scene.graph, self.item.node.id,
                                                "folder", node.id, "folder"))
        finally:
            scene.undo_stack.endMacro()
        scene.node_items[node.id]._control_widget.set_folder(self.folder)

    def commit_folder(self, folder):
        scene = self.item.scene()
        if scene is None:
            return
        files_changed = folder.entries != self.folder.entries
        metadata_changed = folder.metadata != self.folder.metadata
        scene.undo_stack.beginMacro("Edit managed files")
        try:
            if files_changed:
                self.set_param(FILES_PARAM, folder.to_param())
            if metadata_changed:
                self.set_param(METADATA_PARAM, folder.metadata_param())
        finally:
            scene.undo_stack.endMacro()

    def add_metadata_column(self, name):
        name = name.strip()
        if not name or "," in name or name in SYSTEM_COLUMNS:
            raise ValueError("Choose a custom name without commas; built-in fields are reserved")
        fields = list(self.item.node.params.get("metadata_fields", []))
        if name not in fields:
            fields.append(name)
        scene = self.item.scene()
        if scene is None:
            return
        scene.undo_stack.beginMacro("Add metadata column")
        try:
            self.set_param("metadata_fields", fields)
            visible = self.item.node.params.get("visible_columns", "filename")
            if name not in [c.strip() for c in visible.split(",")]:
                self.set_param("visible_columns", visible + ", " + name)
        finally:
            scene.undo_stack.endMacro()

    def columns_menu(self, global_position):
        menu = QMenu(self.window_parent())
        available = self.folder.file_table(self.item.node.params.get("metadata_fields", [])).columns
        for column in available:
            action = menu.addAction(column)
            action.setCheckable(True)
            action.setChecked(column in self.columns)
            action.setEnabled(column != "filename")
            action.triggered.connect(lambda checked, c=column: self.toggle_column(c, checked))
        menu.addSeparator()
        add = menu.addAction("Add metadata column…")
        def add_column():
            name, ok = QInputDialog.getText(self.window_parent(), "Add metadata column", "Column name")
            if ok:
                try:
                    self.add_metadata_column(name)
                except ValueError as exc:
                    QMessageBox.warning(self.window_parent(), "Cannot add column", str(exc))
        add.triggered.connect(add_column)
        menu.exec(global_position)
        menu.deleteLater()

    def toggle_column(self, name, checked):
        columns = list(self.columns)
        if checked and name not in columns:
            columns.append(name)
        elif not checked and name != "filename":
            columns = [c for c in columns if c != name]
        self.set_param("visible_columns", ", ".join(columns))

    def edit_cell(self, row, index):
        field = self.columns[index]
        if field in SYSTEM_COLUMNS:
            return
        name = row.text(0)
        value, ok = QInputDialog.getText(self.window_parent(), "Edit file metadata", field, text=row.text(index))
        if ok:
            self.commit_folder(self.folder.with_metadata(name, {field: value}))

    def duplicate_file(self, source, target):
        self.commit_folder(self.folder.with_file(target, self.folder.read_bytes(source),
                                                metadata=self.folder.metadata_for(source)))

    def edit_csv(self, name):
        from .managed_csv_editor import ManagedCsvEditor
        from PySide6.QtWidgets import QDialog
        dialog = ManagedCsvEditor(name, self.folder.read_bytes(name),
                                  self.folder.metadata_for(name), self.window_parent())
        try:
            if dialog.exec() == QDialog.Accepted:
                self.save_csv(name, dialog.data, *dialog.settings())
        finally:
            dialog.deleteLater()

    def save_csv(self, name, data, encoding=None, separator=None):
        if data == self.folder.read_bytes(name):
            return
        from datetime import datetime, timezone
        folder = self.folder.with_file(name, data, replace=True)
        metadata = {"edited_at": datetime.now(timezone.utc).isoformat()}
        if encoding:
            metadata["encoding"] = encoding
        if separator:
            metadata["separator"] = separator
        folder = folder.with_metadata(name, metadata)
        self.commit_folder(folder)
