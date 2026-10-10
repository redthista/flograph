"""PivotTable from a selection: Insert ▸ PivotTable adds a Show Table in
matrix or grouped mode, wired to the Table, set up from the selection."""
import json

import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry, compile_run
from flograph.core.sheet.pivot import (PIVOT_NODE, PivotLayout, PivotPick,
                                       check, describe, guess, params,
                                       pick, preview, title)
from flograph.ui.spreadsheet import SheetModel, SheetWorkbench
from flograph.ui.spreadsheet.binding import NodeSheetHost
from tests.conftest import FakeContext

REGION = ("Region", "text", ["N", "S", "N", "E"])
MONTH = ("Month", "text", ["Jan", "Jan", "Feb", "Feb"])
SALES = ("Sales", "number", [1, 2, 3, 4])
COST = ("Cost", "auto", [1, 1, 1, 1])
DATA = {n: v for n, _t, v in (REGION, MONTH, SALES, COST)}


class TestLayout:
    def test_two_labels_make_a_matrix(self):
        layout = guess([REGION, MONTH, SALES])
        assert (layout.rows, layout.columns, layout.values) == (
            ["Region"], ["Month"], ["Sales"])
        assert layout.matrix
        assert title(layout) == "Sum of Sales by Region and Month"
        p = params(layout)
        assert (p["mode"], p["matrix_rows"], p["matrix_columns"],
                p["matrix_values"], p["totals"]) == (
            "matrix", "Region", "Month", "Sales", "sum")

    def test_one_label_makes_folded_groups(self):
        layout = guess([REGION, SALES, COST])
        assert not layout.matrix
        p = params(layout)
        assert (p["mode"], p["group_by"], p["groups_start"],
                p["show"]) == ("grouped", "Region", "folded",
                               "Region, Sales, Cost")
        assert "click one to see the rows" in describe(layout)

    def test_more_labels_go_down_the_side(self):
        layout = guess([("Rep", "text", ["a"] * 4), REGION, MONTH, SALES])
        assert layout.rows == ["Rep", "Region"]
        assert layout.columns == ["Month"]

    def test_average_totals_as_an_average(self):
        layout = PivotLayout(["Region"], ["Month"], ["Sales"], agg="mean")
        assert params(layout)["totals"] == "average"
        counted = PivotLayout(["Region"], ["Month"], ["Sales"], agg="count")
        assert params(counted)["totals"] == "sum"   # adding up the counts

    def test_no_grand_total(self):
        assert params(PivotLayout(["Region"], ["Month"], ["Sales"],
                                  total=False))["totals"] == "off"
        grouped = params(PivotLayout(["Region"], [], ["Sales"], total=False))
        assert grouped["format_rules"] == "total hidden"
        assert grouped["totals"] == "sum"       # the subtotals still add up

    def test_what_is_missing_is_said(self):
        assert "Rows" in check(PivotLayout([], [], ["Sales"]))
        assert "Values" in check(PivotLayout(["Region"], [], []))
        assert "comma" in check(PivotLayout(["a,b"], [], ["Sales"]))
        assert isinstance(pick(PivotLayout(["Region"], [], ["Sales"])),
                          PivotPick)

    def test_preview_matrix(self):
        headers, rows = preview(guess([REGION, MONTH, SALES]), DATA)
        assert headers == ["Region", "Jan", "Feb"]
        assert rows == [["N", 1, 3], ["S", 2, None], ["E", None, 4],
                        ["Total", 3, 7]]

    def test_preview_grouped_and_aggs(self):
        layout = guess([REGION, SALES])
        headers, rows = preview(layout, DATA)
        assert headers == ["Region", "Sales"]
        assert rows[0] == ["N", 4] and rows[-1] == ["Total", 10]
        layout.agg = "mean"
        assert preview(layout, DATA)[1][0] == ["N", 2]
        layout.agg = "count"
        assert preview(layout, DATA)[1][-1] == ["Total", 4]


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


class TestTheNodeDrawsIt:
    def test_matrix_and_grouped_settings_run(self, registry):
        import pandas as pd
        frame = pd.DataFrame(DATA)
        spec = registry.get(PIVOT_NODE)
        run = compile_run(spec.source, "pivot-pick")
        for layout in (guess([REGION, MONTH, SALES]),
                       guess([REGION, SALES, COST]),
                       PivotLayout(["Region"], [], ["Sales"], total=False)):
            p = spec.default_params()
            p.update(params(layout))
            out = run(FakeContext(params=p), table=frame)["table"]
            assert len(out)
        p = spec.default_params()
        p.update(params(guess([REGION, MONTH, SALES])))
        out = run(FakeContext(params=p), table=frame)["table"]
        assert list(out["Region"]) == ["N", "S", "E"]


TABLE = {"version": 2,
         "columns": [{"name": "Region"}, {"name": "Month"},
                     {"name": "Sales", "type": "number"}],
         "rows": [["N", "Jan", "1"], ["S", "Jan", "2"], ["N", "Feb", "3"]]}


def _flow(registry):
    graph = Graph()
    table = registry.instantiate("flograph.io.table", (0, 0))
    table.params["data"] = json.dumps(TABLE)
    graph.add_node(table)
    return graph, QUndoStack(), table


