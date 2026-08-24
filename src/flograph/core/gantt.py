"""Gantt scheduling: turn a table of tasks — durations, dependency ids and
the odd pinned date — into concrete start and finish dates, so a task that
slips pushes everything downstream of it.

Qt-free and plotly-free on purpose. The Gantt node draws what this works
out, and the arithmetic is worth testing without a figure in the way.

Two conventions run through the whole module. **Finishes are exclusive**: a
one-day task starting Monday finishes at Tuesday 00:00, so its bar covers
Monday and its successor starts where it ended. And **working days count
whole days** — under that calendar a date is a date, times of day are
dropped, because "three working days" has no meaning at 14:30.
"""
from __future__ import annotations

from collections import deque

UNITS = ("days", "hours", "weeks")
CALENDAR_DAYS = "calendar days"
WORKING_DAYS = "working days (Mon-Fri)"
CALENDARS = (CALENDAR_DAYS, WORKING_DAYS)

# Business days per unit, for the working-days calendar. Hours are absent
# deliberately — see _advance.
_BUSINESS_PER_UNIT = {"days": 1, "weeks": 5}

SCHEDULE_COLUMNS = ["id", "task", "group", "start", "finish", "duration",
                    "progress", "depends_on", "is_milestone"]


def schedule(table, *, task, id=None, start=None, finish=None, duration=None,
             depends_on=None, progress=None, group=None,
             baseline_start=None, baseline_finish=None,
             unit="days", calendar=CALENDAR_DAYS, project_start=None):
    """Resolve every task's start and finish, returning a new DataFrame with
    one row per input row, in input order.

    Every keyword bar `task` names a column that may be absent — pass "" or
    None and that feature is simply not in play. `project_start` is an ISO
    date string (or anything pandas can read as a date), and only decides
    where tasks with neither a pinned start nor a predecessor begin.
    """
    import pandas as pd

    if unit not in UNITS:
        raise ValueError(f"duration unit must be one of {', '.join(UNITS)}")
    if calendar not in CALENDARS:
        raise ValueError(f"calendar must be one of {', '.join(CALENDARS)}")
    working = calendar == WORKING_DAYS
    if working and unit not in _BUSINESS_PER_UNIT:
        raise ValueError(
            f"the {WORKING_DAYS} calendar counts whole days — set the "
            f"duration unit to days or weeks, or use {CALENDAR_DAYS!r}")

    tasks = _column(table, task, "Task")
    if tasks is None:
        raise ValueError("a Gantt chart needs a Task column — the name that "
                         "labels each bar")
    tasks = [_text(v) for v in tasks]
    rows = len(tasks)

    durations = _numbers(_column(table, duration, "Duration"), "Duration")
    starts = _dates(_column(table, start, "Start"), "Start")
    finishes = _dates(_column(table, finish, "Finish"), "Finish")
    if durations is None and finishes is None:
        raise ValueError("a Gantt chart needs a Duration column or a Finish "
                         "column, so it can tell how long each task runs")

    ids = _ids(_column(table, id, "Task id"), tasks)
    preds = _dependencies(_column(table, depends_on, "Depends on"), ids, tasks)
    order = _topological(ids, preds, tasks)

    origin = _origin(project_start, starts, pd)
    if working:
        origin = _roll(origin, pd)

    resolved_start: dict[int, object] = {}
    resolved_finish: dict[int, object] = {}
    resolved_length: dict[int, float] = {}
    for i in order:
        pinned = starts[i] if starts else None
        if pinned is not None:
            begin = pinned
        elif preds[i]:
            begin = max(resolved_finish[j] for j in preds[i])
        else:
            begin = origin
        if working:
            begin = _roll(begin, pd)

        length = durations[i] if durations else None
        pinned_finish = finishes[i] if finishes else None
        if length is None and pinned_finish is not None:
            end = pinned_finish
            if end < begin:
                raise ValueError(
                    f"{tasks[i]!r} finishes {end:%Y-%m-%d} but cannot start "
                    f"until {begin:%Y-%m-%d} — check its dependencies")
            length = _span(begin, end, unit, working, pd)
        else:
            length = 0.0 if length is None else float(length)
            if length < 0:
                raise ValueError(
                    f"{tasks[i]!r} has a negative duration ({length:g})")
            end = _advance(begin, length, unit, working, pd)
        resolved_start[i] = begin
        resolved_finish[i] = end
        resolved_length[i] = length

    groups = _column(table, group, "Group")
    out = {
        "id": ids,
        "task": tasks,
        "group": [_text(v) for v in groups] if groups else [""] * rows,
        "start": [resolved_start[i] for i in range(rows)],
        "finish": [resolved_finish[i] for i in range(rows)],
        "duration": [resolved_length[i] for i in range(rows)],
        "progress": _progress(_column(table, progress, "Progress"), rows),
        "depends_on": [", ".join(ids[j] for j in preds[i])
                       for i in range(rows)],
        "is_milestone": [resolved_length[i] == 0 for i in range(rows)],
    }
    base_start = _dates(_column(table, baseline_start, "Baseline start"),
                        "Baseline start")
    base_finish = _dates(_column(table, baseline_finish, "Baseline finish"),
                         "Baseline finish")
    if base_start is not None or base_finish is not None:
        out["baseline_start"] = base_start or [None] * rows
        out["baseline_finish"] = base_finish or [None] * rows
    frame = pd.DataFrame(out)
    for column in ("start", "finish", "baseline_start", "baseline_finish"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column])
    return frame


