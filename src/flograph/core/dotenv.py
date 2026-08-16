""".env files — where a flow's secrets live, so they never live in the flow.

`serialization.graph_to_dict` writes every param verbatim, so a password
typed into a node is stored in the clear inside the .flograph and travels
with it to whoever you send it to. A `${env:NAME}` reference is the way out:
the project stores the *name* and the path to a file, never the value.

Deliberately hand-rolled rather than pulling in python-dotenv. The format is
forty lines of parsing and the project has four dependencies; that discipline
is worth more than the import. It is also Qt-free and stdlib-only, so the
headless runner and the tests can use it without a display.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ..paths import user_data_dir

FILENAME = ".env"


def is_valid_key(key: str) -> bool:
    """Deliberately the same rule `varlinks.PATTERN` applies after `env:`, so
    a key that could never be referenced cannot be created either."""
    return bool(key) and key.isidentifier()


def parse(text: str) -> dict[str, str]:
    """A .env file's text as a mapping.

    Accepts what these files actually contain: `KEY=value`, `#` comments,
    blank lines, a leading `export `, and values wrapped in single or double
    quotes. A line that isn't a valid assignment is skipped rather than
    raised on — a secrets file half-edited by hand must still yield the keys
    that are fine.
    """
    values: dict[str, str] = {}
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not is_valid_key(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def dump(values: dict[str, str]) -> str:
    """The mapping back as file text, quoting only where it matters.

    Sorted so a file edited through the dialog produces a stable diff rather
    than reordering itself every save.
    """
    lines = []
    for key in sorted(values):
        value = str(values[key])
        if value != value.strip() or any(c in value for c in "#\"'"):
            value = '"' + value.replace('"', '\\"') + '"'
        lines.append(f"{key}={value}")
    return "\n".join(lines) + ("\n" if lines else "")


def default_path() -> Path:
    """The per-user secrets file, used when a project names no other."""
    return user_data_dir() / FILENAME


def resolve_path(env_path: str, project_path: Optional[str] = None) -> Path:
    """Where a project's secrets actually are.

    A project stores its env path *relative to itself* where it can, so a
    team can each keep their own file at the same relative spot and the
    project still opens on every machine. An absolute path is honoured as
    given, and a project that names nothing falls back to the per-user file.
    """
    env_path = str(env_path or "").strip()
    if not env_path:
        return default_path()
    path = Path(env_path).expanduser()
    if path.is_absolute() or not project_path:
        return path
    return (Path(project_path).expanduser().resolve().parent / path)


def store_path(path: str, project_path: Optional[str] = None) -> str:
    """What to write into the project for a chosen file: relative to the
    project when the file sits under it, absolute otherwise."""
    chosen = Path(path).expanduser().resolve()
    if project_path:
        base = Path(project_path).expanduser().resolve().parent
        try:
            return chosen.relative_to(base).as_posix()
        except ValueError:
            pass            # outside the project tree: keep it absolute
    return str(chosen)


def load(path: Path | str) -> dict[str, str]:
    """The file's keys, or an empty mapping if it isn't there or can't be
    read. A missing secrets file is a normal state — the project opens, and
    the nodes that need a secret are the only ones that stop."""
    try:
        return parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}


def save(path: Path | str, values: dict[str, str]) -> None:
    """Write the file, owner-readable only.

    0600 before the content goes in, not after: a secrets file must never
    exist, even for an instant, at whatever the process umask would have
    given it. Best-effort on platforms without POSIX modes.
    """
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    except OSError:
        path.write_text(dump(values), encoding="utf-8")
        return
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
        fh.write(dump(values))
    try:
        os.chmod(path, 0o600)       # an existing file keeps its old mode
    except OSError:
        pass


def environment(path: Path | str) -> dict[str, str]:
    """The secrets a run should see: the file's keys, with `os.environ`
    filling gaps.

    The **file wins**. python-dotenv defaults the other way, but this is a
    desktop app: someone who just typed a value into the dialog has to see
    it take effect, and a stale shell variable silently overriding them is
    an unexplainable bug. `os.environ` still covers keys the file omits,
    which is what makes a CI or container run work with no file at all.
    """
    values = dict(os.environ)
    values.update(load(path))
    return values
