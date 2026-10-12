"""The Input Panel (core.input_panel, nodes/input/input_panel.py,
ui.controls.PanelControl) and Apply Filters.

The user's case, as asked: "filter a table by a pick on column x, then a
slider on column y, then filter dataset 2 by dataset 1's column x pick".
"""
import json

import pandas as pd
import pytest

from flograph.core import Graph, NodeInstance, NodeRegistry, parse_spec, varlinks
from flograph.core import control_apply as ca
from flograph.core.input_panel import (apply_filter, field_name, parse_fields,
                                       run_panel)
from flograph.engine import ExecutionEngine

SALES = pd.DataFrame({
    "region": ["North", "North", "South", "South", "East"],
    "city": ["Leeds", "York", "Bath", "Truro", "Ely"],
    "price": [10.0, 40.0, 25.0, 70.0, 55.0],
    "when": pd.to_datetime(["2026-01-05", "2026-02-10", "2026-02-20",
                            "2026-03-01", "2026-03-15"]),
    "stock": [True, False, True, True, False],
})
ORDERS = pd.DataFrame({"sales_region": ["North", "South", "East", "North"],
                       "qty": [1, 2, 3, 4]})

FIELDS = """
Region = choice region
City   = choice city
Price  = between price
When   = date range when
Search = text city contains
In stock = toggle stock
"""


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def source(graph, frame, label="Src"):
    """A node whose run() returns `frame` - rebuilt from JSON in its own
    script, since node scripts are text and can't hold an object."""
    payload = frame.to_json(orient="records", date_format="iso")
    dates = [c for c in frame.columns if frame[c].dtype.kind == "M"]
    node = NodeInstance.create(parse_spec(
        f'NODE = {{"label": "{label}", "category": "Test", "inputs": [],'
        ' "outputs": [("t", "dataframe")]}\n'
        "def run(ctx):\n"
        "    import io\n"
        "    import pandas as pd\n"
        f"    frame = pd.read_json(io.StringIO({payload!r}), orient='records')\n"
        f"    for c in {dates!r}:\n"
        "        frame[c] = pd.to_datetime(frame[c]).dt.tz_localize(None)\n"
        "    return {'t': frame}\n", f"test.{label.lower()}"))
    graph.add_node(node)
    return node


def panel(graph, registry, fields=FIELDS, **params):
    node = graph.add_node(registry.instantiate("flograph.input.input_panel"))
    graph.set_param(node.id, "fields", fields)
    for name, value in params.items():
        graph.set_param(node.id, name, value)
    return node


# ----------------------------------------------------------------- parsing

class TestParsing:
    def test_lines(self):
        fields, problems = parse_fields(
            "Region = choice region\n"
            "Price = between price step=5\n"
            "Ordered = date range order_date\n"
            "Customer = text customer startswith\n"
            "In stock = toggle in_stock\n"
            "Top N = number min=1 max=50 default=10\n"
            '"Big" = slider "unit price" >= help="the floor"\n'
            "# a comment\n")
        assert problems == []
        by = {f["name"]: f for f in fields}
        assert by["region"]["shape"] == "choice" and by["region"]["op"] == "=="
        assert by["price"]["shape"] == "range" and by["price"]["opts"]["step"] == "5"
        assert by["ordered"]["shape"] == "date_range"
        assert by["customer"]["op"] == "startswith"
        assert by["top_n"]["column"] == "" and by["top_n"]["opts"]["max"] == "50"
        big = by["big"]
        assert big["column"] == "unit price" and big["opts"]["help"] == "the floor"

    def test_problems_are_collected(self):
        fields, problems = parse_fields(
            "nope\nX = gizmo col\nA = choice a\nA = choice b\nB = choice b c d\n")
        assert [f["name"] for f in fields] == ["a"]
        assert len(problems) == 4

    def test_names(self):
        assert field_name("In stock") == "in_stock"
        assert field_name("2024 sales") == "f_2024_sales"


# ----------------------------------------------------------------- the rules

