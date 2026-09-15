"""User-saved CSS snippets for Web reports."""
from __future__ import annotations

import re
from pathlib import Path

from flograph.paths import user_data_dir


def snippets_dir() -> Path:
    return user_data_dir() / "css"


def list_snippets() -> list[Path]:
    """Return saved snippets in stable display order."""
    folder = snippets_dir()
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.css"), key=lambda p: p.name.casefold())


def read_snippet(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def save_snippet(name: str, css: str) -> Path:
    """Save CSS under a safe filename in the user's flograph data folder."""
    stem = re.sub(r"[^\w\- ]+", "", name or "").strip()
    stem = re.sub(r"\s+", "-", stem)[:80] or "snippet"
    folder = snippets_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stem}.css"
    path.write_text(css or "", encoding="utf-8")
    return path
