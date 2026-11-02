#!/usr/bin/env python3
"""Run the test suite with as many workers as the machine can spare.

The suite is happiest at `-n12`, and that is fine on an idle machine. It is
not fine on a machine that is doing something else: twelve workers peg every
core for minutes, and the first time anyone noticed was the CPU running hot
while a game was in the foreground.

So decide at launch instead of picking a number once and living with it.
Three signals, checked before starting the run:

* **Load average** says how much of the machine is already spoken for.
  Workers are drawn from what is *left*, not from the core count.
* **Available memory** caps workers at roughly 3 GiB each. On Linux with
  a user systemd manager, the entire run is limited to 60% of available RAM
  or half of total RAM, whichever is smaller, with swap disabled.
* **CPU temperature** says whether the machine can afford the work at all.
  A hot chip will thermal-throttle under a parallel run anyway, so backing
  off there costs less wall-clock than it looks like it should.

It also runs at `nice -n 19` by default, which is what actually keeps a game
playable: the tests get the cores nobody else wants, and yield the moment
anything else does want them.

    scripts/run_tests.py                     # whole suite, adaptively
    scripts/run_tests.py tests/test_x.py -q  # extra args go to pytest
    scripts/run_tests.py --workers 12        # override the decision
    scripts/run_tests.py --explain           # decide and print, run nothing
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

#: Most workers we will ever ask for. Past this the suite stops getting
#: faster — one module (`test_frames.py`) is the long pole on a single
#: worker — so the extra processes are heat with nothing to show for it.
MAX_WORKERS = 12

GIB = 1024 ** 3
# flograph issue #95: leave room for the desktop and pytest controller.
WORKER_BYTES = 3 * GIB
CONTROLLER_BYTES = GIB // 2

#: Fraction of the *spare* cores to take. Deliberately under 1: load average
#: is a trailing number, and whatever produced it is usually about to ask
#: for more.
SHARE = 0.75

#: CPU temperatures, in °C. At WARM we halve; at HOT we go serial. These are
#: about the machine being *already* hot — a run that starts cool and heats
#: up is what `nice` is for.
WARM_C = 75.0
HOT_C = 85.0

#: hwmon chips that report a real CPU temperature, best first. `acpitz` is
#: deliberately absent: it exists on this machine and reads 16°C while the
#: CPU is at 80°C, which is worse than having no reading at all.
CPU_SENSORS = ("k10temp", "coretemp", "zenpower", "cpu_thermal")


def cpu_temperature() -> "float | None":
    """The CPU's temperature in °C, or None if nothing trustworthy says."""
    chips: dict[str, float] = {}
    for hwmon in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        try:
            name = (hwmon / "name").read_text().strip()
        except OSError:
            continue
        if name not in CPU_SENSORS:
            continue
        readings = []
        for probe in sorted(hwmon.glob("temp*_input")):
            try:
                readings.append(int(probe.read_text().strip()) / 1000.0)
            except (OSError, ValueError):
                continue
        # The hottest probe on the package is the one that throttles.
        if readings:
            chips[name] = max(readings)
    for name in CPU_SENSORS:
        if name in chips:
            return chips[name]
    return None


