"""Bundled example workflows: File > Open Example loads and runs cleanly."""
import importlib.resources
import re

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
    def test_every_template_is_bundled(self):
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
            "09_folium_map.flograph",
            "10_svg_retrofit_workbench.flograph",
            "11_goto_from_workflow.flograph",
        ]

    def test_examples_menu_lists_them_all(self, window):
        assert window._examples_menu.isEnabled()
        assert len(window._examples_menu.actions()) == 11

    @pytest.mark.parametrize("name", [
        "01_load_filter_visualize.flograph",
        "02_aggregate_dashboard.flograph",
        "03_custom_script_chart.flograph",
        "04_join_groupby_compare.flograph",
        "05_interactive_slicer_dashboard.flograph",
        "06_script_pipeline_frame.flograph",
        "07_retail_ops_command_center.flograph",
        "08_geo_population_map.flograph",
        "10_svg_retrofit_workbench.flograph",
        "11_goto_from_workflow.flograph",
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

    def test_folium_map_returns_a_renderable_leaflet_document(self, qtbot, window):
        pytest.importorskip("folium")
        window._open_example(template_path("09_folium_map.flograph"))
        wait_run(qtbot, window.engine)
        cache = window.engine.cache

        # unlike 08's folium node, this one returns the raw folium.Map
        # object (not pre-rendered via get_root().render()) — the point of
        # the example is that the webview card's to_html() now unwraps it
        # automatically, so a node author no longer has to do that by hand.
        folium_map = cache.outputs_for("n_folium_map")["view"]
        assert type(folium_map).__name__ == "Map"

        from flograph.ui.inspector.plotly_view import to_html
        html = to_html(folium_map)
        assert "leaflet" in html.lower()
        assert "trust" not in html.lower()

    def test_svg_retrofit_rebinds_a_page_whose_rects_became_paths(
            self, qtbot, window):
        window._open_example(template_path("10_svg_retrofit_workbench.flograph"))
        wait_run(qtbot, window.engine)
        cache = window.engine.cache

        # the re-export drew every room as an anonymous <path> …
        elements = cache.outputs_for("svg_elem_new")["elements"]
        rooms = elements[elements["tag"] == "path"]
        assert len(rooms) == 5 and (rooms["id"] == "").all()
        # … and the path parser still measures one as the box the <rect> was,
        # which the old read-every-number-in-d approach could not (the corner
        # arcs' radii and flags are not coordinates)
        lab = rooms[rooms["cls"] == "cls-2"].iloc[0]
        assert [lab.x, lab.y, lab.w, lab.h] == [40, 48, 160, 88]

        matches = cache.outputs_for("svg_diff")["matches"]
        by_old = matches.set_index("old_id")
        assert by_old.loc["room-lab", "status"] == "unnamed"   # id dropped
        assert by_old.loc["room-lab", "tag"] == "rect"
        assert by_old.loc["room-lab", "new_tag"] == "path"     # redrawn
        assert by_old.loc["room-lab", "match"] == "box"
        assert by_old.loc["pipe-main", "match"] == "box"       # same d, rewritten
        assert by_old.loc["valve-a", "match"] == "name"
        assert by_old.loc["room-plant", "status"] == "missing"  # genuinely gone

        # every id the page reaches for is back on the right element, bar the
        # room that no longer exists — and the class the export dropped too
        fixed = cache.outputs_for("svg_retrofit")["svg"]
        for element_id in ("room-lab", "room-office", "room-store", "valve-a",
                           "valve-b", "pipe-main", "zone-north"):
            assert f'id="{element_id}"' in fixed
        assert "room-plant" not in fixed
        assert re.search(r'<path id="room-lab" class="cls-2 room"', fixed)
        # ids the page never mentions are restored too — a name nothing asks
        # for costs nothing, and refusing to write one is how this ends up
        # doing nothing at all on a page whose wiring cannot be seen
        assert 'id="bg"' in fixed and 'id="zone-south"' in fixed
        # the office's popup is a Bootstrap modal, opened by attributes on the
        # shape rather than by its id — nothing in the page mentions them, so
        # the old artwork is the only place they exist
        office = re.search(r'<path[^>]*id="room-office"[^>]*>', fixed).group(0)
        assert 'data-bs-toggle="modal"' in office
        assert 'data-bs-target="#office-detail"' in office
        assert 'title="Office — 12 desks"' in office
        # …and not the fill, which belongs to the new drawing
        assert "#0e7490" not in office

        applied = cache.outputs_for("svg_retrofit")["applied"]
        assert list(applied[applied["action"] == "added"]["old_id"]) == [
            "bg", "label-lab", "label-office", "label-store", "pipe-main",
            "room-lab", "room-office", "room-store", "valve-a", "valve-b",
            "zone-north", "zone-south"]

        impact = cache.outputs_for("svg_impact")["impact"]
        verdicts = dict(zip(impact["ref"], impact["verdict"]))
        assert verdicts["room-plant"] == "BREAKS"
        assert verdicts["room"] == "auto-fix"      # the .room class, put back
        assert set(impact["verdict"]) == {"BREAKS", "auto-fix", "not in SVG"}

    def test_goto_from_workflow_links_carry_the_data(self, qtbot, window):
        window._open_example(template_path("11_goto_from_workflow.flograph"))
        graph = window.graph

        # the branches are fed entirely by links: the only real wires live
        # inside Sources & prep and the branch internals, so nothing crosses
        # the page. Four gotos resolve to five From reads (two share one link).
        assert len(graph.connections) == 22
        assert set(graph.links) == {
            "link:gt_from_enriched", "link:gt_from_targets",
            "link:gt_from_clean_p", "link:gt_from_products",
            "link:gt_from_clean_dq"}
        assert graph.links["link:gt_from_clean_p"].src_node == "gt_goto_clean"
        assert graph.links["link:gt_from_clean_dq"].src_node == "gt_goto_clean"
        assert graph.links["link:gt_from_enriched"].src_node == "gt_goto_enriched"
        assert not any(n.spec.broken for n in graph.nodes.values())

        ok = wait_run(qtbot, window.engine)
        assert ok
        cache = window.engine.cache
        for node in graph.nodes.values():
            assert node.status == NodeStatus.DONE, node.status_message

        # every From emitted the value its Goto received
        froms = [n for n in graph.nodes.values()
                 if n.spec.type_id == "flograph.util.goto_from"]
        assert len(froms) == 5
        for f in froms:
            assert cache.outputs_for(f.id)["value"] is not None

        # the shared prep reached every branch
        enriched = cache.outputs_for("gt_enrich")["joined"]
        assert len(enriched) == 10  # 11 orders, the zero-unit line filtered out
        assert {"revenue", "segment"} <= set(enriched.columns)

        region = cache.outputs_for("gt_region_group")["aggregated"]
        by_region = dict(zip(region["region"], region["revenue"]))
        assert by_region == {"North": 4350, "South": 1260, "East": 1420,
                             "West": 2350}
        assert int(region["revenue"].sum()) == 9380

        category = cache.outputs_for("gt_cat_group")["aggregated"]
        by_cat = dict(zip(category["category"], category["revenue"]))
        assert by_cat == {"Electronics": 6250, "Furniture": 2140,
                          "Accessories": 990}

        assert cache.outputs_for("gt_kpi_rev")["value"] == 9380
        assert round(cache.outputs_for("gt_kpi_attain")["value"], 4) == 1.0194

        assert len(graph.pages) == 1
        page = next(iter(graph.pages.values()))
        assert len(page.tiles) == 6


class TestSvgRetrofitRefusesToGuess:
    """The retrofit writes ids onto anonymous elements, which is only safe
    while it can say *which* element — so the interesting cases are the ones
    where it must decline."""

    @staticmethod
    def node(name):
        import json
        graph = json.loads(
            template_path("10_svg_retrofit_workbench.flograph").read_text()
        )["graph"]
        code = next(n["code"] for n in graph["nodes"] if n["id"] == name)
        namespace = {}
        exec(compile(code, f"<{name}>", "exec"), namespace)
        return namespace

    @classmethod
    def retrofit(cls, old_svg, new_svg, **overrides):
        class Ctx:
            def __init__(self, params):
                self.params = params

            def log(self, message):
                pass

        def call(name, **inputs):
            namespace = cls.node(name)
            params = {p["name"]: p.get("default") for p in namespace["PARAMS"]}
            params.update(overrides.get(name, {}))
            return namespace["run"](Ctx(params), **inputs)

        old = call("svg_elem_old", svg=old_svg)["elements"]
        new = call("svg_elem_new", svg=new_svg)["elements"]
        matches = call("svg_diff", old=old, new=new)["matches"]
        result = call("svg_retrofit", svg=new_svg, matches=matches,
                      new_elements=new)
        return matches, result["svg"], result["applied"]

    OLD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
           '<rect id="a" x="10" y="10" width="50" height="50"/>'
           '<rect id="b" x="100" y="10" width="50" height="50"/>'
           "</svg>")

    def test_two_identical_anonymous_paths_are_left_alone(self):
        twins = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
                 '<path d="M10,10h50v50h-50Z"/>'
                 '<path d="M10,10h50v50h-50Z"/>'
                 "</svg>")
        _matches, fixed, applied = self.retrofit(self.OLD, twins)
        assert "id=" not in fixed
        assert set(applied["action"]) == {"manual"}
        assert "would be a guess" in applied.iloc[0]["why"]

    def test_a_transform_is_enough_to_tell_them_apart(self):
        placed = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
                  '<path d="M10,10h50v50h-50Z"/>'
                  '<path transform="translate(90 0)" d="M10,10h50v50h-50Z"/>'
                  "</svg>")
        _matches, fixed, applied = self.retrofit(self.OLD, placed)
        assert '<path id="a" d="M10,10h50v50h-50Z"/>' in fixed
        assert '<path id="b" transform="translate(90 0)"' in fixed
        assert set(applied["action"]) == {"added"}

    def test_angle_brackets_in_a_script_do_not_shift_the_scan(self):
        scripted = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
            '<script>if (a<b && c>d) { mk("<rect x=\'1\'/>"); }</script>'
            '<!-- <rect x="9" y="9" width="1" height="1"/> -->'
            '<path d="M10,10h50v50h-50Z"/>'
            '<path transform="translate(90 0)" d="M10,10h50v50h-50Z"/>'
            "</svg>")
        _matches, fixed, applied = self.retrofit(self.OLD, scripted)
        assert '<path id="a" d=' in fixed and '<path id="b" transform=' in fixed
        assert "id=" not in fixed.split("</script>")[0]

    def test_matching_across_element_types_can_be_switched_off(self):
        placed = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
                  '<path d="M10,10h50v50h-50Z"/>'
                  '<path transform="translate(90 0)" d="M10,10h50v50h-50Z"/>'
                  "</svg>")
        matches, fixed, applied = self.retrofit(
            self.OLD, placed, svg_diff={"cross_tag": False})
        assert set(matches[matches["old_id"] != ""]["status"]) == {"missing"}
        assert "id=" not in fixed
        assert applied.empty


