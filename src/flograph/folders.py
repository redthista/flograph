"""Reading a whole folder of files as one table.

Shared by the `Read … (Folder)` nodes. Node scripts normally keep their own
copies of small helpers — the readers each carry their own `_mapping`, and
that is deliberate, since a node is a script someone may open and edit. This
is the other kind: folder scanning, glob filtering and the ordered parallel
read are one behaviour that all three folder nodes must agree on exactly,
and three copies of it would drift.
"""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

# Peeled off before a file's real extension is considered, so "sales.csv.gz"
# is a CSV rather than an unknown ".gz".
COMPRESSION_SUFFIXES = frozenset({".gz", ".zip", ".bz2", ".xz", ".zst", ".zstd"})

# Readers that hold the GIL throughout, measured rather than assumed:
# openpyxl is pure Python (four workbooks took 6.9s serial and 7.5s across
# four threads — threads made it *worse*), and fastparquet is largely Python
# too (1.14x). Everything else measured at 2x or better on four threads, or
# is already so fast that the difference is thread-creation noise. Auto only
# declines to overlap for the ones on this list, since there the threads buy
# nothing and each one still holds a whole file's worth of memory.
GIL_BOUND_ENGINES = frozenset({"openpyxl", "fastparquet", "python"})

# A folder read holds several files in memory at once, so auto stays modest
# regardless of core count — the machine's memory is the binding constraint
# here, not its CPUs. Someone who knows their data can raise it.
MAX_AUTO_PARALLEL = 4


def patterns(raw: str | None) -> list[str]:
    """Comma-separated globs -> list, ignoring blanks."""
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def meaningful_suffix(name: str) -> str:
    """The extension that says what the file is, ignoring compression."""
    suffixes = Path(name).suffixes
    while suffixes and suffixes[-1].lower() in COMPRESSION_SUFFIXES:
        suffixes.pop()
    return suffixes[-1].lower() if suffixes else ""


def normalise_letter_range(spec: str) -> str:
    """Make a pandas `usecols` string fastexcel will also take.

    fastexcel understands the whole spelling — `A:C`, `A:C,F`, `A,C`,
    `A:C,E:F` — with one exception: a range whose ends are the same column
    ("A:A") is rejected as an empty range, where pandas reads it as that one
    column. Collapsing those leaves the two engines accepting the same input.
    """
    parts = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        match = re.fullmatch(r"([A-Za-z]+):([A-Za-z]+)", part)
        if match and match.group(1).upper() == match.group(2).upper():
            part = match.group(1)
        parts.append(part)
    return ",".join(parts)


def _matches(value: str, pats: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(value, pat) for pat in pats)


def _dir_matches(rel: str, name: str, pats: Sequence[str]) -> bool:
    """A folder pattern matches its path below the root, or its own name.

    `fnmatch`'s `*` crosses `/`, so `2023*` covers everything under `2023`,
    while a bare `q1` matches a folder of that name at any depth.
    """
    return _matches(rel, pats) or _matches(name, pats)


def _file_matches(rel: str, name: str, pats: Sequence[str]) -> bool:
    """A file pattern with a `/` in it is about the path; otherwise the name."""
    return any(fnmatch.fnmatch(rel if "/" in pat else name, pat) for pat in pats)


def _walk(folder: str, recursive: bool, skip_prefixes: tuple[str, ...],
          drop_dirs: Sequence[str]) -> Iterator[tuple[str, list[str]]]:
    """Yield `(folder relative to the root, file names in it)`.

    The root itself is `"."`. Excluded folders are pruned from `os.walk`'s
    own list, which is the documented way to skip a whole subtree rather
    than walking it and throwing the results away.
    """
    if not recursive:
        yield ".", os.listdir(folder)
        return
    for root, dirnames, filenames in os.walk(folder):
        rel = os.path.relpath(root, folder).replace(os.sep, "/")
        dirnames[:] = sorted(
            name for name in dirnames
            if not name.startswith(skip_prefixes)
            and not (drop_dirs and _dir_matches(
                name if rel == "." else f"{rel}/{name}", name, drop_dirs)))
        yield rel, filenames


