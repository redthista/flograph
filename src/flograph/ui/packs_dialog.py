"""Tools ▸ Node Packs — add-on bundles of nodes (see core.packs).

The same shape as Manage Packages and Web Libraries: what you have, how to
get more, and one place flograph keeps it. A pack's Python requirements are
not installed here — they are handed to Manage Packages, prefilled, because
that dialog already knows the package index, the sign-in and the installer
this machine uses, and a second copy of that logic would drift.

Every change ends in `window.reload_packs()`, which re-registers the pack
nodes and rebuilds the library, so a pack added here can be dragged out the
moment the dialog says it is installed.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMenu,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from flograph.core import packs
from flograph.paths import user_data_dir


def status_of(pack: packs.Pack, disabled: bool) -> str:
    if disabled:
        return "Disabled"
    missing = packs.missing_requirements(pack)
    if missing:
        return "Needs " + ", ".join(missing)
    return "Ready"


class NodePacksDialog(QDialog):
    COLUMNS = ("Pack", "Version", "Nodes", "From", "Status")

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self.setWindowTitle("Node Packs")
        self.resize(820, 520)
        self._packs: list[packs.Pack] = []
        self._disabled: set[str] = set()

        intro = QLabel(
            "A node pack adds a section of nodes to the library — install "
            "one from a .zip, or link a folder to use a pack straight from "
            "its own checkout.")
        intro.setWordWrap(True)

        self._table = QTableWidget(0, len(self.COLUMNS))
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._sync)

        self._details = QLabel()
        self._details.setWordWrap(True)
        self._details.setTextFormat(Qt.PlainText)
        self._details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._details.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._details.setMinimumHeight(90)

        def button(text, slot):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            return btn

        self._install_btn = button("Install from .zip…", self._install_zip)
        self._link_btn = button("Link Folder…", self._link_folder)
        self._remove_btn = button("Remove", self._remove)
        self._toggle_btn = button("Disable", self._toggle)
        self._reqs_btn = button("Install Requirements…", self._install_reqs)
        self._more_btn = QPushButton("More")
        more = QMenu(self._more_btn)
        more.addAction("Open Pack Folder", self._open_folder)
        more.addAction("Export as .zip…", self._export)
        self._examples_menu = more.addMenu("Open Example")
        self._more_btn.setMenu(more)
        reload_btn = button("Reload", self.reload)
        close_btn = button("Close", self.close)

        top_row = QHBoxLayout()
        top_row.addWidget(self._install_btn)
        top_row.addWidget(self._link_btn)
        top_row.addStretch(1)
        top_row.addWidget(reload_btn)
        row = QHBoxLayout()
        for btn in (self._reqs_btn, self._toggle_btn, self._remove_btn,
                    self._more_btn):
            row.addWidget(btn)
        row.addStretch(1)
        row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(top_row)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._details)
        layout.addLayout(row)
        self.refresh()

    # ------------------------------------------------------------ listing

    def refresh(self, select: str = "") -> None:
        """Re-read what is on disk. Does not touch the registry."""
        found, errors = packs.discover(user_data_dir())
        self._packs = found
        self._disabled = set(packs.load_config(user_data_dir())["disabled"])
        self._errors = errors
        current = select or (self._current().id if self._current() else "")
        self._table.setRowCount(len(found))
        for row, pack in enumerate(found):
            cells = (pack.name, pack.version, str(len(pack.node_files())),
                     pack.source, status_of(pack, pack.id in self._disabled))
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(str(pack.root) if col == 3 else text)
                self._table.setItem(row, col, item)
            if pack.id == current:
                self._table.selectRow(row)
        if found and not self._table.selectedItems():
            self._table.selectRow(0)
        self._sync()

    def _current(self) -> "packs.Pack | None":
        rows = {i.row() for i in self._table.selectedItems()}
        if len(rows) != 1:
            return None
        row = rows.pop()
        return self._packs[row] if row < len(self._packs) else None

    def _sync(self) -> None:
        pack = self._current()
        for btn in (self._remove_btn, self._toggle_btn, self._reqs_btn,
                    self._more_btn):
            btn.setEnabled(pack is not None)
        lines: list[str] = []
        if pack is not None:
            disabled = pack.id in self._disabled
            self._toggle_btn.setText("Enable" if disabled else "Disable")
            self._remove_btn.setText(
                "Unlink" if pack.source == "linked" else "Remove")
            missing = packs.missing_requirements(pack)
            self._reqs_btn.setEnabled(bool(missing))
            lines.append(f"{pack.name} {pack.version}"
                         + (f" — {pack.author}" if pack.author else ""))
            if pack.description:
                lines.append(pack.description)
            lines.append(f"Folder: {pack.root}")
            if pack.requires:
                lines.append("Requires: " + ", ".join(pack.requires))
            if missing:
                lines.append("Not installed in flograph's environment: "
                             + ", ".join(missing))
                if pack.index_url:
                    lines.append(f"Some of these come from {pack.index_url} "
                                 "— see the pack's README.")
            self._examples_menu.clear()
            for path in pack.examples():
                self._examples_menu.addAction(
                    path.stem, lambda p=path: self._open_example(p))
            self._examples_menu.setEnabled(bool(pack.examples()))
        for path, err in getattr(self, "_errors", []):
            lines.append(f"⚠ {path}: {err}")
        if not self._packs and not lines:
            lines.append("No node packs yet.")
        self._details.setText("\n".join(lines))

    # ------------------------------------------------------------ actions

    def _changed(self, select: str = "") -> None:
        self.refresh(select)
        self._window.reload_packs()

    def _start_dir(self) -> str:
        return QStandardPaths.writableLocation(
            QStandardPaths.DownloadLocation) or str(Path.home())

    def _install_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Install Node Pack", self._start_dir(),
            "Node packs (*.zip);;All files (*)")
        if path:
            self.install_from(Path(path))

    def install_from(self, path: Path) -> None:
        try:
            pack = packs.install(user_data_dir(), path)
        except packs.PackExistsError as exc:
            answer = QMessageBox.question(
                self, "Replace Pack?",
                f"{exc}. Replace it with the one in {path.name}?")
            if answer != QMessageBox.Yes:
                return
            try:
                pack = packs.install(user_data_dir(), path, replace=True)
            except (packs.PackError, OSError) as exc2:
                QMessageBox.warning(self, "Install failed", str(exc2))
                return
        except (packs.PackError, OSError) as exc:
            QMessageBox.warning(self, "Install failed", str(exc))
            return
        self._changed(pack.id)
        self._offer_requirements(pack)

    def _link_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Link a Pack Folder", str(Path.home()))
        if not folder:
            return
        try:
            found = packs.link(user_data_dir(), Path(folder))
        except (packs.PackError, OSError) as exc:
            QMessageBox.warning(self, "Link failed", str(exc))
            return
        self._changed(found[0].id)
        for pack in found:
            self._offer_requirements(pack)

    def _offer_requirements(self, pack: packs.Pack) -> None:
        missing = packs.missing_requirements(pack)
        if not missing:
            return
        answer = QMessageBox.question(
            self, "Install Requirements?",
            f"{pack.name} needs {', '.join(missing)}, which flograph's "
            "environment does not have. Open Manage Packages to install "
            "them?")
        if answer == QMessageBox.Yes:
            self._window.show_packages_for(missing)

    def _install_reqs(self) -> None:
        pack = self._current()
        if pack is not None:
            self._window.show_packages_for(packs.missing_requirements(pack))

    def _remove(self) -> None:
        pack = self._current()
        if pack is None:
            return
        verb = "Unlink" if pack.source == "linked" else "Remove"
        detail = ("Its folder is left where it is."
                  if pack.source == "linked"
                  else f"This deletes {pack.root}.")
        answer = QMessageBox.question(
            self, f"{verb} Pack?",
            f"{verb} {pack.name}? {detail} Flows that use its nodes will "
            "show them as missing until it is back.")
        if answer != QMessageBox.Yes:
            return
        try:
            packs.uninstall(user_data_dir(), pack)
        except (packs.PackError, OSError) as exc:
            QMessageBox.warning(self, f"{verb} failed", str(exc))
            return
        self._changed()

    def _toggle(self) -> None:
        pack = self._current()
        if pack is None:
            return
        packs.set_enabled(user_data_dir(), pack.id,
                          pack.id in self._disabled)
        self._changed(pack.id)

    def _open_folder(self) -> None:
        pack = self._current()
        if pack is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(pack.root)))

    def _export(self) -> None:
        pack = self._current()
        if pack is None:
            return
        default = str(Path(self._start_dir())
                      / f"{pack.id}-{pack.version}.zip")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Node Pack", default, "Node packs (*.zip)")
        if not path:
            return
        try:
            packs.export_zip(pack, Path(path))
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self._window.show_status(f"Wrote {path}", 5000)

    def _open_example(self, path: Path) -> None:
        self._window.open_example(path)

    def reload(self) -> None:
        self._changed()
