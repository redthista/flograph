"""What version of flograph is actually running (Qt-free).

There are two ways flograph gets onto a machine and they disagree about
where the version lives. A pip install has real distribution metadata, and
`importlib.metadata` reads it. The single-file bundle has none: it carries
`src/flograph` and nothing else, unpacks itself to a temp directory and puts
that first on `sys.path`. So a metadata lookup from inside a running bundle
does not describe the bundle at all — it describes whatever *other* flograph
happens to be pip-installed in the interpreter that started it, which is how
a 0.1.14 bundle came to report 0.1.12 in Settings on a machine with an old
install, while running 0.1.14's code the whole time.

`scripts/build_onefile.py` therefore writes `_bundle_version.py` into the
zip — into the zip only, never into the source tree — and it is asked first.
The order matters and only reads one way: the bundle's own module can only
be importable when the bundle's code is the code running, so preferring it
is preferring the truth. A pip install has no such module and falls through
to its metadata, so a pip-installed 0.1.13 reports 0.1.13 even if a newer
bundle is sitting on the same disk.
"""
from __future__ import annotations

import importlib.metadata


def bundled_version() -> str | None:
    """The version stamped into a single-file bundle, or None outside one."""
    try:
        from ._bundle_version import VERSION
    except ImportError:
        return None
    return VERSION or None


def installed_version() -> str | None:
    """The version of the pip-installed distribution, or None without one."""
    try:
        return importlib.metadata.version("flograph")
    except importlib.metadata.PackageNotFoundError:
        return None


def running_version(default: str | None = None) -> str | None:
    """The version of the code that is executing, bundle first."""
    return bundled_version() or installed_version() or default
