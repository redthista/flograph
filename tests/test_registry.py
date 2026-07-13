import pandas as pd
import pytest

from flograph.core import NodeRegistry, fuzzy_score
from tests.conftest import FakeContext


class TestBuiltinDiscovery:
    def test_seed_nodes_load(self, registry):
        type_ids = {spec.type_id for spec in registry.all()}
        assert {"flograph.util.constant", "flograph.util.reroute",
                "flograph.scripting.python_script", "flograph.transform.filter_rows",
                "flograph.io.read_csv"} <= type_ids
        assert all(spec.builtin for spec in registry.all())

    def test_categories(self, registry):
        cats = registry.categories()
        assert "Util" in cats and "Transform" in cats

    def test_instantiate(self, registry):
        node = registry.instantiate("flograph.util.constant", pos=(10, 20))
        assert node.pos == (10, 20)
        assert node.params == {"kind": "string", "value": ""}
        assert node.dirty and not node.forked

    def test_unknown_type(self, registry):
        with pytest.raises(KeyError, match="unknown node type"):
            registry.get("flograph.nope.missing")


class TestSearch:
    def test_word_start_fuzzy(self, registry):
        results = registry.search("fr")
        assert results and results[0].label == "Filter Rows"

    def test_empty_query_returns_all(self, registry):
        assert len(registry.search("  ")) == len(registry.all())

    def test_no_match(self, registry):
        assert registry.search("zzzzqqq") == []

    def test_scorer_prefers_word_starts(self):
        assert fuzzy_score("fr", "Filter Rows") > fuzzy_score("fr", "from")
        assert fuzzy_score("xyz", "Filter Rows") == 0.0


class TestSeedNodeBehaviour:
    def test_constant(self, registry):
        run_source = registry.get("flograph.util.constant").source
        from flograph.core import compile_run
        run = compile_run(run_source, "n1")
        assert run(FakeContext(params={"kind": "int", "value": "42"})) == 42
        assert run(FakeContext(params={"kind": "bool", "value": "yes"})) is True
        assert run(FakeContext(params={"kind": "string", "value": "hi"})) == "hi"

    def test_filter_rows(self, registry):
        from flograph.core import compile_run
        run = compile_run(registry.get("flograph.transform.filter_rows").source, "n2")
        table = pd.DataFrame({"x": [1, -2, 3]})
        ctx = FakeContext(params={"query": "x > 0"})
        result = run(ctx, table=table)
        assert list(result["filtered"]["x"]) == [1, 3]
        assert list(result["rejected"]["x"]) == [-2]
        assert ctx.logs == ["kept 2 / 3 rows"]

    def test_filter_rows_empty_query_passes_through(self, registry):
        from flograph.core import compile_run
        run = compile_run(registry.get("flograph.transform.filter_rows").source, "n3")
        table = pd.DataFrame({"x": [1]})
        result = run(FakeContext(params={"query": " "}), table=table)
        assert result["filtered"] is table
        assert len(result["rejected"]) == 0

    def test_read_csv(self, registry, tmp_path):
        from flograph.core import compile_run
        csv = tmp_path / "data.csv"
        csv.write_text("a,b\n1,2\n3,4\n")
        run = compile_run(registry.get("flograph.io.read_csv").source, "n4")
        table = run(FakeContext(params={"path": str(csv), "sep": ",", "header": True}))
        assert list(table.columns) == ["a", "b"]
        assert len(table) == 2

    def test_read_csv_requires_path(self, registry):
        from flograph.core import compile_run
        run = compile_run(registry.get("flograph.io.read_csv").source, "n5")
        with pytest.raises(ValueError, match="no file selected"):
            run(FakeContext(params={"path": "", "sep": ",", "header": True}))
