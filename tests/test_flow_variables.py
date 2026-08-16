"""Flow-level variables: the derived `${name}` edges, the substitution that
happens at dispatch, and the .env file behind `${env:NAME}`."""
import json

import pandas as pd
import pytest

from flograph.core import Graph, NodeInstance, NodeRegistry, parse_spec, serialization
from flograph.core import dotenv, varlinks
from flograph.core.varlinks import (
    VariableError, link_id, parse_assignments, resolve_var_links, substitute,
    var_problem,
)
from flograph.engine import ExecutionEngine
from flograph.engine.cache_persistence import (
    node_fingerprint, resolve_entries, save_cache,
)

VARS = "flograph.util.variables"

ECHO = """
NODE = {
    "label": "Echo",
    "category": "Test",
    "inputs": [],
    "outputs": [("value", "any")],
}
PARAMS = [
    {"name": "text", "type": "string", "default": ""},
    {"name": "count", "type": "int", "default": 0},
]
def run(ctx):
    return {"value": ctx.params["text"]}
"""

SEES_VARS = """
NODE = {
    "label": "Sees",
    "category": "Test",
    "inputs": [],
    "outputs": [("value", "any")],
}
PARAMS = [{"name": "text", "type": "string", "default": ""}]
def run(ctx):
    return {"value": dict(ctx.vars)}
"""


def echo(type_id="test.echo", source=ECHO):
    return NodeInstance.create(parse_spec(source, type_id))


def wait_run(qtbot, engine, trigger, timeout=5000):
    with qtbot.waitSignal(engine.run_finished, timeout=timeout) as blocker:
        trigger()
    return blocker.args[0]


@pytest.fixture
def flow(registry):
    """A Variables node declaring `region`, and an Echo reading ${region}
    with no wire between them."""
    graph = Graph()
    variables = graph.add_node(registry.instantiate(VARS))
    consumer = graph.add_node(echo())
    graph.set_param(variables.id, "assignments", "region = North")
    graph.set_param(consumer.id, "text", "sales in ${region}")
    return graph, variables, consumer


# ------------------------------------------------------------- parsing

class TestAssignments:
    def test_name_value_per_line(self):
        values, problems = parse_assignments(
            "data_dir = C:/data\n\n# a comment\nregion=North\n")
        assert values == {"data_dir": "C:/data", "region": "North"}
        assert problems == []

    def test_value_may_contain_equals(self):
        values, _ = parse_assignments("query = a == 1")
        assert values == {"query": "a == 1"}

    def test_problems_are_reported_not_raised(self):
        values, problems = parse_assignments("no equals here\n2bad = x\nok = 1")
        assert values == {"ok": "1"}
        assert len(problems) == 2

    def test_duplicate_name_is_a_problem(self):
        _, problems = parse_assignments("a = 1\na = 2")
        assert "defined twice" in problems[0]


class TestSubstitution:
    def test_replaces_every_reference(self):
        assert substitute("${a}/${b}/${a}", {"a": "x", "b": "y"}) == "x/y/x"

    def test_unknown_name_raises(self):
        with pytest.raises(VariableError, match="no variable named 'nope'"):
            substitute("${nope}", {})

    def test_pandas_column_selection_is_not_a_reference(self):
        # the reason for ${} over [[]]: this is ordinary text in an
        # Expression or Python Script param and must survive untouched
        text = "out = df[['a','b']]"
        assert substitute(text, {}) == text

    def test_env_reference_reads_the_env_mapping(self):
        assert substitute("${env:TOKEN}", {}, {"TOKEN": "s3cret"}) == "s3cret"

    def test_missing_secret_raises(self):
        with pytest.raises(VariableError, match="no secret named"):
            substitute("${env:TOKEN}", {}, {})


# -------------------------------------------------------------- edges

