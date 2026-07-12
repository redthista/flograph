"""User-writable data locations (Qt-free, stdlib only).

Imported by both the GUI (`app.py`) and the headless runner
(`engine/headless.py`), so it must not import Qt. The `FLOPY_USER_DIR`
environment variable overrides the platform default — tests point it at a tmp
directory so nothing touches the real profile.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def user_data_dir() -> Path:
    """The flopy per-user data directory (created lazily by callers)."""
    override = os.environ.get("FLOPY_USER_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "flopy"


def user_nodes_dir() -> Path:
    """Directory scanned for user-saved node scripts."""
    return user_data_dir() / "nodes"
