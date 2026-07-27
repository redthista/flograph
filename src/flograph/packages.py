"""Package management helpers (Qt-free).

flograph nodes run in-process, so a library is importable by a node exactly
when it is installed into the environment of the interpreter running flograph
(normally the app's own .venv). These helpers enumerate that environment
and build the installer command lines the Packages dialog executes: pip
when the interpreter has it, `uv pip` pointed at this interpreter as the
fallback (uv-created venvs ship without pip).
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import shutil
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
