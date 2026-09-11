"""A shape as one number (N3), Qt-free: reading one, keeping one while a
side moves, and a tile carrying one through a save.

The UI half — the Shape menu, the dialog, the drag — is
test_tile_shape_ui.py."""
import json

import pytest

from flograph.core import Graph, Page, Tile
from flograph.core.aspect import (PRESETS, format_aspect, keep_aspect,
                                  leading_side, parse_aspect, parse_shape,
                                  preset_for, same_aspect)
from flograph.core.serialization import graph_from_dict, graph_to_dict

FLOOR = (160.0, 90.0)


class TestReadingAShape:
    @pytest.mark.parametrize("text, expected", [
        ("16:9", 16 / 9), ("4x3", 4 / 3), ("3/2", 1.5), ("1.5", 1.5),
        ("16:9  Wide", 16 / 9), ("Wide", 16 / 9), ("wide", 16 / 9),
        ("16 : 9", 16 / 9), ("Column", 1 / 3), ("5:2", 2.5),
    ])
    def test_a_shape(self, text, expected):
        assert parse_shape(text) == (True, pytest.approx(expected))

    @pytest.mark.parametrize("text", ["", "Any", "any shape", "free"])
    def test_no_shape_is_an_answer(self, text):
        assert parse_shape(text) == (True, None)

    @pytest.mark.parametrize("text", ["banana", "16:0", "-2", "0", "inf"])
    def test_words_that_are_not_one(self, text):
        assert parse_shape(text) == (False, None)

    def test_the_report_reads_through_the_same_parser(self):
        """One reader of "16:9" for both kinds of page — the renderer
        imports it rather than keeping a copy that could drift."""
        from flograph.ui.report import render
        assert render.parse_aspect is parse_aspect


class TestWritingOne:
    def test_a_named_shape_is_written_as_its_name_says(self):
        assert format_aspect(16 / 9) == "16:9"
        assert format_aspect(1 / 3) == "1:3"

    def test_anything_else_as_the_simplest_pair(self):
        assert format_aspect(2.5) == "5:2"

    def test_every_preset_reads_back_as_itself(self):
        for name, width, height in PRESETS:
            ok, aspect = parse_shape(format_aspect(width / height))
            assert ok and preset_for(aspect)[0] == name

    def test_a_pixel_of_rounding_is_still_the_same_shape(self):
        assert same_aspect(16 / 9, 420 / 236)
        assert not same_aspect(16 / 9, 4 / 3)
        assert same_aspect(None, None)
        assert not same_aspect(None, 1.0)


class TestKeepingOne:
    def test_the_width_leads_and_the_height_follows(self):
        assert keep_aspect(420, 320, 16 / 9, "width", FLOOR) == (420, 236.0)

    def test_the_height_leads_and_the_width_follows(self):
        assert keep_aspect(420, 270, 16 / 9, "height", FLOOR) == (480.0, 270)

    def test_the_following_side_is_never_under_its_floor(self):
        """A Banner at the narrowest a tile can be would be 53 high; the
        width grows until the height fits instead."""
        assert keep_aspect(160, 90, 3, "width", FLOOR) == (270, 90.0)

    def test_nor_the_leading_one(self):
        assert keep_aspect(100, 100, 1 / 3, "height", FLOOR) == (160.0, 480.0)

    def test_edges_steer_their_own_side(self):
        assert leading_side("right", (400, 300), (500, 500)) == "width"
        assert leading_side("bottom", (400, 300), (900, 310)) == "height"

    def test_the_corner_follows_the_bigger_pull(self):
        assert leading_side("corner", (400, 300), (500, 310)) == "width"
        assert leading_side("corner", (400, 300), (410, 400)) == "height"


class TestATileCarriesItsShape:
    def _graph(self, aspect):
        graph = Graph()
        graph.add_page(Page(id="p1"))
        graph.add_tile("p1", Tile(id="t1", node_id="n1",
                                  rect=(0, 0, 320, 180), aspect=aspect))
        return graph

    def test_through_a_save(self, registry):
        data = json.loads(json.dumps(graph_to_dict(self._graph(16 / 9))))
        tile = graph_from_dict(data, registry).pages["p1"].tiles["t1"]
        assert tile.aspect == pytest.approx(16 / 9)

    def test_a_free_tile_writes_nothing(self, registry):
        """Only a tile given a shape says so — a file with no shaped tiles
        is byte-for-byte what it was before shapes existed."""
        entry = graph_to_dict(self._graph(None))["graph"]["pages"][0]
        assert "aspect" not in entry["tiles"][0]

    @pytest.mark.parametrize("junk", ["wide", -1, 0, None, [1, 2]])
    def test_nonsense_loads_as_no_shape(self, registry, junk):
        data = graph_to_dict(self._graph(None))
        data["graph"]["pages"][0]["tiles"][0]["aspect"] = junk
        tile = graph_from_dict(data, registry).pages["p1"].tiles["t1"]
        assert tile.aspect is None

    def test_moving_a_tile_leaves_its_shape_alone(self):
        graph = self._graph(2.0)
        graph.update_tile("p1", "t1", rect=(40, 40, 400, 200))
        assert graph.pages["p1"].tiles["t1"].aspect == 2.0

    def test_none_takes_it_away(self):
        graph = self._graph(2.0)
        graph.update_tile("p1", "t1", aspect=None)
        assert graph.pages["p1"].tiles["t1"].aspect is None