class TestDerivedEdges:
    def test_reference_becomes_an_edge_but_not_a_connection(self, flow):
        graph, variables, consumer = flow
        assert list(graph.var_links) == [link_id(consumer.id, variables.id)]
        assert graph.connections == {}
        edge = graph.var_links[link_id(consumer.id, variables.id)]
        assert (edge.src_node, edge.dst_node) == (variables.id, consumer.id)

    def test_the_edge_orders_the_run_with_no_wire(self, flow):
        graph, variables, consumer = flow
        assert graph.topo_order().index(variables.id) < \
               graph.topo_order().index(consumer.id)
        assert consumer.id in graph.successors(variables.id)

    def test_a_portless_edge_never_answers_input_connection(self, flow):
        graph, variables, consumer = flow
        # The dangerous failure mode: input_connection must only ever return
        # an edge that really carries a value to that port.
        assert graph.input_connection(consumer.id, "") is None
        assert graph.in_connections(consumer.id)      # ...but it is a dependency

    def test_editing_the_value_dirties_the_consumer(self, flow):
        graph, variables, consumer = flow
        graph.mark_clean(consumer.id)
        graph.set_param(variables.id, "assignments", "region = South")
        assert consumer.dirty

    def test_removing_the_reference_drops_the_edge(self, flow):
        graph, variables, consumer = flow
        graph.set_param(consumer.id, "text", "no references here")
        assert graph.var_links == {}

    def test_two_names_from_one_node_share_one_edge(self, registry):
        graph = Graph()
        variables = graph.add_node(registry.instantiate(VARS))
        consumer = graph.add_node(echo())
        graph.set_param(variables.id, "assignments", "a = 1\nb = 2")
        graph.set_param(consumer.id, "text", "${a}/${b}")
        assert len(graph.var_links) == 1

    def test_a_variables_node_reading_itself_makes_no_edge(self, registry):
        graph = Graph()
        variables = graph.add_node(registry.instantiate(VARS))
        graph.set_param(variables.id, "assignments", "a = ${a}")
        assert graph.var_links == {}

    def test_a_loop_is_refused(self, registry):
        # consumer -> variables by wire, and consumer reads ${a}: taking the
        # edge would close a cycle, so it is refused and explained.
        graph = Graph()
        variables = graph.add_node(registry.instantiate(VARS))
        consumer = graph.add_node(echo())
        graph.connect(consumer.id, "value", variables.id, "values")
        graph.set_param(variables.id, "assignments", "a = 1")
        graph.set_param(consumer.id, "text", "${a}")
        assert graph.var_links == {}
        assert "loop" in var_problem(graph, consumer.id)


class TestProblems:
    def test_unknown_name(self, registry):
        graph = Graph()
        consumer = graph.add_node(echo())
        graph.set_param(consumer.id, "text", "${nope}")
        assert "no variable named 'nope'" in var_problem(graph, consumer.id)

    def test_two_nodes_declaring_one_name_is_refused(self, registry):
        graph = Graph()
        for _ in range(2):
            node = graph.add_node(registry.instantiate(VARS))
            graph.set_param(node.id, "assignments", "region = North")
        consumer = graph.add_node(echo())
        graph.set_param(consumer.id, "text", "${region}")
        assert graph.var_links == {}
        assert "more than one" in var_problem(graph, consumer.id)

    def test_a_clean_flow_has_no_problem(self, flow):
        graph, _variables, consumer = flow
        assert var_problem(graph, consumer.id) is None


# -------------------------------------------------------- fingerprints

class TestFingerprint:
    def test_the_value_changes_the_consumers_fingerprint(self, flow):
        graph, variables, consumer = flow
        before = node_fingerprint(graph, consumer.id, {})
        graph.set_param(variables.id, "assignments", "region = South")
        after = node_fingerprint(graph, consumer.id, {})
        # The regression test for the whole feature: without the variable
        # edge these hash identically and the engine serves South's cached
        # frame for North.
        assert before != after

    def test_a_changed_value_invalidates_the_saved_cache(self, qtbot,
                                                         registry, tmp_path):
        """Save/reopen round trip — the claim the whole design rests on.

        Unchanged, the cached output must come back (or every consumer of a
        variable would silently lose cache persistence). Changed, it must
        not (or the flow serves North's numbers while the card says South).
        """
        graph = Graph()
        variables = graph.add_node(registry.instantiate(VARS))
        consumer = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_param(variables.id, "assignments", "region = North")
        graph.set_param(consumer.id, "value", "${region}")

        engine = ExecutionEngine(graph)
        assert wait_run(qtbot, engine, engine.run_all)
        project = tmp_path / "flow.flograph"
        serialization.save(graph, project)
        save_cache(graph, engine.cache, project)

        reopened = serialization.load(project, registry)
        assert consumer.id in dict(resolve_entries(reopened, project))

        changed = serialization.load(project, registry)
        moved = next(n for n in changed.nodes.values()
                     if n.type_id.endswith("variables"))
        changed.set_param(moved.id, "assignments", "region = South")
        assert consumer.id not in dict(resolve_entries(changed, project))

    def test_an_unrelated_edit_does_not(self, flow):
        graph, variables, consumer = flow
        before = node_fingerprint(graph, consumer.id, {})
        other = graph.add_node(echo("test.other"))
        graph.set_param(other.id, "text", "unrelated")
        assert node_fingerprint(graph, consumer.id, {}) == before


# ------------------------------------------------------------ end to end

