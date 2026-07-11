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


class TestEtlNodes:
    def test_concatenate_union(self, registry, table):
        other = pd.DataFrame({"region": ["west"], "extra": [1]})
        out = run_node(registry, "flopy.transform.concatenate", {},
                       top=table, bottom=other)
        assert len(out) == 5
        assert "extra" in out.columns and out["extra"].isna().sum() == 4
        assert list(out.index) == list(range(5))  # reset by default

    def test_concatenate_intersection(self, registry, table):
        other = pd.DataFrame({"region": ["west"], "extra": [1]})
        out = run_node(registry, "flopy.transform.concatenate",
                       {"columns": "intersection"}, top=table, bottom=other)
        assert list(out.columns) == ["region"]

    def test_missing_values_drop(self, registry):
        t = pd.DataFrame({"a": [1.0, None, 3.0], "b": ["x", "y", None]})
        out = run_node(registry, "flopy.transform.missing_values", {}, table=t)
        assert len(out) == 1

    def test_missing_values_fill_value_parses_numbers(self, registry):
        t = pd.DataFrame({"a": [1.0, None]})
        out = run_node(registry, "flopy.transform.missing_values",
                       {"strategy": "fill value", "fill_value": "0"}, table=t)
        assert out["a"].iloc[1] == 0

    def test_missing_values_mean_subset(self, registry):
        t = pd.DataFrame({"a": [1.0, None, 3.0], "b": [None, "y", "z"]})
        out = run_node(registry, "flopy.transform.missing_values",
                       {"strategy": "mean", "columns": "a"}, table=t)
        assert out["a"].iloc[1] == 2.0
        assert out["b"].isna().iloc[0]  # untouched

    def test_missing_values_mean_needs_numeric(self, registry):
        with pytest.raises(ValueError, match="numeric"):
            run_node(registry, "flopy.transform.missing_values",
                     {"strategy": "mean", "columns": "s"},
                     table=pd.DataFrame({"s": ["a", None]}))

    def test_duplicate_filter(self, registry, table):
        doubled = pd.concat([table, table], ignore_index=True)
        out = run_node(registry, "flopy.transform.duplicate_filter", {},
                       table=doubled)
        assert len(out["unique"]) == 4 and len(out["duplicates"]) == 4

    def test_duplicate_filter_keep_none(self, registry, table):
        doubled = pd.concat([table, table], ignore_index=True)
        out = run_node(registry, "flopy.transform.duplicate_filter",
                       {"keep": "none"}, table=doubled)
        assert len(out["unique"]) == 0 and len(out["duplicates"]) == 8

    def test_duplicate_filter_subset(self, registry, table):
        out = run_node(registry, "flopy.transform.duplicate_filter",
                       {"columns": "region"}, table=table)
        assert len(out["unique"]) == 2

    def test_rename_columns(self, registry, table):
        out = run_node(registry, "flopy.transform.rename_columns",
                       {"mapping": "units = qty\n# note\nrevenue = usd"},
                       table=table)
        assert "qty" in out.columns and "usd" in out.columns
        assert "units" in table.columns  # input untouched

    def test_rename_columns_bad_line(self, registry, table):
        with pytest.raises(ValueError, match="line 1"):
            run_node(registry, "flopy.transform.rename_columns",
                     {"mapping": "just-a-word"}, table=table)

    def test_rename_columns_missing(self, registry, table):
        with pytest.raises(ValueError, match="not in table"):
            run_node(registry, "flopy.transform.rename_columns",
                     {"mapping": "nope = x"}, table=table)

    def test_pivot(self, registry, table):
        out = run_node(registry, "flopy.transform.pivot",
                       {"index": "region", "columns": "units",
                        "values": "revenue"}, table=table)
        assert len(out) == 2 and "region" in out.columns

    def test_pivot_requires_index(self, registry, table):
        with pytest.raises(ValueError, match="no index columns"):
            run_node(registry, "flopy.transform.pivot",
                     {"columns": "units"}, table=table)

    def test_unpivot_roundtrip_shape(self, registry, table):
        out = run_node(registry, "flopy.transform.unpivot",
                       {"id_columns": "region"}, table=table)
        assert list(out.columns) == ["region", "variable", "value"]
        assert len(out) == 8  # 4 rows x 2 value columns

    def test_row_sampling_first(self, registry, table):
        out = run_node(registry, "flopy.transform.row_sampling",
                       {"rows": 2}, table=table)
        assert list(out["units"]) == [10, 20]

    def test_row_sampling_fraction_random_is_seeded(self, registry, table):
        a = run_node(registry, "flopy.transform.row_sampling",
                     {"mode": "random", "fraction": 0.5, "seed": 7},
                     table=table)
        b = run_node(registry, "flopy.transform.row_sampling",
                     {"mode": "random", "fraction": 0.5, "seed": 7},
                     table=table)
        assert len(a) == 2 and a.equals(b)

    def test_convert_types(self, registry):
        t = pd.DataFrame({"n": ["1", "2"], "d": ["2024-01-01", "2024-06-01"]})
        out = run_node(registry, "flopy.transform.convert_types",
                       {"columns": "n", "to": "int"}, table=t)
        assert str(out["n"].dtype) == "Int64"
        out = run_node(registry, "flopy.transform.convert_types",
                       {"columns": "d", "to": "datetime"}, table=t)
        assert out["d"].dt.year.iloc[0] == 2024

    def test_convert_types_coerce(self, registry):
        t = pd.DataFrame({"n": ["1", "oops"]})
        with pytest.raises(Exception):
            run_node(registry, "flopy.transform.convert_types",
                     {"columns": "n", "to": "float"}, table=t)
        out = run_node(registry, "flopy.transform.convert_types",
                       {"columns": "n", "to": "float",
                        "on_error": "set missing"}, table=t)
        assert out["n"].isna().iloc[1]

    def test_string_manipulation_case(self, registry, table):
        out = run_node(registry, "flopy.transform.string_manipulation",
                       {"column": "region", "operation": "upper"}, table=table)
        assert out["region"].iloc[0] == "NORTH"
        assert table["region"].iloc[0] == "north"  # input untouched

    def test_string_manipulation_replace_new_column(self, registry, table):
        out = run_node(registry, "flopy.transform.string_manipulation",
                       {"column": "region", "operation": "replace",
                        "find": "north", "replace_with": "N",
                        "output_column": "code"}, table=table)
        assert out["code"].iloc[0] == "N" and out["region"].iloc[0] == "north"

    def test_string_manipulation_replace_needs_find(self, registry, table):
        with pytest.raises(ValueError, match="Find"):
            run_node(registry, "flopy.transform.string_manipulation",
                     {"column": "region", "operation": "replace"}, table=table)

    def test_statistics(self, registry, table):
        out = run_node(registry, "flopy.transform.statistics", {}, table=table)
        assert "statistic" in out.columns
        mean_row = out[out["statistic"] == "mean"]
        assert mean_row["units"].iloc[0] == 25.0


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

    def test_write_then_read_parquet_round_trip(self, registry, table, tmp_path):
        pytest.importorskip("pyarrow")
        path = tmp_path / "out.parquet"
        passed = run_node(registry, "flopy.io.write_parquet",
                          {"path": str(path)}, table=table)
        assert passed is table
        back = run_node(registry, "flopy.io.read_parquet", {"path": str(path)})
        assert back.equals(table)
        subset = run_node(registry, "flopy.io.read_parquet",
                          {"path": str(path), "columns": "region"})
        assert list(subset.columns) == ["region"]

    def test_write_then_read_json_round_trip(self, registry, table, tmp_path):
        path = tmp_path / "out.json"
        run_node(registry, "flopy.io.write_json", {"path": str(path)},
                 table=table)
        back = run_node(registry, "flopy.io.read_json", {"path": str(path)})
        assert list(back.columns) == list(table.columns)
        assert len(back) == len(table)

    def test_write_then_read_jsonl_round_trip(self, registry, table, tmp_path):
        path = tmp_path / "out.jsonl"
        run_node(registry, "flopy.io.write_json",
                 {"path": str(path), "layout": "lines"}, table=table)
        assert len(path.read_text().strip().splitlines()) == len(table)
        back = run_node(registry, "flopy.io.read_json",
                        {"path": str(path), "layout": "lines"})
        assert len(back) == len(table)

    def test_write_then_read_sqlite_round_trip(self, registry, table, tmp_path):
        path = tmp_path / "out.db"
        passed = run_node(registry, "flopy.io.write_sqlite",
                          {"path": str(path), "table_name": "sales"},
                          table=table)
        assert passed is table
        back = run_node(registry, "flopy.io.read_sqlite",
                        {"path": str(path), "query": "SELECT * FROM sales"})
        assert list(back.columns) == list(table.columns)
        assert len(back) == len(table)
        top = run_node(registry, "flopy.io.read_sqlite",
                       {"path": str(path),
                        "query": "SELECT region, units FROM sales "
                                 "WHERE units > 15"})
        assert len(top) == 3

    def test_read_sqlite_requires_query(self, registry, tmp_path):
        with pytest.raises(ValueError, match="no SQL query"):
            run_node(registry, "flopy.io.read_sqlite",
                     {"path": str(tmp_path / "x.db")})