class TestRules:
    def test_nothing_set_filters_nothing(self):
        fields, _ = parse_fields(FIELDS)
        rows, values, filters, _ = run_panel(fields, {}, SALES)
        assert len(rows) == len(SALES)
        assert filters == []
        assert values["region"] == "" and values["price"] == [10.0, 70.0]

    def test_a_pick_then_a_slider(self):
        fields, _ = parse_fields("Region = choice region\n"
                                 "Price = slider price >=\n")
        rows, values, filters, ctx = run_panel(
            fields, {"region": "North", "price": 20}, SALES, "top to bottom")
        assert list(rows["city"]) == ["York"]
        assert [f["column"] for f in filters] == ["region", "price"]
        # top to bottom: the slider's range is the North rows' prices
        assert ctx["price"][0] == {"minimum": 10.0, "maximum": 40.0}
        # each other: a range keeps its whole column, so a value set on it
        # is never clamped under the person who set it
        _rows, _v, _f, ctx = run_panel(
            fields, {"region": "North", "price": 20}, SALES, "each other")
        assert ctx["price"][0] == {"minimum": 10.0, "maximum": 70.0}

    def test_slicers_filter_each_other(self):
        """Power BI's page of slicers: each list offers what the *others*
        leave, with counts to match — and keeps its own options whole."""
        fields, _ = parse_fields("Region = slicer region\n"
                                 "City = slicer city\n"
                                 "Stocked = toggle stock\n")
        _rows, _v, filters, ctx = run_panel(
            fields, {"city": '["Bath", "Ely"]'}, SALES)
        # Region shows only the regions Bath and Ely are in...
        assert ctx["region"][0]["options"] == ["East", "South"]
        assert ctx["region"][0]["counts"] == {"South": 1, "East": 1}
        # ...and City, filtered by nothing else, still lists every city
        assert len(ctx["city"][0]["options"]) == 5
        rows, _v, _f, ctx = run_panel(
            fields, {"city": '["Bath", "Ely"]', "stocked": True}, SALES)
        assert list(rows["city"]) == ["Bath"]
        assert ctx["region"][0]["options"] == ["South"]
        # the stock filter narrows City's list too
        assert ctx["city"][0]["options"] == ["Bath", "Leeds", "Truro"]

    def test_legacy_tick_box_cascade(self):
        from flograph.core.input_panel import cascade_mode
        assert cascade_mode(True) == "top to bottom"
        assert cascade_mode(False) == "off"
        assert cascade_mode(None) == "each other"

    def test_cascade_narrows_the_next_options(self):
        fields, _ = parse_fields(FIELDS)
        _rows, _v, _f, ctx = run_panel(fields, {"region": "South"}, SALES)
        assert ctx["city"][0]["options"] == ["Bath", "Truro"]
        _rows, _v, _f, ctx = run_panel(fields, {"region": "South"}, SALES,
                                       cascade="off")
        assert len(ctx["city"][0]["options"]) == 5

    def test_each_kind_filters(self):
        fields, _ = parse_fields(FIELDS)
        rows, *_ = run_panel(fields, {"price": "[20, 60]"}, SALES)
        assert sorted(rows["price"]) == [25.0, 40.0, 55.0]
        rows, *_ = run_panel(
            fields, {"when": '["2026-02-01", "2026-02-28"]'}, SALES)
        assert list(rows["city"]) == ["York", "Bath"]
        rows, *_ = run_panel(fields, {"search": "ur"}, SALES)
        assert list(rows["city"]) == ["Truro"]
        rows, *_ = run_panel(fields, {"in_stock": True}, SALES)
        assert list(rows["city"]) == ["Leeds", "Bath", "Truro"]

    def test_multi(self):
        fields, _ = parse_fields("Regions = multi region\n")
        rows, *_ = run_panel(fields, {"regions": '["East", "North"]'}, SALES)
        assert sorted(rows["city"]) == ["Ely", "Leeds", "York"]
        rows, *_ = run_panel(fields, {"regions": "[]"}, SALES)
        assert len(rows) == 5

    def test_a_date_includes_its_whole_end_day(self):
        frame = pd.DataFrame({"t": pd.to_datetime(
            ["2026-01-05 09:00", "2026-01-05 18:00", "2026-01-06 00:00"])})
        flt = {"column": "t", "op": "<=", "value": "2026-01-05", "kind": "date"}
        assert len(apply_filter(frame, flt)) == 2


# ----------------------------------------------------------------- the node

def _flow(registry, fields=FIELDS, **params):
    graph = Graph()
    src = source(graph, SALES, "Sales")
    p = panel(graph, registry, fields, **params)
    graph.connect(src.id, "t", p.id, "data")
    return graph, src, p


def run_engine(qtbot, graph):
    engine = ExecutionEngine(graph)
    failures = {}
    engine.node_failed.connect(lambda nid, e: failures.update({nid: e.message}))
    with qtbot.waitSignal(engine.run_finished, timeout=10000):
        engine.run_all()
    return engine, failures


