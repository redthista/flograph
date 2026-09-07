"""Tools ▸ Web Libraries — install the JavaScript a visual node draws with.

The browser-side twin of Manage Packages, and deliberately the same shape:
a list of what you have, a button to add more, and everything landing in one
place flograph owns. The difference is where it comes from and when: a web
library is fetched from a CDN *here*, once, and from then on every node
reads it off the disk. Nothing in flograph renders from a CDN — see
flograph.weblibs for why that rule is worth the dialog.

The download runs on the thread pool. It is a few megabytes over someone
else's network, and a frozen window for the length of it would make a
one-off install feel like a fault.
"""
from __future__ import annotations

from PySide6.QtCore import (
    QObject, QRunnable, QStandardPaths, Qt, QThreadPool, Signal,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from flograph import weblibs


def _human(size: int) -> str:
    if size <= 0:
        return "—"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


class _InstallSignals(QObject):
    done = Signal(str, str)          # library name, error message ("" = ok)
    step = Signal(str, int, int, str)  # name, done, total, filename


class _Install(QRunnable):
    """One library's download, off the UI thread.

    Swallows nothing: the error text is what the dialog shows, and for a
    failed download that text is the only thing the user has to go on —
    a proxy refusing, a checksum that didn't match, a mirror with a gap.
    """

    def __init__(self, name: str, urls: "list[str] | None" = None,
                 title: str = "") -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.name = name
        self.urls = urls
        self.title = title
        self.signals = _InstallSignals()

    def run(self) -> None:
        def progress(done, total, filename):
            self.signals.step.emit(self.name, done, total, filename)
        try:
            if self.urls:
                weblibs.add_from_url(self.name, self.urls, title=self.title,
                                     progress=progress)
            else:
                weblibs.install(self.name, progress=progress)
        except Exception as exc:
            self.signals.done.emit(self.name, str(exc))
        else:
            self.signals.done.emit(self.name, "")


class WebLibrariesDialog(QDialog):
    NAME, VERSION, SIZE, STATUS = range(4)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Web Libraries")
        self.resize(680, 460)
        self._jobs: dict[str, _Install] = {}

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ["Library", "Version", "Size", "Status"])
        self._table.horizontalHeader().setSectionResizeMode(
            self.NAME, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.ExtendedSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._sync_buttons)

        self._install_btn = QPushButton("Install")
        self._install_btn.clicked.connect(self._install_selected)
        self._file_btn = QPushButton("Install from File…")
        self._file_btn.setToolTip(
            "Already downloaded the files in a browser? Pick them here and "
            "flograph will put them where they belong.")
        self._file_btn.clicked.connect(self._install_from_file)
        self._links_btn = QPushButton("Copy Links")
        self._links_btn.setToolTip(
            "Copy this library's download addresses, to paste into a browser "
            "on a machine where flograph itself can't reach them.")
        self._links_btn.clicked.connect(self._copy_links)
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.clicked.connect(self._remove_selected)
        buttons = QHBoxLayout()
        buttons.addWidget(self._install_btn)
        buttons.addWidget(self._file_btn)
        buttons.addWidget(self._links_btn)
        buttons.addWidget(self._remove_btn)
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)

        self._url_name = QLineEdit()
        self._url_name.setPlaceholderText("name, e.g. vis-network")
        self._url_name.setMaximumWidth(180)
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText(
            "…and one or more URLs, space separated")
        self._url_edit.returnPressed.connect(self._add_from_url)
        add_btn = QPushButton("Add from URL")
        add_btn.clicked.connect(self._add_from_url)
        url_row = QHBoxLayout()
        url_row.addWidget(self._url_name)
        url_row.addWidget(self._url_edit, 1)
        url_row.addWidget(add_btn)

        self._status = QLabel()
        self._status.setTextFormat(Qt.PlainText)
        self._status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Installed once, then used from your own machine — nothing here "
            "is loaded from the internet when a visual renders."))
        layout.addWidget(self._table, 1)
        layout.addLayout(buttons)
        layout.addLayout(url_row)
        layout.addWidget(self._status)

        self.refresh()

    # ---------------------------------------------------------------- table

    def _rows(self) -> "list[weblibs.Library]":
        """The catalogue, plus anything installed that isn't in it — so a
        library added from a URL doesn't vanish from the list that is
        supposed to show what you have."""
        rows = dict(weblibs.CATALOGUE)
        for library in weblibs.installed():
            rows.setdefault(library.name, library)
        return [rows[name] for name in sorted(rows)]

    def refresh(self) -> None:
        selected = self._selected_names()
        self._table.setRowCount(0)
        for library in self._rows():
            version = weblibs.installed_version(library.name)
            row = self._table.rowCount()
            self._table.insertRow(row)

            name_item = QTableWidgetItem(library.title or library.name)
            name_item.setData(Qt.UserRole, library.name)
            tip = library.summary or ""
            if library.license:
                tip = f"{tip}\n{library.license}".strip()
            if library.homepage:
                tip = f"{tip}\n{library.homepage}".strip()
            name_item.setToolTip(tip)
            self._table.setItem(row, self.NAME, name_item)
            self._table.setItem(row, self.VERSION,
                                QTableWidgetItem(library.version))
            self._table.setItem(row, self.SIZE,
                                QTableWidgetItem(_human(library.size)))
            busy = library.name in self._jobs
            self._table.setItem(row, self.STATUS, QTableWidgetItem(
                "Installing…" if busy else
                ("Installed" if version else "Not installed")))
            if library.name in selected:
                self._table.selectRow(row)

        count = len(weblibs.installed())
        self._status.setText(
            f"{count} installed · {weblibs.store_dir()}")
        self._sync_buttons()

    def _selected_names(self) -> list:
        names = []
        for item in self._table.selectedItems():
            if item.column() == self.NAME:
                names.append(item.data(Qt.UserRole))
        return names

    def _sync_buttons(self) -> None:
        names = self._selected_names()
        busy = bool(self._jobs)
        self._install_btn.setEnabled(
            bool(names) and not busy
            and any(not weblibs.is_installed(n) for n in names))
        # One at a time: the file picker has to name which library it is
        # collecting files for, and a dialog saying "choose the files" for
        # four libraries at once could only be answered by guessing.
        self._file_btn.setEnabled(
            len(names) == 1 and not busy and not weblibs.is_installed(names[0]))
        self._links_btn.setEnabled(bool(names))
        self._remove_btn.setEnabled(
            bool(names) and not busy
            and any(weblibs.is_installed(n) for n in names))

    # -------------------------------------------------------------- actions

    def _start(self, name: str, urls=None, title: str = "") -> None:
        job = _Install(name, urls, title)
        job.signals.done.connect(self._finished)
        job.signals.step.connect(self._progress)
        self._jobs[name] = job
        QThreadPool.globalInstance().start(job)

    def _install_selected(self) -> None:
        for name in self._selected_names():
            if not weblibs.is_installed(name) and name not in self._jobs:
                self._start(name)
        self.refresh()

    def _install_from_file(self) -> None:
        """Take files the user already has and put them in the store.

        The escape hatch for the machine this dialog is most needed on: a
        work PC where the download is blocked but the browser reaches cdnjs
        fine. Everything that makes a hand-built store folder go wrong —
        the version in the folder name, the exact filename, the manifest,
        all of it silently — is done here instead.
        """
        names = self._selected_names()
        if len(names) != 1:
            return
        name = names[0]
        library = weblibs.known(name)
        title = library.title if library else name
        wanted = (", ".join(a.filename for a in library.assets)
                  if library else "")
        caption = f"Choose the files for {title}"
        if wanted:
            caption = f"{caption} — {wanted}"
        paths, _ = QFileDialog.getOpenFileNames(
            self, caption,
            QStandardPaths.writableLocation(
                QStandardPaths.DownloadLocation),
            "Web libraries (*.js *.mjs *.css);;All files (*)")
        if not paths:
            return
        try:
            installed = weblibs.install_from_files(name, paths)
        except Exception as exc:
            QMessageBox.warning(
                self, "Install from file",
                f"{title} was not installed.\n\n{exc}")
            self.refresh()
            return
        self.refresh()
        self._status.setText(
            f"{installed.title} {installed.version} installed from "
            f"{len(paths)} file{'s' if len(paths) != 1 else ''} you supplied.")

    def _copy_links(self) -> None:
        """Put the download addresses on the clipboard.

        The first half of the same escape hatch: a URL that can be pasted
        into whatever browser *is* allowed. It is the address an install
        would really use, mirror setting included, rather than a cdnjs one
        printed from the catalogue and wrong on a mirrored network.
        """
        urls = []
        for name in self._selected_names():
            try:
                urls.extend(weblibs.download_urls(name))
            except weblibs.WebLibError:
                continue
        if not urls:
            QMessageBox.information(
                self, "Copy links",
                "There is nothing to download for this one — it was added "
                "from a file, so flograph never knew an address for it.")
            return
        QGuiApplication.clipboard().setText("\n".join(urls))
        self.refresh()
        self._status.setText(
            f"{len(urls)} link{'s' if len(urls) != 1 else ''} copied — open "
            f"in a browser, save the file, then Install from File…")

    def _add_from_url(self) -> None:
        name = self._url_name.text().strip()
        urls = self._url_edit.text().split()
        if not name or not urls:
            QMessageBox.information(
                self, "Add from URL",
                "Give the library a short name and at least one URL to fetch.")
            return
        self._url_name.clear()
        self._url_edit.clear()
        self._start(name, urls=urls, title=name)
        self.refresh()

    def _remove_selected(self) -> None:
        names = [n for n in self._selected_names() if weblibs.is_installed(n)]
        if not names:
            return
        listed = ", ".join(names)
        if QMessageBox.question(
                self, "Remove web libraries",
                f"Remove {listed}?\n\nAny node that draws with one will "
                f"report it as missing until it is installed again."
        ) != QMessageBox.Yes:
            return
        for name in names:
            weblibs.remove(name)
        self.refresh()

    # -------------------------------------------------------------- results

    def _progress(self, name: str, done: int, total: int,
                  filename: str) -> None:
        self._status.setText(f"{name}: {filename} ({done}/{total})")

    def _finished(self, name: str, error: str) -> None:
        self._jobs.pop(name, None)
        if error:
            # A blocked download is the common failure on the machines this
            # dialog exists for, and the way out is two buttons away — so
            # the message that reports it says so, rather than leaving the
            # user to conclude the library is simply unavailable to them.
            QMessageBox.warning(
                self, "Install failed",
                f"{name} could not be installed.\n\n{error}\n\n"
                f"If this machine can't reach the internet, use Copy Links "
                f"to download {name} in a browser, then Install from File…")
        self.refresh()
