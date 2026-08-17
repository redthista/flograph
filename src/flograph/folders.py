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


def discover(folder: str, extensions: Sequence[str], include: str = "",
             exclude: str = "", skip_prefixes: Sequence[str] = ("~",)) -> list[str]:
    """The files to read, in a stable order.

    `skip_prefixes` defaults to Excel's `~$…` lock files, which look like
    real workbooks to a directory listing and fail to open like one.
    """
    if not folder:
        raise ValueError("no folder given")
    if not os.path.isdir(folder):
        raise ValueError(f"{folder!r} is not a folder")

    wanted = tuple(e.lower() for e in extensions)
    names = [
        name for name in os.listdir(folder)
        if os.path.isfile(os.path.join(folder, name))
        and meaningful_suffix(name) in wanted
        and not name.startswith(tuple(skip_prefixes))
    ]

    keep = patterns(include)
    if keep:
        names = [n for n in names
                 if any(fnmatch.fnmatch(n, pat) for pat in keep)]
    drop = patterns(exclude)
    if drop:
        names = [n for n in names
                 if not any(fnmatch.fnmatch(n, pat) for pat in drop)]

    # Sorted, so concatenating them is reproducible run to run. A folder
    # listing is in whatever order the filesystem feels like.
    names.sort()
    return [os.path.join(folder, name) for name in names]


def require_files(files: Sequence[str], folder: str, extensions: Sequence[str],
                  filtered: bool) -> None:
    """Fail with a message that says which of the two things went wrong."""
    if files:
        return
    if filtered:
        raise ValueError(
            f"no files left in {folder!r} after the include/exclude patterns "
            f"— looking for {', '.join(extensions)}")
    raise ValueError(
        f"no {' / '.join(extensions)} files in {folder!r}")


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


def stack(ctx, frames: list, files: Sequence[str], nrows: int = 0):
    """Concatenate the per-file frames and apply a total row cap."""
    import pandas as pd

    if not frames:
        raise ValueError(
            f"no rows read from the {len(files)} file(s) found")
    table = pd.concat(frames, ignore_index=True)
    if nrows and len(table) > nrows:
        # Each file was already capped at nrows where the reader could take a
        # limit, so trimming here leaves exactly the first nrows rows in file
        # order rather than a per-file slice of each.
        table = table.head(nrows).copy()
    ctx.progress(1.0)
    return table