class TestSvgRetrofitMappingIsEditable:
    """The mapping table is the escape hatch: when the automatic match is
    wrong, or never found, you type the id in and it wins."""

    def open(self, qtbot, window):
        window._open_example(template_path("10_svg_retrofit_workbench.flograph"))
        wait_run(qtbot, window.engine)
        return window.engine.cache

    def test_the_plan_lists_new_elements_beside_what_they_matched(
            self, qtbot, window):
        cache = self.open(qtbot, window)
        plan = cache.outputs_for("svg_plan")["plan"]
        assert list(plan["ref"]) == list(range(len(plan)))   # document order
        room = plan[plan["id_wanted"] == "room-lab"].iloc[0]
        assert room["element"].startswith("path")            # the new element
        assert room["at"] == "40,48 160×88"
        assert room["was"] == "rect #room-lab · Lab"          # the old one
        assert room["outcome"] == "write the id on"
        # nothing typed in yet, so the mapping passes the diff straight on
        assert (cache.outputs_for("svg_apply")["matches"]["match"] != "manual").all()

    def test_a_typed_id_beats_the_automatic_match(self, qtbot, window):
        import json

        cache = self.open(qtbot, window)
        plan = cache.outputs_for("svg_plan")["plan"]
        # the demolished plant room has no counterpart — but the new artwork
        # has a Server Room where the operator says it belongs
        server = plan[plan["element"].str.contains("Server Room")].iloc[0]
        rows = [[""] for _ in range(len(plan))]
        rows[int(server.name)] = ["room-plant"]
        window.graph.set_param("svg_map", "data", json.dumps({
            "version": 2,
            "columns": [{"name": "set_id", "type": "text"}],
            "rows": rows,
        }))
        wait_run(qtbot, window.engine)
        cache = window.engine.cache

        matches = cache.outputs_for("svg_apply")["matches"]
        plant = matches[matches["old_id"] == "room-plant"].iloc[0]
        assert plant["status"] == "unnamed" and plant["match"] == "manual"
        assert plant["confidence"] == 1.0
        assert int(plant["new_ref"]) == int(server["ref"])

        # …and the retrofit writes it onto that element, not another
        fixed = cache.outputs_for("svg_retrofit")["svg"]
        assert 'id="room-plant"' in fixed
        assert fixed.count('id="room-plant"') == 1
        assert re.search(r'<path id="room-plant"[^>]*data-name="Server Room"',
                         fixed)
        # the hook that was breaking is now answered
        impact = cache.outputs_for("svg_impact")["impact"]
        verdicts = dict(zip(impact["ref"], impact["verdict"]))
        assert verdicts["room-plant"] == "auto-fix"
        assert "BREAKS" not in set(impact["verdict"])


