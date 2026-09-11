"""Package management helpers (Qt-free).

flograph nodes run in-process, so a library is importable by a node exactly
when it is installed into the environment of the interpreter running flograph
(normally the app's own .venv). These helpers enumerate that environment
and build the installer command lines the Packages dialog executes: pip
when the interpreter has it, `uv pip` pointed at this interpreter as the
fallback (uv-created venvs ship without pip).

Where packages come from (AC1) is a `PackageIndex`: an index URL and the
hosts to trust, set in Settings ▸ Packages. Left blank, pip reads its own
settings (pip.conf, `PIP_INDEX_URL`) as it always did — and `uv pip`, which
reads neither, is handed what pip would have used, so a machine set up for
a private mirror installs from it whichever installer runs.

The update-check helpers at the bottom (`update_status`, `upgrade_hint`) are
strictly read-only: they ask an index what versions exist and compare, never
installing or writing anything. They have to work — or fail quietly — in a
locked-down environment that installs from a private mirror (JFrog,
Artifactory, devpi) and may have no route to pypi.org at all.
"""
from __future__ import annotations

import configparser
import importlib.metadata
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

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


# ---------------------------------------------------- the package index (AC1)

@dataclass(frozen=True)
class PackageIndex:
    """Where installs come from: an index URL, and hosts to trust.

    Empty means "the installer's own default". `source` says where the
    values were read from, for showing; it takes no part in comparing two.
    """
    url: str = ""
    trusted_host: str = ""
    source: str = field(default="", compare=False)

    def hosts(self) -> list[str]:
        """The trusted hosts: pip takes several, space- or comma-separated."""
        return [h for h in re.split(r"[\s,]+", self.trusted_host.strip()) if h]

    def __bool__(self) -> bool:
        return bool(self.url.strip() or self.hosts())

    def pip_args(self) -> list[str]:
        args = ["--index-url", self.url.strip()] if self.url.strip() else []
        for host in self.hosts():
            args += ["--trusted-host", host]
        return args

    def uv_args(self) -> list[str]:
        # --index-url rather than uv's newer --default-index: uv still takes
        # it, and a uv from before --default-index takes nothing else
        args = ["--index-url", self.url.strip()] if self.url.strip() else []
        for host in self.hosts():
            args += ["--allow-insecure-host", host]
        return args


def index_problem(url: str, trusted_host: str = "") -> str:
    """What is wrong with an index typed into Settings, or ""."""
    url = (url or "").strip()
    if url:
        if any(ch.isspace() for ch in url):
            return "The index URL can't contain spaces."
        scheme = url.split(":", 1)[0].lower() if ":" in url else ""
        if scheme not in ("http", "https", "file"):
            return ("The index URL has to start with https://, http:// or "
                    "file://.")
    for host in PackageIndex(trusted_host=trusted_host or "").hosts():
        if host.startswith("-"):
            return f"“{host}” isn't a host name."
    return ""


#: uv's own settings for an index. When one is set, uv has been told where
#: to install from, and pip's settings are not handed over on top of it.
UV_INDEX_ENV = ("UV_INDEX_URL", "UV_DEFAULT_INDEX", "UV_INDEX")


def _pip_config_files(environ) -> list[str]:
    """pip's config files, lowest priority first: global, user, site, then
    PIP_CONFIG_FILE — the order pip loads them in, later ones winning."""
    chosen = environ.get("PIP_CONFIG_FILE", "")
    if chosen == os.devnull:
        return []                       # pip's own switch for "no config"
    home = os.path.expanduser("~")
    files: list[str] = []
    if sys.platform == "win32":
        files.append(os.path.join(environ.get("PROGRAMDATA", r"C:\ProgramData"),
                                  "pip", "pip.ini"))
        files.append(os.path.join(home, "pip", "pip.ini"))
        if environ.get("APPDATA"):
            files.append(os.path.join(environ["APPDATA"], "pip", "pip.ini"))
        site = "pip.ini"
    else:
        if sys.platform == "darwin":
            files.append("/Library/Application Support/pip/pip.conf")
        for base in (environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":"):
            if base:
                files.append(os.path.join(base, "pip", "pip.conf"))
        files.append("/etc/pip.conf")
        files.append(os.path.join(home, ".pip", "pip.conf"))
        if sys.platform == "darwin":
            files.append(os.path.join(home, "Library", "Application Support",
                                      "pip", "pip.conf"))
        files.append(os.path.join(
            environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"),
            "pip", "pip.conf"))
        site = "pip.conf"
    files.append(os.path.join(sys.prefix, site))
    if chosen:
        files.append(chosen)
    return files


