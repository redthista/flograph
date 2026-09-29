"""Map outlines from disk, never from a CDN (flograph.geoassets).

plotly.js fetches a geo map's outlines from cdn.plot.ly when it draws it.
The 1:110m set ships with flograph; the 1:50m set is a Web Library. Every
Plotly page flograph builds carries the files a map needs and points
plotly at a local folder, so nothing is fetched.
"""
import json

import pytest

from flograph import geoassets, weblibs

go = pytest.importorskip("plotly.graph_objects")


class TestNames:
    def test_plotlys_own_naming(self):
        assert geoassets.topojson_name() == "world_110m"
        assert geoassets.topojson_name("north america", 50) == \
            "north-america_50m"
        assert geoassets.topojson_name(None, None) == "world_110m"

    def test_a_default_choropleth_is_drawn_on_the_world(self):
        fig = go.Figure(go.Choropleth(locations=["FRA"], z=[1]))
        assert geoassets.names_for(fig) == ["world_110m"]

    def test_scope_and_resolution_come_from_the_layout(self):
        fig = go.Figure(go.Scattergeo(lon=[0], lat=[0]),
                        layout={"geo": {"scope": "europe",
                                        "resolution": 50}})
        assert geoassets.names_for(fig) == ["europe_50m"]

    def test_every_geo_subplot_is_counted_once(self):
        fig = go.Figure([go.Scattergeo(lon=[0], lat=[0]),
                         go.Scattergeo(lon=[0], lat=[0], geo="geo2")],
                        layout={"geo2": {"scope": "usa"}})
        assert geoassets.names_for(fig) == ["usa_110m", "world_110m"] or \
            sorted(geoassets.names_for(fig)) == ["usa_110m", "world_110m"]

    def test_a_chart_with_no_map_needs_none(self):
        assert geoassets.names_for(go.Figure(go.Bar(y=[1]))) == []

    def test_json_text_works_the_same_as_a_figure(self):
        fig = go.Figure(go.Choropleth(locations=["FRA"], z=[1]),
                        layout={"geo": {"scope": "africa"}})
        assert geoassets.names_for(fig.to_json()) == ["africa_110m"]


class TestOnDisk:
    @pytest.mark.parametrize("scope", geoassets.SCOPES)
    def test_every_scope_ships_at_the_default_resolution(self, scope):
        name = geoassets.topojson_name(scope, 110)
        path = geoassets.find(name)
        assert path is not None and path.parent == geoassets.BUNDLED_DIR
        assert json.loads(path.read_text())["type"] == "Topology"

    def test_fine_detail_is_the_web_library_not_shipped(self, tmp_path,
                                                        monkeypatch):
        monkeypatch.setattr(weblibs, "store_dir", lambda: tmp_path)
        assert geoassets.find("world_50m") is None
        assert geoassets.missing(["world_110m", "world_50m"]) == ["world_50m"]
        assert "Web Libraries" in geoassets.install_hint(["world_50m"])

    def test_fine_detail_is_found_once_installed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(weblibs, "store_dir", lambda: tmp_path)
        library = weblibs.CATALOGUE[geoassets.DETAIL_LIBRARY]
        folder = weblibs.library_dir(library.name, library.version)
        folder.mkdir(parents=True)
        for asset in library.assets:
            (folder / asset.filename).write_text('{"type":"Topology"}')
        assert geoassets.find("world_50m") == folder / "world_50m.json"

    def test_the_catalogue_covers_every_scope_at_50m(self):
        library = weblibs.CATALOGUE[geoassets.DETAIL_LIBRARY]
        assert {a.filename for a in library.assets} == {
            f"{geoassets.topojson_name(s, 50)}.json" for s in geoassets.SCOPES}


class TestPages:
    def test_the_preload_is_where_plotly_looks(self):
        js = geoassets.preload_js(["world_110m", "nowhere_1m"])
        assert "window.PlotlyGeoAssets" in js and '"world_110m"' in js
        assert "nowhere_1m" not in js
        assert "</" not in js      # it goes inside a <script>

    def test_a_card_page_carries_its_outlines_and_never_the_cdn(self):
        from flograph.core.html import to_html
        fig = go.Figure(go.Choropleth(locations=["FRA"], z=[1]))
        html = to_html(fig)
        assert '"world_110m"' in html
        assert geoassets.LOCAL_TOPOJSON_URL in html
        head = html[:html.index("</head>")]
        assert "PlotlyGeoAssets" in head

    def test_a_page_with_no_map_is_unchanged(self):
        from flograph.core.html import to_html
        # (plotly.js itself mentions PlotlyGeoAssets; the preload's own
        # text is what must be absent)
        assert "var G=A.topojson" not in to_html(go.Figure(go.Bar(y=[1])))


class TestInternet:
    @pytest.mark.parametrize("trace", ["Scattermap", "Densitymap",
                                       "Choroplethmap"])
    def test_a_tile_map_needs_the_internet(self, trace):
        assert geoassets.needs_the_internet(go.Figure(getattr(go, trace)()))

    def test_shapes_by_url_need_the_internet(self):
        fig = go.Figure(go.Choropleth(geojson="https://example.com/x.json",
                                      locations=["a"], z=[1]))
        assert geoassets.needs_the_internet(fig)

    def test_a_geo_map_on_outlines_does_not(self):
        fig = go.Figure(go.Choropleth(locations=["FRA"], z=[1]))
        assert not geoassets.needs_the_internet(fig)
