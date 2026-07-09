"""Every shipped node executed headless through the contract, including error
paths."""
import pandas as pd
import pytest

from flopy.core import compile_run
from tests.conftest import FakeContext


@pytest.fixture
def table():
    return pd.DataFrame({
        "region": ["north", "south", "north", "south"],
        "units": [10, 20, 30, 40],
        "revenue": [100.0, 150.0, 300.0, 320.0],
    })


def run_node(registry, type_id, params=None, **inputs):
    spec = registry.get(type_id)
    defaults = spec.default_params()
    defaults.update(params or {})
    run = compile_run(spec.source, f"test-{type_id}")
    return run(FakeContext(params=defaults), **inputs)


class TestTransformNodes:
    def test_select_columns_keep(self, registry, table):
        out = run_node(registry, "flopy.transform.select_columns",
                       {"columns": "region, units"}, table=table)
        assert list(out.columns) == ["region", "units"]

    def test_select_columns_drop(self, registry, table):
        out = run_node(registry, "flopy.transform.select_columns",
                       {"columns": "revenue", "mode": "drop"}, table=table)
        assert "revenue" not in out.columns

    def test_select_columns_missing(self, registry, table):
        with pytest.raises(ValueError, match="not in table"):
            run_node(registry, "flopy.transform.select_columns",
                     {"columns": "nope"}, table=table)

    def test_sort(self, registry, table):
        out = run_node(registry, "flopy.transform.sort",
                       {"by": "units", "descending": True}, table=table)
        assert list(out["units"]) == [40, 30, 20, 10]

    def test_sort_requires_columns(self, registry, table):
        with pytest.raises(ValueError, match="no sort columns"):
            run_node(registry, "flopy.transform.sort", {"by": " "}, table=table)

    def test_join(self, registry, table):
        prices = pd.DataFrame({"region": ["north", "south"],
                               "price": [12.5, 9.75]})
        out = run_node(registry, "flopy.transform.join",
                       {"on": "region"}, left=table, right=prices)
        assert "price" in out.columns and len(out) == 4

    def test_join_missing_key(self, registry, table):
        with pytest.raises(ValueError, match="missing from a side"):
            run_node(registry, "flopy.transform.join", {"on": "nope"},
                     left=table, right=table)

    def test_group_by(self, registry, table):
        out = run_node(registry, "flopy.transform.group_by",
                       {"by": "region", "agg": "sum"}, table=table)
        north = out[out["region"] == "north"]
        assert north["units"].iloc[0] == 40
        assert north["revenue"].iloc[0] == 400.0

    def test_group_by_explicit_values(self, registry, table):
        out = run_node(registry, "flopy.transform.group_by",
                       {"by": "region", "agg": "mean", "values": "units"},
                       table=table)
        assert list(out.columns) == ["region", "units"]

    def test_expression(self, registry, table):
        out = run_node(registry, "flopy.transform.expression",
                       {"expressions": "margin = revenue - units\n"
                                       "# comment line\n"
                                       "double = units * 2"},
                       table=table)
        assert list(out["margin"]) == [90.0, 130.0, 270.0, 280.0]
        assert list(out["double"]) == [20, 40, 60, 80]
        assert "margin" not in table.columns  # input untouched

    def test_expression_empty(self, registry, table):
        with pytest.raises(ValueError, match="no expressions"):
            run_node(registry, "flopy.transform.expression",
                     {"expressions": "  "}, table=table)

    def test_filter_empty_result(self, registry, table):
        out = run_node(registry, "flopy.transform.filter_rows",
                       {"query": "units > 1000"}, table=table)
        assert len(out["filtered"]) == 0
        assert len(out["rejected"]) == 4


class TestIONodes:
    def test_write_then_read_round_trip(self, registry, table, tmp_path):
        path = tmp_path / "out.csv"
        passed = run_node(registry, "flopy.io.write_csv",
                          {"path": str(path)}, table=table)
        assert passed is table  # pass-through
        back = run_node(registry, "flopy.io.read_csv", {"path": str(path)})
        assert list(back.columns) == list(table.columns)
        assert len(back) == len(table)

    def test_write_requires_path(self, registry, table):
        with pytest.raises(ValueError, match="no output file"):
            run_node(registry, "flopy.io.write_csv", {}, table=table)

    def test_write_then_read_excel_round_trip(self, registry, table, tmp_path):
        pytest.importorskip("openpyxl")
        path = tmp_path / "out.xlsx"
        passed = run_node(registry, "flopy.io.write_excel",
                          {"path": str(path)}, table=table)
        assert passed is table  # pass-through
        back = run_node(registry, "flopy.io.read_excel", {"path": str(path)})
        assert list(back.columns) == list(table.columns)
        assert len(back) == len(table)

    def test_write_excel_requires_path(self, registry, table):
        pytest.importorskip("openpyxl")
        with pytest.raises(ValueError, match="no output file"):
            run_node(registry, "flopy.io.write_excel", {}, table=table)

    def test_read_excel_requires_path(self, registry):
        pytest.importorskip("openpyxl")
        with pytest.raises(ValueError, match="no file selected"):
            run_node(registry, "flopy.io.read_excel", {})


class TestVizNodes:
    def test_plot_line_defaults(self, registry, table):
        fig = run_node(registry, "flopy.viz.plot", {}, table=table)
        from matplotlib.figure import Figure
        assert isinstance(fig, Figure)
        ax = fig.axes[0]
        assert len(ax.lines) == 2  # units + revenue

    def test_plot_explicit_columns(self, registry, table):
        fig = run_node(registry, "flopy.viz.plot",
                       {"x": "units", "y": "revenue", "kind": "scatter",
                        "title": "T"}, table=table)
        assert fig.axes[0].get_title() == "T"

    def test_plot_bad_column(self, registry, table):
        with pytest.raises(ValueError, match="not in table"):
            run_node(registry, "flopy.viz.plot", {"y": "nope"}, table=table)

    def test_plot_no_numeric(self, registry):
        with pytest.raises(ValueError, match="no numeric"):
            run_node(registry, "flopy.viz.plot", {},
                     table=pd.DataFrame({"s": ["a", "b"]}))

    def test_show_table_passthrough(self, registry, table):
        out = run_node(registry, "flopy.viz.show_table", {}, table=table)
        assert out["table"] is table

    def test_show_plot_line_defaults(self, registry, table):
        out = run_node(registry, "flopy.viz.show_plot", {}, table=table)
        from matplotlib.figure import Figure
        assert isinstance(out["figure"], Figure)
        ax = out["figure"].axes[0]
        assert len(ax.lines) == 2  # units + revenue

    def test_show_plot_bad_column(self, registry, table):
        with pytest.raises(ValueError, match="not in table"):
            run_node(registry, "flopy.viz.show_plot", {"y": "nope"}, table=table)


class TestUtilNodes:
    def test_reroute_passthrough(self, registry):
        sentinel = object()
        assert run_node(registry, "flopy.util.reroute", {}, value=sentinel) is sentinel

    def test_action_button_runs_as_noop(self, registry):
        assert run_node(registry, "flopy.util.action_button", {}) == {}
