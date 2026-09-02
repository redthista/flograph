"""Idea #21: a node script importing a library this machine doesn't have.

Node scripts are executed to read their NODE/PARAMS declarations, so a
top-level `import` runs at *load* time — when the library panel is built,
when a project is opened, when code is applied. The rule is that none of
those may take the app (or the rest of the file) down with them, and that
the message says what would fix it, since flograph can install packages
itself.
"""
import json
import sys
import types
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry
from flograph.core.script import (MissingDependencyError, NodeScriptError,
                                  compile_run, missing_module_hint, parse_spec)
from flograph.core.serialization import (FLOGRAPH_VERSION, SCHEMA_VERSION,
                                         graph_from_dict, graph_to_dict)

TOP_LEVEL_IMPORT = '''import definitely_not_installed_xyz

NODE = {"label": "Fancy Chart", "category": "Viz",
        "inputs": [("table", "dataframe")], "outputs": [("figure", "any")]}
PARAMS = [{"name": "title", "type": "string", "default": ""}]
def run(ctx, table):
    return {"figure": None}
'''

IMPORT_INSIDE_RUN = '''NODE = {"label": "Fancy Chart", "category": "Viz",
        "inputs": [], "outputs": [("figure", "any")]}
def run(ctx):
    import definitely_not_installed_xyz
    return {"figure": None}
'''


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def project(nodes, connections=()):
    return {"flograph_version": FLOGRAPH_VERSION, "schema": SCHEMA_VERSION,
            "graph": {"nodes": list(nodes), "connections": list(connections),
                      "frames": [], "pages": []}}


def node_entry(node_id, type_id="user.fancy", code=TOP_LEVEL_IMPORT, **kw):
    entry = {"id": node_id, "type": type_id, "pos": [0, 0],
             "params": {}, "code": code}
    entry.update(kw)
    return entry


class TestTheError:

    def test_a_missing_package_is_its_own_kind_of_error(self):
        with pytest.raises(MissingDependencyError) as caught:
            parse_spec(TOP_LEVEL_IMPORT, "user.fancy")
        assert caught.value.module == "definitely_not_installed_xyz"
        # still a script error, so every existing handler keeps working
        assert isinstance(caught.value, NodeScriptError)

    def test_it_says_what_would_fix_it(self):
        with pytest.raises(MissingDependencyError) as caught:
            parse_spec(TOP_LEVEL_IMPORT, "user.fancy")
        message = str(caught.value)
        assert "definitely_not_installed_xyz" in message
        assert "Manage Packages" in message
        assert "run()" in message   # the other way out

    def test_other_load_failures_are_not_confused_with_it(self):
        source = 'raise ValueError("boom")\nNODE = {}\n'
        with pytest.raises(NodeScriptError) as caught:
            parse_spec(source, "user.fancy")
        assert not isinstance(caught.value, MissingDependencyError)

    def test_a_syntax_error_still_reports_its_line(self):
        with pytest.raises(NodeScriptError, match="syntax error on line 2"):
            parse_spec("NODE = {}\ndef run(\n", "user.fancy")

    def test_the_hint_only_fires_for_missing_modules(self):
        assert missing_module_hint(
            ModuleNotFoundError("x", name="plotly")).startswith("The 'plotly'")
        assert missing_module_hint(ValueError("nope")) is None
        assert missing_module_hint(ImportError("cannot import name")) is None


