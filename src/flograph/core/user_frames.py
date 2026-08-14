"""Save a frame and its contents to the user library, and read it back (Qt-free).

A saved frame — a *component* — is a fragment of a flow: one frame, the nodes
inside it, and the wires between them. They live as .floframe files under a
user-writable directory (see `flograph.paths.user_frames_dir`), one file per
component, optionally nested one level deep in a group subdirectory, exactly
as user nodes do:

    <frames_dir>/<stem>.floframe          -> "frame.<stem>"          (ungrouped)
    <frames_dir>/<group>/<stem>.floframe  -> "frame.<group>.<stem>"  (grouped)

Deliberately *not* a node type. A user node is a definition the registry
instantiates; a component is a lump of graph that gets copied in, so it has no
spec, no ports of its own and nothing for `NodeRegistry` to load. It rides the
same shape as the clipboard payload instead, which already knows how to carry
a frame plus its nodes plus their wires.

Inserting one is a copy — every id is freshly minted, and editing the copy
never touches the file. But the copy is stamped with where it came from
(`Frame.source` / `Frame.source_fingerprint`), so a component nobody has
edited can still be told apart from one that has diverged: hash its current
contents the same way and compare. See `content_hash`.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

FRAME_PREFIX = "frame"
SUFFIX = ".floframe"
#: Bumped only if the payload shape changes incompatibly. Readers accept
#: anything they understand and fall back to defaults, as the project format
#: does — an unknown key is not an error.
FORMAT_VERSION = 1


class UserFrameError(Exception):
    """A user-frame file operation could not be completed."""


# --------------------------------------------------------------- naming utils

def slugify(name: str) -> str:
    """A filesystem/id-safe stem derived from a display name."""
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    return slug or "frame"


def frame_id_for(group: Optional[str], stem: str) -> str:
    if group:
        return f"{FRAME_PREFIX}.{group}.{stem}"
    return f"{FRAME_PREFIX}.{stem}"


def split_frame_id(frame_id: str) -> tuple[Optional[str], str]:
    """(group, stem) for a component id. group is None when ungrouped."""
    parts = frame_id.split(".")
    if len(parts) < 2 or parts[0] != FRAME_PREFIX:
        raise UserFrameError(f"not a user frame id: {frame_id!r}")
    if len(parts) == 2:
        return None, parts[1]
    return parts[1], parts[2]


def path_for(frames_dir: Path, frame_id: str) -> Path:
    group, stem = split_frame_id(frame_id)
    base = frames_dir / group if group else frames_dir
    return base / f"{stem}{SUFFIX}"


# ------------------------------------------------------------- fingerprinting

def content_hash(payload: dict) -> str:
    """A stable hash of what a component *is*, ignoring where it sits.

    Ids and positions are normalised out: pasting a component moves it and
    regenerates every id, and neither of those means the user changed
    anything. What survives is the shape — node types, their params and code
    overrides, and the wires between them, keyed by the node labels the wires
    join rather than by ids that differ in every copy.

    So a freshly inserted component hashes equal to its library file, and any
    real edit inside it — a param, a code override, a node added or rewired —
    does not. That is the whole of the pristine-vs-detached test; no
    per-node bookkeeping is needed.
    """
    nodes = sorted(
        (
            str(n.get("label") or ""),
            str(n.get("type") or ""),
            json.dumps(n.get("params") or {}, sort_keys=True,
                       separators=(",", ":"), default=str),
            str(n.get("code") or ""),
        )
        for n in payload.get("nodes", [])
    )
    by_id = {n.get("id"): str(n.get("label") or "")
             for n in payload.get("nodes", [])}
    wires = sorted(
        (by_id.get(c.get("src", [None])[0], ""), str(c.get("src", [None, ""])[1]),
         by_id.get(c.get("dst", [None])[0], ""), str(c.get("dst", [None, ""])[1]))
        for c in payload.get("connections", [])
    )
    frames = sorted(
        (str(f.get("title") or ""), str(f.get("color") or ""))
        for f in payload.get("frames", [])
    )
    blob = json.dumps({"nodes": nodes, "wires": wires, "frames": frames},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


# -------------------------------------------------------------------- reading

def scan(frames_dir: Path) -> list[dict]:
    """Every component in the library: [{id, name, group, path}], sorted.

    A file that will not parse is skipped rather than raising — one bad file
    in the library must not take the whole palette section down with it.
    """
    found: list[dict] = []
    if not frames_dir.is_dir():
        return found
    for path in sorted(frames_dir.glob(f"*{SUFFIX}")):
        entry = _entry(path, None)
        if entry is not None:
            found.append(entry)
    for sub in sorted(p for p in frames_dir.iterdir() if p.is_dir()):
        for path in sorted(sub.glob(f"*{SUFFIX}")):
            entry = _entry(path, sub.name)
            if entry is not None:
                found.append(entry)
    return found


def _entry(path: Path, group: Optional[str]) -> Optional[dict]:
    try:
        payload = read(path)
    except UserFrameError:
        return None
    stem = path.stem
    return {
        "id": frame_id_for(group, stem),
        "name": payload.get("name") or stem,
        "group": group,
        "path": path,
        "fingerprint": content_hash(payload.get("payload", {})),
    }


def read(path: Path) -> dict:
    """Load a .floframe file. Raises UserFrameError if it is not one."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise UserFrameError(f"cannot read {path}: {exc}") from None
    if not isinstance(data, dict) or "payload" not in data:
        raise UserFrameError(f"{path} is not a flograph component")
    return data


