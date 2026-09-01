"""Package management helpers (Qt-free).

flograph nodes run in-process, so a library is importable by a node exactly
when it is installed into the environment of the interpreter running flograph
(normally the app's own .venv). These helpers enumerate that environment
and build the installer command lines the Packages dialog executes: pip
when the interpreter has it, `uv pip` pointed at this interpreter as the
fallback (uv-created venvs ship without pip).

The update-check helpers at the bottom (`update_status`, `upgrade_hint`) are
strictly read-only: they ask an index what versions exist and compare, never
installing or writing anything. They have to work — or fail quietly — in a
locked-down environment that installs from a private mirror (JFrog,
Artifactory, devpi) and may have no route to pypi.org at all.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import shutil
import subprocess
import sys

# Uninstalling these would break the running app; the dialog refuses.
CORE_PACKAGES = frozenset({
    "flograph", "pyside6", "pyside6-addons", "pyside6-essentials", "shiboken6",
    "pandas", "numpy", "matplotlib", "jedi", "pip",
})


def canonical_name(name: str) -> str:
    return name.lower().replace("_", "-")


def list_installed() -> list[tuple[str, str]]:
    """(name, version) for every distribution in this interpreter's
    environment, sorted by name, deduplicated."""
    seen: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            seen.setdefault(canonical_name(name), dist.version or "?")
    return sorted(seen.items())


def installer_kind() -> str | None:
    """'pip' if this interpreter has pip, 'uv' if uv is on PATH, else None."""
    if importlib.util.find_spec("pip") is not None:
        return "pip"
    if shutil.which("uv"):
        return "uv"
    return None


def _stale_pyarrow_problem() -> str:
    """Why pandas cannot use an installed pyarrow, or "" when it can.

    pandas settles the question of whether pyarrow exists exactly once, when
    pandas itself is first imported, and keeps the answer as a set of
    version flags. Installing pyarrow into a running app therefore never
    reaches pandas: the flags still say "absent", which pandas reads as
    "older than 14.0.1" and acts on, patching an extension type that modern
    pyarrow never registers. The failure surfaces much later, inside
    to_parquet, as an ArrowKeyError naming neither parquet nor the cause.
    Restarting is the entire fix, so the Parquet nodes say so instead.
    """
    try:
        import pyarrow
        from pandas.compat.pyarrow import pa_version_under14p1
        from pandas.util.version import Version
    except ImportError:      # a pandas that keeps them somewhere else
        return ""
    genuinely_old = (Version(Version(pyarrow.__version__).base_version)
                     < Version("14.0.1"))
    if pa_version_under14p1 and not genuinely_old:
        return (f"pyarrow {pyarrow.__version__} was installed after flograph "
                f"started, so pandas is still running as though it were "
                f"missing. Restart flograph and Parquet will work.")
    return ""


def parquet_problem(engine: str = "auto") -> str:
    """Why the Parquet nodes cannot run on `engine`, or "" when they can.

    Both engines pandas supports are optional, and "auto" is happy with
    either, so which package has to be present depends on the choice made
    in the node. Only pyarrow has the stale-flags problem above.
    """
    installed = {name: importlib.util.find_spec(name) is not None
                 for name in ("pyarrow", "fastparquet")}
    if engine == "fastparquet":
        if not installed["fastparquet"]:
            return ("The fastparquet engine needs the fastparquet package "
                    "\u2014 install it from Tools > Manage Packages, then "
                    "restart flograph.")
        return ""
    if engine == "pyarrow" and not installed["pyarrow"]:
        return ("The pyarrow engine needs the pyarrow package \u2014 install "
                "it from Tools > Manage Packages, then restart flograph.")
    if not installed["pyarrow"]:
        if installed["fastparquet"]:
            return ""        # "auto": pandas falls back to fastparquet
        return ("Parquet needs either the pyarrow or the fastparquet package "
                "\u2014 install one from Tools > Manage Packages, then "
                "restart flograph.")
    return _stale_pyarrow_problem()


def validate_requirements(specs: list[str]) -> list[str]:
    """Reject empty and option-like ('-r ...') entries; the installer runs
    without a shell, so options are the only injection surface left."""
    cleaned = []
    for spec in specs:
        spec = spec.strip()
        if not spec:
            continue
        if spec.startswith("-"):
            raise ValueError(f"not a package specifier: {spec!r}")
        cleaned.append(spec)
    if not cleaned:
        raise ValueError("no packages given")
    return cleaned


def build_command(action: str, packages: list[str]) -> list[str]:
    """Full argv for install/upgrade/uninstall into this interpreter's
    environment. Raises if no installer is available."""
    if action not in ("install", "upgrade", "uninstall"):
        raise ValueError(f"unknown action {action!r}")
    packages = validate_requirements(packages)
    kind = installer_kind()
    if kind == "pip":
        base = [sys.executable, "-m", "pip"]
        if action == "install":
            return base + ["install", *packages]
        if action == "upgrade":
            return base + ["install", "--upgrade", *packages]
        return base + ["uninstall", "-y", *packages]
    if kind == "uv":
        base = [shutil.which("uv"), "pip"]
        target = ["--python", sys.executable]
        if action == "install":
            return base + ["install", *target, *packages]
        if action == "upgrade":
            return base + ["install", "--upgrade", *target, *packages]
        return base + ["uninstall", *target, *packages]
    raise RuntimeError(
        "no installer found: this interpreter has no pip module and 'uv' is "
        "not on PATH — run 'python -m ensurepip' in flograph's venv or install uv"
    )


# --------------------------------------------------------- update checking

PYPI_JSON_URL = "https://pypi.org/pypi/flograph/json"
GITHUB_RELEASES_URL = "https://github.com/redthista/flograph/releases"


def installed_version() -> str:
    """The running flograph's version, or "0" if it isn't installed as a
    distribution (a source checkout run in place). "0" compares below every
    real release, so such a build is simply never told it is behind."""
    try:
        return importlib.metadata.version("flograph")
    except importlib.metadata.PackageNotFoundError:
        return "0"


def _parse_pip_index_output(text: str) -> list[str]:
    """The version list out of `pip index versions` output. The relevant
    line reads: ``Available versions: 0.1.12, 0.1.11, 0.1.10``."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("available versions:"):
            rest = stripped.split(":", 1)[1]
            return [v.strip() for v in rest.split(",") if v.strip()]
    return []


