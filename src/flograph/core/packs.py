"""Node packs: add-on bundles of node scripts (Qt-free).

A pack is a folder with a ``pack.toml`` manifest beside its node scripts:

    image_generation/
        pack.toml            [pack] id, name, version, requires, ...
        nodes/               node scripts, exactly like the builtins:
            sampler.py           -> pack.image_generation.sampler
            extra/upscale.py     -> pack.image_generation.extra.upscale
        lib/                 optional Python code the nodes share, importable
                             as ``flograph_packs.image_generation``
        examples/            optional .flograph files that show it off
        README.md            optional

Why a pack is more than a folder of user nodes. A node script is executed,
never imported (see core.script), so anything it defines is rebuilt every
time it runs. That is right for a node and wrong for what a pack usually
brings with it: a model that takes ten seconds to load, a connection pool,
a few hundred lines of helpers every node of the pack calls. ``lib/`` is the
home for those. It is reached through an import hook rather than sys.path,
so two packs can each have a ``utils.py`` without one shadowing the other,
and nothing in it runs until a node's ``run()`` first imports it — loading
the library never imports torch.

Where packs come from, in order (an id seen twice keeps its first):

1. ``FLOGRAPH_PACKS`` — os.pathsep-separated folders, for a headless box or
   a test.
2. Linked folders, kept in ``packs.json`` beside the user nodes. A pack in
   development stays where its git checkout is and is read from there.
3. Installed packs: one folder each under ``<user data>/packs/``, which is
   what Install from .zip writes.

A linked path may be a pack or a folder *of* packs (a repo holding
several), so one link covers a whole collection.

Nodes of a pack get the type id ``pack.<id>.<stem>``. A saved flow keeps
only that id, like a builtin's — the pack is distributed on its own, not
pasted into every project — and records which packs it used, so a flow
opened on a machine without one says which pack to install rather than
just "unknown node".
"""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import tomllib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

PACK_PREFIX = "pack"
MANIFEST = "pack.toml"
#: The top-level module every pack's ``lib/`` hangs from.
IMPORT_ROOT = "flograph_packs"
CONFIG_FILE = "packs.json"

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_STEM_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Never copied into a zip or an install: build and editor droppings, and a
# virtualenv someone made inside their pack checkout.
_SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", ".idea", ".mypy_cache",
              ".pytest_cache", ".ruff_cache"}


class PackError(Exception):
    """A pack could not be read, installed or removed."""


class PackExistsError(PackError):
    """Installing would replace a pack already installed under that id."""


@dataclass
class Pack:
    """One pack as read from its manifest."""
    id: str
    name: str
    version: str
    root: Path
    description: str = ""
    author: str = ""
    homepage: str = ""
    requires: list[str] = field(default_factory=list)
    #: an extra package index the requirements need (torch's CUDA wheels)
    index_url: str = ""
    #: "installed", "linked" or "env" — how this machine found it
    source: str = "installed"

    @property
    def nodes_dir(self) -> Path:
        return self.root / "nodes"

    @property
    def lib_dir(self) -> Path:
        return self.root / "lib"

    @property
    def examples_dir(self) -> Path:
        return self.root / "examples"

    def node_files(self) -> list[tuple[str, Path]]:
        """(type_id, path) for every node script, sorted.

        Top-level ``nodes/<stem>.py`` and one level of subfolder, the same
        depth user nodes allow. ``_``-prefixed files are helpers, not nodes.
        """
        out: list[tuple[str, Path]] = []
        base = self.nodes_dir
        if not base.is_dir():
            return out
        for entry in sorted(base.iterdir(), key=lambda e: e.name):
            if entry.name.startswith((".", "_")) or entry.name in _SKIP_DIRS:
                continue
            if entry.is_file() and entry.suffix == ".py":
                out.append((type_id_for(self.id, entry.stem), entry))
            elif entry.is_dir() and _STEM_RE.match(entry.name):
                for sub in sorted(entry.iterdir(), key=lambda e: e.name):
                    if (sub.is_file() and sub.suffix == ".py"
                            and not sub.name.startswith(("_", "."))):
                        out.append((type_id_for(self.id, sub.stem, entry.name),
                                    sub))
        return out

    def examples(self) -> list[Path]:
        if not self.examples_dir.is_dir():
            return []
        return sorted(p for p in self.examples_dir.iterdir()
                      if p.suffix in (".flograph", ".flowf"))


def type_id_for(pack_id: str, stem: str, sub: Optional[str] = None) -> str:
    return (f"{PACK_PREFIX}.{pack_id}.{sub}.{stem}" if sub
            else f"{PACK_PREFIX}.{pack_id}.{stem}")


