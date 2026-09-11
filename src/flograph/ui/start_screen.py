"""The start screen: what the window shows when flograph opens with no
project named (O1), the way PyCharm opens on its recent projects.

It is a page in the window's canvas stack rather than a window of its own.
The window always holds a live canvas, and everything a start screen offers
— New, Open, an example, a recent file — ends in the same `_replace_graph`
that puts the canvas back in front, so there is no second window to hand
over to and nothing to tear down. See MainWindow.show_start_screen.

The rows are the title bar's project switcher's own (`_RecentRow`): same
initials tile, same name and folder, same star — one idea of what a
recent workflow looks like. The one thing the start screen adds is when
each was last edited, read from the file itself, so nothing new has to be
recorded to know it.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from . import theme
from .window_frame import _RecentRow, frame_icon, project_display_name

#: Wider than this and the eye has too far to travel between a name and
#: its star; the screen centres a column of this width on a wide window.
CONTENT_WIDTH = 980

_BG = theme.CANVAS_BG.name()   # the canvas is always dark, and this is it
_QSS = f"""
QWidget#start_screen {{ background: {_BG}; }}
QLabel#start_title {{ color: #f3f4f6; }}
QLabel#start_lede, QLabel#start_empty {{ color: #8b8f99; }}
QLabel#start_heading {{ color: #9ca3af; font-weight: bold; }}
QPushButton {{
    background: #2a2c33; color: #e5e7eb; border: 1px solid #3a3d46;
    border-radius: 5px; padding: 7px 12px; text-align: left;
}}
QPushButton:hover {{ background: #34363f; }}
QPushButton#start_primary {{
    background: {theme.BUTTON_ACCENT.name()}; border-color: transparent;
    color: #ffffff;
}}
QPushButton#start_link {{
    background: transparent; border: none; color: #8b8f99; padding: 4px 2px;
}}
QPushButton#start_link:hover {{ color: #e5e7eb; }}
QLineEdit {{
    background: #24262c; color: #e5e7eb; border: 1px solid #3a3d46;
    border-radius: 5px; padding: 6px 8px;
}}
QListWidget {{
    background: transparent; border: none; color: #c9ccd3;
}}
QListWidget::item {{ padding: 4px 6px; border-radius: 4px; }}
QListWidget::item:hover {{ background: #34363f; color: #f3f4f6; }}
QScrollArea, QWidget#start_rows {{ background: transparent; border: none; }}
"""


def example_title(name: str) -> str:
    """`07_sales_by_region.flograph` as the menu says it: Sales By Region."""
    stem = name[:-len(".flograph")] if name.endswith(".flograph") else name
    if stem[:2].isdigit() and "_" in stem:
        stem = stem.split("_", 1)[1]
    return stem.replace("_", " ").title()


def example_entries() -> list:
    """Every bundled example as (title, path), sorted by title.

    Shared by File ▸ Open Example and the start screen, so the two lists
    cannot disagree about which examples there are.
    """
    import importlib.resources
    try:
        root = importlib.resources.files("flograph.templates")
        entries = [entry for entry in root.iterdir()
                   if entry.name.endswith(".flograph")]
    except (ModuleNotFoundError, FileNotFoundError):
        entries = []
    return sorted(((example_title(entry.name), Path(str(entry)))
                   for entry in entries),
                  key=lambda item: item[0].casefold())


def edited_ago(mtime: float, now: Optional[float] = None) -> str:
    """When a file was last written, the way a person would say it.

    Minutes and hours while that is still the useful answer, then days, and
    past a month the date itself — "edited 41 days ago" makes you do sums
    that "edited on 2 Aug 2026" does not.
    """
    now = time.time() if now is None else now
    seconds = max(0.0, now - mtime)
    minutes = int(seconds // 60)
    hours = int(seconds // 3600)
    days = int(seconds // 86400)
    if minutes < 1:
        return "edited just now"
    if hours < 1:
        return f"edited {minutes} minute{'s' * (minutes != 1)} ago"
    if days < 1:
        return f"edited {hours} hour{'s' * (hours != 1)} ago"
    if days < 2:
        return "edited yesterday"
    if days < 31:
        return f"edited {days} days ago"
    when = datetime.fromtimestamp(mtime)
    return f"edited on {when.day} {when.strftime('%b %Y')}"


def _fit_row(row) -> None:
    """Let a switcher row narrow to the column it is in.

    In the title bar's menu a row sets the menu's width, so its folder line
    is elided to a fixed 340px and asks for all of it. On the start screen
    the column is whatever the docks leave, and a row that insists on its
    width pushes the "edited" note off the right edge. So here the name and
    folder give way — clipped at the right, which the folder, already
    elided in the middle, can afford — and the note and the star keep
    their room.
    """
    row.setMinimumWidth(0)
    detail = getattr(row, "detail_label", None)
    for label in row.findChildren(QLabel):
        if label is not detail and label.pixmap().isNull():
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            label.setMinimumWidth(0)


def _edited(path: str) -> str:
    try:
        return edited_ago(Path(path).stat().st_mtime)
    except OSError:
        return ""


class StartScreen(QWidget):
    """New, Open and the examples down the left; favourite and recent
    workflows down the right, with a box to search them.

    Rebuilt by `refresh` every time it is shown, because what it lists
    lives in the settings and changes whenever anything is opened or saved.
    """

    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self._window = window
        self.setObjectName("start_screen")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_QSS)
        # (row, what a search matches against), in the order shown
        self._rows: list = []
        self._headings: list = []   # (heading label, [rows under it])

        outer = QHBoxLayout(self)
        outer.setContentsMargins(32, 40, 32, 24)
        outer.addStretch(1)
        body = QWidget()
        body.setMaximumWidth(CONTENT_WIDTH)
        outer.addWidget(body, 100)
        outer.addStretch(1)

        columns = QHBoxLayout(body)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(32)
        columns.addLayout(self._build_left(), 0)
        columns.addLayout(self._build_right(), 1)

    # ------------------------------------------------------------ building

    def _build_left(self) -> QVBoxLayout:
        left = QVBoxLayout()
        left.setSpacing(8)

        title = QLabel("flograph")
        title.setObjectName("start_title")
        font = title.font()
        font.setPointSizeF(font.pointSizeF() * 2.0)
        font.setBold(True)
        title.setFont(font)
        left.addWidget(title)
        lede = QLabel("Pick up where you left off, or start something new.")
        lede.setObjectName("start_lede")
        lede.setWordWrap(True)
        left.addWidget(lede)
        left.addSpacing(12)

        window = self._window
        self.new_button = self._button(
            "New Workflow", "new_doc", window.action_new, primary=True)
        self.open_button = self._button("Open…", "folder", window.action_open)
        left.addWidget(self.new_button)
        left.addWidget(self.open_button)
        self.leave_button = QPushButton()
        self.leave_button.setObjectName("start_link")
        self.leave_button.setCursor(Qt.PointingHandCursor)
        self.leave_button.clicked.connect(window.leave_start_screen)
        left.addWidget(self.leave_button)

        left.addSpacing(16)
        left.addWidget(self._heading("Examples"))
        self.examples = QListWidget()
        self.examples.setObjectName("start_examples")
        self.examples.setCursor(Qt.PointingHandCursor)
        self.examples.setFixedWidth(260)
        for text, path in example_entries():
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, str(path))
            self.examples.addItem(item)
        self.examples.itemClicked.connect(
            lambda item: window._open_example(Path(item.data(Qt.UserRole))))
        left.addWidget(self.examples, 1)
        return left

    def _build_right(self) -> QVBoxLayout:
        right = QVBoxLayout()
        right.setSpacing(10)
        self.search = QLineEdit()
        self.search.setObjectName("start_search")
        self.search.setPlaceholderText("Search recent workflows")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_search)
        right.addWidget(self.search)

        rows_host = QWidget()
        rows_host.setObjectName("start_rows")
        self._rows_layout = QVBoxLayout(rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        self._rows_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # rows narrow to fit rather than scrolling sideways — see _fit_row
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(rows_host)
        right.addWidget(scroll, 1)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("start_empty")
        self.empty_label.setWordWrap(True)
        self.empty_label.hide()
        right.addWidget(self.empty_label)
        return right

    def _button(self, text: str, glyph: str, action,
                primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        if primary:
            button.setObjectName("start_primary")
        button.setIcon(frame_icon(glyph))
        button.setIconSize(QSize(16, 16))
        button.setCursor(Qt.PointingHandCursor)
        key = action.shortcut().toString()
        if key:
            button.setToolTip(f"{text} ({key})")
        button.clicked.connect(action.trigger)
        return button

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setObjectName("start_heading")
        return label

    # ------------------------------------------------------------- content

    def refresh(self) -> None:
        """List what the settings hold now: favourites first, then recent
        workflows that are not already starred. Files that have gone are
        left out — the settings keep them, as the switcher does, so a drive
        that is offline today costs nothing tomorrow."""
        window = self._window
        self._clear_rows()
        favs = window._favorite_workflows_existing()
        recent = [p for p in window._recent_files_existing() if p not in favs]
        for title, paths in (("Favourites", favs),
                             ("Recent workflows", recent)):
            if paths:
                self._add_section(title, paths)

        has_work = bool(window._project_path or window.graph.nodes)
        self.leave_button.setText(
            f"Back to {project_display_name(window._project_path)}"
            if has_work else "Start on an Empty Canvas")
        self._apply_search(self.search.text())

    def _add_section(self, title: str, paths: list) -> None:
        heading = self._heading(title)
        at = self._rows_layout.count() - 1   # above the closing stretch
        self._rows_layout.insertWidget(at, heading)
        rows = []
        for path in paths:
            row = _RecentRow(
                path, self._window.open_path,
                is_fav=self._window.is_favorite_workflow(path),
                on_toggle_fav=self._toggle_favorite,
                detail=_edited(path))
            _fit_row(row)
            at += 1
            self._rows_layout.insertWidget(at, row)
            haystack = f"{project_display_name(path)} {path}".casefold()
            self._rows.append((row, haystack))
            rows.append(row)
        self._headings.append((heading, rows))

    def _clear_rows(self) -> None:
        for heading, rows in self._headings:
            for widget in (heading, *rows):
                self._rows_layout.removeWidget(widget)
                widget.deleteLater()
        self._rows = []
        self._headings = []

    def _toggle_favorite(self, path: str) -> bool:
        starred = self._window.toggle_favorite_workflow(path)
        # rebuilt a beat later: the row whose star was clicked is the one
        # handling this click, and clearing the list deletes it
        QTimer.singleShot(0, self.refresh)
        return starred

    def _apply_search(self, text: str) -> None:
        needle = (text or "").strip().casefold()
        for row, haystack in self._rows:
            row.setHidden(bool(needle) and needle not in haystack)
        for heading, rows in self._headings:
            heading.setHidden(all(row.isHidden() for row in rows))
        if not self._rows:
            self.empty_label.setText(
                "Nothing opened yet. Start a new workflow, open one you "
                "have, or begin from one of the examples.")
            self.empty_label.show()
        elif all(row.isHidden() for row, _ in self._rows):
            self.empty_label.setText(f"No recent workflow matches “{text}”.")
            self.empty_label.show()
        else:
            self.empty_label.hide()

    def rows(self) -> list:
        """The workflow rows in the order shown, hidden ones included."""
        return [row for row, _ in self._rows]

    def section_titles(self) -> list:
        return [heading.text() for heading, _ in self._headings]