class TestInsert:
    def test_host_adds_a_wired_show_table(self, registry):
        graph, stack, table = _flow(registry)
        host = NodeSheetHost(graph, lambda: stack, table.id,
                             registry_fn=lambda: registry)
        assert host.can_pivot()
        said = host.insert_pivot(pick(guess([REGION, MONTH, SALES])))
        assert "PivotTable" in said
        node = next(n for n in graph.nodes.values() if n.id != table.id)
        assert node.spec.type_id == PIVOT_NODE
        assert node.params["mode"] == "matrix"
        assert node.label == "Sum of Sales by Region and Month"
        assert stack.undoText().startswith("insert PivotTable")
        stack.undo()
        assert list(graph.nodes) == [table.id]

    def test_dialog_from_the_grid(self, qtbot, registry, monkeypatch):
        graph, stack, table = _flow(registry)
        host = NodeSheetHost(graph, lambda: stack, table.id,
                             registry_fn=lambda: registry)
        bench = SheetWorkbench(SheetModel(json.dumps(TABLE)), host=host)
        qtbot.addWidget(bench)
        view = bench.view
        model = view.model()
        view.setCurrentIndex(model.index(0, 0))
        view.selectionModel().select(
            QItemSelection(model.index(0, 0), model.index(2, 2)),
            QItemSelectionModel.ClearAndSelect)
        from flograph.ui.spreadsheet import pivot_dialog
        seen = {}

        def fake_exec(dialog):
            seen["status"] = dialog.status.text()
            seen["rows"] = dialog.preview.rowCount()
            dialog.roles[1].setCurrentText("Leave out")   # Month out
            dialog.agg.setCurrentIndex(1)                 # Average
            seen["after"] = dialog.status.text()
            return True
        monkeypatch.setattr(pivot_dialog.PivotDialog, "exec", fake_exec)
        view.actions.refresh()
        assert view.actions["pivot"].isEnabled()
        view.actions["pivot"].trigger()
        assert "a column for each Month" in seen["status"]
        assert seen["rows"] == 3                      # N, S + Total
        assert seen["after"].startswith("Average of Sales for each Region")
        node = next(n for n in graph.nodes.values() if n.id != table.id)
        assert node.params["mode"] == "grouped"
        assert node.params["totals"] == "average"

    def test_one_cell_offers_every_column(self, qtbot, registry):
        graph, stack, table = _flow(registry)
        bench = SheetWorkbench(SheetModel(json.dumps(TABLE)))
        qtbot.addWidget(bench)
        bench.view.setCurrentIndex(bench.view.model().index(1, 1))
        assert [c[0] for c in bench.view.pivot_columns()] == [
            "Region", "Month", "Sales"]

    def test_ribbon_has_it(self, qtbot, registry):
        graph, stack, table = _flow(registry)
        host = NodeSheetHost(graph, lambda: stack, table.id,
                             registry_fn=lambda: registry)
        bench = SheetWorkbench(SheetModel(json.dumps(TABLE)), host=host)
        qtbot.addWidget(bench)
        from flograph.ui.spreadsheet.ribbon import RibbonButton
        assert "PivotTable" in {
            b.text() for b in bench.ribbon.findChildren(RibbonButton)}


class TestDateHeadings:
    """A date column across the top reads as dates, not as pandas'
    "2026-01-01 00:00:00" — what the Table hands on is a datetime."""

    def _frame(self):
        import pandas as pd
        return pd.DataFrame({
            "Region": ["N", "S", "N"],
            "Month": pd.to_datetime(["2026-01-01", "2026-01-01",
                                     "2026-02-01"]),
            "Sales": [1.0, 2.0, 3.0], "Cost": [1.0, 1.0, 1.0]})

    def test_matrix_headings(self, registry):
        spec = registry.get(PIVOT_NODE)
        run = compile_run(spec.source, "pivot-dates")
        for values, expect in (("Sales", ["2026-01-01", "2026-02-01"]),
                               ("Sales, Cost", ["Sales_2026-01-01",
                                                "Sales_2026-02-01"])):
            p = spec.default_params()
            p.update(mode="matrix", matrix_rows="Region",
                     matrix_columns="Month", matrix_values=values)
            out = run(FakeContext(params=p), table=self._frame())["table"]
            names = [str(c) for c in out.columns]
            assert all(e in names for e in expect), names
            assert not any("00:00:00" in n for n in names)

    def test_pivot_node_too(self, registry):
        spec = registry.get("flograph.transform.pivot")
        run = compile_run(spec.source, "pivot-node-dates")
        p = spec.default_params()
        p.update(index="Region", columns="Month", values="Sales")
        out = run(FakeContext(params=p), table=self._frame())
        assert list(out.columns) == ["Region", "2026-01-01", "2026-02-01"]

    def test_heading_text(self):
        import pandas as pd
        from flograph.core.matrix import heading_text
        assert heading_text(pd.Timestamp("2026-03-01")) == "2026-03-01"
        assert heading_text(pd.Timestamp("2026-03-01 09:30")) == \
            "2026-03-01 09:30"
        assert heading_text("Jan") == "Jan" and heading_text(3) == "3"