def pack_id_of(type_id: str) -> Optional[str]:
    """The pack a type id belongs to, or None for any other node."""
    parts = type_id.split(".")
    if len(parts) >= 3 and parts[0] == PACK_PREFIX:
        return parts[1]
    return None


# ------------------------------------------------------------------ manifest

def read_manifest(root: Path, source: str = "installed") -> Pack:
    """Read ``root/pack.toml``. Raises PackError saying what to fix."""
    root = Path(root)
    path = root / MANIFEST
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PackError(f"{root} has no {MANIFEST}") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise PackError(f"{path}: {exc}") from None
    except tomllib.TOMLDecodeError as exc:
        raise PackError(f"{path}: {exc}") from None
    table = data.get("pack")
    if not isinstance(table, dict):
        raise PackError(f"{path} must have a [pack] table")
    pack_id = table.get("id")
    if not isinstance(pack_id, str) or not _ID_RE.match(pack_id):
        raise PackError(
            f"{path}: [pack] id must be lower_snake_case letters, digits and "
            f"underscores, starting with a letter (got {pack_id!r})")
    name = table.get("name") or pack_id.replace("_", " ").title()
    version = str(table.get("version") or "").strip()
    if not version:
        raise PackError(f"{path}: [pack] version is required, like \"0.1.0\"")
    requires = table.get("requires", [])
    if (not isinstance(requires, list)
            or not all(isinstance(r, str) for r in requires)):
        raise PackError(f"{path}: [pack] requires must be a list of strings")
    return Pack(
        id=pack_id, name=str(name), version=version, root=root,
        description=str(table.get("description") or ""),
        author=str(table.get("author") or ""),
        homepage=str(table.get("homepage") or ""),
        requires=[r.strip() for r in requires if r.strip()],
        index_url=str(table.get("index_url") or ""),
        source=source,
    )


# ------------------------------------------------------------------ config

def packs_dir(user_dir: Path) -> Path:
    return Path(user_dir) / "packs"


def load_config(user_dir: Path) -> dict:
    """``packs.json``: {"linked": [paths], "disabled": [ids]}."""
    try:
        data = json.loads((Path(user_dir) / CONFIG_FILE).read_text("utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    linked = [str(p) for p in data.get("linked", []) if isinstance(p, str)]
    disabled = [str(p) for p in data.get("disabled", []) if isinstance(p, str)]
    return {"linked": linked, "disabled": disabled}


def save_config(user_dir: Path, config: dict) -> None:
    user_dir = Path(user_dir)
    user_dir.mkdir(parents=True, exist_ok=True)
    tmp = user_dir / (CONFIG_FILE + ".tmp")
    tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.replace(tmp, user_dir / CONFIG_FILE)


def link(user_dir: Path, folder: Path) -> list[Pack]:
    """Link a pack (or a folder of packs) in place. Returns what it holds."""
    folder = Path(folder).resolve()
    found = list(_packs_under(folder, "linked", errors=None))
    if not found:
        raise PackError(f"No {MANIFEST} in {folder} or the folders inside it")
    config = load_config(user_dir)
    if str(folder) not in config["linked"]:
        config["linked"].append(str(folder))
        save_config(user_dir, config)
    return found


def unlink(user_dir: Path, folder: Path) -> None:
    config = load_config(user_dir)
    folder = str(Path(folder).resolve())
    config["linked"] = [p for p in config["linked"]
                        if str(Path(p).resolve()) != folder]
    save_config(user_dir, config)


def set_enabled(user_dir: Path, pack_id: str, enabled: bool) -> None:
    config = load_config(user_dir)
    disabled = [p for p in config["disabled"] if p != pack_id]
    if not enabled:
        disabled.append(pack_id)
    config["disabled"] = disabled
    save_config(user_dir, config)


# ------------------------------------------------------------------ discovery

def _packs_under(folder: Path, source: str,
                 errors: Optional[list]) -> Iterable[Pack]:
    """A pack at `folder`, or each pack one level inside it."""
    if (folder / MANIFEST).is_file():
        candidates = [folder]
    elif folder.is_dir():
        candidates = [d for d in sorted(folder.iterdir(), key=lambda e: e.name)
                      if d.is_dir() and (d / MANIFEST).is_file()]
    else:
        if errors is not None:
            errors.append((folder, "folder not found"))
        return
    for root in candidates:
        try:
            yield read_manifest(root, source)
        except PackError as exc:
            if errors is not None:
                errors.append((root, str(exc)))


def discover(user_dir: Path, environ=None
             ) -> tuple[list[Pack], list[tuple[Path, str]]]:
    """Every pack this machine can see, and the folders that failed to read.

    Disabled packs are included (the Node Packs dialog lists them); the
    registry skips them — see `is_disabled`.
    """
    environ = os.environ if environ is None else environ
    errors: list[tuple[Path, str]] = []
    sources: list[tuple[Path, str]] = []
    for part in (environ.get("FLOGRAPH_PACKS") or "").split(os.pathsep):
        if part.strip():
            sources.append((Path(part.strip()), "env"))
    for path in load_config(user_dir)["linked"]:
        sources.append((Path(path), "linked"))
    sources.append((packs_dir(user_dir), "installed"))

    seen: dict[str, Pack] = {}
    for folder, source in sources:
        if source == "installed" and not folder.is_dir():
            continue        # nothing installed yet is not an error
        for pack in _packs_under(folder, source, errors):
            if pack.id in seen:
                errors.append((pack.root, (
                    f"pack id {pack.id!r} is already provided by "
                    f"{seen[pack.id].root}; this copy is ignored")))
                continue
            seen[pack.id] = pack
    return list(seen.values()), errors


def is_disabled(user_dir: Path, pack_id: str) -> bool:
    return pack_id in load_config(user_dir)["disabled"]


# ------------------------------------------------------------- install/export

def _safe_members(archive: zipfile.ZipFile, dest: Path) -> None:
    dest = dest.resolve()
    for member in archive.namelist():
        target = (dest / member).resolve()
        if target != dest and dest not in target.parents:
            raise PackError(f"refusing {member!r}: it would unpack outside "
                            "the pack folder")


def _find_root(folder: Path) -> Path:
    if (folder / MANIFEST).is_file():
        return folder
    inner = [d for d in folder.iterdir() if d.is_dir()
             and (d / MANIFEST).is_file()]
    if len(inner) == 1:
        return inner[0]
    raise PackError(f"no {MANIFEST} at the top of the archive or in a single "
                    "folder inside it")


def _copy_tree(src: Path, dest: Path) -> None:
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*_SKIP_DIRS))