class TestSvgRetrofitAlignsCoordinateSpaces:
    """Reported from a real site: the old artwork was a CorelDRAW export
    measured in thousands, the new one an Illustrator export measured in
    hundreds — the same drawing 34.589x apart. Every geometric pass failed
    and every element came back `missing`, which reads like "it was redrawn"
    and is nothing of the kind."""

    SCALE, DX, DY = 34.589, 14.93, 21.31

    # the two elements as they appeared in the browser's inspector
    OLD_RECT = ('x="2866.06" y="6308.09" width="1936.97" height="782.76" '
                'rx="98.02" ry="98.02"')
    NEW_PATH = ("M70.76,161.06h50.34c1.56,0,2.83,1.28,2.83,2.83v16.97c0,1.56"
                "-1.28,2.83-2.83,2.83h-50.34c-1.56,0-2.83-1.28-2.83-2.83v"
                "-16.97c0-1.56,1.28-2.83,2.83-2.83")

    def node(self, name):
        import json
        graph = json.loads(
            template_path("10_svg_retrofit_workbench.flograph").read_text()
        )["graph"]
        code = next(n["code"] for n in graph["nodes"] if n["id"] == name)
        namespace = {}
        exec(compile(code, f"<{name}>", "exec"), namespace)
        return namespace

    def call(self, name, _over=None, **inputs):
        class Ctx:
            def __init__(self, params):
                self.params = params

            def log(self, message):
                pass

        namespace = self.node(name)
        params = {p["name"]: p.get("default") for p in namespace["PARAMS"]}
        params.update(_over or {})
        return namespace["run"](Ctx(params), **inputs)

    def files(self):
        def big(x, y, w, h):
            s, dx, dy = self.SCALE, self.DX, self.DY
            return (f'x="{(x + dx) * s:.2f}" y="{(y + dy) * s:.2f}" '
                    f'width="{w * s:.2f}" height="{h * s:.2f}"')

        old = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9000 12000">'
               f'<rect class="fil51" id="G1.1" {self.OLD_RECT}/>'
               f'<rect class="fil52" id="G2.1" {big(67.93, 200, 120, 40)}/>'
               f'<circle class="fil9" id="V1" cx="{(300 + self.DX) * self.SCALE:.2f}"'
               f' cy="{(180 + self.DY) * self.SCALE:.2f}"'
               f' r="{9 * self.SCALE:.2f}"/>'
               "</svg>")
        new = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
               f'<path class="cls-49" d="{self.NEW_PATH}"/>'
               '<path class="cls-50" d="M67.93,200h120v40h-120Z"/>'
               '<circle class="cls-9" cx="300" cy="180" r="9"/>'
               "</svg>")
        return old, new

    def test_without_alignment_nothing_matches_at_all(self):
        old_svg, new_svg = self.files()
        old = self.call("svg_elem_old", svg=old_svg)["elements"]
        new = self.call("svg_elem_new", svg=new_svg)["elements"]
        matches = self.call("svg_diff", {"align": False},
                            old=old, new=new)["matches"]
        assert set(matches[matches["old_id"] != ""]["status"]) == {"missing"}

    def test_aligning_the_spaces_recovers_every_id(self):
        old_svg, new_svg = self.files()
        old = self.call("svg_elem_old", svg=old_svg)["elements"]
        new = self.call("svg_elem_new", svg=new_svg)["elements"]

        # the old rect really is the new path, 34.589x apart
        rect = old[old["id"] == "G1.1"].iloc[0]
        path = new[new["tag"] == "path"].iloc[0]
        assert round(rect.w / path.w, 2) == round(rect.h / path.h, 2) == 34.59

        matches = self.call("svg_diff", old=old, new=new)["matches"]
        by_old = matches.set_index("old_id")
        for element_id in ("G1.1", "G2.1", "V1"):
            assert by_old.loc[element_id, "status"] == "unnamed"
            assert by_old.loc[element_id, "match"] == "box"
            assert by_old.loc[element_id, "confidence"] >= 0.8   # auto-applies

        page = ("<html><body>" + old_svg + "<script>"
                'document.getElementById("G1.1");'
                'document.getElementById("G2.1");'
                'document.getElementById("V1");'
                "</script></body></html>")
        hooks = self.call("svg_hooks", html=page)["hooks"]
        result = self.call("svg_retrofit", svg=new_svg, matches=matches,
                           hooks=hooks, new_elements=new)
        assert set(result["applied"]["action"]) == {"added"}
        assert f'<path id="G1.1" class="cls-49" d="{self.NEW_PATH}"' in result["svg"]
        assert '<circle id="V1" class="cls-9"' in result["svg"]

    def test_an_alignment_that_explains_nothing_is_not_applied(self):
        # two drawings with no correspondence: fitting them together would
        # scale one onto the other and match nothing, so it must not happen
        old_svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                   '<rect id="a" x="0" y="0" width="10" height="10"/>'
                   '<rect id="b" x="80" y="80" width="20" height="5"/></svg>')
        new_svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                   '<circle cx="50" cy="50" r="7"/>'
                   '<path d="M10,90h3v3h-3Z"/></svg>')
        old = self.call("svg_elem_old", svg=old_svg)["elements"]
        new = self.call("svg_elem_new", svg=new_svg)["elements"]
        matches = self.call("svg_diff", old=old, new=new)["matches"]
        assert set(matches[matches["old_id"] != ""]["status"]) == {"missing"}


