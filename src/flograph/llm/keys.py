"""Where AI connection keys are kept (Qt-free).

Not in QSettings: that is a plain-text file on Linux and macOS and a
readable registry key on Windows, and an API key in it is one backup or
one screen-share away from being someone else's. The system keychain —
Windows Credential Manager, the macOS Keychain, the Secret Service
(GNOME Keyring / KWallet) — is what it is for, reached through the
optional `keyring` package.

Where there is no keychain (`keyring` not installed, or a headless box
with no Secret Service), keys go to a file in the user folder that only
this user can read, and `KeyStore.secure` is False so the settings dialog
can say so plainly. That is no worse than where keys used to live, and it
is never chosen silently: a keychain that exists but *refuses* a write is
an error the user sees, not a quiet fall back to a file.

`FLOGRAPH_KEYS=file` forces the file store. The test suite sets it, so no
test can write to the developer's real keychain.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

SERVICE = "flograph"
KEYS_FILE = "ai_keys.json"


class KeyStoreError(Exception):
    """The keychain refused to read or write a key."""


def _keyring_backend():
    """The usable keyring module, or None.

    `keyring` installs a "fail" backend (priority 0) where no real
    keychain exists, and the null backend has negative priority; neither
    stores anything, so both count as "no keychain".
    """
    if os.environ.get("FLOGRAPH_KEYS", "").lower() == "file":
        return None
    try:
        import keyring
        backend = keyring.get_keyring()
    except Exception:
        return None
    if getattr(backend, "priority", 0) <= 0:
        return None
    return keyring


def _backend_name(module) -> str:
    try:
        name = type(module.get_keyring()).__module__
    except Exception:
        return "the system keychain"
    if "Windows" in name:
        return "Windows Credential Manager"
    if "macOS" in name or "OS_X" in name:
        return "the macOS Keychain"
    if "SecretService" in name or "libsecret" in name:
        return "the system keyring (Secret Service)"
    if "kwallet" in name.lower():
        return "KWallet"
    return "the system keychain"


class KeyStore:
    """get/set/delete secrets by name. Empty string means "no key"."""

    def __init__(self, keyring_module=None, file_path: Optional[Path] = None):
        self._keyring = keyring_module
        self._file = file_path

    @property
    def secure(self) -> bool:
        return self._keyring is not None

    @property
    def where(self) -> str:
        """A phrase for the dialog: "Keys are kept in <where>"."""
        if self._keyring is not None:
            return _backend_name(self._keyring)
        return f"a private file in your user folder ({self._path()})"

    def _path(self) -> Path:
        if self._file is not None:
            return self._file
        from ..paths import user_data_dir
        return user_data_dir() / KEYS_FILE

    # -- file store ---------------------------------------------------------

    def _read_file(self) -> dict:
        try:
            data = json.loads(self._path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_file(self, data: dict) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        # Created owner-only rather than chmod-ed afterwards, so there is no
        # moment where the key sits in a world-readable file.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, path)

    # -- API ----------------------------------------------------------------

    def get(self, name: str) -> str:
        if self._keyring is not None:
            try:
                return self._keyring.get_password(SERVICE, name) or ""
            except Exception as exc:
                raise KeyStoreError(
                    f"could not read the key from {self.where}: {exc}") from exc
        value = self._read_file().get(name)
        return value if isinstance(value, str) else ""

    def set(self, name: str, value: str) -> None:
        value = (value or "").strip()
        if not value:
            self.delete(name)
            return
        if self._keyring is not None:
            try:
                self._keyring.set_password(SERVICE, name, value)
            except Exception as exc:
                raise KeyStoreError(
                    f"could not save the key to {self.where}: {exc}") from exc
            return
        data = self._read_file()
        data[name] = value
        self._write_file(data)

    def delete(self, name: str) -> None:
        if self._keyring is not None:
            try:
                self._keyring.delete_password(SERVICE, name)
            except Exception:
                pass  # not there is the same as deleted
            return
        data = self._read_file()
        if data.pop(name, None) is not None:
            self._write_file(data)


def default_store() -> KeyStore:
    return KeyStore(_keyring_backend())