def discover(folder: str, extensions: Sequence[str], include: str = "",
             exclude: str = "", skip_prefixes: Sequence[str] = ("~",),
             recursive: bool = False, include_dirs: str = "",
             exclude_dirs: str = "") -> list[str]:
    """The files to read, in a stable order.

    `skip_prefixes` defaults to Excel's `~$…` lock files, which look like
    real workbooks to a directory listing and fail to open like one.

    With `recursive`, subfolders are searched too. `include_dirs` keeps only
    the folders that match (blank keeps all of them) and `exclude_dirs`
    drops a folder together with everything under it; both are matched by
    `_dir_matches`. The file patterns are unchanged — matched against the
    file's name, or against its path below the root when the pattern itself
    contains a `/`.
    """
    if not folder:
        raise ValueError("no folder given")
    if not os.path.isdir(folder):
        raise ValueError(f"{folder!r} is not a folder")

    wanted = tuple(e.lower() for e in extensions)
    skip = tuple(skip_prefixes)
    keep, drop = patterns(include), patterns(exclude)
    keep_dirs, drop_dirs = patterns(include_dirs), patterns(exclude_dirs)

    found = []
    for rel_dir, names in _walk(folder, recursive, skip, drop_dirs):
        if keep_dirs and not _dir_matches(rel_dir, os.path.basename(rel_dir)
                                          or rel_dir, keep_dirs):
            continue
        for name in names:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            if (meaningful_suffix(name) not in wanted
                    or name.startswith(skip)
                    or not os.path.isfile(os.path.join(folder, *rel.split("/")))):
                continue
            if keep and not _file_matches(rel, name, keep):
                continue
            if drop and _file_matches(rel, name, drop):
                continue
            found.append(rel)

    # Sorted, so concatenating them is reproducible run to run. A folder
    # listing is in whatever order the filesystem feels like, and sorting on
    # the relative path keeps each subfolder's files together.
    found.sort()
    return [os.path.join(folder, *rel.split("/")) for rel in found]


def relative_folder(path: str, folder: str) -> str:
    """Which folder below the root a file came from; `"."` for the root."""
    return os.path.relpath(
        os.path.dirname(os.path.abspath(path)),
        os.path.abspath(folder)).replace(os.sep, "/")


def require_files(files: Sequence[str], folder: str, extensions: Sequence[str],
                  filtered: bool, recursive: bool = False) -> None:
    """Fail with a message that says which of the two things went wrong."""
    if files:
        return
    where = f"{folder!r}" + (" or its subfolders" if recursive else "")
    if filtered:
        raise ValueError(
            f"no files left in {where} after the include/exclude patterns "
            f"— looking for {', '.join(extensions)}")
    raise ValueError(
        f"no {' / '.join(extensions)} files in {where}")


def worker_count(requested: Any, engine: str, file_count: int) -> int:
    """How many files to read at once. 0/blank = decide from the engine."""
    wanted = int(requested or 0)
    if wanted > 0:
        return max(1, min(wanted, file_count))
    if engine in GIL_BOUND_ENGINES:
        return 1
    return max(1, min(MAX_AUTO_PARALLEL, os.cpu_count() or 1, file_count))


def read_files(ctx, files: Sequence[str], read_one: Callable[[str], Any],
               workers: int) -> Iterator[tuple[str, Any]]:
    """Yield `(path, read_one(path))` for every file, in *file* order.

    Ordered whatever order the threads finish in, so the table a folder
    produces does not depend on which disk was quicker today. Progress and
    logging happen on the consuming side only: RunContext.progress keeps
    unlocked throttle state, and the workers have no business touching it.
    """
    from concurrent.futures import ThreadPoolExecutor

    total = len(files)
    if workers <= 1:
        for index, path in enumerate(files):
            ctx.check_cancelled()
            ctx.progress(index / total)
            ctx.log(f"  {os.path.basename(path)} ({index + 1}/{total})")
            yield path, read_one(path)
        return

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(read_one, path) for path in files]
        try:
            for index, (path, future) in enumerate(zip(files, futures)):
                ctx.check_cancelled()
                result = future.result()
                ctx.progress(index / total)
                ctx.log(f"  {os.path.basename(path)} ({index + 1}/{total})")
                yield path, result
        except BaseException:
            # Cancel is a real button, and a failed file should not leave
            # three more workbooks still parsing behind the error.
            for future in futures:
                future.cancel()
            raise


def cap_rows(frame, nrows: int):
    """Keep at most `nrows` rows of one file's frame.

    The row cap is per file, not a cap on the stack: reading 200 rows of
    each of twelve monthly exports is a sample of the year, where the first
    200 rows of the stack is January and nothing else. Most readers push the
    limit into the read itself, which is cheaper and gives the same answer —
    this trims whatever came back over the line anyway, so every path ends
    up honouring the setting even where the underlying reader takes no
    limit (pandas reading Parquet).
    """
    if nrows and len(frame) > nrows:
        return frame.head(nrows).copy()
    return frame


def stack(ctx, frames: list, files: Sequence[str]):
    """Concatenate the per-file frames.

    No row cap here — see cap_rows, which the callers apply per file as each
    one arrives.
    """
    import pandas as pd

    if not frames:
        raise ValueError(
            f"no rows read from the {len(files)} file(s) found")
    table = pd.concat(frames, ignore_index=True)
    ctx.progress(1.0)
    return table
