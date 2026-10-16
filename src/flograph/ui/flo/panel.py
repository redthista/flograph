"""The Flo Assistant dock: a chat that can read and change the flow.

Privacy is the first thing on the panel, not a setting behind it. The
**privacy card** under the connection says in plain words where the words
go (*Local — nothing leaves this PC* / *Online — sent to <host>*) and what
Flo sees, and carries the controls:

- **Flo can see** — Nothing from my data / Column names / Column names and
  summaries: the flow's own level, saved in it and changed by an undoable
  command;
- **Columns…** — per column Hidden / Name only / Name and values, also
  saved in the flow (`privacy_dialog.py`);
- **Can** — Advise (look and explain) or Act (change the flow; each reply
  is one undo step).

Every reply ends with a **receipt** read back from the requests that went
(`flo/receipt.py`): where they went, which column names, whether any
ranges, and that no rows did. The first send to an online server asks
first (`consent.py`), listing what it will and won't see.

What the model is shown is decided by `core/ai_disclosure.py` and by which
tools exist (`flo/tools.py`) — this file only sets the controls and shows the
result. Two rules are enforced here because only the dock sees them happen:

- a **different connection** starts a fresh chat, so nothing the last
  server was shown is replayed to a new one;
- **lowering** what it sees starts a fresh chat too: the history holds what
  the higher level let through, and every request resends the history.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QDesktopServices, QIcon, QKeyEvent,
    QPainter, QPainterPath, QPixmap,
)
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from ...core import ai_disclosure as disc
from ...flo import receipt as receipts
from ...flo.agent import (
    DEFAULT_MAX_STEPS, STEP_CHOICES, Conversation, Event, TurnResult,
)
from ...flo.sendlog import SendLog, log_dir
from ...flo.tools import ACT, ADVISE, Toolbox
from ...llm import wire
from ...llm.profiles import ProfileSet, save as save_profiles
from .bridge import TurnBridge
from .sent_view import SentDialog, format_requests

LEVEL_NAMES = disc.LEVEL_NAMES
LEVEL_TIPS = {
    0: "The flow's layout only — which nodes, how they are wired, their "
       "settings. No column names (they go as <column>, even in what you "
       "type) and no text typed into settings.",
    1: "Also column names and types, and settings as you typed them. "
       "Never rows.",
    2: "Also, per column: how much is empty, how many different values, "
       "the lowest and highest value, and what it looks like (emails, "
       "IDs…). Never rows.",
    3: "Everything: real rows (a sample with each table, and more when it "
       "asks), every category's values, and error messages as they are. "
       "Hidden columns stay hidden.",
}
# what the card says it sees, by level — short, plain, no jargon
LEVEL_SEES = {
    0: "Only the flow's layout — nothing from your data.",
    1: "The flow and your column names — never rows.",
    2: "The flow, column names and summaries — never rows.",
    3: "All your data, rows included — except hidden columns.",
}
AUTONOMY = ((ADVISE, "Advise", "Look at the flow and explain or suggest — "
             "it cannot change anything"),
            (ACT, "Act", "Change the flow: add, wire, set and delete nodes, "
             "make dashboard and report pages, and write node code. "
             "Each reply is one undo step"))

TOOL_WORDS = {
    "describe_flow": "Looking at the flow",
    "get_node": "Reading a node",
    "find_node_types": "Searching the node library",
    "get_node_type": "Reading a node type",
    "get_output": "Reading an output's columns",
    "add_node": "Adding a node",
    "connect": "Wiring",
    "disconnect": "Unwiring",
    "set_params": "Changing settings",
    "rename_node": "Renaming a node",
    "delete_nodes": "Deleting nodes",
    "run_nodes": "Running nodes",
    "get_rows": "Reading rows",
    "get_page": "Reading a page",
    "add_page": "Making a page",
    "add_tiles": "Adding tiles",
    "remove_tiles": "Removing tiles",
    "write_report": "Writing a report",
    "rename_page": "Renaming a page",
    "delete_page": "Deleting a page",
    "set_report_style": "Styling a report",
    "write_report_css": "Writing a report's CSS",
    "set_report_layout": "Laying out a report",
    "get_node_code": "Reading a node's code",
    "write_node_code": "Writing code",
}
RUN_TIMEOUT = 600.0    # seconds a run_nodes call waits before giving up
ACTION_MARK = {"add_node": "+", "delete_nodes": "−", "connect": "→",
               "disconnect": "×", "add_page": "+", "add_tiles": "+",
               "remove_tiles": "−", "delete_page": "−",
               "write_node_code": "✎"}
SUGGESTIONS = (
    "Add a bar chart from my data",
    "Explain what this flow does",
    "What could be simpler here?",
)

_THINK = re.compile(r"<think>.*?(</think>|$)", re.DOTALL | re.IGNORECASE)
_TOOL_FENCE = re.compile(r"```\s*(tool|json)\b", re.IGNORECASE)


def visible_text(raw: str) -> str:
    """What of a reply still arriving is worth showing: no reasoning
    blocks, and nothing from a JSON tool call on (the fallback protocol
    writes its calls into the text)."""
    text = _THINK.sub("", raw or "")
    fence = _TOOL_FENCE.search(text)
    if fence:
        text = text[:fence.start()]
    return text.strip()


LOCAL_TINT = QColor(74, 222, 128)
ONLINE_TINT = QColor(250, 204, 21)

_STYLE = """
QFrame#flo_card_local { background: rgba(74,222,128,0.09);
    border: 1px solid rgba(74,222,128,0.30); border-radius: 10px; }
QFrame#flo_card_online { background: rgba(250,204,21,0.07);
    border: 1px solid rgba(250,204,21,0.30); border-radius: 10px; }
QToolButton#flo_pill { border: 1px solid rgba(127,127,127,0.35);
    border-radius: 11px; padding: 2px 9px; background: transparent; }
QToolButton#flo_pill:hover { background: rgba(127,127,127,0.16); }
QToolButton#flo_pill:disabled { color: palette(placeholder-text); }
QToolButton#flo_pill::menu-indicator { image: none; width: 0; }
QToolButton#flo_flat { border: none; border-radius: 6px; padding: 3px 6px;
    background: transparent; }