class TestSvgRetrofitFitsWhatTheElementsAgreeOn:
    """Also from the real site: fitting the two files by their outer bounds
    put 11 of 1087 elements onto an element of the new artwork. The bounds
    only correspond when both files' outermost edges are the same drawing,
    and an export that adds a frame — or drops one — moves them."""

    SCALE, DX, DY = 34.589, 14.93, 21.31

    # (x, y, w, h) in the new file's units
    ROOMS = [(70.76, 161.06, 56.0, 22.63), (67.93, 200.0, 120.0, 40.0),
             (30.0, 60.0, 45.0, 18.0), (150.0, 90.0, 45.0, 18.0),
             (220.0, 40.0, 80.0, 25.0), (100.0, 250.0, 60.0, 12.0)]

    def node(self, name):
        import json
        graph = json.loads(
            template_path("10_svg_retrofit_workbench.flograph").read_text()
        )["graph"]
        code = next(n["code"] for n in graph["nodes"] if n["id"] == name)
        namespace = {}
        exec(compile(code, f"<{name}>", "exec"), namespace)
        return namespace

    def call(self, name, _over=None, **inputs):
        said = []

        class Ctx:
            def __init__(self, params):
                self.params = params

            def log(self, message):
                said.append(message)

        namespace = self.node(name)
        params = {p["name"]: p.get("default") for p in namespace["PARAMS"]}
        params.update(_over or {})
        result = namespace["run"](Ctx(params), **inputs)
        return result, said

    def files(self, frame=True):
        old = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9000 12000">']
        new = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">']
        for n, (x, y, w, h) in enumerate(self.ROOMS, start=1):
            s, dx, dy = self.SCALE, self.DX, self.DY
            old.append(f'<rect class="fil5{n}" id="G{n}.1" '
                       f'x="{(x + dx) * s:.2f}" y="{(y + dy) * s:.2f}" '
                       f'width="{w * s:.2f}" height="{h * s:.2f}"/>')
            new.append(f'<path class="cls-4{n}" '
                       f'd="M{x},{y}h{w}v{h}h-{w}Z"/>')
        if frame:
            # The whole point: a border the old file never had. It is the
            # outermost thing in the new one, so it decides the outer-bounds
            # fit all by itself.
            new.append('<path class="cls-frame" d="M0,0h400v300h-400Z"/>')
        return "".join(old) + "</svg>", "".join(new) + "</svg>"

    def elements(self, old_svg, new_svg):
        return (self.call("svg_elem_old", svg=old_svg)[0]["elements"],
                self.call("svg_elem_new", svg=new_svg)[0]["elements"])

    def test_a_frame_on_one_side_does_not_wreck_the_alignment(self):
        old, new = self.elements(*self.files(frame=True))
        matches, said = self.call("svg_diff", old=old, new=new)
        matches = matches["matches"]
        assert "".join(said).count("what most elements agree on") == 1

        found = matches[matches["old_id"] != ""].set_index("old_id")
        assert set(found["status"]) == {"unnamed"}, "every room should be paired"
        assert len(found) == len(self.ROOMS)

    def test_the_scale_it_finds_is_the_real_one(self):
        old, new = self.elements(*self.files(frame=True))
        _, said = self.call("svg_diff", old=old, new=new)
        line = next(m for m in said if "scale" in m)
        assert f"{1 / self.SCALE:.4g}" in line
        assert f"{-self.DX:+.4g}" in line and f"{-self.DY:+.4g}" in line

    def test_it_beats_the_outer_bounds_and_says_so(self):
        old, new = self.elements(*self.files(frame=True))
        _, said = self.call("svg_diff", old=old, new=new)
        beaten = next(m for m in said if "would have landed" in m)
        assert "the outer bounds" in beaten
        assert int(beaten.rsplit("landed ", 1)[1].rstrip(")")) < len(self.ROOMS)
        landed = next(m for m in said if "now land on an element" in m)
        assert landed.startswith(f"{len(self.ROOMS)} of")

    def test_the_outer_bounds_still_win_when_they_are_right(self):
        # no frame: both files bound the same drawing, and the cheap fit is
        # the correct one — it must not be discarded for being cheap
        old, new = self.elements(*self.files(frame=False))
        matches, _ = self.call("svg_diff", old=old, new=new)
        found = matches["matches"]
        assert len(found[found["status"] == "unnamed"]) == len(self.ROOMS)


