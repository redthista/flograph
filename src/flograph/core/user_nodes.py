"""Create, name, and organize user-saved node scripts (Qt-free).

User nodes live as .py files under a user-writable directory (see
`flograph.paths.user_nodes_dir`), one file per node, optionally nested one level
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


class UserNodeExistsError(UserNodeError):
    """The destination is already taken.

    Its own class because it is the one failure with an obvious next move —
    the caller offers to overwrite — and catching the base class for that
    would offer to overwrite in answer to "this code doesn't load", where
    trying again can only fail the same way.
    """


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

    Node scripts are not assumed to be ASCII: ast column offsets count UTF-8
    *bytes* into their line, so they are converted to character offsets
    before slicing (see `_abs_offset`). A rewrite that somehow fails to parse
    is discarded rather than written — this function's whole job is to hand
    back something loadable, and a mangled node saves to disk but then
    vanishes from the library at load time.
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
    lines = source.splitlines(keepends=True)
    line_starts = _line_starts(lines)
    wanted = {"label": label, "category": category}
    for key_node, val_node in zip(node_dict.keys, node_dict.values):
        if (isinstance(key_node, ast.Constant) and key_node.value in wanted
                and isinstance(val_node, ast.Constant)
                and isinstance(val_node.value, str)):
            start = _abs_offset(lines, line_starts,
                                val_node.lineno, val_node.col_offset)
            end = _abs_offset(lines, line_starts,
                              val_node.end_lineno, val_node.end_col_offset)
            if start is None or end is None:
                return source
            replacements.append((start, end, repr(wanted[key_node.value])))

    rewritten = source
    for start, end, new_text in sorted(replacements, reverse=True):
        rewritten = rewritten[:start] + new_text + rewritten[end:]
    try:
        ast.parse(rewritten)
    except SyntaxError:
        return source
    return rewritten


def _line_starts(lines: list[str]) -> list[int]:
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    return starts


def _abs_offset(lines: list[str], line_starts: list[int],
                lineno: int, col_offset: int) -> Optional[int]:
    """Absolute character index in the source for an ast (lineno, col_offset).

    `col_offset` counts UTF-8 bytes into the line, so an em dash or an accent
    anywhere to its left on that line makes it larger than the character
    index. Converting it is what keeps a label like "Café — x" from splicing
    the replacement a few characters too far along and shredding the dict.
    """
    line = lines[lineno - 1]
    try:
        prefix = line.encode("utf-8")[:col_offset].decode("utf-8")
    except UnicodeDecodeError:  # offset inside a character: not ours to guess
        return None
    return line_starts[lineno - 1] + len(prefix)


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
        raise UserNodeExistsError(f"a user node already exists at {dest}")
    body = set_node_metadata(source, label=name, category=group or "User")
    _reject_unloadable(body, type_id)
    dest.write_text(body, encoding="utf-8")
    return type_id


def _reject_unloadable(body: str, type_id: str) -> None:
    """Refuse to write a node script the library could not load back.

    A file that saves and then fails to parse is the worst outcome available
    here: it reports success, occupies the name, and simply never appears in
    the library. Checking costs one parse of a script that is already loaded
    in this process. A *missing package* is deliberately allowed through —
    that is this machine's state, not a fault in the script, and the node
    loads as a placeholder that installing the package fixes.
    """
    from .script import MissingDependencyError, NodeScriptError, parse_spec
    try:
        parse_spec(body, type_id)
    except MissingDependencyError:
        return
    except NodeScriptError as exc:
        raise UserNodeError(
            f"this node's code can't be loaded as a node script, so saving "
            f"it would put something in the library that never appears "
            f"there: {exc}") from None


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
    source = set_node_metadata(src.read_text(encoding="utf-8"),
                               label=new_name, category=group or "User")
    new_stem = slugify(new_name)
    dest = (nodes_dir / group if group else nodes_dir) / f"{new_stem}.py"
    if dest != src and dest.exists():
        raise UserNodeExistsError(f"a user node already exists at {dest}")
    _reject_unloadable(source, type_id_for(group, new_stem))
    dest.write_text(source, encoding="utf-8")
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
        raise UserNodeExistsError(f"a user node already exists at {dest}")
    # keep the label, refresh the category to match the new group
    label = _current_label(src) or stem
    moved = set_node_metadata(src.read_text(encoding="utf-8"), label=label,
                              category=new_group or "User")
    _reject_unloadable(moved, type_id_for(new_group, stem))
    src.write_text(moved, encoding="utf-8")
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
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
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