QToolButton#flo_flat:hover { background: rgba(127,127,127,0.16); }
QToolButton#flo_flat::menu-indicator { image: none; width: 0; }
QFrame#flo_user { background: rgba(124,108,246,0.20); border-radius: 14px; }
QFrame#flo_changes { border: 1px solid rgba(127,127,127,0.22);
    border-radius: 10px; }
QFrame#flo_error { background: rgba(239,68,68,0.12); border-radius: 10px; }
QFrame#flo_input { border: 1px solid rgba(127,127,127,0.35);
    border-radius: 14px; background: palette(base); }
QFrame#flo_input QPlainTextEdit { border: none; background: transparent; }
QToolButton#flo_send { border: none; border-radius: 14px;
    background: #7c6cf6; color: white; font-weight: bold;
    min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; }
QToolButton#flo_send:hover { background: #8f81f8; }
QToolButton#flo_send:disabled { background: rgba(127,127,127,0.30); }
QPushButton#flo_chip { border: 1px solid rgba(127,127,127,0.30);
    border-radius: 12px; padding: 5px 12px; text-align: left;
    background: transparent; }
QPushButton#flo_chip:hover { background: rgba(127,127,127,0.14); }
QFrame#flo_about { background: rgba(124,108,246,0.14); border-radius: 10px; }
QLabel#flo_muted { color: palette(placeholder-text); }
QScrollArea#flo_scroll, QScrollArea#flo_scroll > QWidget > QWidget {
    background: transparent; }
QScrollArea#flo_scroll QScrollBar:vertical { width: 8px; margin: 2px 0;
    background: transparent; border: none; }
QScrollArea#flo_scroll QScrollBar::handle:vertical {
    background: rgba(127,127,127,0.35); border-radius: 4px; min-height: 32px; }
QScrollArea#flo_scroll QScrollBar::handle:vertical:hover {
    background: rgba(127,127,127,0.55); }
QScrollArea#flo_scroll QScrollBar::add-line:vertical,
QScrollArea#flo_scroll QScrollBar::sub-line:vertical { height: 0; }
QScrollArea#flo_scroll QScrollBar::add-page:vertical,
QScrollArea#flo_scroll QScrollBar::sub-page:vertical { background: none; }
QLabel#flo_title { font-size: 15px; font-weight: 600; }
"""


def shield_icon(color: QColor, size: int = 16) -> QIcon:
    """A small shield — the privacy card's mark, tinted local/online."""
    icon = QIcon()
    for ratio in (1, 2):
        pm = QPixmap(size * ratio, size * ratio)
        pm.fill(Qt.transparent)
        pm.setDevicePixelRatio(ratio)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(0, 0, size, size).adjusted(2, 1, -2, -1)
        path = QPainterPath(QPointF(r.center().x(), r.top()))
        path.lineTo(r.right(), r.top() + r.height() * 0.18)
        path.cubicTo(QPointF(r.right(), r.top() + r.height() * 0.62),
                     QPointF(r.center().x() + r.width() * 0.25, r.bottom() - 1),
                     QPointF(r.center().x(), r.bottom()))
        path.cubicTo(QPointF(r.center().x() - r.width() * 0.25, r.bottom() - 1),
                     QPointF(r.left(), r.top() + r.height() * 0.62),
                     QPointF(r.left(), r.top() + r.height() * 0.18))
        path.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawPath(path)
        p.end()
        icon.addPixmap(pm)
    return icon


def _link_style() -> str:
    from .. import theme
    colour = "#a99cff" if theme.is_dark() else "#5b4bd6"
    return f"color:{colour}; text-decoration:none;"


def _styled(html: str) -> str:
    """Links in the panel's own accent, not the platform's underlined blue
    — paler on dark, deeper on light, so they read on either."""
    return html.replace("<a href=", f'<a style="{_link_style()}" href=')


def _label(text: str = "", *, muted: bool = False, rich: bool = False,
           markdown: bool = False, name: str = "") -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    label.setTextFormat(Qt.MarkdownText if markdown else
                        Qt.RichText if rich else Qt.PlainText)
    label.setText(_styled(text) if rich else text)
    label.setTextInteractionFlags(Qt.TextBrowserInteraction)
    label.setOpenExternalLinks(False)
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
    if name or muted:
        label.setObjectName(name or "flo_muted")
    return label


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _pill(text: str, tip: str = "") -> QToolButton:
    button = QToolButton()
    button.setObjectName("flo_pill")
    button.setText(text)
    button.setToolTip(tip)
    button.setPopupMode(QToolButton.InstantPopup)
    button.setCursor(Qt.PointingHandCursor)
    return button