# ---- reading the input ---------------------------------------------------

def _column(table, name, label):
    """The named column as a plain list, or None when no name was given."""
    name = (name or "").strip()
    if not name:
        return None
    if name not in table.columns:
        raise ValueError(f"{label} column {name!r} is not in the table")
    return list(table[name])


def _text(value):
    return "" if _blank(value) else str(value).strip()


def _blank(value):
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        # NaN and NaT, without importing pandas for a scalar test
        return bool(value != value)
    except (TypeError, ValueError):
        # pandas' NA refuses to become a bool at all, which is itself the
        # answer — an empty cell of a typed column arrives as one.
        return True


def _key(value):
    """A task id as text, so an id column pandas made a float still matches
    the same id typed into a depends-on cell."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _dates(values, label):
    if values is None:
        return None
    import pandas as pd

    out = []
    for value in values:
        if _blank(value):
            out.append(None)
            continue
        try:
            out.append(pd.Timestamp(value))
        except (ValueError, TypeError):
            raise ValueError(
                f"{label} is not a date: {value!r}") from None
    return out


def _numbers(values, label):
    if values is None:
        return None
    out = []
    for value in values:
        if _blank(value):
            out.append(None)
            continue
        try:
            out.append(float(value))
        except (ValueError, TypeError):
            raise ValueError(
                f"{label} is not a number: {value!r}") from None
    return out


def _progress(values, rows):
    """0..1 per task. A column whose largest value is over 1 is read as a
    percentage — the whole column, not value by value, so a mixed column
    cannot mean two different things in two rows."""
    if values is None:
        return [None] * rows
    numbers = _numbers(values, "Progress")
    scale = 100.0 if any(v is not None and v > 1 for v in numbers) else 1.0
    return [None if v is None else min(max(v / scale, 0.0), 1.0)
            for v in numbers]


def _ids(values, tasks):
    ids = [_key(v) for v in values] if values else list(tasks)
    seen = {}
    for i, tid in enumerate(ids):
        if not tid:
            raise ValueError(f"{tasks[i]!r} has no task id — a blank id "
                             f"cannot be depended on")
        if tid in seen:
            raise ValueError(
                f"two tasks share the id {tid!r} ({tasks[seen[tid]]!r} and "
                f"{tasks[i]!r}) — dependencies could not tell them apart")
        seen[tid] = i
    return ids


def _dependencies(values, ids, tasks):
    """Per row, the row indices it waits for. Ids are resolved here so a
    typo is reported against the task that made it."""
    index = {tid: i for i, tid in enumerate(ids)}
    preds = []
    for i in range(len(ids)):
        # A one-dependency column can arrive numeric, in which case pandas
        # may have made it a float — _key puts it back the way an id reads.
        raw = None if values is None else values[i]
        cell = "" if _blank(raw) else (
            raw.strip() if isinstance(raw, str) else _key(raw))
        seen = []
        for key in (_key(part) for part in cell.split(",") if part.strip()):
            if key not in index:
                raise ValueError(
                    f"{tasks[i]!r} depends on {key!r}, which is not a task "
                    f"id in this table")
            if index[key] not in seen:
                seen.append(index[key])
        preds.append(seen)
    return preds


def _topological(ids, preds, tasks):
    """Row indices in an order where every task follows its predecessors."""
    successors: dict[int, list[int]] = {i: [] for i in range(len(ids))}
    indegree = [len(p) for p in preds]
    for i, parents in enumerate(preds):
        for j in parents:
            successors[j].append(i)
    queue = deque(i for i in range(len(ids)) if indegree[i] == 0)
    order = []
    while queue:
        i = queue.popleft()
        order.append(i)
        for j in successors[i]:
            indegree[j] -= 1
            if indegree[j] == 0:
                queue.append(j)
    if len(order) < len(ids):
        done = set(order)
        stuck = [tasks[i] for i in range(len(ids)) if i not in done]
        raise ValueError("these tasks depend on each other in a circle, so "
                         "none of them can start: " + ", ".join(stuck))
    return order


# ---- date arithmetic -----------------------------------------------------

def _origin(project_start, starts, pd):
    """Where a task with no pinned start and no predecessor begins."""
    if not _blank(project_start):
        try:
            return pd.Timestamp(project_start)
        except (ValueError, TypeError):
            raise ValueError(
                f"Project start is not a date: {project_start!r}") from None
    pinned = [s for s in (starts or []) if s is not None]
    return min(pinned) if pinned else pd.Timestamp.now().normalize()


def _roll(when, pd):
    """The same day, or the next working day when it lands on a weekend."""
    import numpy as np

    day = np.busday_offset(when.to_numpy().astype("datetime64[D]"), 0,
                           roll="forward")
    return pd.Timestamp(day)


def _advance(begin, length, unit, working, pd):
    if working:
        import numpy as np

        days = int(round(length * _BUSINESS_PER_UNIT[unit]))
        day = np.busday_offset(begin.to_numpy().astype("datetime64[D]"),
                               days, roll="forward")
        return pd.Timestamp(day)
    return begin + pd.Timedelta(**{unit: length})


def _span(begin, end, unit, working, pd):
    """How long `begin`..`end` is, in `unit`."""
    if working:
        import numpy as np

        days = int(np.busday_count(begin.to_numpy().astype("datetime64[D]"),
                                   end.to_numpy().astype("datetime64[D]")))
        return days / _BUSINESS_PER_UNIT[unit]
    return (end - begin) / pd.Timedelta(**{unit: 1})
