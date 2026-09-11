"""Tools ▸ What This Flow Needs (AC2): the Python packages and web libraries
the open flow uses, with what this machine is missing marked.

Read from the nodes' own code by `flograph.requirements`; nothing is
installed from here. The buttons open Manage Packages with the missing
names already in its install box, or Web Libraries, and the install is
still a button somebody presses.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

from flograph import packages
from flograph.requirements import PACKAGE, WEBLIB, missing, requirements_of

#: how many node names a row lists before "and N more"
USED_BY_SHOWN = 3


def status_text(need) -> str:
    """What a row says about whether it is there — short, to fit its
    column; `status_tip` says the rest."""
    if need.installed:
        return "installed"
    if need.optional:
        return "not installed (optional)"
    if not need.certain:
        return "not installed — name is a guess"
    return "not installed"


def status_tip(need) -> str:
    if need.installed:
        return "Installed on this machine."
    if need.optional:
        return ("Not installed, but every node that imports it has a "
                "fallback and manages without it.")
    if not need.certain:
        return (f"Not installed. The code imports “{need.module}”, and the "
                f"package is probably called “{need.name}” — check before "
                "installing.")
    return "Not installed: the nodes that use it will fail until it is."


def used_by_text(labels: list) -> str:
    shown = ", ".join(labels[:USED_BY_SHOWN])
    more = len(labels) - USED_BY_SHOWN
    return f"{shown} and {more} more" if more > 0 else shown


def flow_needs(graph, name_installed: bool = True) -> list:
    """What `graph` needs — flograph's own dependencies left out, since
    they are there whenever flograph is running. `name_installed=False`
    for a quick count of what is missing (see `requirements_of`)."""
    return requirements_of(graph.nodes.values(), skip=packages.CORE_PACKAGES,
                           name_installed=name_installed)


class RequirementsDialog(QDialog):
    def __init__(self, window, parent=None) -> None:
        super().__init__(parent or window)
        self.setWindowTitle("What This Flow Needs")
        self.resize(700, 420)
        self._window = window
        self.needs: list = []

        self._summary = QLabel()
        self._summary.setObjectName("requirements_summary")
        self._summary.setWordWrap(True)

        self._tree = QTreeWidget()
        self._tree.setObjectName("requirements_tree")
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(["Needs", "Kind", "Status", "Used by"])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        header = self._tree.header()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        self._tree.setColumnWidth(0, 170)
        self._tree.setColumnWidth(1, 90)
        self._tree.setColumnWidth(2, 250)

        self._install_btn = QPushButton("Install Missing Packages…")
        self._install_btn.setObjectName("requirements_install_button")
        self._install_btn.setToolTip(
            "Open Manage Packages with the missing packages in its install "
            "box — check the names, then press Install")
        self._install_btn.clicked.connect(self._install_missing)
        self._weblibs_btn = QPushButton("Web Libraries…")
        self._weblibs_btn.setObjectName("requirements_weblibs_button")
        self._weblibs_btn.clicked.connect(self._open_weblibs)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)

        buttons = QHBoxLayout()
        buttons.addWidget(self._install_btn)
        buttons.addWidget(self._weblibs_btn)
        buttons.addStretch(1)
        buttons.addWidget(refresh_btn)
        buttons.addWidget(close_btn)

        note = QLabel(
            "Read from each node's code — its imports, and the web libraries "
            "a visual asks for. An import name is not always the name you "
            "install (sklearn is scikit-learn); a guess is marked as one.")
        note.setWordWrap(True)
        font = note.font()
        font.setPointSizeF(font.pointSizeF() * 0.9)
        note.setFont(font)

        layout = QVBoxLayout(self)
        layout.addWidget(self._summary)
        layout.addWidget(self._tree, 1)
        layout.addWidget(note)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        self.needs = flow_needs(self._window.graph)
        self._tree.clear()
        bold = QFont(self._tree.font())
        bold.setBold(True)
        for need in self.needs:
            name = ("⚠ " if need.missing and not need.optional else "") \
                + need.name
            item = QTreeWidgetItem([name, need.kind, status_text(need),
                                    used_by_text(need.nodes)])
            if need.kind == PACKAGE and need.module \
                    and need.module.lower() != need.name.lower():
                item.setToolTip(0, f"import {need.module}")
            item.setToolTip(2, status_tip(need))
            item.setToolTip(3, "\n".join(need.nodes))
            if need.missing and not need.optional:
                for column in range(4):
                    item.setFont(column, bold)
            item.setData(0, Qt.UserRole, need)
            self._tree.addTopLevelItem(item)
        gaps = missing(self.needs)
        if not self.needs:
            self._summary.setText(
                "This flow uses nothing beyond flograph itself.")
        elif gaps:
            self._summary.setText(
                f"{len(gaps)} thing{'s' if len(gaps) != 1 else ''} this flow "
                f"uses {'is' if len(gaps) == 1 else 'are'} not installed "
                f"here. The nodes that use "
                f"{'it' if len(gaps) == 1 else 'them'} will fail until "
                f"{'it is' if len(gaps) == 1 else 'they are'}.")
        else:
            self._summary.setText(
                "Everything this flow uses is installed.")
        self._install_btn.setEnabled(bool(self._missing_packages()))
        self._weblibs_btn.setEnabled(
            any(n.kind == WEBLIB and n.missing for n in self.needs))

    def _missing_packages(self) -> list:
        """Missing packages to offer: the required ones, or the optional
        ones when those are all that is missing."""
        wanted = [n for n in missing(self.needs) if n.kind == PACKAGE]
        if not wanted:
            wanted = [n for n in missing(self.needs, include_optional=True)
                      if n.kind == PACKAGE]
        return [n.name for n in wanted]

    def _install_missing(self) -> None:
        names = self._missing_packages()
        if names:
            self._window.show_packages_for(names)

    def _open_weblibs(self) -> None:
        self._window._show_weblibs()

    def showEvent(self, event) -> None:
        # a package installed in the meantime shows as installed
        self.refresh()
        super().showEvent(event)