class TestVizNodes:
    def test_plot_line_defaults(self, registry, table):
        out = run_node(registry, "flopy.viz.show_plot", {}, table=table)
        from matplotlib.figure import Figure
        assert isinstance(out["figure"], Figure)
        ax = out["figure"].axes[0]
        assert len(ax.lines) == 2  # units + revenue

    def test_plot_explicit_columns(self, registry, table):
        out = run_node(registry, "flopy.viz.show_plot",
                       {"x": "units", "y": "revenue", "kind": "scatter",
                        "title": "T"}, table=table)
        assert out["figure"].axes[0].get_title() == "T"

    def test_plot_bad_column(self, registry, table):
        with pytest.raises(ValueError, match="not in table"):
            run_node(registry, "flopy.viz.show_plot", {"y": "nope"}, table=table)

    def test_plot_no_numeric(self, registry):
        with pytest.raises(ValueError, match="no numeric"):
            run_node(registry, "flopy.viz.show_plot", {},
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


class TestCardNode:
    def test_sum(self, registry, table):
        out = run_node(registry, "flopy.viz.card",
                       {"column": "units"}, table=table)
        assert out["value"] == 100
        assert isinstance(out["value"], int)  # numpy scalar unwrapped

    def test_average(self, registry, table):
        out = run_node(registry, "flopy.viz.card",
                       {"column": "revenue", "aggregation": "Average"},
                       table=table)
        assert out["value"] == pytest.approx(217.5)

    def test_count_is_non_null(self, registry):
        df = pd.DataFrame({"v": [1.0, None, 3.0]})
        out = run_node(registry, "flopy.viz.card",
                       {"column": "v", "aggregation": "Count"}, table=df)
        assert out["value"] == 2

    def test_distinct_count(self, registry, table):
        out = run_node(registry, "flopy.viz.card",
                       {"column": "region", "aggregation": "Distinct count"},
                       table=table)
        assert out["value"] == 2

    def test_first_and_last(self, registry, table):
        first = run_node(registry, "flopy.viz.card",
                         {"column": "region", "aggregation": "First"},
                         table=table)
        last = run_node(registry, "flopy.viz.card",
                        {"column": "region", "aggregation": "Last"},
                        table=table)
        assert (first["value"], last["value"]) == ("north", "south")

    def test_requires_column(self, registry, table):
        with pytest.raises(ValueError, match="no column selected"):
            run_node(registry, "flopy.viz.card", {}, table=table)

    def test_bad_column(self, registry, table):
        with pytest.raises(ValueError, match="not in table"):
            run_node(registry, "flopy.viz.card", {"column": "nope"},
                     table=table)

    def test_first_on_empty_table(self, registry):
        with pytest.raises(ValueError, match="no rows"):
            run_node(registry, "flopy.viz.card",
                     {"column": "v", "aggregation": "First"},
                     table=pd.DataFrame({"v": []}))

    def test_average_of_strings_is_actionable(self, registry, table):
        with pytest.raises(ValueError, match="cannot compute Average"):
            run_node(registry, "flopy.viz.card",
                     {"column": "region", "aggregation": "Average"},
                     table=table)


class TestSlicerNode:
    def test_no_selection_passes_everything(self, registry, table):
        out = run_node(registry, "flopy.viz.slicer",
                       {"column": "region"}, table=table)
        assert out["table"] is table

    def test_json_selection_filters(self, registry, table):
        out = run_node(registry, "flopy.viz.slicer",
                       {"column": "region", "selected": '["north"]'},
                       table=table)
        assert list(out["table"]["units"]) == [10, 30]
        assert list(table["units"]) == [10, 20, 30, 40]  # input untouched

    def test_comma_list_selection_filters(self, registry, table):
        out = run_node(registry, "flopy.viz.slicer",
                       {"column": "region", "selected": "north, south"},
                       table=table)
        assert len(out["table"]) == 4

    def test_matches_values_as_strings(self, registry, table):
        out = run_node(registry, "flopy.viz.slicer",
                       {"column": "units", "selected": '["10", "40"]'},
                       table=table)
        assert list(out["table"]["units"]) == [10, 40]

    def test_requires_column(self, registry, table):
        with pytest.raises(ValueError, match="no column selected"):
            run_node(registry, "flopy.viz.slicer", {}, table=table)

    def test_bad_column(self, registry, table):
        with pytest.raises(ValueError, match="not in table"):
            run_node(registry, "flopy.viz.slicer", {"column": "nope"},
                     table=table)


class TestTableSpecNode:
    def test_spec_shape(self, registry, table):
        out = run_node(registry, "flopy.viz.table_spec", {}, table=table)
        spec = out["spec"]
        assert list(spec.columns) == ["column", "type", "non-null",
                                      "unique", "min", "max"]
        assert list(spec["column"]) == ["region", "units", "revenue"]

    def test_spec_values(self, registry, table):
        out = run_node(registry, "flopy.viz.table_spec", {}, table=table)
        units = out["spec"].set_index("column").loc["units"]
        assert units["non-null"] == "4 / 4"
        assert (units["min"], units["max"]) == ("10", "40")

    def test_spec_survives_awkward_cells(self, registry):
        df = pd.DataFrame({"o": [{"a": 1}, {"b": 2}]})  # unhashable cells
        out = run_node(registry, "flopy.viz.table_spec", {}, table=df)
        assert out["spec"].loc[0, "unique"] == ""


class TestUtilNodes:
    def test_reroute_passthrough(self, registry):
        sentinel = object()
        assert run_node(registry, "flopy.util.reroute", {}, value=sentinel) is sentinel

    def test_action_button_runs_as_noop(self, registry):
        assert run_node(registry, "flopy.util.action_button", {}) == {}


class TestScriptingNodes:
    def test_node_template_registers_with_docs(self, registry):
        spec = registry.get("flopy.scripting.node_template")
        assert spec.category == "Scripting"
        assert "Edit Code" in spec.doc  # the doc is the how-to

    def test_node_template_computes_a_column(self, registry, table):
        out = run_node(registry, "flopy.scripting.node_template",
                       {"source": "units", "factor": 3.0}, table=table)
        assert list(out["table"]["result"]) == [30.0, 60.0, 90.0, 120.0]
        assert "result" not in table.columns  # input left untouched

    def test_node_template_defaults_to_first_numeric(self, registry, table):
        out = run_node(registry, "flopy.scripting.node_template",
                       {"operation": "add", "factor": 1.0,
                        "new_column": "bumped"}, table=table)
        assert list(out["table"]["bumped"]) == [11.0, 21.0, 31.0, 41.0]

    def test_node_template_bad_column(self, registry, table):
        with pytest.raises(ValueError, match="not in table"):
            run_node(registry, "flopy.scripting.node_template",
                     {"source": "nope"}, table=table)