class TestRunning:
    def test_the_param_arrives_substituted(self, qtbot, flow):
        graph, _variables, consumer = flow
        engine = ExecutionEngine(graph)
        assert wait_run(qtbot, engine, engine.run_all)
        assert engine.cache.outputs_for(consumer.id)["value"] == "sales in North"

    def test_scripts_see_ctx_vars(self, qtbot, registry):
        graph = Graph()
        variables = graph.add_node(registry.instantiate(VARS))
        consumer = graph.add_node(echo("test.sees", SEES_VARS))
        graph.set_param(variables.id, "assignments", "a = 1\nb = two")
        graph.set_param(consumer.id, "text", "${a}")
        engine = ExecutionEngine(graph)
        assert wait_run(qtbot, engine, engine.run_all)
        assert engine.cache.outputs_for(consumer.id)["value"] == {"a": "1",
                                                                 "b": "two"}

    def test_an_unknown_name_stops_the_node(self, qtbot, registry):
        graph = Graph()
        consumer = graph.add_node(echo())
        graph.set_param(consumer.id, "text", "${nope}")
        engine = ExecutionEngine(graph)
        failures = []
        engine.node_failed.connect(lambda nid, err: failures.append(err.message))
        assert not wait_run(qtbot, engine, engine.run_all)
        assert "no variable named 'nope'" in failures[0]
        assert consumer.id not in engine.cache.peek(consumer.id)

    def test_changing_a_value_re_runs_the_consumer(self, qtbot, flow):
        graph, variables, consumer = flow
        engine = ExecutionEngine(graph)
        assert wait_run(qtbot, engine, engine.run_all)
        graph.set_param(variables.id, "assignments", "region = South")
        assert wait_run(qtbot, engine, engine.run_all)
        assert engine.cache.outputs_for(consumer.id)["value"] == "sales in South"


class TestNodeInputs:
    def test_a_wired_dict_overrides_the_text(self, qtbot, registry, fake_ctx):
        source = registry.get(VARS).source
        run = _run_fn(source)
        ctx = fake_ctx({"assignments": "region = North",
                        "table_mode": "first row (columns are names)"})
        assert run(ctx, values={"region": "South"}) == {
            "vars": {"region": "South"}}

    def test_a_table_row_becomes_variables(self, registry, fake_ctx):
        run = _run_fn(registry.get(VARS).source)
        ctx = fake_ctx({"assignments": "",
                        "table_mode": "first row (columns are names)"})
        table = pd.DataFrame({"region": ["North"], "year": [2026]})
        assert run(ctx, table=table) == {"vars": {"region": "North",
                                                  "year": 2026}}

    def test_name_value_columns(self, registry, fake_ctx):
        run = _run_fn(registry.get(VARS).source)
        ctx = fake_ctx({"assignments": "", "table_mode": "name/value columns"})
        table = pd.DataFrame({"name": ["a", "b"], "value": ["1", "2"]})
        assert run(ctx, table=table) == {"vars": {"a": "1", "b": "2"}}

    def test_unusable_names_are_dropped_with_a_note(self, registry, fake_ctx):
        run = _run_fn(registry.get(VARS).source)
        ctx = fake_ctx({"assignments": "",
                        "table_mode": "first row (columns are names)"})
        table = pd.DataFrame({"2024": ["x"], "ok": ["y"]})
        assert run(ctx, table=table) == {"vars": {"ok": "y"}}
        assert any("not a valid variable name" in line for line in ctx.logs)


def _run_fn(source: str):
    namespace: dict = {}
    exec(compile(source, "<node:test>", "exec"), namespace)
    return namespace["run"]


# ------------------------------------------------------------------ .env

