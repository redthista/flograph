"""Where a Browse… dialog opens.

A file dialog given no start directory opens in the process's working
directory — for flograph, wherever it was launched from, which is nobody's
data. The usual rule, and this one: open on the file the field already
names (selected), else the nearest folder above it that still exists, else
the last folder browsed to from any field, else home.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

LAST_FOLDER_SETTING = "dialogs/last_folder"


def start_path(current: str = "", *, folder: bool = False) -> str:
    """The path to hand a QFileDialog as its start: a file path selects
    that file (or prefills the name to save as), a folder opens there."""
    text = (current or "").strip()
    if text:
        path = Path(text).expanduser()
        if folder:
            if path.is_dir():
                return str(path.absolute())
        elif path.exists() or (path.parent != Path(".")
                               and path.parent.is_dir()):
            return str(path.absolute())
        # A relative path stops before ".": climbing to the working
        # directory is the very place this is here to avoid.
        for parent in path.parents:
            if parent in (Path("."), Path(parent.anchor)):
                break
            if parent.is_dir():
                return str(parent.absolute())
    last = str(QSettings("flograph", "flograph").value(
        LAST_FOLDER_SETTING, "") or "")
    if last and Path(last).is_dir():
        return last
    return str(Path.home())


def remember(chosen: str) -> None:
    """Note the folder of a path the user picked, for the next empty field."""
    if not chosen:
        return
    path = Path(chosen)
    where = path if path.is_dir() else path.parent
    if where.is_dir():
        QSettings("flograph", "flograph").setValue(
            LAST_FOLDER_SETTING, str(where.absolute()))
