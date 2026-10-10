"""Charts from a selection: Insert ▸ Chart on a Table grid adds a Show
Plotly node wired to the table, with the selected columns picked."""
import json

import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry, Page, Tile, compile_run
from flograph.core.sheet.chart import (CHART_NODE, ChartPick, column_role,
                                       pick_chart, place_beside)
from flograph.ui.spreadsheet import SheetModel, SheetWorkbench
from flograph.ui.spreadsheet.binding import NodeSheetHost, SheetHost
from tests.conftest import FakeContext

REGION = ("Region", "text", ["North", "South", "North", "East"])
SALES = ("Sales", "number", [10, 20, 30, 40])
COST = ("Cost", "auto", [4, 5, 6, 7.5])
WHEN = ("When", "date", ["2026-01-01", "2026-02-01", "2026-03-01",
                         "2026-04-01"])


class TestPick:
    def test_roles(self):
        assert column_role("auto", [1, 2.5, ""]) == "number"
        assert column_role("auto", [1, "x"]) == "text"
        assert column_role("auto", [True, False]) == "text"
        assert column_role("bool", [True]) == "text"
        assert column_role("integer", []) == "number"

    def test_labels_and_numbers_make_a_column_chart(self):
        pick = pick_chart([REGION, SALES, COST])
        assert pick.kind == "bar"
        assert pick.params["x"] == "Region"
        assert pick.params["y"] == "Sales, Cost"
        assert pick.params["summarise"] == "sum"      # North repeats
        assert pick.params["title"] == "Sales and Cost by Region"

    def test_no_repeats_no_totalling(self):
        pick = pick_chart([("Item", "text", ["a", "b"]),
                           ("N", "number", [1, 2])])
        assert "summarise" not in pick.params

    def test_dates_make_a_line(self):
        assert pick_chart([WHEN, SALES]).kind == "line"

    def test_numbers_alone(self):
        assert pick_chart([SALES, COST]).kind == "scatter"
        hist = pick_chart([SALES])
        assert hist.kind == "histogram" and hist.params["x"] == "Sales"
        assert pick_chart([SALES, COST, SALES]).kind == "line"

    def test_pie(self):
        pick = pick_chart([REGION, SALES, COST], "pie")
        assert pick.params["names"] == "Region"
        assert pick.params["values"] == "Sales"
        assert "Cost left out" in pick.note
        assert "labels" in pick_chart([SALES], "pie")

    def test_scatter_colours_by_the_labels(self):
        pick = pick_chart([REGION, SALES, COST], "scatter")
        assert (pick.params["x"], pick.params["y"],
                pick.params["color"]) == ("Sales", "Cost", "Region")
        assert "two number columns" in pick_chart([REGION, SALES],
                                                  "scatter")

    def test_refusals_say_why(self):
        assert "Select" in pick_chart([])
        assert "no numbers" in pick_chart([REGION])
        assert "comma" in pick_chart([("a,b", "number", [1])])

    def test_extra_label_column_is_noted(self):
        pick = pick_chart([REGION, ("Rep", "text", ["x"] * 4), SALES])
        assert pick.params["x"] == "Region"
        assert "Rep isn't numbers" in pick.note

    def test_place_beside_steps_past_what_is_there(self):
        anchor = (0, 0, 100, 100)
        assert place_beside(anchor, (50, 50), []) == (160, 0)
        assert place_beside(anchor, (50, 50), [(150, 0, 80, 80)]) == (160, 110)


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


DATA = {"version": 2,
        "columns": [{"name": "Region"}, {"name": "Sales", "type": "number"},
                    {"name": "Cost", "type": "number"}],
        "rows": [["North", "10", "4"], ["South", "20", "5"],
                 ["North", "30", "6"]]}


def _flow(registry):
    graph = Graph()
    table = registry.instantiate("flograph.io.table", (100, 50))
    table.params["data"] = json.dumps(DATA)
    graph.add_node(table)
    return graph, QUndoStack(), table