class TestSvgRetrofitSeesIdsThePageOnlyQuotes:
    """The reason a real page looked as if it touched 3 ids out of 173: its
    popups are bound by one delegated handler that looks `event.target.id`
    up in a table of its own, so the ids appear in the page as nothing but
    quoted strings."""

    node = TestSvgRetrofitFitsWhatTheElementsAgreeOn.node
    call = TestSvgRetrofitFitsWhatTheElementsAgreeOn.call

    ART = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
           '<rect class="fil51" id="G1.1" x="10" y="10" width="60" height="20"/>'
           '<rect class="fil52" id="G2.1" x="90" y="10" width="60" height="20"/>'
           '<rect class="fil53" id="G3.1" x="170" y="10" width="60" height="20"/>'
           "</svg>")
    WIRING = ('<script src="/lib/popups.js"></script>'
              '<script>var rooms = {"G1.1": {t: "Lab"}, "G2.1": {t: "Store"}};'
              'plan.addEventListener("click", function (e) {'
              '  var room = rooms[e.target.id]; if (room) show(room); });'
              "</script>")

    def page(self):
        return "<html><body>" + self.ART + self.WIRING + "</body></html>"

    def test_without_the_artwork_the_page_looks_untouched(self):
        hooks, _ = self.call("svg_hooks", html=self.page())
        outside = hooks["hooks"]
        outside = outside[(outside["where"] != "internal")
                          & (outside["target"] == "id")]
        assert list(outside["ref"]) == []

    def test_knowing_the_artwork_finds_the_ids_it_quotes(self):
        elements = self.call("svg_elem_old", svg=self.ART)[0]["elements"]
        hooks, said = self.call("svg_hooks", html=self.page(),
                                elements=elements)
        found = hooks["hooks"]
        found = found[(found["where"] != "internal") & (found["target"] == "id")]
        assert sorted(found["ref"]) == ["G1.1", "G2.1"]
        assert set(found["where"]) == {"script"}
        assert "2 of the 3 ids in the old artwork are named by the page" in said

    def test_the_artworks_own_ids_are_not_the_page_using_them(self):
        # every id appears quoted inside the inline <svg> as id="G1.1"; that
        # is the drawing, not the page reaching into it
        elements = self.call("svg_elem_old", svg=self.ART)[0]["elements"]
        page = "<html><body>" + self.ART + "</body></html>"
        hooks, _ = self.call("svg_hooks", html=page, elements=elements)
        found = hooks["hooks"]
        assert list(found[found["where"] != "internal"]["ref"]) == []

    def test_it_names_the_scripts_it_cannot_see_into(self):
        _, said = self.call("svg_hooks", html=self.page())
        assert any("popups.js" in message and "could not be read" in message
                   and "wire the page's Path in" in message
                   for message in said)

    def test_the_retrofit_then_has_something_to_restore(self):
        elements = self.call("svg_elem_old", svg=self.ART)[0]["elements"]
        new_svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
                   '<path class="cls-1" d="M10,10h60v20h-60Z"/>'
                   '<path class="cls-2" d="M90,10h60v20h-60Z"/>'
                   '<path class="cls-3" d="M170,10h60v20h-60Z"/></svg>')
        new = self.call("svg_elem_new", svg=new_svg)[0]["elements"]
        matches = self.call("svg_diff", old=elements, new=new)[0]["matches"]
        hooks = self.call("svg_hooks", html=self.page(),
                          elements=elements)[0]["hooks"]
        result, said = self.call("svg_retrofit", svg=new_svg, matches=matches,
                                 hooks=hooks, new_elements=new)
        assert '<path id="G1.1"' in result["svg"]
        assert '<path id="G2.1"' in result["svg"]
        # G3.1 is in the drawing and nothing on the page asks for it — it is
        # written anyway, an id nothing uses costing nothing
        assert '<path id="G3.1"' in result["svg"]
        assert not any("nothing was written" in m for m in said)
        assert "2 of the 2 id(s) the page asks for now exist in the artwork" \
            in said

    def test_the_restriction_is_still_there_for_those_who_want_it(self):
        elements = self.call("svg_elem_old", svg=self.ART)[0]["elements"]
        new_svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
                   '<path class="cls-1" d="M10,10h60v20h-60Z"/>'
                   '<path class="cls-3" d="M170,10h60v20h-60Z"/></svg>')
        new = self.call("svg_elem_new", svg=new_svg)[0]["elements"]
        matches = self.call("svg_diff", old=elements, new=new)[0]["matches"]
        hooks = self.call("svg_hooks", html=self.page(),
                          elements=elements)[0]["hooks"]
        result, _ = self.call("svg_retrofit", {"only_hooked": True},
                              svg=new_svg, matches=matches, hooks=hooks,
                              new_elements=new)
        assert '<path id="G1.1"' in result["svg"]
        assert 'id="G3.1"' not in result["svg"]

    def test_a_class_the_page_does_not_style_is_left_off(self):
        # the asymmetry: an id is a name, a class is a style. Putting back a
        # `fil51` the old stylesheet still has a rule for changes the drawing.
        art = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
               '<rect class="fil51" id="G1.1" x="10" y="10" '
               'width="60" height="20"/></svg>')
        new_svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
                   '<path class="cls-1" d="M10,10h60v20h-60Z"/></svg>')
        elements = self.call("svg_elem_old", svg=art)[0]["elements"]
        new = self.call("svg_elem_new", svg=new_svg)[0]["elements"]
        matches = self.call("svg_diff", old=elements, new=new)[0]["matches"]
        page = ('<html><body>' + art + '<script>var r = {"G1.1": 1};</script>'
                "</body></html>")
        hooks = self.call("svg_hooks", html=page, elements=elements)[0]["hooks"]
        result, _ = self.call("svg_retrofit", svg=new_svg, matches=matches,
                              hooks=hooks, new_elements=new)
        assert '<path id="G1.1"' in result["svg"]
        assert "fil51" not in result["svg"]


