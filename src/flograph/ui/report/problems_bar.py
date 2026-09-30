"""A report page's problems: one quiet row under the editor, a list when
clicked.

Every problem the page has — what the lint finds as you type (core/
report_lint.py) and what the render finds (an embed that names no node,
map outlines not installed) — used to be one orange sentence across the
toolbar, as long as the first message was and saying nothing of the rest.
Now it is one row at the foot of the text: a dot (red for an error, amber
when there are only warnings), how many, and the first of them, cut to fit.
Click it and the list opens above it; click a problem there and the editor
goes to its line. Nothing to say, and the row goes away.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QListView, QListWidget, QListWidgetItem,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..editor.diagnostics import DIAGNOSTIC_COLORS, dot_icon


@dataclass(frozen=True)
class Problem:
    source: str                 # "markdown", "css" or "preview"
    message: str
    line: Optional[int] = None  # 1-based, in its source's text
    severity: str = "error"     # "error" or "warning"

    def label(self) -> str:
        where = {"markdown": "Markdown", "css": "CSS"}.get(self.source,
                                                            "Preview")
        if self.line:
            where += f" · line {self.line}"
        return f"{where} — {self.message}"


#: the tallest the open list grows before it scrolls, in pixels
LIST_MAX_HEIGHT = 200


class ProblemsBar(QWidget):
    """The row, and the list it opens."""

    #: a problem was clicked: its source and line
    jump = Signal(str, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("report_problems")
        self._problems: list = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._list = QListWidget()
        self._list.setObjectName("report_problems_list")
        # wrapped to the width, never scrolled sideways: a problem is read
        # in full, not a line and a scroll bar
        self._list.setWordWrap(True)
        self._list.setUniformItemSizes(False)
        self._list.setResizeMode(QListView.Adjust)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setFrameShape(QListWidget.NoFrame)
        self._list.setStyleSheet(
            "QListWidget { border-top: 1px solid palette(mid); }"
            "QListWidget::item { padding: 3px 4px; }")
        self._list.itemClicked.connect(self._clicked)
        self._list.itemActivated.connect(self._clicked)
        self._list.hide()
        self._row = QToolButton()
        self._row.setObjectName("report_problems_row")
        self._row.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._row.setAutoRaise(True)
        self._row.setCursor(Qt.PointingHandCursor)
        self._row.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._row.setStyleSheet(
            "QToolButton { text-align: left; padding: 3px 8px;"
            " border-top: 1px solid palette(mid); border-radius: 0; }")
        self._row.clicked.connect(self.toggle)
        layout.addWidget(self._list)
        layout.addWidget(self._row)
        self.hide()

    # ------------------------------------------------------------- model

    def set_problems(self, problems: list) -> None:
        """Show these, errors first; none hides the bar."""
        order = {"error": 0, "warning": 1}
        self._problems = sorted(
            problems, key=lambda p: (order.get(p.severity, 2),
                                     p.source != "markdown", p.line or 0))
        self._list.clear()
        for problem in self._problems:
            item = QListWidgetItem(problem.label())
            item.setIcon(dot_icon(DIAGNOSTIC_COLORS.get(
                problem.severity, DIAGNOSTIC_COLORS["error"])))
            item.setToolTip(problem.label()
                            + ("\nClick to go to it." if problem.line else ""))
            self._list.addItem(item)
        if not self._problems:
            self._list.hide()
            self.hide()
            return
        worst = "error" if any(p.severity == "error"
                               for p in self._problems) else "warning"
        self._row.setIcon(dot_icon(DIAGNOSTIC_COLORS[worst]))
        self.show()
        self._fit_list()
        self._update_row()

    def _fit_list(self) -> None:
        """As tall as its rows, wrapped to the width it has, up to
        LIST_MAX_HEIGHT; past that it scrolls."""
        self._list.doItemsLayout()
        total = sum(max(self._list.sizeHintForRow(i),
                        self._list.fontMetrics().lineSpacing() + 6)
                    for i in range(self._list.count()))
        self._list.setFixedHeight(max(24, min(LIST_MAX_HEIGHT, total + 4)))

    def problems(self) -> list:
        return list(self._problems)

    def is_open(self) -> bool:
        return self._list.isVisibleTo(self)

    def toggle(self) -> None:
        self._list.setVisible(not self._list.isVisibleTo(self))
        if self.is_open():
            self._fit_list()
        self._update_row()

    # ---------------------------------------------------------- the row

    def _summary(self) -> str:
        count = len(self._problems)
        errors = sum(p.severity == "error" for p in self._problems)
        warnings = count - errors
        parts = []
        if errors:
            parts.append(f"{errors} error{'s' if errors != 1 else ''}")
        if warnings:
            parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
        return ", ".join(parts)

    def _update_row(self) -> None:
        if not self._problems:
            return
        arrow = "▾" if self.is_open() else "▴"
        head = f"{self._summary()}  {arrow}"
        first = self._problems[0].label()
        room = max(40, self._row.width() - 60)
        metrics = self._row.fontMetrics()
        if self.is_open():
            text = head
        else:
            tail = metrics.elidedText(first, Qt.ElideRight,
                                      max(0, room - metrics.horizontalAdvance(
                                          head + "  ·  ")))
            text = f"{head}  ·  {tail}" if tail else head
        self._row.setText(text)
        self._row.setToolTip(
            "Click to see every problem" if not self.is_open()
            else "Click to close the list")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.is_open() and event.size().width() != event.oldSize().width():
            self._fit_list()          # rows wrap differently at a new width
        self._update_row()

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(0, hint.height())

    def _clicked(self, item) -> None:
        index = self._list.row(item)
        if 0 <= index < len(self._problems):
            problem = self._problems[index]
            if problem.line:
                self.jump.emit(problem.source, problem.line)