class TestOpeningAProject:
    """The one place this used to be fatal: a forked node whose script
    can't load here took the whole file with it."""

    def test_the_project_still_opens(self, registry):
        data = project([
            node_entry("bad"),
            node_entry("good", "flograph.util.constant", code=None),
        ])
        graph = graph_from_dict(json.loads(json.dumps(data)), registry)
        assert set(graph.nodes) == {"bad", "good"}
        assert not graph.node("good").spec.broken

    def test_the_node_says_why_and_how_to_fix_it(self, registry):
        graph = graph_from_dict(project([node_entry("bad")]), registry)
        node = graph.node("bad")
        assert node.spec.broken
        assert node.status.name == "ERROR"
        assert "definitely_not_installed_xyz" in node.status_message
        assert "Manage Packages" in node.status_message

    def test_an_unknown_type_still_gets_its_own_wording(self, registry):
        """The pre-existing case must not inherit the dependency message."""
        graph = graph_from_dict(
            project([node_entry("gone", "flograph.nope.gone", code=None)]),
            registry)
        assert "not available in this build" \
            in graph.node("gone").spec.doc
        assert "Unknown node type" in graph.node("gone").status_message

    def test_nothing_the_user_wrote_is_lost(self, registry):
        """Re-saving a file opened with a broken node must write it back
        byte for byte — otherwise opening a project on the wrong machine
        quietly destroys work."""
        entry = node_entry("bad", params={"title": "My chart"},
                           label="Renamed", description="notes",
                           color="#ff0000")
        graph = graph_from_dict(project([entry]), registry)
        saved = next(e for e in graph_to_dict(graph)["graph"]["nodes"]
                     if e["id"] == "bad")
        assert saved["code"] == TOP_LEVEL_IMPORT
        assert saved["params"] == {"title": "My chart"}
        assert saved["label"] == "Renamed"
        assert saved["description"] == "notes"
        assert saved["color"] == "#ff0000"

    def test_its_wiring_survives(self, registry):
        data = project(
            [node_entry("src", "flograph.util.constant", code=None),
             node_entry("bad")],
            [{"id": "c1", "src": ["src", "value"], "dst": ["bad", "table"]}])
        graph = graph_from_dict(data, registry)
        assert len(graph.connections) == 1
        assert [p.name for p in graph.node("bad").spec.inputs] == ["table"]


class TestTheOtherSurfaces:
    """These already behaved; the tests pin them so they keep behaving."""

    def test_a_user_node_directory_skips_the_bad_file(self, registry, tmp_path):
        (tmp_path / "fancy.py").write_text(TOP_LEVEL_IMPORT)
        (tmp_path / "fine.py").write_text(
            'NODE = {"label": "Fine", "category": "Util",\n'
            '        "inputs": [], "outputs": [("value", "any")]}\n'
            'def run(ctx):\n    return {"value": 1}\n')
        errors = registry.reload_user_nodes(tmp_path)
        assert [p.name for p, _ in errors] == ["fancy.py"]
        assert "definitely_not_installed_xyz" in errors[0][1]
        assert registry.maybe_get("user.fine") is not None

    def test_compiling_it_to_run_raises_rather_than_crashing(self):
        with pytest.raises(MissingDependencyError):
            compile_run(TOP_LEVEL_IMPORT, "node123")

    def test_a_run_time_import_error_carries_the_hint(self):
        from flograph.engine.errors import build_node_error
        try:
            compile_run(IMPORT_INSIDE_RUN, "n1")(SimpleNamespace(params={}))
        except Exception as exc:      # noqa: BLE001 — that's the point
            error = build_node_error("n1", IMPORT_INSIDE_RUN, exc)
        assert "definitely_not_installed_xyz" in error.message
        assert "Manage Packages" in error.message
        assert "Manage Packages" in error.formatted_tb
        # the node line is still located, hint or no hint
        assert error.script_line == 4

    def test_an_ordinary_run_error_is_untouched(self):
        from flograph.engine.errors import build_node_error
        source = ('NODE = {"label": "X", "category": "Util",\n'
                  '        "inputs": [], "outputs": [("v", "any")]}\n'
                  'def run(ctx):\n    raise ValueError("boom")\n')
        try:
            compile_run(source, "n1")(SimpleNamespace(params={}))
        except Exception as exc:      # noqa: BLE001
            error = build_node_error("n1", source, exc)
        assert error.message == "ValueError: boom"