class TestSvgRetrofitCarriesBehaviourAcross:
    """Reported from a real site, and the reason restoring every id still
    left the page dead: the popups are Bootstrap modals, and a modal is not
    opened by an id. It is opened by attributes sitting on the shape —

        data-bs-toggle="modal" data-bs-target="#phasegates"
        data-placement="left" title="Phase Gate Summaries"

    — which the re-export dropped along with the id. Nothing in the page
    mentions them, so nothing but the old artwork knows they existed."""

    node = TestSvgRetrofitFitsWhatTheElementsAgreeOn.node
    call = TestSvgRetrofitFitsWhatTheElementsAgreeOn.call

    OLD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
           '<rect class="fil51" id="G1.1" x="10" y="10" width="60" height="20" '
           'data-bs-toggle="modal" data-bs-target="#phasegates" '
           'data-toggle="tooltip" data-placement="left" '
           'title="phase Gate Summaries" style="cursor: pointer;"/>'
           '<rect class="fil52" id="G2.1" x="90" y="10" width="60" height="20" '
           'fill="#0e7490"/>'
           "</svg>")
    NEW = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
           '<path class="cls-1" d="M10,10h60v20h-60Z"/>'
           '<path class="cls-2" d="M90,10h60v20h-60Z" fill="#0e7490"/></svg>')

    def retrofit(self, _over=None, old=None, new=None):
        old_svg, new_svg = old or self.OLD, new or self.NEW
        olds = self.call("svg_elem_old", svg=old_svg)[0]["elements"]
        news = self.call("svg_elem_new", svg=new_svg)[0]["elements"]
        matches = self.call("svg_diff", old=olds, new=news)[0]["matches"]
        return self.call("svg_retrofit", _over, svg=new_svg, matches=matches,
                         new_elements=news)

    def test_the_element_list_carries_what_makes_an_element_interactive(self):
        olds = self.call("svg_elem_old", svg=self.OLD)[0]["elements"]
        import json
        carried = json.loads(olds[olds["id"] == "G1.1"].iloc[0]["behaviour"])
        assert carried == {"data-bs-toggle": "modal",
                           "data-bs-target": "#phasegates",
                           "data-toggle": "tooltip",
                           "data-placement": "left",
                           "title": "phase Gate Summaries"}
        # presentation is not behaviour: the new drawing is the drawing
        assert "style" not in carried and "fill" not in carried
        # and the plain element carries nothing at all
        assert olds[olds["id"] == "G2.1"].iloc[0]["behaviour"] == ""

    def test_the_modal_attributes_land_on_the_path_that_replaced_the_rect(self):
        result, said = self.retrofit()
        fixed = result["svg"]
        assert 'data-bs-toggle="modal"' in fixed
        assert 'data-bs-target="#phasegates"' in fixed
        assert 'title="phase Gate Summaries"' in fixed
        # on the right element, and only that one
        at = fixed.index("<path")
        first = fixed[at:fixed.index("<path", at + 1)]
        assert 'id="G1.1"' in first and "data-bs-toggle" in first
        assert fixed.count("data-bs-toggle") == 1
        assert any("given back the attributes that make them interactive"
                   in message for message in said)

    def test_the_new_export_wins_where_it_already_says_something(self):
        # an attribute the new file has is the new file's business
        new = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
               '<path class="cls-1" d="M10,10h60v20h-60Z" title="Redrawn"/>'
               '<path class="cls-2" d="M90,10h60v20h-60Z"/></svg>')
        fixed = self.retrofit(new=new)[0]["svg"]
        assert 'title="Redrawn"' in fixed
        assert "phase Gate Summaries" not in fixed
        assert 'data-bs-toggle="modal"' in fixed      # this one it lacked

    def test_it_is_reported_and_can_be_turned_off(self):
        applied = self.retrofit()[0]["applied"]
        row = applied[applied["old_id"] == "G1.1"].iloc[0]
        assert set(row["attributes"].split()) == {
            "data-bs-toggle", "data-bs-target", "data-toggle",
            "data-placement", "title"}

        off, said = self.retrofit({"restore_behaviour": False})
        assert "data-bs-toggle" not in off["svg"]
        assert 'id="G1.1"' in off["svg"]              # the id still comes back
        assert not any("given back the attributes" in m for m in said)

    def test_a_quoted_value_cannot_break_out_of_the_attribute(self):
        old = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
               '<rect id="G1.1" x="10" y="10" width="60" height="20" '
               "title='Fish &amp; Chips &lt;b&gt;\"quoted\"' /></svg>")
        new = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
               '<path class="cls-1" d="M10,10h60v20h-60Z"/></svg>')
        fixed = self.retrofit(old=old, new=new)[0]["svg"]
        assert '&amp;' in fixed and "&lt;b&gt;" in fixed and "&quot;" in fixed
        # still one tag, not two
        assert fixed.count("<path") == 1 and fixed.count("/>") == 1

    def test_the_log_says_so_when_the_old_artwork_has_none_of_this(self):
        old = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
               '<rect id="G1.1" x="10" y="10" width="60" height="20"/></svg>')
        new = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
               '<path class="cls-1" d="M10,10h60v20h-60Z"/></svg>')
        said = self.retrofit(old=old, new=new)[1]
        assert any("check that the old SVG being read is the one the page "
                   "really used" in message for message in said)