def _pip_index_versions(name: str = "flograph", timeout: float = 8.0) -> list[str]:
    """Ask pip which versions of `name` its configured index carries.

    `pip index versions` talks to whatever index this environment installs
    from — a private JFrog / Artifactory / devpi mirror included — so in a
    locked-down setup it answers the question that actually matters: what
    can I install *here*. Read-only. Returns [] on any failure: no pip, pip
    too old for the subcommand (added 21.2), no network, a mirror that
    refuses the request.
    """
    if importlib.util.find_spec("pip") is None:
        return []
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "index", "versions", name],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
    except (OSError, subprocess.SubprocessError):
        return []
    return _parse_pip_index_output(proc.stdout)


def _pypi_latest_version(timeout: float = 6.0) -> "str | None":
    """The newest flograph version on PyPI, or None if PyPI can't be
    reached. Only consulted when pip's own index lookup came back empty —
    an environment pinned to a private mirror generally can't reach this
    and simply gets None."""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(PYPI_JSON_URL, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception:
        return None
    return (data.get("info") or {}).get("version") or None


def latest_available_version() -> "str | None":
    """Newest flograph version this environment could install, or None when
    that can't be determined (offline, blocked index, ancient pip).

    Purely read-only — queries an index, installs nothing, writes nothing.
    """
    # pandas vendors packaging's Version; used elsewhere in this file too,
    # and packaging itself is not a direct dependency
    from pandas.util.version import InvalidVersion, Version

    parsed = []
    for raw in _pip_index_versions():
        try:
            parsed.append(Version(raw))
        except InvalidVersion:
            continue
    if parsed:
        return str(max(parsed))
    return _pypi_latest_version()


def update_status() -> "tuple[str, str | None, bool]":
    """(installed version, latest available or None, latest is newer).

    Never raises — a checker calling this on a background thread wants an
    answer or a shrug, not an exception to marshal back to the UI thread.
    """
    # pandas vendors packaging's Version; used elsewhere in this file too,
    # and packaging itself is not a direct dependency
    from pandas.util.version import InvalidVersion, Version

    current = installed_version()
    try:
        latest = latest_available_version()
    except Exception:
        latest = None
    if latest is None:
        return current, None, False
    try:
        newer = Version(latest) > Version(current)
    except InvalidVersion:
        newer = False
    return current, latest, newer


def upgrade_hint() -> str:
    """What to show a user who wants the newer version — a command they run
    themselves, or a page to visit. flograph never runs this; the in-app
    route is Tools ▸ Manage Packages, which the notice also names."""
    if getattr(sys, "frozen", False):
        return f"Download the latest release from {GITHUB_RELEASES_URL}"
    if installer_kind() == "uv":
        return "uv pip install --upgrade flograph"
    return "pip install --upgrade flograph"