class TestDotenv:
    def test_round_trip(self, tmp_path):
        path = tmp_path / ".env"
        dotenv.save(path, {"TOKEN": "abc", "DB_PASS": "p @ss"})
        assert dotenv.load(path) == {"TOKEN": "abc", "DB_PASS": "p @ss"}

    def test_reads_what_these_files_actually_contain(self):
        assert dotenv.parse(
            '# comment\n\nexport A=1\nB="two"\nC=\'three\'\nnot a line\n'
        ) == {"A": "1", "B": "two", "C": "three"}

    def test_a_missing_file_is_an_empty_mapping(self, tmp_path):
        assert dotenv.load(tmp_path / "nope.env") == {}

    def test_written_owner_only(self, tmp_path):
        path = tmp_path / ".env"
        dotenv.save(path, {"A": "1"})
        assert path.stat().st_mode & 0o777 == 0o600

    def test_the_file_wins_over_the_process_environment(self, tmp_path,
                                                        monkeypatch):
        monkeypatch.setenv("SHARED", "from-shell")
        monkeypatch.setenv("ONLY_SHELL", "shell")
        path = tmp_path / ".env"
        dotenv.save(path, {"SHARED": "from-file"})
        env = dotenv.environment(path)
        assert env["SHARED"] == "from-file"
        assert env["ONLY_SHELL"] == "shell"

    def test_path_is_stored_relative_to_the_project(self, tmp_path):
        project = tmp_path / "flows" / "a.flograph"
        project.parent.mkdir(parents=True)
        project.write_text("{}")
        stored = dotenv.store_path(str(tmp_path / "flows" / ".env"), str(project))
        assert stored == ".env"
        assert dotenv.resolve_path(stored, str(project)) == tmp_path / "flows" / ".env"

    def test_a_path_outside_the_project_stays_absolute(self, tmp_path):
        project = tmp_path / "flows" / "a.flograph"
        project.parent.mkdir(parents=True)
        project.write_text("{}")
        stored = dotenv.store_path(str(tmp_path / "secrets" / ".env"), str(project))
        assert stored.endswith("secrets/.env")
        assert dotenv.resolve_path(stored, str(project)).is_absolute()


class TestSecrets:
    def test_a_secret_resolves_into_a_param(self, qtbot, registry, tmp_path):
        graph = Graph()
        consumer = graph.add_node(echo())
        graph.set_param(consumer.id, "text", "token=${env:TOKEN}")
        graph.env = {"TOKEN": "s3cret"}
        engine = ExecutionEngine(graph)
        assert wait_run(qtbot, engine, engine.run_all)
        assert engine.cache.outputs_for(consumer.id)["value"] == "token=s3cret"

    def test_a_secret_creates_no_edge(self, registry):
        graph = Graph()
        consumer = graph.add_node(echo())
        graph.set_param(consumer.id, "text", "${env:TOKEN}")
        assert graph.var_links == {}
        assert var_problem(graph, consumer.id) is None

    def test_a_missing_secret_stops_the_node(self, qtbot, registry):
        graph = Graph()
        consumer = graph.add_node(echo())
        graph.set_param(consumer.id, "text", "${env:TOKEN}")
        engine = ExecutionEngine(graph)
        failures = []
        engine.node_failed.connect(lambda nid, err: failures.append(err.message))
        assert not wait_run(qtbot, engine, engine.run_all)
        assert "no secret named 'TOKEN'" in failures[0]

    def test_a_secret_consumer_is_never_written_to_the_disk_cache(
            self, qtbot, registry, tmp_path):
        graph = Graph()
        plain = graph.add_node(echo("test.plain"))
        secret = graph.add_node(echo("test.secret"))
        graph.set_param(plain.id, "text", "safe")
        graph.set_param(secret.id, "text", "${env:TOKEN}")
        graph.env = {"TOKEN": "s3cret"}
        engine = ExecutionEngine(graph)
        assert wait_run(qtbot, engine, engine.run_all)

        project = tmp_path / "flow.flograph"
        project.write_text("{}")
        save_cache(graph, engine.cache, project)
        manifest = json.loads(
            (tmp_path / "flow.flograph.cache" / "manifest.json").read_text())
        assert plain.id in manifest["nodes"]
        assert secret.id not in manifest["nodes"]


class TestPersistence:
    def test_the_env_path_survives_a_round_trip(self, registry, tmp_path):
        graph = Graph()
        graph.env_path = "secrets/.env"
        path = tmp_path / "flow.flograph"
        serialization.save(graph, path)
        assert "env_path" in json.loads(path.read_text())["graph"]
        assert serialization.load(path, registry).env_path == "secrets/.env"

    def test_a_file_written_before_variables_existed_still_loads(
            self, registry, tmp_path):
        graph = Graph()
        path = tmp_path / "flow.flograph"
        serialization.save(graph, path)
        data = json.loads(path.read_text())
        del data["graph"]["env_path"]
        path.write_text(json.dumps(data))
        assert serialization.load(path, registry).env_path == ""

    def test_variable_edges_are_not_serialized(self, registry, tmp_path):
        # Builtin nodes both ends, so the reload really rebuilds the specs
        # this derivation reads from.
        graph = Graph()
        variables = graph.add_node(registry.instantiate(VARS))
        consumer = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_param(variables.id, "assignments", "region = North")
        graph.set_param(consumer.id, "value", "${region}")
        assert len(graph.var_links) == 1

        path = tmp_path / "flow.flograph"
        serialization.save(graph, path)
        assert "var_links" not in path.read_text()
        # ...and are re-derived on load, from the params alone
        assert len(serialization.load(path, registry).var_links) == 1
