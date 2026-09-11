"""What a flow needs installed (AC2): the Python packages its nodes import
and the web libraries its visuals load, and which this machine is missing.

Nothing declares either. The imports are in each node's own code — a
forked or custom node carries its code in the file, a library node's is
its script — and a visual asks for a web library by calling
`weblibs.markup("d3")`. Both are read here from the source text, parsed
and never run. Qt-free.

The hard part is honest: an import name is not a package name (`import
sklearn` is `pip install scikit-learn`). An installed module names its own
package; a missing one is looked up in a table of the common mismatches,
and otherwise the import name is offered as a guess and marked as one.
"""
from __future__ import annotations

import ast
import functools
import importlib.metadata
import importlib.util
import sys
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

#: Import names that are not the name you install. Only mismatches: pip
#: ignores case, so `yaml` is here and `requests` is not.
PACKAGE_FOR_IMPORT = {
    "attr": "attrs",
    "bs4": "beautifulsoup4",
    "Crypto": "pycryptodome",
    "cv2": "opencv-python",
    "dataikuapi": "dataiku-api-client",
    "dateutil": "python-dateutil",
    "discord": "discord.py",
    "docx": "python-docx",
    "dotenv": "python-dotenv",
    "fitz": "PyMuPDF",
    "gi": "PyGObject",
    "jwt": "PyJWT",
    "ldap": "python-ldap",
    "magic": "python-magic",
    "MySQLdb": "mysqlclient",
    "OpenSSL": "pyOpenSSL",
    "PIL": "Pillow",
    "pptx": "python-pptx",
    "pythoncom": "pywin32",
    "pywintypes": "pywin32",
    "serial": "pyserial",
    "skimage": "scikit-image",
    "sklearn": "scikit-learn",
    "slugify": "python-slugify",
    "snowflake": "snowflake-connector-python",
    "telegram": "python-telegram-bot",
    "usb": "pyusb",
    "win32api": "pywin32",
    "win32com": "pywin32",
    "wx": "wxPython",
    "yaml": "PyYAML",
    "zmq": "pyzmq",
}

#: Exceptions whose handler makes an import optional: the node carries on
#: without the module, so a missing one is worth knowing, not a failure.
_OPTIONAL_CATCHES = {"ImportError", "ModuleNotFoundError", "Exception",
                     "BaseException"}

#: The web-library calls a node makes: `markup("d3")`, `require("echarts")`.
_WEBLIB_CALLS = {"markup", "require"}

PACKAGE = "package"
WEBLIB = "web library"


@dataclass
class Need:
    """One thing a flow needs installed."""
    kind: str                  # PACKAGE or WEBLIB
    name: str                  # what to install: a pip name, or a web library
    module: str = ""           # the import it was read from (packages only)
    certain: bool = True       # False: the package name is a guess
    optional: bool = False     # every use has a fallback if it is missing
    installed: bool = False
    nodes: list = field(default_factory=list)   # labels of the nodes using it

    @property
    def missing(self) -> bool:
        return not self.installed


# ------------------------------------------------------------ reading code

