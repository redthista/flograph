"""Portable, immutable file values. No Qt or filesystem dependency in readers."""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import PurePosixPath

FILES_PARAM = "_managed_files"
METADATA_PARAM = "_managed_metadata"
SYSTEM_COLUMNS = ("filename", "extension", "size_bytes", "source_modified", "imported_at", "edited_at")


def import_metadata(path=None):
    from datetime import datetime, timezone
    metadata = {"imported_at": datetime.now(timezone.utc).isoformat()}
    if path is not None:
        metadata["source_modified"] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    return metadata


def valid_name(name: str) -> str:
    if not name or name in (".", "..") or "/" in name or "\\" in name or ":" in name or "\x00" in name:
        raise ValueError("Choose a filename without folders or path separators")
    return name


@dataclass(frozen=True)
class ManagedFolder:
    """An immutable snapshot, safe to share between concurrent node bodies."""
    entries: tuple[tuple[str, bytes], ...] = ()
    metadata: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, "entries", tuple(self.entries))
        object.__setattr__(self, "metadata", tuple((n, tuple(values)) for n, values in self.metadata))
        names = set()
        for name, data in self.entries:
            valid_name(name)
            if name in names or not isinstance(data, bytes):
                raise ValueError("Folder entries need unique names and immutable bytes")
            names.add(name)
        for name, values in self.metadata:
            if name not in names:
                raise ValueError("Metadata must belong to a file in the folder")
            for key, value in values:
                if not isinstance(key, str) or not isinstance(value, (str, int, float, bool, type(None))):
                    raise ValueError("Metadata fields must have names and scalar values")

    @classmethod
    def from_params(cls, params):
        return cls(tuple((valid_name(n), base64.b64decode(v, validate=True))
                         for n, v in (params.get(FILES_PARAM) or {}).items()),
                   tuple((n, tuple(values.items())) for n, values in (params.get(METADATA_PARAM) or {}).items()
                         if n in (params.get(FILES_PARAM) or {})))

    def to_param(self):
        return {n: base64.b64encode(b).decode("ascii") for n, b in self.entries}

    def metadata_param(self):
        names = set(self.names())
        return {n: dict(values) for n, values in self.metadata if n in names}

    def metadata_for(self, name):
        return dict(dict(self.metadata).get(name, ()))

    def with_metadata(self, name, values):
        if name not in self.names():
            raise FileNotFoundError(name)
        for key, value in values.items():
            if key in ("filename", "extension", "size_bytes"):
                raise ValueError(f"{key} is calculated from the file")
            if not isinstance(value, (str, int, float, bool, type(None))):
                raise ValueError("Metadata values must be text, numbers, booleans or empty")
        meta = self.metadata_param()
        meta[name] = {**meta.get(name, {}), **values}
        return ManagedFolder(self.entries, tuple((n, tuple(v.items())) for n, v in meta.items()))

    def without(self, names):
        return ManagedFolder(tuple((n, b) for n, b in self.entries if n not in names),
                             tuple((n, v) for n, v in self.metadata if n not in names))

    def renamed(self, old, new):
        valid_name(new)
        if new in self.names():
            raise ValueError("A file with that name already exists")
        return ManagedFolder(tuple((new if n == old else n, b) for n, b in self.entries),
                             tuple((new if n == old else n, v) for n, v in self.metadata))

    def names(self):
        return tuple(n for n, _ in self.entries)

    def read_bytes(self, name):
        for n, data in self.entries:
            if n == name:
                return data
        raise FileNotFoundError(f"No file named {name!r} in the managed folder")

    def open(self, name, mode="rb", encoding="utf-8"):
        if mode == "rb":
            return io.BytesIO(self.read_bytes(name))
        if mode in ("r", "rt"):
            return io.StringIO(self.read_bytes(name).decode(encoding))
        raise ValueError("Managed folder inputs are read-only; use an Upload node")

    def with_file(self, name, data, *, replace=False, metadata=None):
        valid_name(name)
        if name in self.names() and not replace:
            raise ValueError(f"{name!r} already exists — enable Replace existing file")
        entries = dict(self.entries)
        entries[name] = bytes(data)
        meta = self.metadata_param()
        if metadata is not None and name in meta:
            meta[name] = {k: v for k, v in meta[name].items()
                          if k not in ("source_modified", "imported_at")}
        folder = ManagedFolder(tuple(entries.items()), tuple((n, tuple(v.items())) for n, v in meta.items()))
        return folder.with_metadata(name, metadata) if metadata else folder

    def merged(self, other):
        if not isinstance(other, ManagedFolder):
            raise TypeError("Connect a managed folder value to this input")
        entries = dict(self.entries)
        entries.update(other.entries)
        meta = self.metadata_param()
        other_metadata = other.metadata_param()
        for name in other.names():
            meta[name] = {**{k: v for k, v in meta.get(name, {}).items()
                             if k not in ("source_modified", "imported_at")},
                          **other_metadata.get(name, {})}
        return ManagedFolder(tuple(entries.items()), tuple((n, tuple(v.items())) for n, v in meta.items() if v))

    def file_table(self, fields=()):
        import pandas as pd
        metadata = self.metadata_param()
        rows = [{**metadata.get(n, {}), "filename": n, "extension": PurePosixPath(n).suffix,
                 "size_bytes": len(data)} for n, data in self.entries]
        columns = list(dict.fromkeys([*SYSTEM_COLUMNS, *fields, *(k for row in rows for k in row)]))
        return pd.DataFrame(rows).reindex(columns=columns)


