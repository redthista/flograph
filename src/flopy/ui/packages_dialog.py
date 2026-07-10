"""Packages dialog: browse, install, upgrade and uninstall pip packages in
flopy's own environment (Tools > Manage Packages).

The installer (pip, or `uv pip` when the venv has no pip) runs as a
QProcess so the UI stays live and its output streams into the log pane.
Nodes import from this same environment, so anything installed here is
immediately available to `run()` code — except for *upgrades* of modules
already imported by the running app, which need a restart to take effect.
"""
from __future__ import annotations

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from flopy import packages


class PackagesDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage Packages")
        self.resize(720, 560)
        self._process: QProcess | None = None

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter installed packages…")
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self._apply_filter)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Package", "Version"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.ExtendedSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)

        self._install_edit = QLineEdit()
        self._install_edit.setPlaceholderText(
            "package to install, e.g. requests or polars==1.8")
        self._install_edit.returnPressed.connect(self._install)
        self._install_btn = QPushButton("Install")
        self._install_btn.clicked.connect(self._install)
        install_row = QHBoxLayout()
        install_row.addWidget(self._install_edit, 1)
        install_row.addWidget(self._install_btn)

        self._upgrade_btn = QPushButton("Upgrade Selected")
        self._upgrade_btn.clicked.connect(self._upgrade)
        self._uninstall_btn = QPushButton("Uninstall Selected")
        self._uninstall_btn.clicked.connect(self._uninstall)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel_process)
        buttons = QHBoxLayout()
        buttons.addWidget(self._upgrade_btn)
        buttons.addWidget(self._uninstall_btn)
        buttons.addStretch(1)
        buttons.addWidget(self._cancel_btn)
        buttons.addWidget(self._refresh_btn)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(2000)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSizeF(9.0)
        self._log.setFont(font)

        self._status = QLabel()
        self._status.setTextFormat(Qt.PlainText)

        layout = QVBoxLayout(self)
        layout.addWidget(self._filter)
        layout.addWidget(self._table, 3)
        layout.addLayout(install_row)
        layout.addLayout(buttons)
        layout.addWidget(self._log, 2)
        layout.addWidget(self._status)

        kind = packages.installer_kind()
        if kind is None:
            self._status.setText(
                "No installer available — no pip in this environment and no "
                "uv on PATH.")
            for btn in (self._install_btn, self._upgrade_btn,
                        self._uninstall_btn):
                btn.setEnabled(False)
        else:
            self._status.setText(f"Installer: {kind} — packages land in "
                                 f"flopy's own environment.")
        self.refresh()

    # ---------------------------------------------------------------- table

    def refresh(self) -> None:
        self._table.setRowCount(0)
        for name, version in packages.list_installed():
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(name))
            self._table.setItem(row, 1, QTableWidgetItem(version))
        self._apply_filter(self._filter.text())

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self._table.rowCount()):
            name = self._table.item(row, 0).text()
            self._table.setRowHidden(row, bool(needle) and needle not in name)

    def _selected_packages(self) -> list[str]:
        rows = {index.row() for index in self._table.selectedIndexes()}
        return [self._table.item(row, 0).text() for row in sorted(rows)]

    # -------------------------------------------------------------- actions

    def _install(self) -> None:
        spec = self._install_edit.text().strip()
        if spec:
            self._run_installer("install", spec.split())

    def _upgrade(self) -> None:
        selected = self._selected_packages()
        if selected:
            self._run_installer("upgrade", selected)

    def _uninstall(self) -> None:
        selected = self._selected_packages()
        if not selected:
            return
        core = [p for p in selected if p in packages.CORE_PACKAGES]
        if core:
            QMessageBox.warning(
                self, "Protected packages",
                f"flopy itself depends on: {', '.join(core)} — uninstalling "
                f"them would break the running app, so they are protected.")
            return
        answer = QMessageBox.question(
            self, "Uninstall packages",
            "Uninstall " + ", ".join(selected) + "?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self._run_installer("uninstall", selected)

    # -------------------------------------------------------------- process

    @property
    def busy(self) -> bool:
        return (self._process is not None
                and self._process.state() != QProcess.NotRunning)

    def _run_installer(self, action: str, specs: list[str]) -> None:
        if self.busy:
            return
        try:
            argv = packages.build_command(action, specs)
        except (ValueError, RuntimeError) as exc:
            self._append_log(f"error: {exc}")
            return
        self._append_log("$ " + " ".join(argv))
        self._set_busy(True)
        process = QProcess(self)
        process.readyReadStandardOutput.connect(
            lambda: self._append_log(bytes(
                process.readAllStandardOutput()).decode(errors="replace"),
                newline=False))
        process.readyReadStandardError.connect(
            lambda: self._append_log(bytes(
                process.readAllStandardError()).decode(errors="replace"),
                newline=False))
        process.finished.connect(
            lambda code, _status: self._on_finished(action, code))
        process.errorOccurred.connect(
            lambda _err: self._append_log(process.errorString()))
        self._process = process
        process.start(argv[0], argv[1:])

    def _on_finished(self, action: str, code: int) -> None:
        self._append_log(f"— {action} "
                         f"{'finished' if code == 0 else f'failed ({code})'} —")
        if code == 0 and action in ("upgrade", "uninstall"):
            self._append_log(
                "note: modules already imported by the running app keep "
                "their old version until flopy is restarted")
        self._set_busy(False)
        self.refresh()

    def _cancel_process(self) -> None:
        if self.busy:
            self._process.kill()

    def _set_busy(self, busy: bool) -> None:
        for btn in (self._install_btn, self._upgrade_btn,
                    self._uninstall_btn, self._refresh_btn):
            btn.setEnabled(not busy)
        self._cancel_btn.setEnabled(busy)

    def _append_log(self, text: str, newline: bool = True) -> None:
        if newline:
            self._log.appendPlainText(text.rstrip("\n"))
        else:
            self._log.moveCursor(QTextCursor.End)
            self._log.insertPlainText(text)
            self._log.moveCursor(QTextCursor.End)

    def closeEvent(self, event) -> None:
        if self.busy:
            self._process.kill()
            self._process.waitForFinished(2000)
        super().closeEvent(event)