def decide(cores: int, load: float, temp: "float | None",
           cap: int = MAX_WORKERS) -> "tuple[int, str]":
    """How many workers, and the one-line reason to print."""
    spare = max(0.0, cores - load)
    workers = max(1, min(cap, int(spare * SHARE)))
    why = (f"{cores} cores, load {load:.1f} -> {spare:.1f} spare, "
           f"{SHARE:.0%} of that = {workers}")

    if temp is None:
        return workers, why + "; no CPU temperature available"
    if temp >= HOT_C:
        return 1, (why + f"; but CPU is {temp:.0f}°C (>= {HOT_C:.0f}) "
                   "— running serial to let it cool")
    if temp >= WARM_C:
        halved = max(1, workers // 2)
        return halved, (why + f"; but CPU is {temp:.0f}°C "
                        f"(>= {WARM_C:.0f}) — halved to {halved}")
    return workers, why + f"; CPU {temp:.0f}°C"


def memory_plan(total: int, available: int, requested: int) -> tuple[int, int]:
    """Budget the whole run, including the controller and worker children."""
    budget = max(1, min(total // 2, int(available * 0.6)))
    capacity = max(1, (budget - CONTROLLER_BYTES) // WORKER_BYTES)
    return min(requested, capacity), budget


def memory_scope(budget: int) -> list[str]:
    """Probe enforcement before pytest starts; never retry a failed test run."""
    if sys.platform != "linux" or not shutil.which("systemd-run"):
        return []
    prefix = ["systemd-run", "--user", "--scope", "--quiet",
              "-p", f"MemoryMax={budget}", "-p", "MemorySwapMax=0"]
    try:
        probe = subprocess.run(prefix + ["true"], capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return prefix if probe.returncode == 0 else []


def interpreter() -> str:
    """The Python that owns *this* checkout, not whichever one is on PATH.

    A worktree has its own `.venv` with its own editable install, but the
    ambient shell usually still exports `VIRTUAL_ENV` pointing at the main
    checkout. Run this script by its shebang from a worktree and the tests
    import the *other* tree's code: edits appear to do nothing, a module
    you just added reports as missing, and nothing anywhere says why.

    So the interpreter is chosen by where the script lives, and the choice
    is printed — never inferred from the environment.
    """
    own = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"
    if own.is_file() and str(own) != sys.executable:
        return str(own)
    return sys.executable


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run pytest with a worker count chosen from current load "
                    "CPU temperature and available RAM.",
        epilog="Anything not listed here is passed straight to pytest.")
    parser.add_argument("--workers", type=int, metavar="N",
                        help="request N workers, still bounded by RAM (0 = serial)")
    parser.add_argument("--max-workers", type=int, default=MAX_WORKERS,
                        metavar="N", help=f"ceiling (default {MAX_WORKERS})")
    parser.add_argument("--no-nice", action="store_true",
                        help="do not lower the run's priority")
    parser.add_argument("--explain", action="store_true",
                        help="print the decision and exit")
    known, extra = parser.parse_known_args(argv)

    cores = os.cpu_count() or 1
    load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
    temp = cpu_temperature()

    if known.workers is None:
        workers, why = decide(cores, load, temp, max(1, known.max_workers))
    else:
        workers = max(0, known.workers)
        why = "asked for on the command line"

    # psutil is a project dependency; use the checkout interpreter so it is
    # available even when this script's shebang uses the system Python.
    snapshot = subprocess.check_output(
        [interpreter(), "-c", "import psutil; m=psutil.virtual_memory(); "
         "print(m.total, m.available)"], text=True)
    total, available = map(int, snapshot.split())
    workers, budget = memory_plan(total, available, workers)
    why += f"; RAM budget {budget / GIB:.1f} GiB (3 GiB per worker)"
    scope = memory_scope(budget)
    print("[run_tests] " + ("whole-run memory limit enforced; swap disabled"
          if scope else "WARNING: no OS memory limit available; worker limit only"),
          file=sys.stderr)

    plan = "serial" if workers <= 1 else f"{workers} workers"
    print(f"[run_tests] {plan} — {why}", file=sys.stderr)
    if known.explain:
        return 0

    command: list[str] = list(scope)
    if not known.no_nice and shutil.which("nice"):
        # The whole point on a busy machine: the tests take the cores
        # nobody else wants, and give them back the instant anyone does.
        command += ["nice", "-n", "19"]
    python = interpreter()
    if python != sys.executable:
        print(f"[run_tests] using this checkout's own interpreter: {python}",
              file=sys.stderr)
    command += [python, "-m", "pytest", "-q"]
    if workers > 1:
        # `--dist loadfile` is required, not a preference: modules share a
        # module-scoped Qt fixture and isolate QSettings per file, so a
        # module has to stay on one worker.
        command += ["-n", str(workers), "--dist", "loadfile",
                    "--max-worker-restart", "0"]
    command += extra or []

    environment = dict(os.environ)
    # Qt must not try to open a window; a suite that pops up windows on a
    # machine somebody is using is its own kind of rude.
    environment["QT_QPA_PLATFORM"] = "offscreen"
    # Avoid each worker creating its own full BLAS/OpenMP thread pool.
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        environment[name] = "1"

    print(f"[run_tests] {' '.join(command)}", file=sys.stderr)
    result = subprocess.call(command, env=environment)
    if result and scope:
        print("[run_tests] Run failed. If workers were killed, the memory "
              "ceiling may have been reached; retry with fewer --workers.",
              file=sys.stderr)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