class TestSvgRetrofitNoticesTheSameDrawingTwice:
    """The easy mistake: point the page input at the file this flow last
    wrote, and it retrofits the new artwork onto itself. Every number in
    that run looks healthy and nothing whatever is handed back."""

    node = TestSvgRetrofitFitsWhatTheElementsAgreeOn.node
    call = TestSvgRetrofitFitsWhatTheElementsAgreeOn.call

    ART = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
           + "".join(f'<rect id="G{n}.1" x="{n * 30}" y="10" '
                     f'width="20" height="{10 + n}"/>' for n in range(1, 8))
           + "</svg>")

    def test_it_says_so_when_both_sides_are_the_same_file(self):
        elements = self.call("svg_elem_old", svg=self.ART)[0]["elements"]
        _, said = self.call("svg_diff", old=elements, new=elements)
        assert any("look like the same drawing" in message for message in said)
        assert any("not a page this flow has written" in message
                   for message in said)

    def test_a_real_re_export_is_not_accused_of_it(self):
        new_svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
                   + "".join(f'<path class="cls-{n}" d="M{n * 30},10h20v{10 + n}'
                             f'h-20Z"/>' for n in range(1, 8)) + "</svg>")
        old = self.call("svg_elem_old", svg=self.ART)[0]["elements"]
        new = self.call("svg_elem_new", svg=new_svg)[0]["elements"]
        _, said = self.call("svg_diff", old=old, new=new)
        assert not any("same drawing" in message for message in said)


class TestSvgRetrofitReadsTheScriptsThePageLoads:
    """From a real site: 173 ids in the artwork, 2 named by the page, and
    five .js files doing all the work. From the HTML alone the page looks as
    if it barely touches its own drawing."""

    node = TestSvgRetrofitFitsWhatTheElementsAgreeOn.node
    call = TestSvgRetrofitFitsWhatTheElementsAgreeOn.call

    ART = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
           '<rect class="fil51" id="G1.1" x="10" y="10" width="60" height="20"/>'
           '<rect class="fil51" id="G2.1" x="90" y="10" width="60" height="20"/>'
           '<rect class="fil52" id="G3.1" x="170" y="10" width="60" height="20"/>'
           "</svg>")
    PAGE = ('<html><body>' + ART
            + '<script src="js/phases.js"></script>'
            + '<script src="/assets/steps.js"></script>'
            + '<script src="https://cdn.example.com/bootstrap.js"></script>'
            + '<script src="missing.js"></script></body></html>')

    def site(self, tmp_path):
        (tmp_path / "js").mkdir()
        (tmp_path / "js" / "phases.js").write_text(
            'var phases = {"G1.1": "Design", "G2.1": "Build"};\n'
            'document.getElementById("G1.1").classList.add("on");\n')
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "steps.js").write_text(
            'document.querySelectorAll(".fil51").forEach(hook);\n')
        page = tmp_path / "overview.html"
        page.write_text(self.PAGE)
        return page

    def test_the_page_alone_looks_almost_untouched(self, tmp_path):
        elements = self.call("svg_elem_old", svg=self.ART)[0]["elements"]
        hooks = self.call("svg_hooks", html=self.PAGE,
                          elements=elements)[0]["hooks"]
        outside = hooks[hooks["where"] != "internal"]
        assert list(outside["ref"]) == []

    def test_reading_them_finds_what_the_page_never_says(self, tmp_path):
        page = self.site(tmp_path)
        elements = self.call("svg_elem_old", svg=self.ART)[0]["elements"]
        found, said = self.call("svg_hooks", html=self.PAGE,
                                elements=elements, path=str(page))
        hooks = found["hooks"]
        outside = hooks[hooks["where"] != "internal"]
        ids = sorted(outside[outside["target"] == "id"]["ref"])
        classes = sorted(set(outside[outside["target"] == "class"]["ref"]))
        assert ids == ["G1.1", "G2.1"]
        assert "fil51" in classes
        # the file that wants it is named, so the report can say which
        assert set(outside["where"]) == {"phases.js", "steps.js"}
        assert any("read 2 script(s)" in message for message in said)

    def test_a_cdn_is_not_ours_to_read_and_a_missing_file_is_named(self, tmp_path):
        page = self.site(tmp_path)
        _, said = self.call("svg_hooks", html=self.PAGE, path=str(page))
        complaint = next(m for m in said if "could not be read" in m)
        assert "missing.js" in complaint
        assert "bootstrap.js" not in complaint      # a CDN, never expected here

    def test_the_classes_it_finds_are_then_restored(self, tmp_path):
        page = self.site(tmp_path)
        new_svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
                   '<path class="cls-1" d="M10,10h60v20h-60Z"/>'
                   '<path class="cls-2" d="M90,10h60v20h-60Z"/>'
                   '<path class="cls-3" d="M170,10h60v20h-60Z"/></svg>')
        elements = self.call("svg_elem_old", svg=self.ART)[0]["elements"]
        new = self.call("svg_elem_new", svg=new_svg)[0]["elements"]
        matches = self.call("svg_diff", old=elements, new=new)[0]["matches"]
        hooks = self.call("svg_hooks", html=self.PAGE, elements=elements,
                          path=str(page))[0]["hooks"]
        fixed = self.call("svg_retrofit", svg=new_svg, matches=matches,
                          hooks=hooks, new_elements=new)[0]["svg"]
        # steps.js selects .fil51, so that class has to come back
        assert fixed.count("fil51") == 2
        assert "fil52" not in fixed          # nothing selects it