def install(user_dir: Path, source: Path, replace: bool = False) -> Pack:
    """Copy a pack from a .zip or a folder into the installed packs.

    Raises PackExistsError when that id is installed and `replace` is off,
    so the caller can ask before overwriting.
    """
    source = Path(source)
    dest_root = packs_dir(user_dir)
    dest_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest_root, prefix=".incoming-") as tmp:
        tmp_path = Path(tmp)
        if source.is_file():
            try:
                with zipfile.ZipFile(source) as archive:
                    _safe_members(archive, tmp_path / "x")
                    archive.extractall(tmp_path / "x")
            except zipfile.BadZipFile:
                raise PackError(f"{source.name} is not a zip file") from None
            root = _find_root(tmp_path / "x")
        elif source.is_dir():
            root = _find_root(source)
        else:
            raise PackError(f"{source} not found")
        pack = read_manifest(root)
        dest = dest_root / pack.id
        if dest.exists():
            if not replace:
                raise PackExistsError(
                    f"a pack with id {pack.id!r} is already installed")
            shutil.rmtree(dest)
        if root.is_relative_to(tmp_path):
            shutil.move(str(root), str(dest))
        else:
            _copy_tree(root, dest)
    return read_manifest(dest)


def uninstall(user_dir: Path, pack: Pack) -> None:
    """Remove an installed pack's folder, or forget a linked one.

    A linked pack is somebody's working copy: it is unlinked, never deleted.
    """
    if pack.source == "installed":
        target = packs_dir(user_dir) / pack.id
        if target.resolve() != pack.root.resolve():
            raise PackError(f"{pack.root} is not in the installed packs folder")
        shutil.rmtree(target)
        return
    if pack.source == "linked":
        config = load_config(user_dir)
        root = pack.root.resolve()
        keep = []
        for path in config["linked"]:
            p = Path(path).resolve()
            if p == root:
                continue
            keep.append(path)
        if len(keep) == len(config["linked"]):
            raise PackError(
                f"{pack.name} comes from the linked folder of packs it sits "
                "in — unlink that folder instead")
        config["linked"] = keep
        save_config(user_dir, config)
        return
    raise PackError(f"{pack.name} comes from FLOGRAPH_PACKS; change that "
                    "variable to remove it")


def export_zip(pack: Pack, dest: Path) -> Path:
    """Write the pack to a .zip that `install` accepts, inside one folder."""
    dest = Path(dest)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(pack.root.rglob("*")):
            rel = path.relative_to(pack.root)
            if any(part in _SKIP_DIRS for part in rel.parts):
                continue
            if path.is_file():
                archive.write(path, f"{pack.id}/{rel.as_posix()}")
    return dest


# ------------------------------------------------------------- requirements