def pip_config_index(environ=None, files=None) -> PackageIndex:
    """The index pip is configured with, read without pip.

    `PIP_INDEX_URL` / `PIP_TRUSTED_HOST` first, as pip does, then pip's
    config files, where an `[install]` section outranks `[global]`. For the
    `uv pip` fallback, which reads none of it — and for saying, on a machine
    with pip, where its installs are coming from.
    """
    environ = os.environ if environ is None else environ
    files = _pip_config_files(environ) if files is None else files
    found = {"index-url": ("", ""), "trusted-host": ("", "")}
    for section in ("global", "install"):
        for path in files:
            parser = configparser.RawConfigParser()
            try:
                if not parser.read(path, encoding="utf-8"):
                    continue
            except (configparser.Error, OSError, UnicodeDecodeError):
                continue
            if not parser.has_section(section):
                continue
            for key in found:
                for spelling in (key, key.replace("-", "_")):
                    value = parser.get(section, spelling, fallback="").strip()
                    if value:
                        found[key] = (value, f"pip config ({path})")
    url, url_from = found["index-url"]
    hosts, hosts_from = found["trusted-host"]
    if environ.get("PIP_INDEX_URL", "").strip():
        url, url_from = environ["PIP_INDEX_URL"].strip(), "PIP_INDEX_URL"
    if environ.get("PIP_TRUSTED_HOST", "").strip():
        hosts, hosts_from = environ["PIP_TRUSTED_HOST"].strip(), "PIP_TRUSTED_HOST"
    return PackageIndex(url=url, trusted_host=" ".join(hosts.split()),
                        source=url_from or hosts_from)


def effective_index(configured: "PackageIndex | None" = None,
                    environ=None, files=None) -> PackageIndex:
    """The index an install will use: flograph's own setting when there is
    one, otherwise whatever pip is configured with (which may be nothing —
    PyPI)."""
    if configured:
        return PackageIndex(configured.url, configured.trusted_host,
                            source=configured.source or "flograph's settings")
    return pip_config_index(environ, files)


def describe_index(index: PackageIndex) -> str:
    """One line saying where installs come from, for the Packages dialog."""
    if not index.url.strip():
        where = "PyPI, the public index"
    else:
        where = index.url.strip()
    if index.hosts():
        where += f" (trusting {', '.join(index.hosts())})"
    return f"{where} — from {index.source}" if index.source else where


def uv_has_own_index(environ=None) -> bool:
    """Has uv been told an index of its own, in its environment variables?"""
    environ = os.environ if environ is None else environ
    return any(environ.get(name, "").strip() for name in UV_INDEX_ENV)


def build_command(action: str, packages: list[str],
                  index: "PackageIndex | None" = None,
                  environ=None, files=None) -> list[str]:
    """Full argv for install/upgrade/uninstall into this interpreter's
    environment. Raises if no installer is available.

    `index` is flograph's own Settings ▸ Packages index, or None. pip reads
    its own settings, so it is given only that; `uv pip` reads pip's
    settings not at all, so without one it is given what pip would have
    used — unless uv has been told an index of its own. Uninstalling needs
    no index, and pip refuses the options there.
    """
    if action not in ("install", "upgrade", "uninstall"):
        raise ValueError(f"unknown action {action!r}")
    packages = validate_requirements(packages)
    environ = os.environ if environ is None else environ
    kind = installer_kind()
    if kind == "pip":
        base = [sys.executable, "-m", "pip"]
        where = index.pip_args() if index else []
        if action == "install":
            return base + ["install", *where, *packages]
        if action == "upgrade":
            return base + ["install", "--upgrade", *where, *packages]
        return base + ["uninstall", "-y", *packages]
    if kind == "uv":
        base = [shutil.which("uv"), "pip"]
        target = ["--python", sys.executable]
        if index:
            where = index.uv_args()
        elif uv_has_own_index(environ):
            where = []
        else:
            where = pip_config_index(environ, files).uv_args()
        if action == "install":
            return base + ["install", *target, *where, *packages]
        if action == "upgrade":
            return base + ["install", "--upgrade", *target, *where, *packages]
        return base + ["uninstall", *target, *packages]
    raise RuntimeError(
        "no installer found: this interpreter has no pip module and 'uv' is "
        "not on PATH — run 'python -m ensurepip' in flograph's venv or install uv"
    )


# --------------------------------------------------------- update checking

PYPI_JSON_URL = "https://pypi.org/pypi/flograph/json"
GITHUB_RELEASES_URL = "https://github.com/redthista/flograph/releases"


def installed_version() -> str:
    """The running flograph's version, or "0" when nothing can name it (a
    source checkout run in place). "0" compares below every real release, so
    such a build is simply never told it is behind.

    Via `version.running_version`, so a single-file bundle is compared on its
    own version rather than on that of some older pip install sharing the
    interpreter — which would have offered an update to something already
    running, or hidden one that mattered.
    """
    from .version import running_version
    return running_version("0")


