"""Create, name, and organize user-saved node scripts (Qt-free).

User nodes live as .py files under a user-writable directory (see
`flopy.paths.user_nodes_dir`), one file per node, optionally nested one level
deep in a group subdirectory. Their type_id encodes the layout:

    <nodes_dir>/<stem>.py           -> "user.<stem>"          (ungrouped)
    <nodes_dir>/<group>/<stem>.py   -> "user.<group>.<stem>"  (grouped)

Both group and stem are slugs (no dots), so the type_id splits unambiguously.
These helpers only touch the filesystem; registering the results into a
`NodeRegistry` is `registry.load_user_nodes` / `reload_user_nodes`.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Optional

USER_PREFIX = "user"


class UserNodeError(Exception):
    """A user-node file/dir operation could not be completed."""


# --------------------------------------------------------------- naming utils

def slugify(name: str) -> str:
    """A filesystem/type-id-safe stem derived from a display name."""
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    return slug or "node"


def type_id_for(group: Optional[str], stem: str) -> str:
    if group:
        return f"{USER_PREFIX}.{group}.{stem}"
    return f"{USER_PREFIX}.{stem}"


def split_type_id(type_id: str) -> tuple[Optional[str], str]:
    """(group, stem) for a user type_id. group is None when ungrouped."""
    parts = type_id.split(".")
    if len(parts) < 2 or parts[0] != USER_PREFIX:
        raise UserNodeError(f"not a user node type_id: {type_id!r}")
    if len(parts) == 2:
        return None, parts[1]
    return parts[1], parts[2]


def path_for(nodes_dir: Path, type_id: str) -> Path:
    group, stem = split_type_id(type_id)
    base = nodes_dir / group if group else nodes_dir
    return base / f"{stem}.py"


# ------------------------------------------------------------ source rewriting

def set_node_metadata(source: str, label: str, category: str) -> str:
    """Return `source` with the NODE dict's label/category string literals
    replaced. Leaves PARAMS and run() untouched. If NODE isn't a simple dict
    literal with string label/category values, returns the source unchanged.

    Node scripts are ASCII, so ast column offsets are treated as character
    offsets.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    node_dict: Optional[ast.Dict] = None
    for stmt in tree.body:
        if (isinstance(stmt, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "NODE"
                        for t in stmt.targets)
                and isinstance(stmt.value, ast.Dict)):
            node_dict = stmt.value
            break
    if node_dict is None:
        return source

    replacements: list[tuple[int, int, str]] = []  # (start, end, new_text)
    line_starts = _line_starts(source)
    wanted = {"label": label, "category": category}
    for key_node, val_node in zip(node_dict.keys, node_dict.values):
        if (isinstance(key_node, ast.Constant) and key_node.value in wanted
                and isinstance(val_node, ast.Constant)
                and isinstance(val_node.value, str)):
            start = line_starts[val_node.lineno - 1] + val_node.col_offset
            end = line_starts[val_node.end_lineno - 1] + val_node.end_col_offset
            replacements.append((start, end, repr(wanted[key_node.value])))

    for start, end, new_text in sorted(replacements, reverse=True):
        source = source[:start] + new_text + source[end:]
    return source


def _line_starts(source: str) -> list[int]:
    starts = [0]
    for line in source.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    return starts


# ------------------------------------------------------------- file mutations

def write_user_node(nodes_dir: Path, group: Optional[str], name: str,
                    source: str, *, overwrite: bool = False) -> str:
    """Write `source` as a user node named `name` in `group`. Returns its
    type_id. Raises UserNodeError if the target exists and not `overwrite`."""
    group = group or None
    stem = slugify(name)
    type_id = type_id_for(group, stem)
    dest_dir = nodes_dir / group if group else nodes_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{stem}.py"
    if dest.exists() and not overwrite:
        raise UserNodeError(f"a user node already exists at {dest}")
    body = set_node_metadata(source, label=name, category=group or "User")
    dest.write_text(body)
    return type_id


def delete_user_node(nodes_dir: Path, type_id: str) -> None:
    path = path_for(nodes_dir, type_id)
    if not path.exists():
        raise UserNodeError(f"no such user node: {type_id}")
    path.unlink()


def rename_user_node(nodes_dir: Path, type_id: str, new_name: str) -> str:
    """Rename a user node's file (and its label) in place, same group."""
    group, _ = split_type_id(type_id)
    src = path_for(nodes_dir, type_id)
    if not src.exists():
        raise UserNodeError(f"no such user node: {type_id}")
    source = set_node_metadata(src.read_text(), label=new_name,
                               category=group or "User")
    new_stem = slugify(new_name)
    dest = (nodes_dir / group if group else nodes_dir) / f"{new_stem}.py"
    if dest != src and dest.exists():
        raise UserNodeError(f"a user node already exists at {dest}")
    dest.write_text(source)
    if dest != src:
        src.unlink()
    return type_id_for(group, new_stem)


def move_user_node(nodes_dir: Path, type_id: str,
                   new_group: Optional[str]) -> str:
    """Move a user node into `new_group` (None = ungrouped, top level)."""
    new_group = new_group or None
    old_group, stem = split_type_id(type_id)
    if new_group == old_group:
        return type_id
    src = path_for(nodes_dir, type_id)
    if not src.exists():
        raise UserNodeError(f"no such user node: {type_id}")
    dest_dir = nodes_dir / new_group if new_group else nodes_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{stem}.py"
    if dest.exists():
        raise UserNodeError(f"a user node already exists at {dest}")
    # keep the label, refresh the category to match the new group
    label = _current_label(src) or stem
    src.write_text(set_node_metadata(src.read_text(), label=label,
                                     category=new_group or "User"))
    src.rename(dest)
    return type_id_for(new_group, stem)


def create_group(nodes_dir: Path, group: str) -> str:
    slug = slugify(group)
    (nodes_dir / slug).mkdir(parents=True, exist_ok=True)
    return slug


def list_groups(nodes_dir: Path) -> list[str]:
    if not nodes_dir.exists():
        return []
    return sorted(e.name for e in nodes_dir.iterdir()
                  if e.is_dir() and not e.name.startswith((".", "_")))


def _current_label(path: Path) -> Optional[str]:
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return None
    for stmt in tree.body:
        if (isinstance(stmt, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "NODE"
                        for t in stmt.targets)
                and isinstance(stmt.value, ast.Dict)):
            for k, v in zip(stmt.value.keys, stmt.value.values):
                if (isinstance(k, ast.Constant) and k.value == "label"
                        and isinstance(v, ast.Constant)):
                    return v.value
    return None
