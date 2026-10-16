"""'What was sent' — the requests behind one reply, as readable text.

The same view asks before a request goes when *Confirm every send* is on.
It shows the conversation's own messages, which is everything in a request
besides the format's wrapping (model name, token limit, the tool list's
JSON schema): the converters in `llm/toolcall.py` reshape, they never add.
"""
from __future__ import annotations

import json

from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
)

_ROLE = {"system": "INSTRUCTIONS (system prompt)", "user": "YOU",
         "assistant": "AI", "tool": "TOOL RESULT"}


def format_messages(messages: list) -> str:
    parts = []
    for message in messages:
        role = message.get("role", "")
        head = _ROLE.get(role, role.upper())
        if role == "tool":
            head += f" — {message.get('name', '')}"
        body = str(message.get("content") or "")
        if role == "tool":
            try:
                body = json.dumps(json.loads(body), indent=2, ensure_ascii=False)
            except (TypeError, ValueError):
                pass
        calls = message.get("tool_calls") or []
        for call in calls:
            body += ("\n" if body else "") + (
                f"→ {call.get('name')}("
                f"{json.dumps(call.get('arguments') or {}, ensure_ascii=False)})")
        parts.append(f"── {head} ──\n{body}".rstrip())
    return "\n\n".join(parts)


def _tokens(entry: dict) -> str:
    """The server's count for one request, once its reply is back."""
    if "usage" not in entry:
        return ""        # not answered yet (Confirm every send), or failed
    usage = entry.get("usage")
    if not isinstance(usage, dict):
        return "Tokens: not reported by the server\n"
    return (f"Tokens: {int(usage.get('input') or 0):,} in, "
            f"{int(usage.get('output') or 0):,} out\n")


def format_requests(entries: list, destination: str, *, before: list = ()) -> str:
    """The requests of one turn, each showing only what it added.

    `before` is the message list of the request just ahead of the first
    entry (empty for a conversation's first request), so nothing already
    shown in an earlier reply's view is repeated."""
    out = []
    previous = list(before)
    for index, entry in enumerate(entries, 1):
        messages = entry.get("messages") or []
        if messages and messages[0].get("role") == "system":
            new = list(messages[max(len(previous), 1):])
            if not previous or previous[0].get("content") != messages[0].get("content"):
                new.insert(0, messages[0])
        else:
            new = list(messages[len(previous):])
        tools = ", ".join(entry.get("tools") or []) or "none"
        out.append(f"REQUEST {index} → {destination}\n"
                   f"Tools offered: {tools}\n" + _tokens(entry) + "\n"
                   + format_messages(new))
        previous = messages
    return "\n\n\n".join(out) if out else "Nothing was sent."


class SentDialog(QDialog):
    def __init__(self, title: str, intro: str, text: str, parent=None, *,
                 confirm: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        label = QLabel(intro)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.text = QPlainTextEdit(text)
        self.text.setReadOnly(True)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        layout.addWidget(self.text, 1)
        buttons = QDialogButtonBox()
        copy = QPushButton("Copy")
        copy.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.text.toPlainText()))
        buttons.addButton(copy, QDialogButtonBox.ActionRole)
        if confirm:
            send = buttons.addButton("Send", QDialogButtonBox.AcceptRole)
            send.setDefault(True)
            buttons.addButton("Don't Send", QDialogButtonBox.RejectRole)
        else:
            buttons.addButton(QDialogButtonBox.Close)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
