"""A .flograph project file is one of two things on disk:

  * **plain JSON** — the graph alone, byte-identical to what flograph has
    always written. This is what a save produces when the user has turned
    *Settings ▸ General ▸ Saving ▸ Include cached results in the project
    file* off.
  * **a zip bundle** — ``project.json`` plus a ``cache/`` tree (the
    manifest, one pickle blob per cached node, and the run history). This
    is the default: one file you can hand to someone, cached results and
    all.

``core.serialization.load`` sniffs the first bytes and dispatches; this
module owns the bundle side. Two properties the sidecar-folder design had
are kept:

  * **Lazy open.** ``BundleReader`` reads only the zip's central directory,
    so opening a project still touches one small manifest and inflates no
    blob — a node's output is pulled from its member only when something
    asks for it (see ``engine.cache_persistence``).
  * **Crash safety.** ``BundleWriter`` builds the whole archive in a
    sibling ``<name>.tmp`` and swaps it in with ``os.replace`` only once
    ``commit()`` has been called and the archive closed cleanly. A crash
    mid-write leaves the previous file untouched — there is no
    half-written state to recover, which is simpler than the per-blob
    atomicity the folder needed.

Blobs are stored, not deflated: the pickles they hold are already
zlib-framed when cache compression is on (the reader sniffs each one — a
pickle starts ``0x80``, a zlib stream never does), and deflating an
incompressible stream a second time only burns CPU. The small JSON members
are deflated.
"""
from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import IO, Any

#: First four bytes of every zip file (local file header signature).
ZIP_MAGIC = b"PK\x03\x04"

PROJECT_MEMBER = "project.json"
CACHE_PREFIX = "cache/"
MANIFEST_MEMBER = "cache/manifest.json"
RUNS_MEMBER = "cache/runs.json"


def blob_member(node_id: str) -> str:
    """The archive member holding one node's cached output. Node ids are
    already constrained to what a filename allows (the folder layout used
    ``<id>.pkl`` too), so no escaping is needed."""
    return f"{CACHE_PREFIX}{node_id}.pkl"


def blob_node_id(member: str) -> str:
    """Inverse of :func:`blob_member`."""
    return member[len(CACHE_PREFIX):-len(".pkl")]


def is_bundle(path: str | Path) -> bool:
    """True if `path` is a zip bundle rather than plain JSON.

    A missing or unreadable file is not a bundle — the caller falls through
    to the JSON path, which raises the error the user should see."""
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == ZIP_MAGIC
    except OSError:
        return False


class BundleReader:
    """Random-access reader over a .flograph zip bundle.

    Cheap to open — only the central directory is read. Use as a context
    manager or call :meth:`close`. Every accessor returns ``None`` / a
    falsy value for a missing member rather than raising: a bundle written
    by a newer build, or one whose cache half was stripped on a
    save-without-cache, still has to open.
    """

    def __init__(self, path: str | Path) -> None:
        self._zip = zipfile.ZipFile(path, "r")
        self._names = set(self._zip.namelist())

    def __enter__(self) -> "BundleReader":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self._zip.close()

    def has(self, member: str) -> bool:
        return member in self._names

    def read_bytes(self, member: str) -> "bytes | None":
        if member not in self._names:
            return None
        with self._zip.open(member) as fh:
            return fh.read()

    def read_text(self, member: str) -> "str | None":
        data = self.read_bytes(member)
        return None if data is None else data.decode("utf-8")

    def open(self, member: str) -> IO[bytes]:
        """A streaming read handle for one member — for copying a blob into
        a new bundle without holding it in memory. Raises ``KeyError`` if
        the member is absent; callers that might ask for a missing blob
        check :meth:`has` first."""
        return self._zip.open(member)

    def blob_members(self) -> list[str]:
        return sorted(n for n in self._names
                      if n.startswith(CACHE_PREFIX) and n.endswith(".pkl"))

    def stored_size(self, member: str) -> int:
        """Bytes this member occupies in the archive, or 0 if absent — for
        the resource monitor's on-disk cache figure."""
        try:
            return self._zip.getinfo(member).compress_size
        except KeyError:
            return 0


class BundleWriter:
    """Builds a .flograph bundle in ``<path>.tmp`` and swaps it in on
    :meth:`commit` plus a clean close.

    Members go in in order: ``project.json``, then each blob, then the
    manifest and run history. A blob is either streamed in by the caller
    (:meth:`open_blob`) or byte-copied from a previous bundle
    (:meth:`copy_blob`) — the copy path is what keeps a save whose cache
    has not changed from re-pickling gigabytes.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._tmp = self._path.with_name(self._path.name + ".tmp")
        self._zip: "zipfile.ZipFile | None" = None
        self._committed = False

    def __enter__(self) -> "BundleWriter":
        self._zip = zipfile.ZipFile(
            self._tmp, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True)
        return self

    def __exit__(self, exc_type: Any, *rest: Any) -> None:
        assert self._zip is not None
        self._zip.close()
        if exc_type is None and self._committed:
            os.replace(self._tmp, self._path)
        else:
            self._tmp.unlink(missing_ok=True)

    # -- JSON members ----------------------------------------------------

    def write_project(self, data: dict) -> None:
        assert self._zip is not None
        self._zip.writestr(PROJECT_MEMBER, json.dumps(data, indent=2))

    def write_manifest(self, manifest: dict) -> None:
        assert self._zip is not None
        self._zip.writestr(MANIFEST_MEMBER, json.dumps(manifest, indent=2))

    def write_runs(self, payload: dict) -> None:
        assert self._zip is not None
        self._zip.writestr(RUNS_MEMBER, json.dumps(payload))

    # -- blobs ---------------------------------------------------------

    def open_blob(self, node_id: str) -> IO[bytes]:
        """A writable stream for one node's blob, stored uncompressed. The
        caller streams the (already zlib-framed, when compression is on)
        pickle into it. Only one blob stream may be open at a time."""
        assert self._zip is not None
        info = zipfile.ZipInfo(blob_member(node_id))
        info.compress_type = zipfile.ZIP_STORED
        return self._zip.open(info, "w")

    def copy_blob(self, source: IO[bytes], node_id: str) -> int:
        """Stream an existing blob in unchanged. Returns bytes written."""
        written = 0
        with self.open_blob(node_id) as dst:
            while True:
                chunk = source.read(1 << 20)
                if not chunk:
                    break
                dst.write(chunk)
                written += len(chunk)
        return written

    def commit(self) -> None:
        """Mark the archive complete. Without this the ``.tmp`` is discarded
        on close and the previous file is left in place."""
        self._committed = True
