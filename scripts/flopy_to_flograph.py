#!/usr/bin/env python3
"""Migrate legacy ``.flopy`` project files to the renamed ``.flograph`` format.

The project was renamed flopy -> flograph (the name ``flopy`` is taken on PyPI
by USGS MODFLOW). The rename is a clean break with no in-app backward
compatibility, so this one-shot tool upgrades any projects saved by the old
build:

  * builtin node type-ids ``flopy.<sub>.<name>`` -> ``flograph.<sub>.<name>``
    (``user.*`` and any other prefixes are left untouched);
  * the informational ``flopy_version`` key -> ``flograph_version``;
  * the file itself ``<name>.flopy`` -> ``<name>.flograph``;
  * the side-car cache dir ``<name>.flopy.cache/`` -> ``<name>.flograph.cache/``.

Standalone and stdlib-only on purpose: it does not import the ``flograph``
package, so it runs against old files in any environment.

Usage::

    python scripts/flopy_to_flograph.py project.flopy
    python scripts/flopy_to_flograph.py path/to/dir --recursive
    python scripts/flopy_to_flograph.py project.flopy --delete-original
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LEGACY_PREFIX = "flopy."
NEW_PREFIX = "flograph."


def convert_project_data(data: dict) -> tuple[dict, int]:
    """Return a rewritten copy of a project dict and the number of builtin
    node type-ids that were re-prefixed. Non-``flopy.*`` type-ids (notably
    ``user.*``) are preserved verbatim."""
    rewritten = 0
    if "flopy_version" in data and "flograph_version" not in data:
        data["flograph_version"] = data.pop("flopy_version")
    graph = data.get("graph")
    if isinstance(graph, dict):
        for node in graph.get("nodes", []):
            type_id = node.get("type")
            if isinstance(type_id, str) and type_id.startswith(LEGACY_PREFIX):
                node["type"] = NEW_PREFIX + type_id[len(LEGACY_PREFIX):]
                rewritten += 1
    return data, rewritten


def _new_path(path: Path) -> Path:
    # only the trailing ".flopy" suffix is swapped; the stem is preserved even
    # if it happens to contain the substring "flopy".
    return path.with_name(path.name[: -len(".flopy")] + ".flograph")


def convert_file(path: Path, *, delete_original: bool = False) -> tuple[Path, int]:
    """Convert one ``.flopy`` file, writing a sibling ``.flograph`` file and
    renaming any ``.flopy.cache`` side-car. Returns (output_path, type_ids
    rewritten)."""
    data = json.loads(path.read_text())
    data, rewritten = convert_project_data(data)
    out_path = _new_path(path)
    out_path.write_text(json.dumps(data, indent=2))

    old_cache = path.with_name(path.name + ".cache")
    if old_cache.is_dir():
        new_cache = out_path.with_name(out_path.name + ".cache")
        if not new_cache.exists():
            old_cache.rename(new_cache)

    if delete_original:
        path.unlink()

    return out_path, rewritten


def _iter_projects(paths: list[Path], recursive: bool):
    for p in paths:
        if p.is_dir():
            yield from sorted(p.rglob("*.flopy") if recursive else p.glob("*.flopy"))
        else:
            yield p


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path,
                        help="`.flopy` files and/or directories to convert")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="recurse into directories looking for `.flopy` files")
    parser.add_argument("--delete-original", action="store_true",
                        help="delete each source `.flopy` after converting it")
    args = parser.parse_args(argv)

    files = 0
    total_ids = 0
    errors = 0
    for project in _iter_projects(args.paths, args.recursive):
        if project.suffix != ".flopy":
            print(f"skip (not a .flopy file): {project}", file=sys.stderr)
            continue
        try:
            out_path, rewritten = convert_file(
                project, delete_original=args.delete_original)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"error: {project}: {exc}", file=sys.stderr)
            errors += 1
            continue
        files += 1
        total_ids += rewritten
        print(f"converted {project} -> {out_path} ({rewritten} type-ids rewritten)")

    print(f"\n{files} file(s) converted, {total_ids} type-id(s) rewritten, "
          f"{errors} error(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
