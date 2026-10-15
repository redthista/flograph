"""The Flo Assistant dock: a chat that can read and change the flow.

The header carries the two dials and where the words go:

- the **connection** (a profile from AI Assistant Settings) and a badge
  saying *Local — nothing leaves this PC* or *Online — <host>*;
- **Sees** — Structure / Schema / Profile, never above the lowest of the
  connection's ceiling and the flow's own cap (Columns… sets that, with the
  per-column Sensitive / Alias rules);
- **Can** — Advise (look and explain) or Act (change the flow; each reply
  is one undo step).

What the model is shown is decided by `core/ai_disclosure.py` and by which
tools exist (`flo/tools.py`) — this file only picks the dials and shows the
result. Two rules are enforced here because only the dock sees them happen:

- a **different connection** starts a fresh chat, so nothing the last
  server was shown is replayed to a new one;
- **lowering** what it sees starts a fresh chat too: the history holds what
  the higher level let through, and every request resends the history.

Every request is kept in the conversation's outbox (each reply has a *What
was sent* link), written to the send log, and — with *Confirm Every Send*
on — shown for approval before it goes.
"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QDesktopServices, QKeyEvent
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QMenu, QPlainTextEdit,
    QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from ...core import ai_disclosure as disc
from ...flo.agent import Conversation, Event, TurnResult
from ...flo.sendlog import SendLog, log_dir
from ...flo.tools import ACT, ADVISE, Toolbox
from ...llm import wire
from ...llm.profiles import LEVELS, ProfileSet, save as save_profiles
from .bridge import TurnBridge
from .sent_view import SentDialog, format_requests

LEVEL_NAMES = {0: "Structure", 1: "Schema", 2: "Profile"}
LEVEL_TIPS = {
    0: "The flow only — node types, wires and settings. No column names: "
       "they are replaced with <column> everywhere, even in what you type.",
    1: "Column names and types, as well as the flow. No values.",
    2: "Column names and types, plus per column its empty share, distinct "
       "count, range and what it looks like (emails, IDs…). Never rows.",
}
AUTONOMY = ((ADVISE, "Advise", "Look at the flow and explain or suggest — "
             "it cannot change anything"),
            (ACT, "Act", "Change the flow: add, wire, set and delete nodes. "
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
}

_STYLE = """
QFrame#flo_user { background: rgba(124,108,246,0.18); border-radius: 8px; }
QFrame#flo_ai { background: palette(alternate-base); border-radius: 8px; }
QFrame#flo_error { background: rgba(239,68,68,0.16); border-radius: 8px; }
QFrame#flo_notice { border: 1px dashed palette(mid); border-radius: 8px; }
QLabel#flo_muted { color: palette(placeholder-text); }
QLabel#flo_badge_local { background: rgba(74,222,128,0.20);
    border-radius: 9px; padding: 1px 8px; }
QLabel#flo_badge_online { background: rgba(250,204,21,0.22);
    border-radius: 9px; padding: 1px 8px; }
