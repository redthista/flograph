"""Rebindable keyboard shortcuts.

Every menu/toolbar QAction the main window builds is registered here as it
is created, which gives three things the app had no way to do before: a
list of what the shortcuts *are* (Settings > Keyboard Shortcuts), a place
to change them, and somewhere to remember the change.

An entry's id is a slug of its label ("Save &As…" -> "save_as"), rather
than a hand-maintained table of ids parallel to the actions themselves --
one list that can drift out of step with the other is exactly how a
rebind ends up applied to the wrong command. The cost is that renaming a
command orphans anyone's saved override for it, which falls back to the
default binding rather than failing; labels here are stable enough that
this is the better trade.

Defaults are captured from the action at registration, so "reset" means
"whatever the code shipped with" without that value being written down
twice either.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QKeySequence

_PREFIX = "shortcuts/"


def slug(label: str) -> str:
    """"Save &As…" -> "save_as". Menu accelerators, ellipses and
    punctuation all go, since none of them identify the command."""
    text = label.replace("&", "").replace("…", "").replace("...", "")
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


@dataclass
class ShortcutEntry:
    key: str
    label: str
    group: str
    action: QAction
    default: QKeySequence

    def binding(self) -> QKeySequence:
        return self.action.shortcut()

    def is_default(self) -> bool:
        return self.action.shortcut() == self.default


class ShortcutRegistry(QObject):
    """The app's shortcuts, and any saved rebinds of them."""

    changed = Signal()

    def __init__(self, settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._entries: dict[str, ShortcutEntry] = {}

    # ------------------------------------------------------------ building

    def register(self, action: QAction, group: str) -> QAction:
        """Take ownership of `action`'s shortcut and apply any saved
        rebind. Called as the action is built, so a stored override is in
        force from the first keystroke rather than after a settings visit."""
        key = slug(action.text())
        entry = ShortcutEntry(key=key, label=action.text().replace("&", ""),
                              group=group, action=action,
                              default=QKeySequence(action.shortcut()))
        self._entries[key] = entry
        stored = self._settings.value(f"{_PREFIX}{key}", None)
        if stored is not None:
            action.setShortcut(QKeySequence(stored))
        return action

    # ------------------------------------------------------------ querying

    def entries(self) -> list[ShortcutEntry]:
        """Registration order, which is menu order -- File before Edit
        before Run, the way someone reading the menus would meet them."""
        return list(self._entries.values())

    def groups(self) -> list[str]:
        seen: list[str] = []
        for entry in self._entries.values():
            if entry.group not in seen:
                seen.append(entry.group)
        return seen

    def entry(self, key: str) -> ShortcutEntry | None:
        return self._entries.get(key)

    def owner_of(self, sequence: QKeySequence,
                 ignoring: str = "") -> ShortcutEntry | None:
        """Which command already answers to `sequence`, if any. Two actions
        on one key is not an error Qt reports -- it just quietly stops
        firing either of them -- so a clash has to be caught here."""
        if sequence.isEmpty():
            return None
        for entry in self._entries.values():
            if entry.key != ignoring and entry.binding() == sequence:
                return entry
        return None

    # ------------------------------------------------------------ changing

    def set_binding(self, key: str, sequence: QKeySequence) -> str | None:
        """Rebind `key`, or explain why not. An empty sequence unbinds the
        command, which is allowed -- some are menu-only already.

        Returns None on success, or the label of the command already using
        that key. Refusing beats applying it: a duplicate leaves both
        shortcuts dead, which looks like the app ignoring the keyboard.
        """
        entry = self._entries.get(key)
        if entry is None:
            return None
        clash = self.owner_of(sequence, ignoring=key)
        if clash is not None:
            return clash.label
        entry.action.setShortcut(sequence)
        if sequence == entry.default:
            self._settings.remove(f"{_PREFIX}{key}")
        else:
            self._settings.setValue(f"{_PREFIX}{key}", sequence.toString())
        self.changed.emit()
        return None

    def reset(self, key: str) -> None:
        entry = self._entries.get(key)
        if entry is None:
            return
        entry.action.setShortcut(QKeySequence(entry.default))
        self._settings.remove(f"{_PREFIX}{key}")
        self.changed.emit()

    def reset_all(self) -> None:
        for entry in self._entries.values():
            entry.action.setShortcut(QKeySequence(entry.default))
            self._settings.remove(f"{_PREFIX}{entry.key}")
        self.changed.emit()
