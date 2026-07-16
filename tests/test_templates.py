"""Bundled example workflows: File > Open Example loads and runs cleanly."""
import importlib.resources

import pytest

from flograph.core import NodeRegistry, NodeStatus
from flograph.ui.mainwindow import MainWindow


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def wait_run(qtbot, engine, timeout=20000):
    with qtbot.waitSignal(engine.run_finished, timeout=timeout) as blocker:
        engine.run_all()
    return blocker.args[0]


def template_path(name: str):
    root = importlib.resources.files("flograph.templates")
    return root / name


class TestBundledExamples:
    def test_exactly_eight_templates_bundled(self):
        root = importlib.resources.files("flograph.templates")
        names = sorted(e.name for e in root.iterdir() if e.name.endswith(".flograph"))
        assert names == [
            "01_load_filter_visualize.flograph",
            "02_aggregate_dashboard.flograph",
            "03_custom_script_chart.flograph",
            "04_join_groupby_compare.flograph",
            "05_interactive_slicer_dashboard.flograph",
            "06_script_pipeline_frame.flograph",
            "07_retail_ops_command_center.flograph",
            "08_geo_population_map.flograph",
        ]

    def test_examples_menu_lists_all_eight(self, window):
        assert window._examples_menu.isEnabled()
        assert len(window._examples_menu.actions()) == 8

    @pytest.mark.parametrize("name", [
        "01_load_filter_visualize.flograph",
        "02_aggregate_dashboard.flograph",
        "03_custom_script_chart.flograph",
        "04_join_groupby_compare.flograph",
        "05_interactive_slicer_dashboard.flograph",
        "06_script_pipeline_frame.flograph",
        "07_retail_ops_command_center.flograph",
        "08_geo_population_map.flograph",
    ])
    def test_template_loads_and_runs_without_error(self, qtbot, window, name):
        window._open_example(template_path(name))
        assert window.graph.nodes
        assert not any(n.spec.broken for n in window.graph.nodes.values())

        ok = wait_run(qtbot, window.engine)
        assert ok
        for node in window.graph.nodes.values():
            assert node.status == NodeStatus.DONE, node.status_message

    def test_open_example_does_not_bind_project_path(self, qtbot, window, tmp_path):
        # opening a real project first, to prove _open_example resets it
        window._project_path = str(tmp_path / "existing.flograph")
        window._open_example(template_path("01_load_filter_visualize.flograph"))
        assert window._project_path is None

    def test_aggregate_dashboard_groups_and_totals_correctly(self, qtbot, window):
        window._open_example(template_path("02_aggregate_dashboard.flograph"))
        wait_run(qtbot, window.engine)

        groupby = next(n for n in window.graph.nodes.values()
                        if n.spec.type_id == "flograph.transform.group_by")
        aggregated = window.engine.cache.outputs_for(groupby.id)["aggregated"]
        assert set(aggregated["region"]) == {"North", "South", "East"}
        assert int(aggregated["revenue"].sum()) == 1905

        card = next(n for n in window.graph.nodes.values()
                    if n.spec.type_id == "flograph.viz.card")
        assert window.engine.cache.outputs_for(card.id)["value"] == 1905

        assert len(window.graph.pages) == 1
        page = next(iter(window.graph.pages.values()))
        assert len(page.tiles) == 2

    def test_custom_script_chart_computes_cumulative_column(self, qtbot, window):
        window._open_example(template_path("03_custom_script_chart.flograph"))
        wait_run(qtbot, window.engine)

        script = next(n for n in window.graph.nodes.values()
                      if n.code_override is not None)
        out = window.engine.cache.outputs_for(script.id)["out1"]
        assert list(out["cumulative"]) == [120, 218, 358, 468, 633, 843, 1018]

    def test_join_groupby_compare_rolls_up_and_sorts_by_region(self, qtbot, window):
        window._open_example(template_path("04_join_groupby_compare.flograph"))
        wait_run(qtbot, window.engine)

        join = next(n for n in window.graph.nodes.values()
                    if n.spec.type_id == "flograph.transform.join")
        joined = window.engine.cache.outputs_for(join.id)["joined"]
        assert len(joined) == 10  # every order's customer_id resolves (inner join)

        sort = next(n for n in window.graph.nodes.values()
                    if n.spec.type_id == "flograph.transform.sort")
        ranked = window.engine.cache.outputs_for(sort.id)["table"]
        assert list(ranked["region"]) == ["North", "East", "South"]
        assert list(ranked["revenue"]) == [920, 685, 655]

    def test_slicer_dashboard_filters_before_downstream_nodes(self, qtbot, window):
        window._open_example(template_path("05_interactive_slicer_dashboard.flograph"))
        wait_run(qtbot, window.engine)

        slicer = next(n for n in window.graph.nodes.values()
                      if n.spec.type_id == "flograph.viz.slicer")
        filtered = window.engine.cache.outputs_for(slicer.id)["table"]
        assert set(filtered["region"]) == {"North", "South"}  # East/West ticked off
        assert len(filtered) == 8

        groupby = next(n for n in window.graph.nodes.values()
                        if n.spec.type_id == "flograph.transform.group_by")
        aggregated = window.engine.cache.outputs_for(groupby.id)["aggregated"]
        assert int(aggregated["revenue"].sum()) == 2390  # North+South only

        assert len(window.graph.pages) == 1
        page = next(iter(window.graph.pages.values()))
        assert len(page.tiles) == 3

    def test_script_pipeline_frame_isolates_above_average_days(self, qtbot, window):
        window._open_example(template_path("06_script_pipeline_frame.flograph"))
        wait_run(qtbot, window.engine)

        sort = next(n for n in window.graph.nodes.values()
                    if n.spec.type_id == "flograph.transform.sort")
        ranked = window.engine.cache.outputs_for(sort.id)["table"]
        assert list(ranked["day"]) == [
            "Day 13", "Day 6", "Day 12", "Day 5", "Day 10", "Day 3", "Day 1"]
        assert list(ranked["visits"]) == [225, 210, 180, 165, 150, 140, 120]
        assert set(ranked["performance"]) == {"above"}

        assert len(window.graph.frames) == 1

    def test_retail_ops_command_center_full_pipeline(self, qtbot, window):
        window._open_example(template_path("07_retail_ops_command_center.flograph"))
        assert len(window.graph.nodes) == 36
        assert len(window.graph.frames) == 6
        assert len(window.graph.pages) == 3
        assert sum(len(p.tiles) for p in window.graph.pages.values()) == 13

        wait_run(qtbot, window.engine)
        cache = window.engine.cache

        # concatenated + double-joined + derived columns
        enriched = cache.outputs_for("t7expr_finance")["table"]
        assert len(enriched) == 48
        assert {"revenue", "cost", "margin", "region", "segment",
                "category"} <= set(enriched.columns)

        # KPI cards over the enriched table / rollup
        assert cache.outputs_for("t7kpi_revenue")["value"] == 73620
        assert cache.outputs_for("t7kpi_margin")["value"] == 24424
        assert round(cache.outputs_for("t7kpi_attain")["value"], 1) == 94.2

        # regional rollup joined to targets, sorted by attainment
        rollup = cache.outputs_for("t7sort_attain")["table"]
        assert list(rollup["region"]) == ["West", "South", "North", "East"]
        assert [round(a, 1) for a in rollup["attainment"]] == [
            112.3, 108.9, 93.8, 61.9]

        # slicer keeps Enterprise+SMB only, feeding the trend groupby
        sliced = cache.outputs_for("t7slicer")["table"]
        assert len(sliced) == 35
        assert set(sliced["segment"]) == {"Enterprise", "SMB"}

        # pivot fans category rows out to one revenue column per region
        pivoted = cache.outputs_for("t7pivot")["pivoted"]
        assert list(pivoted.columns) == [
            "category", "revenue_East", "revenue_North",
            "revenue_South", "revenue_West"]

        # ABC classification script: Pareto classes in rank order
        abc = cache.outputs_for("t7script_abc")["out1"]
        assert list(abc["product"])[:2] == ["Laptop", "Phone"]
        assert list(abc["abc_class"]) == ["A", "A", "B", "B", "C", "C", "C", "C"]

        # forked Show Web node renders the HTML briefing from live data
        html = cache.outputs_for("t7exec_web")["view"]
        assert "Quarterly Briefing" in html
        assert "West" in html and "112%" in html

    def test_geo_population_map_geopandas_pipeline(self, qtbot, window):
        pytest.importorskip("geopandas")
        pytest.importorskip("folium")
        window._open_example(template_path("08_geo_population_map.flograph"))
        wait_run(qtbot, window.engine)
        cache = window.engine.cache

        # embedded GeoJSON -> GeoDataFrame survives the stock Join node
        joined = cache.outputs_for("t8join")["joined"]
        assert type(joined).__name__ == "GeoDataFrame"
        assert len(joined) == 12
        assert int(joined["population"].sum()) == 67571000
        assert {"London", "Scotland", "Wales",
                "Northern Ireland"} <= set(joined["region"])

        assert cache.outputs_for("t8kpi_pop")["value"] == 67571000

        # choropleth node draws a real matplotlib Figure
        fig = cache.outputs_for("t8choropleth")["figure"]
        assert type(fig).__name__ == "Figure"

        # folium fork returns the map's standalone HTML (get_root().render(),
        # not _repr_html_() — that wraps it in Jupyter's "trusted notebook"
        # placeholder, which is only ever hidden by a real notebook's CSS)
        html_map = cache.outputs_for("t8folium")["view"]
        assert isinstance(html_map, str)
        assert "leaflet" in html_map.lower()
        assert "trust" not in html_map.lower()

        top = cache.outputs_for("t8sort_cities")["table"]
        assert top.iloc[0]["city"] == "London"