class TestRecoveringFromIt:

    @pytest.fixture
    def env(self, qtbot, registry):
        from flograph.ui.editor.editor_dock import EditorPanel
        graph = graph_from_dict(
            project([node_entry("bad", code=RECOVERABLE)]), registry)
        stack = QUndoStack()
        panel = EditorPanel(graph, stack, registry)
        qtbot.addWidget(panel)
        panel.set_node("bad")
        yield SimpleNamespace(graph=graph, panel=panel, stack=stack)
        sys.modules.pop("pretend_lib", None)

    def test_the_editor_still_shows_the_code(self, env):
        """A broken node's spec has no source of its own — the code lives
        on the instance, and that is what makes this recoverable at all."""
        assert "pretend_lib" in env.panel.editor.toPlainText()

    def test_applying_it_while_still_missing_reports_the_reason(self, env):
        env.panel.apply_code()
        assert "pretend_lib" in env.panel._message.text()
        assert env.graph.node("bad").spec.broken

    def test_applying_it_unchanged_after_installing_repairs_the_node(self, env):
        """Nothing about the text changed — installing the package is the
        edit. Refusing this as "no changes to apply" would leave the node
        broken with no way back short of typing a character."""
        sys.modules["pretend_lib"] = types.ModuleType("pretend_lib")
        env.panel.apply_code()

        node = env.graph.node("bad")
        assert env.panel._message.text() == "Applied."
        assert not node.spec.broken
        assert node.spec.label == "Fancy Chart"
        assert [p.name for p in node.spec.outputs] == ["figure"]

    def test_a_healthy_node_still_refuses_a_no_op_apply(self, env, registry):
        graph = Graph()
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        from flograph.ui.editor.editor_dock import EditorPanel
        panel = EditorPanel(graph, QUndoStack(), registry)
        panel.set_node(node.id)
        panel.apply_code()
        assert panel._message.text() == "No changes to apply."


RECOVERABLE = '''import pretend_lib

NODE = {"label": "Fancy Chart", "category": "Viz",
        "inputs": [], "outputs": [("figure", "any")]}
def run(ctx):
    return {"figure": pretend_lib.make()}
'''


#: Modules a node script may import at the top level: the standard library
#: pieces small enough not to matter, plus `flograph.core` — the Qt-free,
#: dependency-free half of the app itself, which the registry doing the
#: parsing has already imported. `typing` and `__future__` cover a node
#: whose module-level PARAMS-building code (Show Plotly, Chart per Value
#: (Plotly)) is typed. `flograph.ui` and `flograph.engine` are deliberately
#: not allowed: those do pull in Qt, at registry-load time, for every node.
TOP_LEVEL_IMPORTS_OK = ("json", "uuid", "math", "datetime", "re", "os",
                        "sys", "textwrap", "base64", "typing", "__future__")


def _import_is_allowed(name: str) -> bool:
    if name == "flograph.core" or name.startswith("flograph.core."):
        return True
    return name.split(".")[0] in TOP_LEVEL_IMPORTS_OK


def test_no_builtin_imports_a_third_party_package_at_top_level():
    """The shipped nodes must load on a bare install — load_builtins raises
    rather than skipping, so one top-level import would be a dead app."""
    import ast
    import importlib.resources

    offenders = []
    root = importlib.resources.files("flograph.nodes")
    for pkg in root.iterdir():
        if not pkg.is_dir() or pkg.name.startswith(("_", ".")):
            continue
        for entry in pkg.iterdir():
            if not entry.name.endswith(".py") or entry.name.startswith("_"):
                continue
            tree = ast.parse(entry.read_text())
            for node in tree.body:      # top level only — inside run() is fine
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    name = (node.names[0].name if isinstance(node, ast.Import)
                            else (node.module or ""))
                    if not _import_is_allowed(name):
                        offenders.append(f"{pkg.name}/{entry.name}: {name}")
    assert offenders == []


def test_a_node_may_not_reach_the_ui_at_the_top_level():
    """The allowance above is for `flograph.core` alone — the Qt-free half.

    Importing `flograph.ui` from a node's module level would drag Qt in at
    registry load, for every node, in a headless run included.
    """
    assert _import_is_allowed("flograph.core.plotly_spec")
    assert not _import_is_allowed("flograph.ui.canvas")
    assert not _import_is_allowed("flograph.engine")
    assert not _import_is_allowed("flograph")
    assert not _import_is_allowed("pandas")
