"""How much trouble the machine's memory is in, and what to do about it.

Kept apart from the resource monitor on purpose. That widget answers a
*blame* question — "is this project the reason the machine is filling up" —
which is right for a warning aimed at the person who built the flow, and
wrong for the engine: at the point the machine is about to start thrashing it
does not matter whose fault it is, and a flow holding a modest share can
still be the last straw. This module answers "is the machine in trouble",
full stop, and the monitor builds its blame question on top of it.

The functions are pure and take plain numbers, so the policy can be tested
without allocating anything or having a particular machine.

Why the ratio is not enough on its own: 85% of 128 GB leaves 19 GB free and
nothing is wrong, while 85% of an 8 GB laptop is nothing left at all. A tool
that nags the big machine is a tool that gets in the way of being powerful,
which is the opposite of the point. So headroom decides first and the ratio
only breaks the tie in the middle.
"""
from __future__ import annotations

# Levels, in increasing order of trouble.
CALM, TIGHT, CRITICAL = 0, 1, 2

SYSTEM_PRESSURE = 0.85            # fraction in use, once headroom is gone
PRESSURE_RELIEF = 0.05            # how far it must fall to stop warning
COMFORT_FREE = 8 * 1024 ** 3      # this much still free: the machine is fine
LOW_FREE = 1536 * 1024 ** 2       # this little left: tight on any machine
CRITICAL_FREE = 768 * 1024 ** 2   # this little left: stop making it worse
FREE_RELIEF = 512 * 1024 ** 2     # hysteresis for the byte thresholds


def machine_is_tight(used: int, total: int, available: int,
                     already_warning: bool = False) -> bool:
    """Is the machine short of memory? Says nothing about whose fault it is.

    Plenty free is fine whatever the ratio; nearly nothing free is tight
    whatever the ratio; in between, the ratio decides.
    """
    if total <= 0:
        return False
    slack = FREE_RELIEF if already_warning else 0
    if available <= LOW_FREE + slack:
        return True
    if available > COMFORT_FREE + slack:
        return False
    line = SYSTEM_PRESSURE - (PRESSURE_RELIEF if already_warning else 0.0)
    return used / total >= line


def pressure_level(used: int, total: int, available: int,
                   current: int = CALM) -> int:
    """CALM, TIGHT or CRITICAL, with hysteresis via `current`.

    CRITICAL is deliberately an absolute: a machine with a few hundred MB
    left is in trouble at any size, and a fraction cannot say that.
    """
    if total <= 0:
        return CALM
    slack = FREE_RELIEF if current >= CRITICAL else 0
    if available <= CRITICAL_FREE + slack:
        return CRITICAL
    if machine_is_tight(used, total, available, already_warning=current >= TIGHT):
        return TIGHT
    return CALM


def worker_cap(base: int, level: int, explicit: bool = False) -> int:
    """How many nodes may run at once at this level.

    **Never returns 0.** A limit of nothing is not "run slowly", it is a
    dispatch loop that starts nothing, finds nothing running, concludes the
    run is over and reports success having executed the plan not at all.

    An `explicit` worker count — one the user typed into Settings — is
    honoured until things are actually critical. Somebody who chose a number
    should get it, and it keeps a machine that is merely busy from silently
    contradicting the setting.
    """
    base = max(1, base)
    if level >= CRITICAL:
        return 1
    if level >= TIGHT and not explicit:
        return max(1, base // 2)
    return base


def read_memory() -> tuple[int, int, int]:
    """`(used, total, available)` for this machine, or zeroes.

    `available` is the figure to reason with: it is the only one that means
    the same thing on Windows, macOS and Linux. `used` means three different
    things across them — Linux already excludes reclaimable page cache, and
    Windows simply defines used as total minus available.

    Degrades to zeroes rather than raising, on the same principle as
    runstats.ProcessSampler: a memory reading is never worth an exception,
    and `total = 0` reads as CALM everywhere above.
    """
    try:
        import psutil
        vm = psutil.virtual_memory()
        return int(vm.used), int(vm.total), int(vm.available)
    except Exception:
        return 0, 0, 0
