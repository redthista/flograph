"""Favorites: which node types the user has starred, persisted in QSettings.

Shared by the library tree and the Tab palette popup. A favourite is a
type_id string; a type_id that no longer resolves (a user node deleted, a
builtin that no longer exists) is ignored at display time, not pruned —
pruning would make an offline move permanent.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Signal

_SETTINGS_KEY = "library/favorites"


class Favorites(QObject):
    """An observable set of favorite type_ids, persisted on every change."""

    changed = Signal()

    def __init__(self, settings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        raw = settings.value(_SETTINGS_KEY, [])
        if isinstance(raw, str):  # guard against a malformed stored value
            raw = [raw]
        self._ids = list(dict.fromkeys(raw))

    def ids(self) -> list[str]:
        return list(self._ids)

    def contains(self, type_id: str) -> bool:
        return type_id in self._ids

    def toggle(self, type_id: str) -> bool:
        """Star/unstar type_id. Returns True when it is now a favourite."""
        if type_id in self._ids:
            self._ids.remove(type_id)
            added = False
        else:
            self._ids.append(type_id)
            added = True
        self._settings.setValue(_SETTINGS_KEY, self._ids)
        self.changed.emit()
        return added
