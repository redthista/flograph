"""User-writable data locations (Qt-free, stdlib only).

Imported by both the GUI (`app.py`) and the headless runner
(`engine/headless.py`), so it must not import Qt. The `FLOGRAPH_USER_DIR`
environment variable overrides the platform default — tests point it at a tmp
directory so nothing touches the real profile.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def user_data_dir() -> Path:
    """The flograph per-user data directory (created lazily by callers)."""
    override = os.environ.get("FLOGRAPH_USER_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "flograph"


def user_nodes_dir() -> Path:
    """Directory scanned for user-saved node scripts."""
    return user_data_dir() / "nodes"


def user_images_dir() -> Path:
    """Store for images pasted onto the canvas from the clipboard.

    A clipboard image has no file of its own, so it needs somewhere to live
    before an Image node can point a path at it. Keeping it here rather than
    inline in the .flograph file matches how every other file-backed node
    works (Read CSV stores a path, not the CSV) and keeps a project holding
    a screenshot from carrying megabytes of base64 through every save and
    every undo entry. Files are named by content hash, so pasting the same
    screenshot twice costs one file.
    """
    return user_data_dir() / "images"
