"""Before the first send to an online server: what it will and won't get.

Asked once per connection and level — again if "Flo can see" is raised
above what was agreed — unless the user ticks "don't ask again". A local server
never asks: nothing leaves the PC. The lists are built from the same level
and privacy rules the disclosure module enforces, so they describe what
will happen rather than a policy.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout,
)

from ...core import ai_disclosure as disc


def will_see(level: int, privacy: disc.Privacy) -> list[str]:
    out = ["What you type in this chat",
           "The flow's layout: which nodes, how they are wired, and their "
           "settings" + (" — but no text typed into them"
                         if level < disc.SCHEMA else
                         ", as typed (a filter's values too)")]
    if level >= disc.SCHEMA:
        hidden = privacy.names(disc.HIDDEN)
        out.append("Column names and types" + (
            f" — except {len(hidden)} hidden column"
            f"{'s' if len(hidden) != 1 else ''}" if hidden else ""))
        shared = privacy.names(disc.VALUES)
        if shared:
            out.append("The values of the columns you chose to share: "
                       + ", ".join(shared))
    if level >= disc.PROFILE:
        out.append("Per column: how much is empty, how many different values, "
                   "and the lowest and highest value")
    return out


def never_sees(level: int) -> list[str]:
    out = ["Any row of your data", "Passwords",
           "Full file paths — only file names"]
    if level < disc.SCHEMA:
        out.insert(1, "Column names — they go as <column>, even in what you type")
    return out


def _bullets(items: list[str]) -> str:
    return "".join(f"<li>{item.replace('<column>', '&lt;column&gt;')}</li>"
                   for item in items)


class ConsentDialog(QDialog):
    def __init__(self, host: str, connection: str, level: int,
                 privacy: disc.Privacy, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Send to {host}?")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        text = QLabel(
            f"<p>The Flo Assistant is about to send to <b>{host}</b> "
            f"({connection}) — a server outside this PC.</p>"
            f"<p><b>It will see</b></p><ul>{_bullets(will_see(level, privacy))}</ul>"
            f"<p><b>It will never see</b></p><ul>{_bullets(never_sees(level))}</ul>"
            "<p>Every request is shown under its reply (<i>What was sent</i>) "
            "and logged on this PC.</p>")
        text.setTextFormat(Qt.RichText)
        text.setWordWrap(True)
        layout.addWidget(text)
        self.remember = QCheckBox("Don't ask again for this connection")
        layout.addWidget(self.remember)
        buttons = QDialogButtonBox()
        send = buttons.addButton("Send", QDialogButtonBox.AcceptRole)
        send.setDefault(True)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
