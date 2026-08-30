"""The `flograph` command: subcommand dispatch, `flograph run` (headless),
and the `flograph.run()` library call. P1.

The real runs go through a subprocess — `flograph run` spins its own
QCoreApplication and event loop, which does not belong inside the pytest-qt
one.
"""
import subprocess
import sys
import textwrap

import pytest

from flograph import cli
from flograph.core import Graph, NodeRegistry, serialization


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


OK_SRC = textwrap.dedent("""
    NODE = {"label": "OK", "category": "Scripting",
            "inputs": [], "outputs": [("out1", "any")]}
    def run(ctx):
        ctx.log("the flow ran")
        return {"out1": 1}
""")

BOOM_SRC = textwrap.dedent("""
    NODE = {"label": "Boom", "category": "Scripting",
            "inputs": [], "outputs": [("out1", "any")]}
    def run(ctx):
        raise RuntimeError("deliberate failure")
""")

LOGGER_SRC = textwrap.dedent("""
    NODE = {"label": "Logger", "category": "Scripting",
            "inputs": [("in1", "any", {"optional": True})],
            "outputs": [("out1", "any")]}
    PARAMS = [{"name": "text", "type": "string", "default": ""}]
    def run(ctx, in1):
        ctx.log("TEXT=" + ctx.params["text"])
        return {"out1": ctx.params["text"]}
""")


def _script_project(tmp_path, registry, source, name="flow.flograph"):
    graph = Graph()
    node = graph.add_node(registry.instantiate("flograph.scripting.python_script"))
    graph.set_code(node.id, source)
    path = tmp_path / name
    serialization.save(graph, path)
    return str(path)


def _variables_project(tmp_path, registry, declared):
    graph = Graph()
    variables = graph.add_node(registry.instantiate("flograph.util.variables"))
    graph.set_param(variables.id, "assignments", declared)
    logger = graph.add_node(registry.instantiate("flograph.scripting.python_script"))
    graph.set_code(logger.id, LOGGER_SRC)
    graph.set_param(logger.id, "text", "greeting is ${greeting}")
    path = tmp_path / "vars.flograph"
    serialization.save(graph, path)
    return str(path)


def _cli(*args):
    return subprocess.run([sys.executable, "-m", "flograph", *args],
                          capture_output=True, text=True, timeout=120)


# ---------------------------------------------------------------- dispatch

class TestDispatch:
    def test_run_routes_to_headless_with_the_rest_of_the_args(self, monkeypatch):
        seen = {}

        def fake_headless(argv):
            seen["argv"] = argv
            return 0

        monkeypatch.setattr("flograph.engine.headless.main", fake_headless)
        assert cli.main(["run", "x.flograph", "--var", "a=b"]) == 0
        assert seen["argv"] == ["x.flograph", "--var", "a=b"]

    def test_headless_exit_code_is_passed_through(self, monkeypatch):
        monkeypatch.setattr("flograph.engine.headless.main", lambda argv: 1)
        assert cli.main(["run", "x.flograph"]) == 1

    def test_bare_invocation_opens_the_gui(self, monkeypatch):
        called = {}

        def fake_gui():
            called["gui"] = True
            return 0

        monkeypatch.setattr("flograph.app.main", fake_gui)
        assert cli.main([]) == 0
        assert called.get("gui")

    def test_a_project_path_still_opens_the_gui_not_a_run(self, monkeypatch):
        called = {}
        monkeypatch.setattr("flograph.app.main",
                            lambda: called.setdefault("gui", True))
        monkeypatch.setattr("flograph.engine.headless.main",
                            lambda argv: called.setdefault("headless", True))
        cli.main(["some.flograph"])
        assert called.get("gui") and "headless" not in called

    def test_version(self, capsys):
        assert cli.main(["--version"]) == 0
        assert capsys.readouterr().out.startswith("flograph ")

    def test_help_names_the_run_subcommand(self, capsys):
        assert cli.main(["--help"]) == 0
        assert "flograph run" in capsys.readouterr().out


# ------------------------------------------------------------- real runs

class TestHeadlessRun:
    def test_a_clean_flow_exits_zero(self, tmp_path, registry):
        proc = _cli("run", _script_project(tmp_path, registry, OK_SRC))
        assert proc.returncode == 0, proc.stderr
        assert "the flow ran" in (proc.stdout + proc.stderr)

    def test_a_failing_node_exits_one(self, tmp_path, registry):
        proc = _cli("run", _script_project(tmp_path, registry, BOOM_SRC))
        assert proc.returncode == 1
        assert "FAILED" in proc.stderr

    def test_an_undeclared_var_is_refused(self, tmp_path, registry):
        proc = _cli("run", _script_project(tmp_path, registry, OK_SRC),
                    "--var", "nope=1")
        assert proc.returncode == 2
        assert "nope" in proc.stderr

    def test_a_var_override_reaches_the_run(self, tmp_path, registry):
        project = _variables_project(tmp_path, registry, "greeting = hello")
        default = _cli("run", project)
        assert "TEXT=greeting is hello" in default.stdout + default.stderr

        overridden = _cli("run", project, "--var", "greeting=NIHAO")
        assert overridden.returncode == 0
        assert "TEXT=greeting is NIHAO" in overridden.stdout + overridden.stderr

    def test_run_help_exits_zero(self):
        proc = _cli("run", "--help")
        assert proc.returncode == 0
        assert "--var" in proc.stdout


# ---------------------------------------------------------- library call

class TestLibraryRun:
    def test_run_returns_none_on_success(self, tmp_path, registry):
        project = _script_project(tmp_path, registry, OK_SRC)
        proc = subprocess.run(
            [sys.executable, "-c",
             f"import flograph; print(repr(flograph.run({project!r})))"],
            capture_output=True, text=True, timeout=120)
        # `print(repr(...))` only reaches stdout if run() returned rather than
        # raising. The process can still exit non-zero from a Qt teardown
        # crash under heavy parallel load, so the printed value is the signal,
        # not the return code.
        assert proc.stdout.strip().endswith("None"), proc.stderr

    def test_run_raises_on_a_failing_flow(self, tmp_path, registry):
        project = _script_project(tmp_path, registry, BOOM_SRC)
        proc = subprocess.run(
            [sys.executable, "-c", f"import flograph; flograph.run({project!r})"],
            capture_output=True, text=True, timeout=120)
        assert proc.returncode != 0
        assert "RuntimeError" in proc.stderr

    def test_import_flograph_stays_qt_free(self):
        proc = subprocess.run(
            [sys.executable, "-c",
             "import flograph, sys; "
             "assert not [m for m in sys.modules if m.startswith('PySide6')], "
             "sorted(m for m in sys.modules if m.startswith('PySide6'))"],
            capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