def _parse_pip_index_output(text: str) -> list[str]:
    """The version list out of `pip index versions` output. The relevant
    line reads: ``Available versions: 0.1.12, 0.1.11, 0.1.10``."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("available versions:"):
            rest = stripped.split(":", 1)[1]
            return [v.strip() for v in rest.split(",") if v.strip()]
    return []


def _pip_index_versions(name: str = "flograph", timeout: float = 8.0,
                        index: "PackageIndex | None" = None) -> list[str]:
    """Ask pip which versions of `name` its configured index carries.

    `pip index versions` talks to whatever index this environment installs
    from — a private JFrog / Artifactory / devpi mirror included — so in a
    locked-down setup it answers the question that actually matters: what
    can I install *here*. `index` is flograph's own setting, which outranks
    pip's the way it does for an install. Read-only. Returns [] on any
    failure: no pip, pip too old for the subcommand (added 21.2), no
    network, a mirror that refuses the request.
    """
    if importlib.util.find_spec("pip") is None:
        return []
    where = index.pip_args() if index else []
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "index", "versions", *where, name],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
    except (OSError, subprocess.SubprocessError):
        return []
    return _parse_pip_index_output(proc.stdout)


#: A distribution file's name: project, version, then a wheel's tags or an
#: sdist's extension.
_DIST_FILE = re.compile(
    r"^(?P<name>.+?)-(?P<version>\d[^-]*?)"
    r"(?:-[^/]+\.whl|\.tar\.gz|\.tar\.bz2|\.zip)$", re.IGNORECASE)


def _normal(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _versions_from_simple_page(body: str, name: str) -> list[str]:
    """The versions on a simple-index project page — PEP 691 JSON (its
    `versions`, or else its file names) or PEP 503 HTML (the link texts)."""
    import json
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if isinstance(data, dict):
        if isinstance(data.get("versions"), list):
            return [str(v) for v in data["versions"]]
        filenames = [str(f.get("filename", "")) for f in data.get("files", [])
                     if isinstance(f, dict)]
    else:
        filenames = re.findall(r">\s*([^<>]+?)\s*</a>", body)
    versions: list[str] = []
    for filename in filenames:
        match = _DIST_FILE.match(filename.strip())
        if match and _normal(match["name"]) == _normal(name) \
                and match["version"] not in versions:
            versions.append(match["version"])
    return versions


def _simple_index_versions(index: PackageIndex, name: str = "flograph",
                           timeout: float = 8.0) -> list[str]:
    """Ask a simple index directly which versions of `name` it carries.

    What the update check does when there is no pip to ask — which is every
    environment uv made. Read-only; [] on any failure. A trusted host is
    trusted here too, so a mirror with an internal certificate answers.
    """
    import ssl
    import urllib.parse
    import urllib.request
    url = index.url.strip()
    if not url:
        return []
    page = url.rstrip("/") + "/" + _normal(name) + "/"
    request = urllib.request.Request(page, headers={
        "Accept": "application/vnd.pypi.simple.v1+json, text/html;q=0.1"})
    context = None
    if (urllib.parse.urlsplit(page).hostname or "") in index.hosts():
        context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout,
                                    context=context) as resp:
            body = resp.read().decode("utf-8", "replace")
    except Exception:
        return []
    return _versions_from_simple_page(body, name)


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


def latest_available_version(index: "PackageIndex | None" = None) -> "str | None":
    """Newest flograph version this environment could install, or None when
    that can't be determined (offline, blocked index, ancient pip).

    Asked of pip when there is one; with no pip, of the index an install
    would use, directly. Purely read-only — queries an index, installs
    nothing, writes nothing.
    """
    # pandas vendors packaging's Version; used elsewhere in this file too,
    # and packaging itself is not a direct dependency
    from pandas.util.version import InvalidVersion, Version

    versions = _pip_index_versions(index=index)
    if not versions and importlib.util.find_spec("pip") is None:
        versions = _simple_index_versions(effective_index(index))
    parsed = []
    for raw in versions:
        try:
            parsed.append(Version(raw))
        except InvalidVersion:
            continue
    if parsed:
        return str(max(parsed))
    return _pypi_latest_version()


def update_status(index: "PackageIndex | None" = None
                  ) -> "tuple[str, str | None, bool]":
    """(installed version, latest available or None, latest is newer).

    `index` is flograph's own Settings ▸ Packages index, when one is set.
    Never raises — a checker calling this on a background thread wants an
    answer or a shrug, not an exception to marshal back to the UI thread.
    """
    # pandas vendors packaging's Version; used elsewhere in this file too,
    # and packaging itself is not a direct dependency
    from pandas.util.version import InvalidVersion, Version

    current = installed_version()
    try:
        latest = latest_available_version(index)
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