"""


def _label(text: str = "", *, muted: bool = False, rich: bool = False,
           markdown: bool = False) -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    label.setTextFormat(Qt.MarkdownText if markdown else
                        Qt.RichText if rich else Qt.PlainText)
    label.setText(text)
    label.setTextInteractionFlags(Qt.TextBrowserInteraction)
    label.setOpenExternalLinks(False)
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
    if muted:
        label.setObjectName("flo_muted")
    return label


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


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

    def __init__(self, graph, registry, undo_stack, cache=None, *,
                 settings: Optional[QSettings] = None, parent=None) -> None:
        super().__init__(parent)
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
        self._busy = False
        self._cancel = False
        self._turns: list[dict] = []
        self._turn: dict = {}
        self._started = 0.0
        self._doing = ""
        self.setStyleSheet(_STYLE)
        self._build()
        self.reload_profiles()
        # a bound slot, so the connection dies with the panel
        self.undo_stack.indexChanged.connect(self._on_undo_index)
        self._clear_thread()

    # -- layout ---------------------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)

        row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setToolTip("Which AI connection to use — set them "
                                      "up in AI Assistant Settings")
        self.profile_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.profile_combo.setMinimumContentsLength(8)
        self.profile_combo.activated.connect(self._on_profile_chosen)
        row.addWidget(self.profile_combo, 1)
        self.badge = QLabel()
        row.addWidget(self.badge)
        self.menu_btn = QToolButton()
        self.menu_btn.setText("⋯")
        self.menu_btn.setToolTip("More")
        self.menu_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.menu_btn)
        self.action_new_chat = menu.addAction("New Chat", self.new_chat)
        menu.addAction("Connections…", self.settings_requested.emit)
        menu.addSeparator()
        self.action_confirm = menu.addAction("Confirm Every Send")
        self.action_confirm.setCheckable(True)
        self.action_confirm.setChecked(
            self.settings.value("flo/confirm_sends", False, type=bool))
        self.action_confirm.toggled.connect(
            lambda on: self.settings.setValue("flo/confirm_sends", bool(on)))
        menu.addAction("Open Send Log Folder", self._open_log_folder)
        self.menu_btn.setMenu(menu)
        row.addWidget(self.menu_btn)
        outer.addLayout(row)

        dials = QHBoxLayout()
        dials.addWidget(QLabel("Sees"))
        self.level_combo = QComboBox()
        for index in range(disc.BUILT_MAX + 1):
            self.level_combo.addItem(LEVEL_NAMES[index], index)
            self.level_combo.setItemData(index, LEVEL_TIPS[index], Qt.ToolTipRole)
        self.level_combo.activated.connect(self._on_level_chosen)
        dials.addWidget(self.level_combo)
        dials.addSpacing(6)
        dials.addWidget(QLabel("Can"))
        self.autonomy_combo = QComboBox()
        for index, (key, name, tip) in enumerate(AUTONOMY):
            self.autonomy_combo.addItem(name, key)
            self.autonomy_combo.setItemData(index, tip, Qt.ToolTipRole)
        chosen = self.settings.value("flo/autonomy", ACT, type=str)
        self.autonomy_combo.setCurrentIndex(
            max(0, self.autonomy_combo.findData(chosen)))
        self.autonomy_combo.activated.connect(self._on_autonomy_chosen)
        dials.addWidget(self.autonomy_combo)
        dials.addStretch(1)
        self.columns_btn = QPushButton("Columns…")
        self.columns_btn.setToolTip(
            "What this flow lets the AI see: its limit, and which columns "
            "are sensitive or go by another name")
        self.columns_btn.clicked.connect(self.edit_privacy)
        dials.addWidget(self.columns_btn)
        outer.addLayout(dials)

        self.limit_note = _label(muted=True)
        outer.addWidget(self.limit_note)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.thread = QWidget()
        self.thread_layout = QVBoxLayout(self.thread)
        self.thread_layout.setContentsMargins(0, 0, 4, 0)
        self.thread_layout.setSpacing(8)
        self.thread_layout.addStretch(1)
        self.scroll.setWidget(self.thread)
        outer.addWidget(self.scroll, 1)

        self.progress = _label(muted=True)
        self.progress.hide()
        outer.addWidget(self.progress)
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._show_progress)

        entry = QHBoxLayout()
        self.input = _Input()
        self.input.setPlaceholderText(
            "Ask for a change — e.g. add a bar chart of sales by region "
            "from my Excel reader")
        self.input.setFixedHeight(64)
        self.input.submitted.connect(self.send)
        entry.addWidget(self.input, 1)
        self.send_btn = QPushButton("Send")
        self.send_btn.setDefault(True)
        self.send_btn.clicked.connect(self._on_send_clicked)
        entry.addWidget(self.send_btn, 0, Qt.AlignBottom)
        outer.addLayout(entry)

    # -- the dials ------------------------------------------------------------------

    def reload_profiles(self) -> None:
        """Re-read the connections (after AI Assistant Settings closes)."""
        from ..ai_settings_dialog import load_profiles
        self.profiles = load_profiles()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in self.profiles.profiles:
            self.profile_combo.addItem(profile.name, profile.id)
        active = self.profiles.active()
        self.profile_combo.setCurrentIndex(
            max(0, self.profile_combo.findData(active.id)))
        self.profile_combo.blockSignals(False)
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

    def allowed_level(self) -> int:
        """The most the dials may be set to: the connection's ceiling and
        the flow's own cap, whichever is lower."""
        return disc.effective_level(self.profile().effective_ceiling(),
                                    self._privacy().level)

    def level(self) -> int:
        wanted = self.settings.value("flo/level", disc.PROFILE, type=int)
        return disc.effective_level(self.allowed_level(), None, wanted)

    def autonomy(self) -> str:
        return self.autonomy_combo.currentData() or ACT

    def _on_undo_index(self, _index: int) -> None:
        self.refresh_header()

    def refresh_header(self) -> None:
        if self.profiles is None:
            return
        profile = self.profile()
        local = profile.is_local()
        self.badge.setObjectName("flo_badge_local" if local else "flo_badge_online")
        self.badge.setText("Local" if local else "Online")
        self.badge.setToolTip(profile.where_label())
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)

        allowed, level = self.allowed_level(), self.level()
        model = self.level_combo.model()
        for index in range(self.level_combo.count()):
            item = model.item(index)
            item.setEnabled(index <= allowed)
        self.level_combo.setCurrentIndex(level)
        self.level_combo.setToolTip(LEVEL_TIPS[level])

        why = []
        ceiling = profile.effective_ceiling()
        flow_cap = self._privacy().level
        if flow_cap is not None and flow_cap < min(ceiling, disc.BUILT_MAX):
            why.append(f"this flow allows up to {LEVEL_NAMES.get(flow_cap, '?')}")
        if ceiling < disc.BUILT_MAX:
            why.append(f"this connection allows up to "
                       f"{LEVEL_NAMES.get(ceiling, '?')}")
        place = ("Local — nothing leaves this PC." if local
                 else f"Online — what is sent goes to {_host(profile)}.")
        limits = "; ".join(why)
        self.limit_note.setText(place + (f" {limits[:1].upper()}{limits[1:]}."
                                         if why else ""))

        if self._has_history() and level < self._chat_level:
            self.new_chat(note=(
                f"What the AI may see went down to {LEVEL_NAMES[level]} — "
                "started a fresh chat, so nothing it was shown before is "
                "sent again."))

    def _switched_note(self, profile) -> str:
        where = ("this PC" if profile.is_local() else _host(profile))
        return (f"Switched to {profile.name} — started a fresh chat, so "
                f"nothing from the last one goes to {where}.")

    def _on_profile_chosen(self, index: int) -> None:
        profile_id = self.profile_combo.itemData(index)
        if self.profiles is None or profile_id == self.profiles.active_id:
            return
        self.profiles.active_id = profile_id
        try:
            save_profiles(self.profiles)
        except OSError:
            pass  # still in force for this session
        if self._has_history():
            self.new_chat(note=self._switched_note(self.profile()))
        else:
            self._reset_chat()
        self.refresh_header()

    def _on_level_chosen(self, index: int) -> None:
        self.settings.setValue("flo/level", int(self.level_combo.itemData(index)))
        self.refresh_header()

    def _on_autonomy_chosen(self, _index: int) -> None:
        self.settings.setValue("flo/autonomy", self.autonomy())

    def edit_privacy(self) -> None:
        from ..commands import SetAiPrivacyCommand
        from .privacy_dialog import PrivacyDialog
        dialog = PrivacyDialog(self.graph, self.cache, self)
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

    def _scroll_to_end(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _bubble(self, kind: str, *labels: QLabel) -> QFrame:
        frame = QFrame()
        frame.setObjectName(kind)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        for label in labels:
            label.linkActivated.connect(self._on_link)
            layout.addWidget(label)
        return self._add(frame)

    def _clear_thread(self) -> None:
        while self.thread_layout.count() > 1:
            item = self.thread_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._bubble("flo_notice", _label(
            "**Ask for a change to this flow** — for example *“Add a bar "
            "chart of sales by region from my Excel reader.”*\n\n"
            "*Sees* sets how much of your data it is told about, *Can* "
            "whether it may change the flow. Nothing is sent until you "
            "press Send, and *What was sent* under each reply shows "
            "exactly what went.", markdown=True))

    def notice(self, text: str) -> None:
        self._bubble("flo_notice", _label(text, muted=True))

    def _reset_chat(self) -> None:
        """Drop the conversation; a worker still out is cut loose."""
        if self.bridge is not None:
            self.bridge.close()
            self.bridge.deleteLater()
        if self.toolbox is not None:
            self.toolbox.end_turn()   # a stopped turn's undo step stays whole
        self.chat = self.toolbox = self.bridge = None
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
            self._doing = "Stopping once the AI answers"
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
                               autonomy=self.autonomy(), cache=self.cache)
        self.bridge = TurnBridge(self)
        self.bridge.event.connect(self._on_event)
        self.bridge.finished.connect(self._on_finished)
        self.bridge.failed.connect(self._on_failed)
        self.chat = Conversation(connection, self.toolbox,
                                 tool_mode=profile.tool_mode or "auto",
                                 on_ui=self.bridge.on_ui,
                                 before_send=self._before_send)
        self._chat_profile = profile.to_dict()
        return True

    def send(self, text: Optional[str] = None) -> bool:
        if self._busy:
            return False
        text = (self.input.toPlainText() if text is None else text).strip()
        if not text or not self._ensure_chat():
            return False
        self.input.clear()
        level, autonomy, profile = self.level(), self.autonomy(), self.profile()
        self.toolbox.set_view(disc.Disclosure(level, self._privacy()), autonomy)
        self._chat_level = max(self._chat_level, level)
        user = _label(text)
        bubble = self._bubble("flo_user", user)
        self._turn = {
            "bubble": bubble, "text": text, "start": len(self.chat.outbox),
            "before": (self.chat.outbox[-1]["messages"]
                       if self.chat.outbox else []),
            "to": "this PC" if profile.is_local() else _host(profile),
            "meta": {"connection": profile.name,
                     "to": profile.where_label(),
                     "model": self.chat.connection.model,
                     "sees": LEVELS[level][0], "can": autonomy},
            "confirm": self.action_confirm.isChecked(),
        }
        self._cancel = False
        self._doing = "Waiting for the AI"
        self._set_busy(True)
        chat, bridge = self.chat, self.bridge
        bridge.start(lambda: chat.send(text, cancelled=lambda: self._cancel,
                                       on_event=bridge.event.emit))
        return True

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

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.send_btn.setText("Stop" if busy else "Send")
        for widget in (self.profile_combo, self.level_combo,
                       self.autonomy_combo, self.columns_btn):
            # a dial moved mid-turn would apply halfway through it, and a
            # privacy edit would land inside the AI's undo step
            widget.setEnabled(not busy)
        self.action_new_chat.setEnabled(True)
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
            self._doing = "Waiting for the AI"
        elif event.kind == "tool":
            self._doing = TOOL_WORDS.get(event.name, event.name)
        self._show_progress()

    def _on_failed(self, message: str) -> None:
        if self.toolbox is not None:
            self.toolbox.end_turn()
        self._set_busy(False)
        self._error(f"Something went wrong inside flograph: {message}")

    def _error(self, text: str) -> None:
        self._bubble("flo_error", _label(text), _label(
            '<a href="settings:">Check the connection…</a>', rich=True))

    def _on_finished(self, result: Optional[TurnResult]) -> None:
        self._set_busy(False)
        if result is None or self.chat is None:
            return
        turn = self._turn
        if result.sent_text and result.sent_text != turn["text"]:
            note = _label("The AI got this as: " + result.sent_text, muted=True)
            turn["bubble"].layout().addWidget(note)
        index = len(self._turns)
        record = {"start": turn["start"], "end": len(self.chat.outbox),
                  "before": turn["before"], "to": turn["to"],
                  "undo_index": (self.undo_stack.index()
                                 if result.actions else None),
                  "undone": False}
        self._turns.append(record)

        labels = []
        if result.stopped == "error":
            kind = "flo_error"
            labels.append(_label(result.text))
        else:
            kind = "flo_ai"
            labels.append(_label(result.text or "(no answer)", markdown=True))
        if result.actions:
            lines = []
            for action in result.actions:
                line = _escape(action.summary)
                live = [n for n in action.node_ids if n in self.graph.nodes]
                if live:
                    line += f' · <a href="node:{live[-1]}">show</a>'
                lines.append("• " + line)
            labels.append(_label("<br>".join(lines), rich=True))
        links = []
        if result.actions:
            links.append(f'<a href="undo:{index}">Undo these changes</a>')
        sent = record["end"] - record["start"]
        if sent:
            links.append(f'<a href="sent:{index}">What was sent</a> '
                         f'({sent} request{"s" if sent != 1 else ""} to '
                         f'{_escape(turn["to"])})')
        if result.stopped == "error":
            links.append('<a href="settings:">Check the connection…</a>')
        if links:
            footer = _label(" · ".join(links), rich=True, muted=True)
            record["footer"] = footer
            labels.append(footer)
        self._bubble(kind, *labels)

    # -- links ---------------------------------------------------------------------

    def _on_link(self, href: str) -> None:
        kind, _, ident = href.partition(":")
        if kind == "node":
            if ident in self.graph.nodes:
                self.navigate_requested.emit("node", ident)
            else:
                self.notice("That node is no longer in the flow.")
        elif kind == "undo":
            self._undo_turn(int(ident))
        elif kind == "sent":
            self._show_sent(int(ident))
        elif kind == "settings":
            self.settings_requested.emit()

    def _undo_turn(self, index: int) -> None:
        record = self._turns[index]
        if record["undone"]:
            return
        if self._busy or self.undo_stack.index() != record["undo_index"]:
            self.notice("Other changes came after that reply, so it can't be "
                        "undone on its own — use Edit ▸ Undo to step back "
                        "through them.")
            return
        self.undo_stack.undo()
        record["undone"] = True
        footer = record.get("footer")
        if footer is not None:
            footer.setText(footer.text().replace(
                f'<a href="undo:{index}">Undo these changes</a>',
                "Undone (Edit ▸ Redo brings it back)"))

    def _show_sent(self, index: int) -> None:
        if self.chat is None:
            return
        record = self._turns[index]
        entries = self.chat.outbox[record["start"]:record["end"]]
        text = format_requests(entries, record["to"], before=record["before"])
        SentDialog("What Was Sent",
                   f"Everything this reply sent to {record['to']}, request by "
                   "request. Each request also repeats the conversation before "
                   "it; only what is new is shown.", text, self).exec()

    def focus_input(self) -> None:
        self.input.setFocus()


def _host(profile) -> str:
    from ...llm.profiles import url_host
    return url_host(profile.base_url) or "the server"