class TestNode:
    def test_filtered_values_filters(self, qtbot, registry):
        graph, _src, p = _flow(registry,
                               value=json.dumps({"region": "North"}))
        engine, failures = run_engine(qtbot, graph)
        assert not failures, failures
        out = engine.cache.outputs_for(p.id)
        assert list(out["filtered"]["city"]) == ["Leeds", "York"]
        assert out["values"]["region"] == "North"
        assert out["filters"][0]["column"] == "region"

    def test_a_bad_line_fails_the_node(self, qtbot, registry):
        graph, _src, p = _flow(registry, fields="Oops = gizmo x")
        _engine, failures = run_engine(qtbot, graph)
        assert "not a field shape" in failures[p.id]

    def test_a_required_field(self, qtbot, registry):
        graph, _src, p = _flow(registry, fields="Who = text city required=yes")
        _engine, failures = run_engine(qtbot, graph)
        assert "Who is required" in failures[p.id]

    def test_apply_filters_reuses_the_picks_on_a_second_table(
            self, qtbot, registry):
        graph, _src, p = _flow(registry,
                               value=json.dumps({"region": "North"}))
        orders = source(graph, ORDERS, "Orders")
        apply_node = graph.add_node(
            registry.instantiate("flograph.transform.apply_filters"))
        graph.set_param(apply_node.id, "mapping", "region = sales_region")
        graph.connect(orders.id, "t", apply_node.id, "table")
        graph.connect(p.id, "filters", apply_node.id, "filters")
        engine, failures = run_engine(qtbot, graph)
        assert not failures, failures
        out = engine.cache.outputs_for(apply_node.id)["filtered"]
        assert list(out["qty"]) == [1, 4]

    def test_apply_filters_missing_column(self, qtbot, registry):
        graph, _src, p = _flow(registry,
                               value=json.dumps({"region": "North"}))
        orders = source(graph, ORDERS, "Orders")
        apply_node = graph.add_node(
            registry.instantiate("flograph.transform.apply_filters"))
        graph.set_param(apply_node.id, "missing", "fail")
        graph.connect(orders.id, "t", apply_node.id, "table")
        graph.connect(p.id, "filters", apply_node.id, "filters")
        _engine, failures = run_engine(qtbot, graph)
        assert "no column 'region'" in failures[apply_node.id]


class TestVariables:
    def test_each_field_is_a_variable(self, registry):
        graph = Graph()
        p = panel(graph, registry)
        assert "region" in varlinks.providers(graph)
        graph.set_param(p.id, "variable", "f")
        assert "f_region" in varlinks.providers(graph)
        graph.set_param(p.id, "publish", False)
        assert varlinks.providers(graph) == {}

    def test_a_field_reaches_a_text_param(self, qtbot, registry):
        graph, _src, p = _flow(registry,
                               value=json.dumps({"region": "South"}))
        echo = graph.add_node(NodeInstance.create(parse_spec(
            'NODE = {"label": "Echo", "category": "Test", "inputs": [],'
            ' "outputs": [("v", "any")]}\n'
            'PARAMS = [{"name": "text", "type": "string", "default": ""}]\n'
            "def run(ctx):\n    return {'v': ctx.params['text']}\n",
            "test.echo")))
        graph.set_param(echo.id, "text", "region == '${region}'")
        assert graph.var_sources(echo.id) == [p.id]
        engine, failures = run_engine(qtbot, graph)
        assert not failures, failures
        assert engine.cache.outputs_for(echo.id)["v"] == "region == 'South'"


# ----------------------------------------------------------------- the card

class TestCard:
    def test_fields_are_the_standard_widgets(self, qtbot, registry):
        from flograph.ui.controls import (ChoiceControl, RangeControl,
                                          host_control)
        graph = Graph()
        p = panel(graph, registry)
        widget = host_control(p)
        qtbot.addWidget(widget)
        widget.set_upstream({"data": SALES})
        assert isinstance(widget.field_widget("region"), ChoiceControl)
        assert isinstance(widget.field_widget("price"), RangeControl)
        region = widget.field_widget("region")
        assert region._combo.itemText(0) == "(All)"

    def test_a_field_commits_the_whole_panel_and_cascades(
            self, qtbot, registry):
        from flograph.ui.controls import host_control
        graph = Graph()
        p = panel(graph, registry)
        widget = host_control(p)
        qtbot.addWidget(widget)
        widget.set_upstream({"data": SALES})
        seen = []
        widget.value_committed.connect(seen.append)
        region = widget.field_widget("region")
        index = region._combo.findData("South")
        region._combo.setCurrentIndex(index)
        region._combo.activated.emit(index)
        assert json.loads(seen[-1]) == {"region": "South"}
        graph.set_param(p.id, "value", seen[-1])
        widget.sync(p.params)
        city = widget.field_widget("city")
        assert [city._combo.itemText(i) for i in range(city._combo.count())] \
            == ["(All)", "Bath", "Truro"]

    def test_held_panel_holds_every_field(self, qtbot, registry):
        from PySide6.QtGui import QUndoStack
        from flograph.ui import control_binding as cb
        graph = Graph()
        p = panel(graph, registry, apply=ca.WAIT)
        stack = QUndoStack()
        cb.commit_value(graph, stack, p.id, json.dumps({"region": "East"}))
        assert p.params["value"] == "" and ca.has_draft(p)
        assert cb.apply(graph, stack, p.id)
        assert json.loads(p.params["value"]) == {"region": "East"}

    def test_a_problem_line_is_shown(self, qtbot, registry):
        from flograph.ui.controls import host_control
        graph = Graph()
        p = panel(graph, registry, fields="Oops = gizmo")
        widget = host_control(p)
        qtbot.addWidget(widget)
        assert "not a field shape" in widget._problem.text()