class _Imports(ast.NodeVisitor):
    """Top-level module names imported, each with whether every import of
    it sits inside a `try` that carries on without it."""

    def __init__(self) -> None:
        self.found: dict[str, bool] = {}
        self._guarded = 0

    def _add(self, module: str) -> None:
        top = module.split(".")[0]
        if not top:
            return
        optional = self._guarded > 0
        self.found[top] = self.found.get(top, True) and optional

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._add(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module:   # not a relative import
            self._add(node.module)

    def visit_Try(self, node) -> None:
        guards = any(_catches_import_error(h) for h in node.handlers)
        self._guarded += guards
        for child in node.body:
            self.visit(child)
        self._guarded -= guards
        for child in [*node.handlers, *node.orelse, *node.finalbody]:
            self.visit(child)

    visit_TryStar = visit_Try


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:                  # a bare except:
        return True
    types = (handler.type.elts if isinstance(handler.type, ast.Tuple)
             else [handler.type])
    return any(isinstance(t, ast.Name) and t.id in _OPTIONAL_CATCHES
               or isinstance(t, ast.Attribute) and t.attr in _OPTIONAL_CATCHES
               for t in types)


def _parse(source: str) -> Optional[ast.AST]:
    try:
        return ast.parse(source or "")
    except (SyntaxError, ValueError):
        return None


def imports_in(source: str) -> dict[str, bool]:
    """{top-level module: optional} for every third-party import in
    `source`. The standard library, flograph and relative imports are left
    out. Code that does not parse imports nothing."""
    tree = _parse(source)
    if tree is None:
        return {}
    visitor = _Imports()
    visitor.visit(tree)
    stdlib = getattr(sys, "stdlib_module_names", frozenset())
    return {name: optional for name, optional in visitor.found.items()
            if name not in stdlib and name not in ("flograph", "__future__")}


def web_libraries_in(source: str) -> list[str]:
    """Web libraries `source` asks for: the string arguments of each
    `markup(...)` / `require(...)` call made through `flograph.weblibs`.
    Only calls count — a library named in a docstring or a comment is an
    example, not a use."""
    tree = _parse(source)
    if tree is None:
        return []
    direct: set[str] = set()       # names imported from flograph.weblibs
    modules: set[str] = set()      # names the weblibs module is bound to
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "flograph.weblibs":
            direct.update(a.asname or a.name for a in node.names
                          if a.name in _WEBLIB_CALLS)
        elif isinstance(node, ast.ImportFrom) and node.module == "flograph":
            modules.update(a.asname or a.name for a in node.names
                           if a.name == "weblibs")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "flograph.weblibs":
                    modules.add(alias.asname or "flograph.weblibs")
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            hit = func.id in direct
        elif isinstance(func, ast.Attribute) and func.attr in _WEBLIB_CALLS:
            hit = ast.unparse(func.value) in modules
        else:
            hit = False
        if not hit:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                    and arg.value not in names:
                names.append(arg.value)
    return names


# ------------------------------------------------------ naming the package

def package_for(module: str, installed_names=None) -> tuple[str, bool]:
    """(package to install, whether that name is known rather than guessed)
    for an import. `installed_names` is `packages_distributions()`, passed
    in so a scan reads it once."""
    if installed_names is None:
        installed_names = importlib.metadata.packages_distributions()
    dists = installed_names.get(module)
    if dists:
        return dists[0], True
    if module in PACKAGE_FOR_IMPORT:
        return PACKAGE_FOR_IMPORT[module], True
    return module, False


def _importable(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


# ------------------------------------------------------------- the scan

@functools.lru_cache(maxsize=1024)
def _scan(source: str) -> tuple:
    """(imports, web libraries) of one source, kept: a library node's
    script is the same text in every flow, and parsing the whole library
    costs a quarter of a second."""
    return tuple(imports_in(source).items()), tuple(web_libraries_in(source))


def requirements_of(nodes: Iterable, *,
                    weblib_installed: Optional[Callable[[str], bool]] = None,
                    importable: Callable[[str], bool] = _importable,
                    skip: Iterable[str] = (),
                    name_installed: bool = True) -> list[Need]:
    """Everything the nodes of a flow need, missing things first.

    `nodes` are the graph's node instances. `skip` names packages to leave
    out — flograph's own dependencies, which are there if flograph is
    running. A package used by several nodes is one row naming them all,
    optional only if every one of them can do without it.

    `name_installed` asks each *installed* module which package it came
    from. That reads every installed package's metadata — a sixth of a
    second — so the check made on opening a file, which only counts what is
    missing, turns it off; a missing module has no metadata to ask anyway.
    """
    if weblib_installed is None:
        from . import weblibs
        weblib_installed = weblibs.is_installed
    skipped = {s.lower().replace("_", "-") for s in skip}
    lazily: dict = {}

    def installed_names() -> dict:
        if "names" not in lazily:
            lazily["names"] = (importlib.metadata.packages_distributions()
                               if name_installed else {})
        return lazily["names"]

    needs: dict[tuple, Need] = {}

    def note(key, make, label, optional):
        need = needs.get(key)
        if need is None:
            need = needs[key] = make()
            need.optional = optional
        else:
            need.optional = need.optional and optional
        if label not in need.nodes:
            need.nodes.append(label)

    for node in nodes:
        spec = getattr(node, "spec", None)
        if spec is None or getattr(spec, "broken", False):
            continue
        modules, libraries = _scan(node.source or "")
        label = getattr(node, "label", "") or spec.label
        for module, optional in modules:
            there = importable(module)
            name, certain = package_for(
                module, installed_names() if there else {})
            if name.lower().replace("_", "-") in skipped \
                    or module.lower().replace("_", "-") in skipped:
                continue
            note((PACKAGE, name.lower()),
                 lambda: Need(PACKAGE, name, module=module, certain=certain,
                              installed=there),
                 label, optional)
        for library in libraries:
            note((WEBLIB, library),
                 lambda: Need(WEBLIB, library,
                              installed=bool(weblib_installed(library))),
                 label, False)
    return sorted(needs.values(),
                  key=lambda n: (n.installed, n.optional, n.kind,
                                 n.name.lower()))


def missing(needs: Iterable[Need], include_optional: bool = False) -> list[Need]:
    """The needs this machine can't meet — required ones unless asked."""
    return [n for n in needs
            if n.missing and (include_optional or not n.optional)]