class TestInsert:
    def test_adds_a_wired_chart_beside_the_table_in_one_undo(self, registry):
        graph, stack, table = _flow(registry)
        ran = []
        host = NodeSheetHost(graph, lambda: stack, table.id,
                             on_submitted=lambda: ran.append(1),
                             registry_fn=lambda: registry)
        assert host.offers_charts() and host.can_chart()
        said = host.insert_chart(pick_chart([REGION, SALES]))
        assert "column chart" not in said and "bar chart" in said
        assert ran == [1]                       # runs, so it draws now
        chart = next(n for n in graph.nodes.values() if n.id != table.id)
        assert chart.spec.type_id == CHART_NODE
        assert chart.params["x"] == "Region" and chart.params["y"] == "Sales"
        assert chart.label == "Sales by Region"
        assert chart.pos[0] > table.pos[0] and chart.pos[1] == table.pos[1]
        [wire] = graph.connections.values()
        assert (wire.src_node, wire.dst_node, wire.dst_port) == (
            table.id, chart.id, "table")
        assert stack.count() == 1
        stack.undo()
        assert list(graph.nodes) == [table.id] and not graph.connections
        stack.redo()
        assert len(graph.nodes) == 2 and len(graph.connections) == 1

    def test_on_a_dashboard_it_gets_a_tile_too(self, registry):
        graph, stack, table = _flow(registry)
        page = Page(id="p1", title="Board")
        graph.add_page(page)
        graph.add_tile("p1", Tile(id="t1", node_id=table.id,
                                  rect=(0, 0, 400, 300)))
        host = NodeSheetHost(
            graph, lambda: stack, table.id, registry_fn=lambda: registry,
            tile_fn=lambda: ("p1", (0, 0, 400, 300), []))
        assert "on this page" in host.insert_chart(
            pick_chart([REGION, SALES]))
        tiles = list(graph.pages["p1"].tiles.values())
        chart_tile = next(t for t in tiles if t.id != "t1")
        assert chart_tile.rect[0] == 416 and chart_tile.port == "figure"
        stack.undo()
        assert list(graph.pages["p1"].tiles) == ["t1"]

    def test_a_bare_grid_has_no_charts(self):
        assert not SheetHost().offers_charts()
        assert not NodeSheetHost(Graph(), lambda: None, "x").offers_charts()

    def test_the_settings_draw(self, registry):
        """What the pick writes is something Show Plotly can draw."""
        pytest.importorskip("plotly")
        import pandas as pd
        frame = pd.DataFrame({"Region": ["North", "South", "North"],
                              "Sales": [10.0, 20.0, 30.0],
                              "Cost": [4.0, 5.0, 6.0]})
        spec = registry.get(CHART_NODE)
        run = compile_run(spec.source, "chart-pick")
        cols = [("Region", "text", list(frame.Region)),
                ("Sales", "number", list(frame.Sales)),
                ("Cost", "number", list(frame.Cost))]
        for kind in ("auto", "bar", "line", "area", "pie", "scatter",
                     "histogram"):
            pick = pick_chart(cols, kind)
            assert isinstance(pick, ChartPick), kind
            params = spec.default_params()
            params.update(pick.params)
            fig = run(FakeContext(params=params), table=frame)["figure"]
            assert fig.data, kind
        bars = pick_chart(cols, "bar")
        params = spec.default_params()
        params.update(bars.params)
        fig = run(FakeContext(params=params), table=frame)["figure"]
        assert sorted(fig.data[0].x) == ["North", "South"]   # totalled


def _select_columns(view, cols):
    model = view.model()
    sel = QItemSelection()
    for c in cols:
        sel.select(model.index(0, c), model.index(model.rowCount() - 1, c))
    view.setCurrentIndex(model.index(0, cols[0]))
    view.selectionModel().select(sel, QItemSelectionModel.ClearAndSelect)


class TestGrid:
    def _bench(self, qtbot, registry):
        graph, stack, table = _flow(registry)
        host = NodeSheetHost(graph, lambda: stack, table.id,
                             registry_fn=lambda: registry)
        bench = SheetWorkbench(SheetModel(json.dumps(DATA)), host=host)
        qtbot.addWidget(bench)
        return bench, graph

    def test_insert_tab_and_command(self, qtbot, registry):
        bench, graph = self._bench(qtbot, registry)
        from flograph.ui.spreadsheet.ribbon import RibbonButton
        labels = {b.text() for b in bench.ribbon.findChildren(RibbonButton)}
        assert {"Recommended", "Column", "Pie", "Histogram"} <= labels
        view = bench.view
        _select_columns(view, [0, 2])
        view.actions.refresh()
        assert view.actions["chart"].isEnabled()
        view.actions["chart_pie"].trigger()
        chart = next(n for n in graph.nodes.values()
                     if n.spec.type_id == CHART_NODE)
        assert (chart.params["kind"], chart.params["names"],
                chart.params["values"]) == ("pie", "Region", "Cost")

    def test_hidden_columns_are_left_out(self, qtbot, registry):
        bench, _graph = self._bench(qtbot, registry)
        view = bench.view
        view.setColumnHidden(1, True)
        _select_columns(view, [0, 1, 2])
        assert [c[0] for c in view.chart_columns()] == ["Region", "Cost"]

    def test_no_tab_without_a_node(self, qtbot):
        bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
        qtbot.addWidget(bench)
        from flograph.ui.spreadsheet.ribbon import RibbonButton
        labels = {b.text() for b in bench.ribbon.findChildren(RibbonButton)}
        assert "Recommended" not in labels