def read_table(folder, name, *, format="auto", separator=",", sheet="", encoding="utf-8"):
    """Shared tabular reader for file readers and row-directed lookups."""
    import pandas as pd
    if not isinstance(folder, ManagedFolder):
        raise TypeError("Connect a Managed Folder to folder")
    fmt = format
    suffix = PurePosixPath(name).suffix.lower()
    compression = suffix if suffix in (".gz", ".bz2", ".xz", ".zip") else ""
    bare_name = name[:-len(compression)] if compression else name
    if fmt == "auto":
        fmt = {".csv": "csv", ".tsv": "csv", ".txt": "csv", ".psv": "csv",
               ".xlsx": "excel", ".xlsm": "excel", ".xls": "excel", ".xlsb": "excel",
               ".ods": "excel", ".odf": "excel", ".odt": "excel",
               ".json": "json", ".jsonl": "json", ".ndjson": "json",
               ".parquet": "parquet", ".pq": "parquet"}.get(PurePosixPath(bare_name).suffix.lower())
    raw = folder.read_bytes(name)
    if compression == ".gz":
        import gzip
        raw = gzip.decompress(raw)
    elif compression == ".bz2":
        import bz2
        raw = bz2.decompress(raw)
    elif compression == ".xz":
        import lzma
        raw = lzma.decompress(raw)
    elif compression == ".zip":
        import zipfile
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = [n for n in archive.namelist() if not n.endswith("/")]
            if len(members) != 1:
                raise ValueError("A compressed lookup ZIP must contain exactly one file")
            raw = archive.read(members[0])
    with io.BytesIO(raw) as stream:
        if fmt == "csv":
            if bare_name.lower().endswith(".tsv") and separator == ",":
                separator = "\t"
            if separator == "\\t":
                separator = "\t"
            if separator == "auto":
                return pd.read_csv(stream, sep=None, engine="python", encoding=encoding)
            return pd.read_csv(stream, sep=separator, encoding=encoding)
        if fmt == "excel":
            chosen_sheet = sheet if sheet not in (None, "") else 0
            engine = None
            if PurePosixPath(bare_name).suffix.lower() in (".xls", ".xlsb", ".ods"):
                from importlib.util import find_spec
                if find_spec("python_calamine") is not None:
                    engine = "calamine"
            with pd.ExcelFile(stream, engine=engine) as workbook:
                if (isinstance(chosen_sheet, str) and chosen_sheet.isdigit()
                        and chosen_sheet not in workbook.sheet_names):
                    chosen_sheet = int(chosen_sheet)
                return workbook.parse(sheet_name=chosen_sheet)
        if fmt == "json":
            return pd.read_json(stream, encoding=encoding,
                                lines=bare_name.lower().endswith((".jsonl", ".ndjson")))
        if fmt == "parquet":
            return pd.read_parquet(stream)
    raise ValueError(f"Cannot read {name!r} as a table; use CSV, Excel, JSON or Parquet")