class TestSvgRetrofitGivesALayerItsIdBack:
    """Both ids a real page named turned out to be <g> layers, and groups
    were the one thing the matcher would not pair — so a drawing whose every
    shape matched still lost the handle the page scopes its handlers to."""

    node = TestSvgRetrofitFitsWhatTheElementsAgreeOn.node
    call = TestSvgRetrofitFitsWhatTheElementsAgreeOn.call

    def files(self, wrap=False):
        old = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
               '<g id="New_x0020_Boxes">'
               '<rect id="G1.1" x="10" y="10" width="60" height="20"/>'
               '<rect id="G2.1" x="90" y="10" width="140" height="20"/>'
               "</g></svg>")
        inner = ('<g>'
                 '<path class="cls-1" d="M10,10h60v20h-60Z"/>'
                 '<path class="cls-2" d="M90,10h140v20h-140Z"/>'
                 "</g>")
        new = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
               + (f"<g>{inner}</g>" if wrap else inner) + "</svg>")
        return old, new

    def matches(self, wrap=False):
        old_svg, new_svg = self.files(wrap)
        old = self.call("svg_elem_old", svg=old_svg)[0]["elements"]
        new = self.call("svg_elem_new", svg=new_svg)[0]["elements"]
        return self.call("svg_diff", old=old, new=new)[0]["matches"], new_svg, new

    def test_the_layer_id_comes_back(self):
        found, new_svg, new = self.matches()
        row = found[found["old_id"] == "New_x0020_Boxes"].iloc[0]
        assert row["status"] == "unnamed" and row["match"] == "layer"
        fixed = self.call("svg_retrofit", svg=new_svg, matches=found,
                          new_elements=new)[0]["svg"]
        assert '<g id="New_x0020_Boxes">' in fixed

    def test_it_picks_the_group_that_actually_holds_them(self):
        # a wrapper around the real layer holds the same shapes and more —
        # the tightest group that holds them is the counterpart
        found, new_svg, new = self.matches(wrap=True)
        row = found[found["old_id"] == "New_x0020_Boxes"].iloc[0]
        assert row["match"] == "layer"
        fixed = self.call("svg_retrofit", svg=new_svg, matches=found,
                          new_elements=new)[0]["svg"]
        # the inner one, not the wrapper
        assert fixed.startswith('<svg xmlns="http://www.w3.org/2000/svg" '
                                'viewBox="0 0 400 300"><g><g '
                                'id="New_x0020_Boxes">')

    def test_a_group_holding_nothing_that_matched_is_left_alone(self):
        old_svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
                   '<g id="New_x0020_Boxes">'
                   '<rect id="G1.1" x="10" y="10" width="60" height="20"/>'
                   "</g></svg>")
        new_svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
                   '<g><path d="M300,250h9v9h-9Z"/></g></svg>')
        old = self.call("svg_elem_old", svg=old_svg)[0]["elements"]
        new = self.call("svg_elem_new", svg=new_svg)[0]["elements"]
        found = self.call("svg_diff", old=old, new=new)[0]["matches"]
        row = found[found["old_id"] == "New_x0020_Boxes"].iloc[0]
        assert row["status"] == "missing"

    def test_a_group_is_never_matched_on_position_alone(self):
        # every <g> has a 0x0 box, so the geometry pass used to pair any two
        # of them perfectly — a match that means nothing
        old_svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
                   '<g id="Layer_1"/><rect id="G1.1" x="10" y="10" '
                   'width="60" height="20"/></svg>')
        new_svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
                   '<g/><path d="M10,10h60v20h-60Z"/></svg>')
        old = self.call("svg_elem_old", svg=old_svg)[0]["elements"]
        new = self.call("svg_elem_new", svg=new_svg)[0]["elements"]
        found = self.call("svg_diff", old=old, new=new)[0]["matches"]
        assert found[found["old_id"] == "Layer_1"].iloc[0]["status"] == "missing"
        assert found[found["old_id"] == "G1.1"].iloc[0]["status"] == "unnamed"


class TestSvgDiffSaysWhenNothingLinesUp:
    """From a real run: a Source File whose path was not set yet read its
    built-in sample, so a 1,087-element drawing was compared against a
    16-element toy. Nothing failed. The fit landed 1 of 1087, 172 elements
    came back missing, and every number after that was nonsense wearing the
    shape of an answer."""

    node = TestSvgRetrofitFitsWhatTheElementsAgreeOn.node
    call = TestSvgRetrofitFitsWhatTheElementsAgreeOn.call

    def drawing(self, count, size=20):
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4000 4000">'
                + "".join(f'<rect id="G{n}" x="{n * 30}" y="{n * 7}" '
                          f'width="{size + n % 5}" height="{size}"/>'
                          for n in range(count)) + "</svg>")

    def test_the_wrong_file_entirely_is_called_out(self):
        old = self.call("svg_elem_old", svg=self.drawing(200))[0]["elements"]
        new = self.call("svg_elem_new",
                        svg=self.drawing(4, size=3))[0]["elements"]
        _, said = self.call("svg_diff", old=old, new=new)
        complaint = next(m for m in said if "almost nothing" in m)
        assert "do not look like two versions of one drawing" in complaint
        assert "built-in sample" in complaint

    def test_a_drawing_that_does_line_up_is_not_nagged(self):
        old = self.call("svg_elem_old", svg=self.drawing(200))[0]["elements"]
        new = self.call("svg_elem_new", svg=self.drawing(200))[0]["elements"]
        _, said = self.call("svg_diff", old=old, new=new)
        assert not any("almost nothing" in message for message in said)

    def test_two_tiny_files_are_not_nagged_either(self):
        # under a score of elements there is nothing to be confident about
        old = self.call("svg_elem_old", svg=self.drawing(4))[0]["elements"]
        new = self.call("svg_elem_new",
                        svg=self.drawing(2, size=3))[0]["elements"]
        _, said = self.call("svg_diff", old=old, new=new)
        assert not any("almost nothing" in message for message in said)
