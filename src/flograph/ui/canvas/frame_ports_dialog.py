"""Inputs and outputs of a frame that has become a model canvas (G13).

A box stands for a block of the flow, and what it shows on its edges is
the whole of its interface. Derived pins — one per wire that happens to
cross — say only which node and port they land on; a declared port says
what the block takes and gives, in words chosen by whoever built it.

Every port a node inside could expose is listed, ticked when declared, so
the dialog is a picture of the block's surface rather than a form to fill
in twice. A name defaults to the port's own, which is right often enough
to leave alone.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHeaderView, QLabel, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from flograph.core import FramePort

#: (node_id, node label, port name, "input" | "output") for every port of
#: every node on the box's canvas — what the dialog offers.
Candidate = tuple


class FramePortsDialog(QDialog):
    def __init__(self, title: str, candidates: list, ports: tuple,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Inputs and outputs — {title}")
        self._candidates = list(candidates)
        declared = {(p.node_id, p.port): p.name for p in ports}

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Tick what this box shows on its edges, and name it. A wire to "
            "a declared port is a real wire to the node behind it — the "
            "name only decides what the box calls it.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        layout.addWidget(hint)

        self.table = QTableWidget(len(self._candidates), 3, self)
        self.table.setHorizontalHeaderLabels(["Show", "Name", "Inside"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        for row, (node_id, label, port, side) in enumerate(self._candidates):
            tick = QTableWidgetItem()
            tick.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            on = (node_id, port) in declared
            tick.setCheckState(Qt.Checked if on else Qt.Unchecked)
            self.table.setItem(row, 0, tick)

            name = QTableWidgetItem(declared.get((node_id, port), port))
            self.table.setItem(row, 1, name)

            inside = QTableWidgetItem(
                f"{label} · {port}   ({'in' if side == 'input' else 'out'})")
            inside.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 2, inside)
        layout.addWidget(self.table)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(520, 380)

    def ports(self) -> tuple:
        """The declared ports, in the order they are listed — which is the
        order they stack down the box's edges."""
        chosen = []
        for row, (node_id, _label, port, side) in enumerate(self._candidates):
            tick = self.table.item(row, 0)
            if tick is None or tick.checkState() != Qt.Checked:
                continue
            name = (self.table.item(row, 1).text().strip() or port)
            chosen.append(FramePort(name=name, node_id=node_id, port=port,
                                    side=side))
        return tuple(chosen)
