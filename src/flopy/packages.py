"""Package management helpers (Qt-free).

flopy nodes run in-process, so a library is importable by a node exactly
when it is installed into the environment of the interpreter running flopy
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
    "flopy", "pyside6", "pyside6-addons", "pyside6-essentials", "shiboken6",
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
        "not on PATH — run 'python -m ensurepip' in flopy's venv or install uv"
    )
