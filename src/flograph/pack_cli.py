"""`flograph pack ...` — manage node packs without the GUI.

    flograph pack list                      every pack this machine can see
    flograph pack install PACK.zip|FOLDER   copy a pack in (--replace to update)
    flograph pack link FOLDER               use a pack (or folder of packs) in place
    flograph pack unlink FOLDER             stop using a linked folder
    flograph pack remove ID                 uninstall (or unlink) a pack
    flograph pack export ID OUT.zip         write a pack to a shareable .zip
    flograph pack enable|disable ID         keep a pack but hide its nodes

Qt-free, like everything in core.packs it drives. The Node Packs dialog
(Tools ▸ Node Packs…) does the same from the window.
"""
from __future__ import annotations

import sys
from pathlib import Path

from flograph.core import packs
from flograph.paths import user_data_dir


def _find(pack_id: str) -> packs.Pack:
    found, _errors = packs.discover(user_data_dir())
    for pack in found:
        if pack.id == pack_id:
            return pack
    raise packs.PackError(f"no pack with id {pack_id!r} (try: flograph pack list)")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    cmd, rest = argv[0], argv[1:]
    user_dir = user_data_dir()
    try:
        if cmd == "list":
            found, errors = packs.discover(user_dir)
            disabled = set(packs.load_config(user_dir)["disabled"])
            if not found:
                print("no node packs")
            for pack in found:
                state = " (disabled)" if pack.id in disabled else ""
                missing = packs.missing_requirements(pack)
                print(f"{pack.id:24} {pack.version:10} {pack.name}{state}")
                print(f"{'':24} {pack.source}: {pack.root}")
                print(f"{'':24} {len(pack.node_files())} nodes")
                if missing:
                    print(f"{'':24} missing: {' '.join(missing)}")
            for path, err in errors:
                print(f"error: {path}: {err}", file=sys.stderr)
            return 0
        if cmd == "install" and rest:
            pack = packs.install(user_dir, Path(rest[0]),
                                 replace="--replace" in rest[1:])
            print(f"installed {pack.name} {pack.version} -> {pack.root}")
            missing = packs.missing_requirements(pack)
            if missing:
                print("it needs: " + " ".join(missing))
            return 0
        if cmd == "link" and rest:
            for pack in packs.link(user_dir, Path(rest[0])):
                print(f"linked {pack.name} {pack.version} ({pack.root})")
            return 0
        if cmd == "unlink" and rest:
            packs.unlink(user_dir, Path(rest[0]))
            print(f"unlinked {rest[0]}")
            return 0
        if cmd == "remove" and rest:
            pack = _find(rest[0])
            packs.uninstall(user_dir, pack)
            print(f"removed {pack.name}")
            return 0
        if cmd == "export" and len(rest) >= 2:
            out = packs.export_zip(_find(rest[0]), Path(rest[1]))
            print(f"wrote {out}")
            return 0
        if cmd in ("enable", "disable") and rest:
            _find(rest[0])
            packs.set_enabled(user_dir, rest[0], cmd == "enable")
            print(f"{cmd}d {rest[0]}")
            return 0
    except packs.PackExistsError as exc:
        print(f"{exc} — add --replace to update it", file=sys.stderr)
        return 1
    except (packs.PackError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(__doc__.strip(), file=sys.stderr)
    return 2
