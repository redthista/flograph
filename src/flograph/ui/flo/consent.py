"""Before the first send to an online server: what it will and won't get.

Asked once per connection and level — again if *Sees* is raised above
what was agreed — unless the user ticks "don't ask again". A local server
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
    hidden = sum(1 for rule in privacy.columns.values() if rule.sensitive)
    aliased = sum(1 for rule in privacy.columns.values() if rule.alias)
    out = ["What you type in this chat",
           "The flow: which nodes there are, their names, how they are wired, "
           "and their settings" + (" — text you typed into settings is hidden"
                                   if privacy.hide_text else
                                   " — including text you typed into them, "
                                   "such as a filter's values")]
    if level >= disc.SCHEMA:
        extra = []
        if aliased:
            extra.append(f"{aliased} under an alias")
        if hidden:
            extra.append(f"{hidden} marked sensitive")
        out.append("Column names and types" + (f" ({', '.join(extra)})"
                                               if extra else ""))
    if level >= disc.PROFILE:
        out.append("Per column: how much is empty and how many distinct values "
                   "— and, for numbers and dates, the smallest and largest "
                   "value" + (" (not for sensitive columns)" if hidden else ""))
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