# ------------------------------------------------------------- file mutations

def write_user_frame(frames_dir: Path, group: Optional[str], name: str,
                     payload: dict, *, overwrite: bool = False) -> str:
    """Save `payload` (a clipboard-shaped fragment) as a component."""
    group = group or None
    stem = slugify(name)
    dest_dir = frames_dir / group if group else frames_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{stem}{SUFFIX}"
    if dest.exists() and not overwrite:
        raise UserFrameError(f"a component already exists at {dest}")
    dest.write_text(json.dumps({
        "flograph_component": FORMAT_VERSION,
        "name": name,
        "payload": payload,
    }, indent=2))
    return frame_id_for(group, stem)


def delete_user_frame(frames_dir: Path, frame_id: str) -> None:
    path = path_for(frames_dir, frame_id)
    if not path.exists():
        raise UserFrameError(f"no such component: {frame_id}")
    path.unlink()


def rename_user_frame(frames_dir: Path, frame_id: str, new_name: str) -> str:
    """Rename a component's file and its display name, same group."""
    group, _stem = split_frame_id(frame_id)
    src = path_for(frames_dir, frame_id)
    if not src.exists():
        raise UserFrameError(f"no such component: {frame_id}")
    data = read(src)
    data["name"] = new_name
    new_stem = slugify(new_name)
    dest = (frames_dir / group if group else frames_dir) / f"{new_stem}{SUFFIX}"
    if dest != src and dest.exists():
        raise UserFrameError(f"a component already exists at {dest}")
    dest.write_text(json.dumps(data, indent=2))
    if dest != src:
        src.unlink()
    return frame_id_for(group, new_stem)


def move_user_frame(frames_dir: Path, frame_id: str,
                    new_group: Optional[str]) -> str:
    """Move a component into `new_group` (None = ungrouped, top level)."""
    new_group = new_group or None
    old_group, stem = split_frame_id(frame_id)
    if new_group == old_group:
        return frame_id
    src = path_for(frames_dir, frame_id)
    if not src.exists():
        raise UserFrameError(f"no such component: {frame_id}")
    dest_dir = frames_dir / new_group if new_group else frames_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{stem}{SUFFIX}"
    if dest.exists():
        raise UserFrameError(f"a component already exists at {dest}")
    src.rename(dest)
    return frame_id_for(new_group, stem)