class TestApplyOnTheNode:
    """Apply and Reset on the node itself: a control set to "with ✓ on the
    control" always shows its Apply, lit only while a change waits; an
    Input Panel gets real Apply / Reset buttons along its bottom."""

    def test_a_single_control_always_shows_apply(self, qtbot, registry):
        from flograph.ui.controls import host_control
        graph = Graph()
        node = graph.add_node(registry.instantiate("flograph.input.slider"))
        graph.set_param(node.id, "apply", ca.BUTTON)
        widget = host_control(node)
        qtbot.addWidget(widget)
        assert not widget._apply_button.isHidden()
        assert not widget._apply_button.property("pending")
        graph.set_param(node.id, "draft", ca.encode(70))
        widget.sync(node.params)
        assert widget._apply_button.property("pending") is True

    def test_pressing_apply_with_nothing_waiting_still_runs(self, qtbot,
                                                            registry):
        from PySide6.QtGui import QUndoStack
        from flograph.ui.controls import connect_control, host_control
        graph = Graph()
        node = graph.add_node(registry.instantiate("flograph.input.slider"))
        graph.set_param(node.id, "apply", ca.BUTTON)
        widget = host_control(node)
        qtbot.addWidget(widget)
        stack = QUndoStack()
        runs = []
        connect_control(widget, lambda: graph, lambda: stack,
                        lambda: node.id, runs.append)
        widget._apply_button.click()
        assert runs == [node.id]

    def test_the_panel_has_a_footer_and_reset_applies(self, qtbot, registry):
        from PySide6.QtGui import QUndoStack
        from flograph.ui.controls import connect_control, host_control
        graph = Graph()
        p = panel(graph, registry, apply=ca.BUTTON)
        widget = host_control(p)
        qtbot.addWidget(widget)
        stack = QUndoStack()
        runs = []
        connect_control(widget, lambda: graph, lambda: stack,
                        lambda: p.id, runs.append)
        assert not widget._footer.isHidden()
        assert widget._apply_button.isHidden()      # the footer's, not this
        graph.set_param(p.id, "value", json.dumps({"region": "North"}))
        widget.sync(p.params)
        widget._panel_reset.click()
        assert p.params["value"] == "" and not ca.has_draft(p)
        assert runs and runs[-1] == p.id


class TestSlicerField:
    def test_list_with_counts_search_and_ticks(self, qtbot, registry):
        from PySide6.QtCore import Qt
        from flograph.ui.controls import ListControl, host_control
        graph = Graph()
        p = panel(graph, registry, fields="Region = slicer region\n"
                                           "City = slicer city\n")
        widget = host_control(p)
        qtbot.addWidget(widget)
        widget.set_upstream({"data": SALES})
        region = widget.field_widget("region")
        assert isinstance(region, ListControl)
        labels = [region._list.item(r).text()
                  for r in range(region._list.count())]
        assert labels == ["East   1", "North   2", "South   2"]
        seen = []
        widget.value_committed.connect(seen.append)
        region._list.item(1).setCheckState(Qt.Checked)
        assert json.loads(seen[-1]) == {"region": '["North"]'}

    def test_the_checklist_node(self, qtbot, registry):
        graph = Graph()
        node = graph.add_node(registry.instantiate("flograph.input.checklist"))
        graph.set_param(node.id, "items", "a\nb\nc")
        graph.set_param(node.id, "value", '["c"]')
        engine, _failures = run_engine(qtbot, graph)
        assert engine.cache.outputs_for(node.id)["value"] == ["c"]


class TestSize:
    """A filter pane down the side of a dashboard can want the full height
    of the page (Dan: "its limited to 600 but i might want more"), so a
    panel, a Checklist and Multi Choice grow like a Slicer; a single-value
    control keeps its 600."""

    def test_a_panel_can_be_made_tall(self, qtbot, registry):
        from PySide6.QtGui import QUndoStack
        from flograph.ui.canvas import NodeGraphScene
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        p = panel(graph, registry, height=2400, width=1200)
        item = scene.node_items[p.id]
        _minw, maxw, _minh, maxh = item._resize_bounds()
        assert (maxw, maxh) == (1600.0, 4000.0)
        assert item.body_height >= 2400 and item.width == 1200
        slider = graph.add_node(registry.instantiate("flograph.input.slider"))
        assert scene.node_items[slider.id]._resize_bounds()[3] == 600.0