class _Input(QPlainTextEdit):
    """Enter sends; Shift+Enter is a new line."""
    submitted = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (
                event.modifiers() & Qt.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class FloPanel(QWidget):
    navigate_requested = Signal(str, str)
    settings_requested = Signal()
    review_code_requested = Signal(str)     # node id: open its code editor

    def __init__(self, graph, registry, undo_stack, cache=None, *,
                 settings: Optional[QSettings] = None, engine=None,
                 parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.graph = graph
        self.registry = registry
        self.undo_stack = undo_stack
        self.cache = cache
        self.settings = settings or QSettings("flograph", "flograph")
        self.profiles: Optional[ProfileSet] = None
        self.chat: Optional[Conversation] = None
        self.toolbox: Optional[Toolbox] = None
        self.bridge: Optional[TurnBridge] = None
        self.send_log = SendLog()
        self._chat_profile: Optional[dict] = None   # as the chat began
        self._chat_level = -1          # the most the chat's history has seen
        self._agreed: set = set()      # (profile id, level) agreed this session
        self._busy = False
        self._cancel = False
        self._turns: list[dict] = []
        self._turn: dict = {}
        self._started = 0.0
        self._doing = ""
        self._welcome: Optional[QWidget] = None
        self._user_bubbles: list[QFrame] = []
        self._about: list[str] = []           # node ids "this" means
        # () -> the id of the page in front of the user, or "" for the
        # canvas; the window sets it, so "this report" means something
        self.on_screen = lambda: ""
        # (node_id, code) -> put code in that node's code editor, unapplied;
        # and take it back again. The window sets both; with no editor,
        # Flo is not offered write_node_code at all
        self.suggest_code = None
        self.discard_code = lambda node_id, code: None
        self._about_title = ""
        self._live: Optional[QLabel] = None   # the reply as it arrives
        self._live_raw = ""
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(50)
        self._live_timer.timeout.connect(self._paint_live)
        self.setStyleSheet(_STYLE)
        self._build()
        self.reload_profiles()
        # a bound slot, so the connection dies with the panel
        self.undo_stack.indexChanged.connect(self._on_undo_index)
        self._clear_thread()

    # -- layout ---------------------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(4)
        self.connection_btn = QToolButton()
        self.connection_btn.setObjectName("flo_flat")
        self.connection_btn.setPopupMode(QToolButton.InstantPopup)
        self.connection_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.connection_btn.setToolTip("Which AI connection to use")
        self.connection_menu = QMenu(self.connection_btn)
        self.connection_btn.setMenu(self.connection_menu)
        top.addWidget(self.connection_btn)
        top.addStretch(1)
        self.new_btn = QToolButton()
        self.new_btn.setObjectName("flo_flat")
        self.new_btn.setText("New chat")
        self.new_btn.setToolTip("Start a fresh conversation")
        self.new_btn.clicked.connect(lambda: self.new_chat())
        top.addWidget(self.new_btn)
        self.more_btn = QToolButton()
        self.more_btn.setObjectName("flo_flat")
        self.more_btn.setText("⋯")
        self.more_btn.setToolTip("More")
        self.more_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.more_btn)
        self.action_new_chat = menu.addAction("New Chat", self.new_chat)
        menu.addAction("Columns…", self.edit_privacy)
        menu.addAction("Connections…", self.settings_requested.emit)
        menu.addSeparator()
        self.action_confirm = menu.addAction("Confirm Every Send")
        self.action_confirm.setCheckable(True)
        self.action_confirm.setChecked(
            self.settings.value("flo/confirm_sends", False, type=bool))
        self.action_confirm.toggled.connect(
            lambda on: self.settings.setValue("flo/confirm_sends", bool(on)))
        steps = menu.addMenu("Steps per Reply")
        steps.setToolTipsVisible(True)
        group = QActionGroup(steps)
        chosen = self.max_steps()
        for count in STEP_CHOICES:
            action = steps.addAction(str(count))
            action.setCheckable(True)
            action.setChecked(count == chosen)
            action.setToolTip("How many requests one reply may make before it "
                              "pauses to let you check — Continue carries on")
            action.triggered.connect(
                lambda _=False, n=count: self.settings.setValue("flo/max_steps", n))
            group.addAction(action)
        menu.addAction("Open Send Log Folder", self._open_log_folder)
        self.more_btn.setMenu(menu)
        top.addWidget(self.more_btn)
        outer.addLayout(top)

        # -- the privacy card
        self.card = QFrame()
        card = QVBoxLayout(self.card)
        card.setContentsMargins(10, 8, 10, 8)
        card.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.shield = QLabel()
        head.addWidget(self.shield, 0, Qt.AlignTop)
        self.where = _label()
        font = self.where.font()
        font.setBold(True)
        self.where.setFont(font)
        head.addWidget(self.where, 1)
        card.addLayout(head)
        self.sees_line = _label(muted=True)
        card.addWidget(self.sees_line)
        dials = QHBoxLayout()
        dials.setSpacing(6)
        self.sees_btn = _pill("", "How much of your data Flo is told about — "
                              "saved in this flow")
        self.level_menu = QMenu(self.sees_btn)
        self.level_menu.setToolTipsVisible(True)
        self.level_group = QActionGroup(self)
        self.level_actions: dict[int, QAction] = {}
        for index in range(disc.BUILT_MAX + 1):
            action = self.level_menu.addAction(LEVEL_NAMES[index])
            action.setCheckable(True)
            action.setToolTip(LEVEL_TIPS[index])
            action.triggered.connect(lambda _=False, i=index: self.choose_level(i))
            self.level_group.addAction(action)
            self.level_actions[index] = action
        self.sees_btn.setMenu(self.level_menu)
        dials.addWidget(self.sees_btn)
        self.can_btn = _pill("", "Whether the AI may change the flow")
        self.autonomy_menu = QMenu(self.can_btn)
        self.autonomy_menu.setToolTipsVisible(True)
        group = QActionGroup(self)
        self.autonomy_actions: dict[str, QAction] = {}
        chosen = self.settings.value("flo/autonomy", ACT, type=str)
        for key, name, tip in AUTONOMY:
            action = self.autonomy_menu.addAction(name)
            action.setCheckable(True)
            action.setToolTip(tip)
            action.setChecked(key == chosen)
            action.triggered.connect(lambda _=False, k=key: self.choose_autonomy(k))
            group.addAction(action)
            self.autonomy_actions[key] = action
        if not any(a.isChecked() for a in self.autonomy_actions.values()):
            self.autonomy_actions[ACT].setChecked(True)
        self.autonomy_menu.addSeparator()
        self.action_apply_code = self.autonomy_menu.addAction(
            "Apply Code It Writes")
        self.action_apply_code.setCheckable(True)
        self.action_apply_code.setToolTip(
            "Under Act, code Flo writes for a node is applied at once, as part "
            "of the reply's undo step. Off: it waits in the code editor until "
            "you have read it and pressed Apply — the safer choice when Flo "
            "can see your data, since text in a cell reaches the AI too")
        self.action_apply_code.setChecked(
            self.settings.value("flo/apply_code", True, type=bool))
        self.action_apply_code.toggled.connect(
            lambda on: self.settings.setValue("flo/apply_code", bool(on)))
        self.can_btn.setMenu(self.autonomy_menu)
        dials.addWidget(self.can_btn)
        dials.addStretch(1)
        self.privacy_btn = _pill("Columns…", "Hide a column from Flo, or let "
                                 "it see a column's values")
        self.privacy_btn.setPopupMode(QToolButton.DelayedPopup)
        self.privacy_btn.clicked.connect(self.edit_privacy)
        dials.addWidget(self.privacy_btn)
        card.addLayout(dials)
        outer.addWidget(self.card)

        # -- the thread
        self.scroll = QScrollArea()
        self.scroll.setObjectName("flo_scroll")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.thread = QWidget()
        self.thread_layout = QVBoxLayout(self.thread)
        self.thread_layout.setContentsMargins(2, 4, 6, 4)
        self.thread_layout.setSpacing(14)
        self.thread_layout.addStretch(1)
        self.scroll.setWidget(self.thread)
        outer.addWidget(self.scroll, 1)

        self.progress = _label(muted=True)
        self.progress.hide()
        outer.addWidget(self.progress)
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._show_progress)

        # -- what "this" means: set from a node's or frame's Ask Flo menu
        self.about_row = QFrame()
        self.about_row.setObjectName("flo_about")
        about = QHBoxLayout(self.about_row)
        about.setContentsMargins(10, 3, 4, 3)
        self.about_label = _label()
        about.addWidget(self.about_label, 1)
        clear = QToolButton()
        clear.setObjectName("flo_flat")
        clear.setText("×")
        clear.setToolTip("Don't send this with the message")
        clear.clicked.connect(self.clear_about)
        about.addWidget(clear)
        self.about_row.hide()
        outer.addWidget(self.about_row)

        # -- the input
        box = QFrame()
        box.setObjectName("flo_input")
        entry = QHBoxLayout(box)
        entry.setContentsMargins(10, 6, 6, 6)
        entry.setSpacing(6)
        self.input = _Input()
        self.input.setPlaceholderText("Ask Flo to build or change something…")
        self.input.setToolTip("Enter sends · Shift+Enter starts a new line")
        self.input.setFixedHeight(54)
        self.input.submitted.connect(self.send)
        entry.addWidget(self.input, 1)
        self.send_btn = QToolButton()
        self.send_btn.setObjectName("flo_send")
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.clicked.connect(self._on_send_clicked)
        entry.addWidget(self.send_btn, 0, Qt.AlignBottom)
        outer.addWidget(box)
        self._set_send_face(False)

    # -- the dials ------------------------------------------------------------------

    def reload_profiles(self) -> None:
        """Re-read the connections (after AI Assistant Settings closes)."""
        from ..ai_settings_dialog import load_profiles
        self.profiles = load_profiles()
        active = self.profiles.active()
        self.connection_menu.clear()
        group = QActionGroup(self.connection_menu)
        for profile in self.profiles.profiles:
            action = self.connection_menu.addAction(
                f"{profile.name}  —  {'this PC' if profile.is_local() else _host(profile)}")
            action.setCheckable(True)
            action.setChecked(profile.id == active.id)
            action.setData(profile.id)
            action.triggered.connect(
                lambda _=False, pid=profile.id: self.choose_profile(pid))
            group.addAction(action)
        self.connection_menu.addSeparator()
        self.connection_menu.addAction("Manage Connections…",
                                       self.settings_requested.emit)
        if self._chat_profile is not None and self._has_history():
            if self._chat_profile.get("id") != active.id:
                self.new_chat(note=self._switched_note(active))
            elif self._chat_profile != active.to_dict():
                # same connection, but its address or ceiling may have moved
                self.new_chat(note="The connection's settings changed — "
                              "started a fresh chat.")
        elif self._chat_profile is not None and \
                self._chat_profile != active.to_dict():
            self._reset_chat()   # nothing said yet: just pick the new one up
        self.refresh_header()

    def profile(self):
        return self.profiles.active()

    def _privacy(self) -> disc.Privacy:
        return disc.Privacy.from_dict(self.graph.ai_privacy)

    def level(self) -> int:
        """What Flo can see: the flow's own setting (Column names unless
        it says otherwise)."""
        return self._privacy().effective

    def autonomy(self) -> str:
        for key, action in self.autonomy_actions.items():
            if action.isChecked():
                return key
        return ACT

    def _on_undo_index(self, _index: int) -> None:
        # a QWidget deletes its children before the panel's own slot is
        # disconnected, so a stack change while the window closes can land
        # here with the menus already gone
        from shiboken6 import isValid
        parts = (self, self.level_menu, self.autonomy_menu, self.card,
                 self.sees_btn, *self.level_actions.values(),
                 *self.autonomy_actions.values())
        if not all(isValid(part) for part in parts):
            return
        try:
            self.refresh_header()
        except RuntimeError:   # torn down between the check and the call
            pass

    def refresh_header(self) -> None:
        if self.profiles is None:
            return
        profile = self.profile()
        local = profile.is_local()
        tint = LOCAL_TINT if local else ONLINE_TINT
        self.connection_btn.setIcon(shield_icon(tint, 12))
        self.connection_btn.setText(f"{profile.name}  ▾")
        self.connection_btn.setToolTip(profile.where_label())
        self.card.setObjectName("flo_card_local" if local else "flo_card_online")
        self.card.style().unpolish(self.card)
        self.card.style().polish(self.card)
        self.shield.setPixmap(shield_icon(tint, 16).pixmap(QSize(16, 16)))
        self.where.setText("Local — nothing leaves this PC" if local
                           else f"Online — sent to {_host(profile)}")

        level = self.level()
        for index, action in self.level_actions.items():
            action.setChecked(index == level)
        self.sees_btn.setText(f"Flo can see: {LEVEL_NAMES[level]}  ▾")
        self.can_btn.setText(f"Can: {dict((k, n) for k, n, _ in AUTONOMY)[self.autonomy()]}  ▾")

        privacy = self._privacy()
        extra = []
        if level >= disc.SCHEMA:
            hidden = privacy.names(disc.HIDDEN)
            shared = privacy.names(disc.VALUES)
            if hidden:
                extra.append(f"{len(hidden)} column{'s' if len(hidden) != 1 else ''} "
                             "hidden.")
            if shared:
                extra.append(f"Values shared: {', '.join(shared[:4])}"
                             + ("…" if len(shared) > 4 else "") + ".")
        self.sees_line.setText(" ".join([LEVEL_SEES[level]] + extra))
        self.sees_line.setToolTip(LEVEL_TIPS[level])

        if self._has_history() and level < self._chat_level:
            self.new_chat(note=(
                f"What the AI may see went down to {LEVEL_NAMES[level]} — "
                "started a fresh chat, so nothing it was shown before is "
                "sent again."))

    def _switched_note(self, profile) -> str:
        where = ("this PC" if profile.is_local() else _host(profile))
        return (f"Switched to {profile.name} — started a fresh chat, so "
                f"nothing from the last one goes to {where}.")

    def choose_profile(self, profile_id: str) -> None:
        if self.profiles is None or profile_id == self.profiles.active_id \
                or self.profiles.get(profile_id) is None:
            return
        self.profiles.active_id = profile_id
        try:
            save_profiles(self.profiles)
        except OSError:
            pass  # still in force for this session
        for action in self.connection_menu.actions():
            if action.isCheckable():
                action.setChecked(action.data() == profile_id)
        if self._has_history():
            self.new_chat(note=self._switched_note(self.profile()))
        else:
            self._reset_chat()
        self.refresh_header()

    def choose_level(self, level: int) -> None:
        """Set what Flo can see — saved in the flow, an undoable edit like
        any other (and not mid-turn: it would land in the AI's undo step)."""
        if self._busy or int(level) == self.level():
            self.refresh_header()
            return
        from ..commands import SetAiPrivacyCommand
        privacy = self._privacy()
        privacy.level = int(level)
        self.undo_stack.push(SetAiPrivacyCommand(self.graph, privacy.to_dict()))
        self.refresh_header()

    def choose_autonomy(self, key: str) -> None:
        self.autonomy_actions[key].setChecked(True)
        self.settings.setValue("flo/autonomy", key)
        self.refresh_header()

    def edit_privacy(self) -> None:
        if self._busy:
            return    # it would land inside the AI's undo step
        from ..commands import SetAiPrivacyCommand
        from .privacy_dialog import ColumnsDialog
        dialog = ColumnsDialog(self.graph, self.cache, self)
        if dialog.exec() != QDialog.Accepted:
            return
        privacy = dialog.privacy()
        if privacy != self.graph.ai_privacy:
            self.undo_stack.push(SetAiPrivacyCommand(self.graph, privacy))
        self.refresh_header()

    def _open_log_folder(self) -> None:
        from PySide6.QtCore import QUrl
        folder = log_dir()
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # -- the thread ---------------------------------------------------------------

    def _has_history(self) -> bool:
        return self.chat is not None and any(
            m["role"] == "user" for m in self.chat.messages)

    def _add(self, widget: QWidget) -> QWidget:
        self.thread_layout.insertWidget(self.thread_layout.count() - 1, widget)
        QTimer.singleShot(0, self._scroll_to_end)
        return widget

    def _fit_bubble(self, bubble: QFrame) -> None:
        """A word-wrapped label in a right-aligned row settles on its
        narrowest width, which made every message a thin column. Size the
        bubble to its longest line instead, capped at 85% of the chat."""
        from shiboken6 import isValid
        if not isValid(bubble):
            return
        room = max(180, int(self.scroll.viewport().width() * 0.85))
        widest = 0
        for label in bubble.findChildren(QLabel):
            metrics = label.fontMetrics()
            for line in (label.text() or " ").splitlines() or [" "]:
                widest = max(widest, metrics.horizontalAdvance(line))
        margins = bubble.layout().contentsMargins()
        bubble.setFixedWidth(min(room, widest + margins.left()
                                 + margins.right() + 6))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        for bubble in self._user_bubbles:
            self._fit_bubble(bubble)

    def _scroll_to_end(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _block(self, *widgets: QWidget, name: str = "",
               margins: tuple = (0, 0, 0, 0)) -> QFrame:
        frame = QFrame()
        if name:
            frame.setObjectName(name)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(*margins)
        layout.setSpacing(6)
        for widget in widgets:
            if isinstance(widget, QLabel):
                widget.linkActivated.connect(self._on_link)
            layout.addWidget(widget)
        return frame

    def _hide_welcome(self) -> None:
        if self._welcome is not None:
            self._welcome.hide()
            self._welcome.deleteLater()
            self._welcome = None

    def _clear_thread(self) -> None:
        self._user_bubbles = []
        while self.thread_layout.count() > 1:
            item = self.thread_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._welcome = None
        title = _label("What should we build?", name="flo_title")
        sub = _label("Describe a change and Flo will add and wire the nodes. "
                     "Nothing is sent until you press Enter, and every reply "
                     "says exactly what left.", muted=True)
        chips = []
        for text in SUGGESTIONS:
            chip = QPushButton(text)
            chip.setObjectName("flo_chip")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _=False, t=text: self._use_suggestion(t))
            chips.append(chip)
        self._welcome = self._add(self._block(title, sub, *chips,
                                              margins=(4, 12, 4, 4)))

    def _use_suggestion(self, text: str) -> None:
        self.input.setPlainText(text)
        self.input.setFocus()
        cursor = self.input.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.input.setTextCursor(cursor)

    def notice(self, text: str) -> None:
        label = _label(text, muted=True)
        label.setAlignment(Qt.AlignCenter)
        self._add(self._block(label, margins=(16, 0, 16, 0)))

    def _reset_chat(self) -> None:
        """Drop the conversation; a worker still out is cut loose."""
        if self.bridge is not None:
            self.bridge.close()
            self.bridge.deleteLater()
        if self.toolbox is not None:
            self.toolbox.end_turn()   # a stopped turn's undo step stays whole
        self.chat = self.toolbox = self.bridge = None
        self._drop_live()
        self._chat_profile = None
        self._chat_level = -1
        self._turns = []
        self.send_log.reset()
        self._set_busy(False)

    def new_chat(self, note: str = "") -> None:
        self._reset_chat()
        self._clear_thread()
        if note:
            self.notice(note)

    def graph_replaced(self) -> None:
        """New or Open: the chat was about the flow that just went."""
        self.new_chat()
        self.refresh_header()

    # -- sending -----------------------------------------------------------------

    def _on_send_clicked(self) -> None:
        if self._busy:
            self.stop()
        else:
            self.send()

    def stop(self) -> None:
        if self._busy:
            self._cancel = True
            self._doing = "Stopping"
            self._show_progress()

    def _ensure_chat(self) -> bool:
        if self.chat is not None:
            return True
        from ..ai_settings_dialog import key_for
        profile = self.profile()
        try:
            connection = profile.connection(key_for(profile))
        except wire.LLMError as exc:
            self._error(str(exc))
            return False
        level = self.level()
        self.toolbox = Toolbox(self.graph, self.registry, self.undo_stack,
                               disclosure=disc.Disclosure(level, self._privacy()),
                               autonomy=self.autonomy(), cache=self.cache,
                               runner=(self._run_nodes if self.engine is not None
                                       else None),
                               suggest_code=self.suggest_code,
                               apply_code=self.action_apply_code.isChecked())
        self.bridge = TurnBridge(self)
        self.bridge.event.connect(self._on_event)
        self.bridge.finished.connect(self._on_finished)
        self.bridge.failed.connect(self._on_failed)
        self.chat = Conversation(connection, self.toolbox,
                                 tool_mode=profile.tool_mode or "auto",
                                 on_ui=self.bridge.on_ui,
                                 before_send=self._before_send,
                                 stream=True)
        self._chat_profile = profile.to_dict()
        return True

    def _run_nodes(self, node_ids: list, cancelled) -> str:
        """run_nodes, on the worker: start the run on the GUI thread, wait
        here for the engine to finish, cancel it if Stop is pressed."""
        bridge, engine = self.bridge, self.engine
        if bridge is None or engine is None:
            return "not available"
        finished = threading.Event()

        def on_finished(*_args) -> None:
            finished.set()

        def start() -> None:
            engine.run_finished.connect(on_finished)
            engine.run_targets(list(node_ids))
            if not engine.active:          # all up to date: nothing to run
                finished.set()

        def stop_listening() -> None:
            try:
                engine.run_finished.disconnect(on_finished)
            except (RuntimeError, TypeError):
                pass

        bridge.on_ui(start)
        outcome, deadline = "done", time.monotonic() + RUN_TIMEOUT
        try:
            while not finished.wait(0.25):
                if cancelled():
                    bridge.on_ui(engine.cancel)
                    outcome = "cancelled — the user pressed Stop"
                    break
                if time.monotonic() > deadline:
                    outcome = (f"still running after {int(RUN_TIMEOUT)} s — "
                               "not waited for")
                    break
        finally:
            bridge.on_ui(stop_listening)
        return outcome

    def _agreed_to(self, profile, level: int) -> bool:
        """An online server: has sending at this level been agreed to?"""
        if profile.is_local() or (profile.id, level) in self._agreed:
            return True
        stored = self.settings.value(f"flo/agreed/{profile.id}", -1, type=int)
        return stored >= level

    def _ask_consent(self, profile, level: int) -> tuple[bool, bool]:
        """(send?, remember?) — the dialog, kept apart so tests can answer."""
        from .consent import ConsentDialog
        dialog = ConsentDialog(_host(profile), profile.name, level,
                               self._privacy(), self)
        ok = dialog.exec() == QDialog.Accepted
        return ok, dialog.remember.isChecked()

    def max_steps(self) -> int:
        return self.settings.value("flo/max_steps", DEFAULT_MAX_STEPS, type=int)

    def _consent(self, profile, level: int) -> bool:
        if self._agreed_to(profile, level):
            return True
        ok, remember = self._ask_consent(profile, level)
        if not ok:
            return False
        self._agreed.add((profile.id, level))
        if remember:
            self.settings.setValue(f"flo/agreed/{profile.id}", level)
        return True

    def continue_turn(self) -> bool:
        """Carry on a reply the step limit paused — no new message."""
        if self._busy or self.chat is None:
            return False
        level, autonomy, profile = self.level(), self.autonomy(), self.profile()
        if not self._consent(profile, level):
            return False
        self.toolbox.set_view(disc.Disclosure(level, self._privacy()), autonomy)
        self.toolbox.apply_code = self.action_apply_code.isChecked()
        self._chat_level = max(self._chat_level, level)
        self._launch(None, None, profile, level, autonomy)
        return True

    def send(self, text: Optional[str] = None) -> bool:
        if self._busy:
            return False
        text = (self.input.toPlainText() if text is None else text).strip()
        if not text:
            return False
        level, autonomy, profile = self.level(), self.autonomy(), self.profile()
        if not self._consent(profile, level):
            return False
        if not self._ensure_chat():
            return False
        about_title = self._about_title if self._about else ""
        context = self._about_context()
        screen_title, screen = self._screen_context()
        context = screen + context
        self.clear_about()
        self.input.clear()
        self._hide_welcome()
        self.toolbox.set_view(disc.Disclosure(level, self._privacy()), autonomy)
        self.toolbox.apply_code = self.action_apply_code.isChecked()
        self._chat_level = max(self._chat_level, level)
        parts = [_label(text)]
        if about_title:
            parts.append(_label(f"About: {about_title}", muted=True))
        elif screen_title:
            parts.append(_label(f"Looking at: {screen_title}", muted=True))
        bubble = self._block(*parts, name="flo_user", margins=(12, 8, 12, 8))
        self._user_bubbles.append(bubble)
        self._fit_bubble(bubble)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(24, 0, 0, 0)
        line.addStretch(1)
        line.addWidget(bubble)
        self._add(row)
        self._launch(context + text, bubble, profile, level, autonomy)
        return True

    def _launch(self, message: Optional[str], bubble, profile, level: int,
                autonomy: str) -> None:
        """Start a turn on the worker: `message`, or None to carry on."""
        self.chat.max_steps = self.max_steps()
        self._turn = {
            "bubble": bubble, "text": message or "",
            "start": len(self.chat.outbox),
            "before": (self.chat.outbox[-1]["messages"]
                       if self.chat.outbox else []),
            "to": "this PC" if profile.is_local() else _host(profile),
            "local": profile.is_local(),
            "meta": {"connection": profile.name,
                     "to": profile.where_label(),
                     "model": self.chat.connection.model,
                     "sees": disc.LEVEL_KEYS[level], "can": autonomy},
            "confirm": self.action_confirm.isChecked(),
        }
        self._cancel = False
        self._doing = "Thinking"
        self._set_busy(True)
        chat, bridge = self.chat, self.bridge
        bridge.start(lambda: chat.send(message, cancelled=lambda: self._cancel,
                                       on_event=bridge.event.emit))

    def _before_send(self, entry: dict) -> bool:
        """On the worker thread, just before a request goes."""
        turn, bridge = self._turn, self.bridge
        if turn.get("confirm") and bridge is not None:
            if not bridge.on_ui(lambda: self._confirm(entry, turn)):
                return False
        self.send_log.write(entry, turn.get("meta", {}))
        return True

    def _confirm(self, entry: dict, turn: dict) -> bool:
        before = (self.chat.outbox[-1]["messages"] if self.chat and
                  self.chat.outbox else [])
        text = format_requests([entry], turn["to"], before=before)
        dialog = SentDialog(
            "Send This to the AI?",
            f"This is about to go to {turn['to']}. Don't Send stops the "
            "reply here; nothing below has left yet.", text, self,
            confirm=True)
        return dialog.exec() == QDialog.Accepted

    def _set_send_face(self, busy: bool) -> None:
        self.send_btn.setText("■" if busy else "↑")
        self.send_btn.setToolTip("Stop" if busy else "Send  (Enter)")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._set_send_face(busy)
        for widget in (self.connection_btn, self.sees_btn, self.can_btn,
                       self.privacy_btn):
            # a dial moved mid-turn would apply halfway through it, and a
            # privacy edit would land inside the AI's undo step
            widget.setEnabled(not busy)
        self.progress.setVisible(busy)
        if busy:
            self._started = time.monotonic()
            self._show_progress()
            self._tick.start()
        else:
            self._tick.stop()

    def _show_progress(self) -> None:
        seconds = int(time.monotonic() - self._started)
        self.progress.setText(f"{self._doing}…  {seconds} s")

    def _on_event(self, event: Event) -> None:
        if self._cancel:
            return
        if event.kind == "thinking":
            self._doing = "Thinking"
            self._live_raw = ""          # a new step writes afresh
            self._paint_live()
        elif event.kind == "text":
            self._doing = "Writing"
            self._live_raw += event.detail
            if not self._live_timer.isActive():
                self._live_timer.start()
        elif event.kind == "tool":
            self._doing = TOOL_WORDS.get(event.name, event.name)
        self._show_progress()

    def _paint_live(self) -> None:
        """Show the reply so far — at most every 50 ms, however fast it
        streams, since a Markdown relayout per token would stall the
        window on a long answer."""
        text = visible_text(self._live_raw)
        if not text:
            if self._live is not None:
                self._live.hide()
            return
        if self._live is None:
            self._live = _label(markdown=True)
            self._live.linkActivated.connect(self._on_link)
            self._add(self._live)
        self._live.setText(text)
        self._live.show()
        QTimer.singleShot(0, self._scroll_to_end)

    def _drop_live(self) -> None:
        self._live_timer.stop()
        self._live_raw = ""
        if self._live is not None:
            self._live.hide()
            self._live.deleteLater()
            self._live = None

    def _on_failed(self, message: str) -> None:
        self._drop_live()
        if self.toolbox is not None:
            self.toolbox.end_turn()
        self._set_busy(False)
        self._error(f"Something went wrong inside flograph: {message}")

    def _error(self, text: str) -> None:
        self._add(self._block(_label(text), _label(
            '<a href="settings:">Check the connection…</a>', rich=True),
            name="flo_error", margins=(12, 8, 12, 8)))

    def _receipt_label(self, receipt: receipts.Receipt) -> QLabel:
        details = "<br>".join(_escape(line) for line in receipt.details())
        label = _label(f"{_escape(receipt.summary())}"
                       + (' <a href="receipt:">details</a>'
                          if receipt.sent_anything else ""),
                       rich=True, muted=True)
        label.setProperty("details", details)
        label.setProperty("summary", receipt.summary())
        icon = QLabel()
        icon.setPixmap(shield_icon(LOCAL_TINT if receipt.local else ONLINE_TINT,
                                   12).pixmap(QSize(12, 12)))
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        line.addWidget(icon, 0, Qt.AlignTop)
        line.addWidget(label, 1)
        label.linkActivated.connect(lambda _href, lbl=label: self._toggle_details(lbl))
        label._row = row
        return label

    def _toggle_details(self, label: QLabel) -> None:
        open_now = not label.property("open")
        label.setProperty("open", open_now)
        summary = _escape(label.property("summary"))
        if open_now:
            label.setText(_styled(f'{summary} <a href="receipt:">hide</a><br>'
                                  f'{label.property("details")}'))
        else:
            label.setText(_styled(f'{summary} <a href="receipt:">details</a>'))

    def _on_finished(self, result: Optional[TurnResult]) -> None:
        self._drop_live()
        self._set_busy(False)
        if result is None or self.chat is None:
            return
        turn = self._turn
        if turn["bubble"] is not None and result.sent_text \
                and result.sent_text != turn["text"]:
            note = _label("The AI got this as: " + result.sent_text.split(
                "]\n", 1)[-1], muted=True)
            turn["bubble"].layout().addWidget(note)
            self._fit_bubble(turn["bubble"])
        index = len(self._turns)
        entries = self.chat.outbox[turn["start"]:]
        record = {"start": turn["start"], "end": len(self.chat.outbox),
                  "before": turn["before"], "to": turn["to"],
                  "undo_index": (self.undo_stack.index()
                                 if self.toolbox.pushed else None),
                  # code put in an editor, unapplied: undone by taking it back
                  "code": [(a.node_ids[0], a.code) for a in result.actions
                           if a.tool == "write_node_code" and a.node_ids
                           and a.code],
                  "undone": False}
        record["receipt"] = receipts.build(
            entries, turn["before"], self.toolbox.disclosure,
            destination=turn["to"], local=turn["local"])
        self._turns.append(record)

        parts: list[QWidget] = []
        if result.stopped == "error":
            parts.append(self._block(_label(result.text), name="flo_error",
                                     margins=(12, 8, 12, 8)))
        else:
            parts.append(_label(result.text or "(no answer)", markdown=True))
        if result.actions:
            lines = []
            for action in result.actions:
                mark = ACTION_MARK.get(action.tool, "•")
                line = f"{mark}&nbsp;&nbsp;{_escape(action.summary)}"
                live = [n for n in action.node_ids if n in self.graph.nodes]
                if live and action.tool == "write_node_code":
                    line += (f' &nbsp;<a href="code:{live[-1]}">'
                             f'Review code</a>')
                elif live:
                    line += f' &nbsp;<a href="node:{live[-1]}">show</a>'
                lines.append(line)
            changes = _label("<br>".join(lines), rich=True)
            parts.append(self._block(changes, name="flo_changes",
                                     margins=(10, 6, 10, 6)))
        receipt_label = self._receipt_label(record["receipt"])
        record["receipt_label"] = receipt_label
        parts.append(receipt_label._row)
        links = []
        if result.actions:
            links.append(f'<a href="undo:{index}">Undo these changes</a>')
        if record["end"] - record["start"]:
            links.append(f'<a href="sent:{index}">What was sent</a>')
        if result.stopped == "step limit":
            links.insert(0, f'<a href="continue:{index}">Continue</a>')
        if result.stopped == "error":
            links.append('<a href="settings:">Check the connection…</a>')
        if links:
            footer = _label(" · ".join(links), rich=True, muted=True)
            record["footer"] = footer
            parts.append(footer)
        self._add(self._block(*parts))

    # -- links ---------------------------------------------------------------------

    def _on_link(self, href: str) -> None:
        kind, _, ident = href.partition(":")
        if kind == "node":
            if ident in self.graph.nodes:
                self.navigate_requested.emit("node", ident)
            else:
                self.notice("That node is no longer in the flow.")
        elif kind == "code":
            if ident in self.graph.nodes:
                self.review_code_requested.emit(ident)
            else:
                self.notice("That node is no longer in the flow.")
        elif kind == "undo":
            self._undo_turn(int(ident))
        elif kind == "sent":
            self._show_sent(int(ident))
        elif kind == "settings":
            self.settings_requested.emit()
        elif kind == "continue":
            if int(ident) == len(self._turns) - 1:
                self.continue_turn()
            else:
                self.notice("That reply has been followed by others — ask "
                            "again to carry on from here.")

    def _undo_turn(self, index: int) -> None:
        record = self._turns[index]
        if record["undone"]:
            return
        pushed = record["undo_index"] is not None
        if self._busy or (pushed and self.undo_stack.index() != record["undo_index"]):
            self.notice("Other changes came after that reply, so it can't be "
                        "undone on its own — use Edit ▸ Undo to step back "
                        "through them.")
            return
        if pushed:
            self.undo_stack.undo()
        for node_id, code in record.get("code", ()):
            self.discard_code(node_id, code)
        record["undone"] = True
        footer = record.get("footer")
        if footer is not None:
            footer.setText(re.sub(
                rf'<a [^>]*href="undo:{index}">Undo these changes</a>',
                "Undone (Edit ▸ Redo brings it back)" if pushed else "Undone",
                footer.text()))

    def _show_sent(self, index: int) -> None:
        if self.chat is None:
            return
        record = self._turns[index]
        entries = self.chat.outbox[record["start"]:record["end"]]
        text = format_requests(entries, record["to"], before=record["before"])
        receipt = record.get("receipt")
        intro = (f"Everything this reply sent to {record['to']}, request by "
                 "request. Each request also repeats the conversation before "
                 "it; only what is new is shown.")
        if receipt is not None:
            intro = receipt.summary() + "\n\n" + intro
        SentDialog("What Was Sent", intro, text, self).exec()

    def focus_input(self) -> None:
        self.input.setFocus()

    # -- "this": nodes picked from the canvas --------------------------------------

    def ask_about(self, node_ids: list[str], title: str,
                  prompt: Optional[str] = None) -> None:
        """Point the next message at these nodes (Ask Flo on a node, a
        selection or a frame). With `prompt`, send it straight away."""
        self._about = [n for n in node_ids if n in self.graph.nodes]
        self._about_title = title
        if not self._about:
            self.clear_about()
            return
        self.about_label.setText(f"About: {title}")
        self.about_label.setToolTip("Sent with your next message, so the AI "
                                    "knows which nodes you mean")
        self.about_row.show()
        if prompt and not self._busy:
            self.send(prompt)
        else:
            self.focus_input()

    def clear_about(self) -> None:
        self._about = []
        self._about_title = ""
        self.about_row.hide()

    def _about_context(self) -> str:
        """The line that tells the model which nodes "this" is."""
        ids = [n for n in self._about if n in self.graph.nodes][:30]
        if not ids or self.toolbox is None:
            return ""
        scrub = self.toolbox.disclosure.scrub
        named = "; ".join(
            f'{self.toolbox.handle(n)} "{scrub(self.graph.nodes[n].label)}" '
            f"({self.graph.nodes[n].type_id})" for n in ids)
        return (f"[I'm pointing at {self._about_title}: {named}. "
                "Read them with get_node first.]\n")


    def _screen_context(self) -> tuple:
        """(the page's title for the bubble, the line telling the model
        which page the user is looking at) — empty on the canvas."""
        try:
            page = self.graph.pages.get(self.on_screen() or "")
        except Exception:
            page = None
        if page is None or page.kind not in ("dashboard", "report") \
                or self.toolbox is None:
            return "", ""
        handle = self.toolbox.page_handle(page.id)
        title = self.toolbox.disclosure.scrub(page.title)
        if page.kind == "report":
            view = "Web preview" if page.preview_mode == "web" else "Pages preview"
            return page.title, (
                f'[On screen: report page {handle} "{title}", {view}. '
                '"This page", "the report" and "its look" mean this page: its '
                "text is its markdown (write_report), its look is its CSS "
                "(get_page with css, set_report_style, write_report_css) — "
                "not the nodes on the canvas.]\n")
        return page.title, (
            f'[On screen: dashboard page {handle} "{title}". "This page" and '
            '"the dashboard" mean this page and its tiles.]\n')


def _host(profile) -> str:
    from ...llm.profiles import url_host
    return url_host(profile.base_url) or "the server"