_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def missing_requirements(pack: Pack) -> list[str]:
    """The pack's requirements this interpreter does not satisfy.

    A version specifier is honoured when `packaging` is importable; without
    it only the name is checked, which errs on the side of saying nothing.
    """
    try:
        from packaging.requirements import InvalidRequirement, Requirement
    except ImportError:
        Requirement = None
    missing: list[str] = []
    for req in pack.requires:
        if Requirement is not None:
            try:
                parsed = Requirement(req)
            except InvalidRequirement:
                missing.append(req)
                continue
            if parsed.marker is not None and not parsed.marker.evaluate():
                continue
            try:
                have = importlib.metadata.version(parsed.name)
            except importlib.metadata.PackageNotFoundError:
                missing.append(req)
                continue
            if parsed.specifier and not parsed.specifier.contains(
                    have, prereleases=True):
                missing.append(req)
            continue
        match = _NAME_RE.match(req)
        if not match:
            missing.append(req)
            continue
        try:
            importlib.metadata.version(match.group(1))
        except importlib.metadata.PackageNotFoundError:
            missing.append(req)
    return missing


# ------------------------------------------------------------- import hook

class _EmptyLoader(importlib.abc.Loader):
    """Loader for a package that has no __init__.py of its own."""

    def create_module(self, spec):
        return None

    def exec_module(self, module) -> None:
        pass


class _PackFinder(importlib.abc.MetaPathFinder):
    """Maps ``flograph_packs.<id>`` onto that pack's ``lib/`` folder.

    Only the two top levels are this finder's: once
    ``flograph_packs.<id>`` exists with ``lib/`` as its search path, Python's
    own path finder resolves everything below it, so a pack's lib is an
    ordinary package in every other respect.
    """

    def __init__(self) -> None:
        self.libs: dict[str, Path] = {}

    def find_spec(self, fullname, path=None, target=None):
        if fullname == IMPORT_ROOT:
            spec = importlib.machinery.ModuleSpec(
                fullname, _EmptyLoader(), is_package=True)
            spec.submodule_search_locations = []
            return spec
        prefix = IMPORT_ROOT + "."
        if not fullname.startswith(prefix) or "." in fullname[len(prefix):]:
            return None
        lib = self.libs.get(fullname[len(prefix):])
        if lib is None:
            return None
        init = lib / "__init__.py"
        if init.is_file():
            return importlib.util.spec_from_file_location(
                fullname, init, submodule_search_locations=[str(lib)])
        spec = importlib.machinery.ModuleSpec(
            fullname, _EmptyLoader(), is_package=True)
        spec.submodule_search_locations = [str(lib)]
        return spec


_FINDER = _PackFinder()
#: every pack exposed this session, by id — what a save records about the
#: packs a flow used (see serialization.graph_to_dict)
_LOADED: dict[str, Pack] = {}


def loaded(pack_id: str) -> Optional[Pack]:
    return _LOADED.get(pack_id)


def used_by(type_ids: Iterable[str]) -> dict[str, dict]:
    """{pack id: {"name", "version"}} for the packs these node types need.

    Written into a saved flow so that, opened where a pack is missing, the
    placeholder can name the pack to install instead of an opaque type id.
    """
    out: dict[str, dict] = {}
    for type_id in type_ids:
        pack_id = pack_id_of(type_id)
        if pack_id is None or pack_id in out:
            continue
        pack = _LOADED.get(pack_id)
        out[pack_id] = ({"name": pack.name, "version": pack.version}
                        if pack else {"name": pack_id, "version": ""})
    return out


def missing_reason(type_id: str, recorded: Optional[dict] = None) -> str:
    """What a node of a pack this machine lacks says about itself."""
    pack_id = pack_id_of(type_id) or "?"
    info = (recorded or {}).get(pack_id) or {}
    name = info.get("name") or pack_id
    version = f" {info['version']}" if info.get("version") else ""
    if pack_id in _LOADED:
        return (f"The {name} pack is installed, but has no node "
                f"{type_id.rsplit('.', 1)[-1]!r} — it may have been renamed "
                f"or removed in this version of the pack.")
    return (f"Needs the {name}{version} node pack ({pack_id}), which is not "
            f"installed here. Add it from Tools ▸ Node Packs…, then reopen "
            f"the flow.")


def expose(packs: Iterable[Pack]) -> None:
    """Make each pack's ``lib/`` importable as ``flograph_packs.<id>``.

    Nothing is imported here: a pack's lib runs the first time a node's
    ``run()`` imports it. A pack already imported this session keeps the
    module it has — Python cannot unload one, and a model held by it is
    exactly what a reload must not throw away.
    """
    if _FINDER not in sys.meta_path:
        sys.meta_path.insert(0, _FINDER)
    for pack in packs:
        _LOADED[pack.id] = pack
        if pack.lib_dir.is_dir():
            _FINDER.libs[pack.id] = pack.lib_dir


def exposed_lib(pack_id: str) -> Optional[Path]:
    return _FINDER.libs.get(pack_id)
