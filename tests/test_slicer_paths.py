"""The Slicer's path model (`flograph.core.slicer`) — Qt-free, and the one
answer the node's run(), the engine's introspection and the card all read.

The tests that matter most here are the compatibility ones: the "selected"
param is written into every saved project, so what it accepts and what it
writes back is a file-format promise.
"""
import pytest

from flograph.core.slicer import (SlicerOptions, build_tree, dump_paths,
                                  is_descendant, leaf_values, matches,
                                  normalise, parse_path, path_label,
                                  selected_paths, slicer_columns)


class TestColumns:
    def test_one_column(self):
        assert slicer_columns("region") == ["region"]

    def test_several_columns_keep_their_order(self):
        assert slicer_columns(" region , store ") == ["region", "store"]

    def test_duplicates_are_dropped(self):
        """A repeated column would draw a level whose every branch has one
        child, which is a level that says nothing."""
        assert slicer_columns("region, region") == ["region"]

    def test_blank_is_no_columns(self):
        assert slicer_columns("") == []
        assert slicer_columns(None) == []


class TestReadingTheParam:
    def test_the_flat_form_older_builds_wrote(self):
        assert selected_paths('["north", "south"]') == \
            [("north",), ("south",)]

    def test_the_nested_form(self):
        assert selected_paths('[["north", "alpha"], ["south"]]') == \
            [("north", "alpha"), ("south",)]

    def test_a_mix_of_both(self):
        assert selected_paths('["north", ["south", "alpha"]]') == \
            [("north",), ("south", "alpha")]

    def test_a_hand_typed_comma_list(self):
        assert selected_paths("north, south") == [("north",), ("south",)]

    def test_a_hand_typed_path(self):
        assert selected_paths("north > alpha, south") == \
            [("north", "alpha"), ("south",)]

    def test_blank_is_nothing_ticked(self):
        assert selected_paths("") == []
        assert selected_paths(None) == []

    def test_duplicates_are_dropped_in_order(self):
        assert selected_paths('["a", "b", "a"]') == [("a",), ("b",)]

    def test_non_strings_are_coerced(self):
        """A hand-edited param can hold anything JSON can; values are
        matched as strings everywhere else, so they arrive as strings."""
        assert selected_paths("[1, [2, 3]]") == [("1",), ("2", "3")]


class TestWritingTheParam:
    def test_one_level_writes_flat(self):
        """A single-column slicer must keep saving the form every earlier
        build wrote — and reads."""
        assert dump_paths([("north",), ("south",)]) == '["north", "south"]'

    def test_any_depth_writes_nested(self):
        assert dump_paths([("north", "alpha")]) == '[["north", "alpha"]]'

    def test_a_mixed_depth_selection_writes_nested_throughout(self):
        assert dump_paths([("north",), ("south", "alpha")]) == \
            '[["north"], ["south", "alpha"]]'

    def test_nothing_ticked_is_the_empty_string(self):
        """Blank is what "keeps every row" is stored as — not "[]"."""
        assert dump_paths([]) == ""

    def test_a_round_trip_is_lossless(self):
        paths = [("north", "alpha"), ("south",)]
        assert selected_paths(dump_paths(paths)) == paths


class TestPathRules:
    def test_descendant(self):
        assert is_descendant(("a", "b"), ("a",))
        assert not is_descendant(("a",), ("a",))     # not *strictly* under
        assert not is_descendant(("b", "c"), ("a",))

    def test_normalise_drops_what_a_shallower_tick_covers(self):
        assert normalise([("a", "b"), ("a",)]) == [("a",)]

    def test_normalise_keeps_unrelated_branches(self):
        assert normalise([("a", "b"), ("c",)]) == [("a", "b"), ("c",)]

    def test_matches_is_a_prefix_test(self):
        assert matches(("north", "alpha"), [("north",)])
        assert matches(("north", "alpha"), [("north", "alpha")])
        assert not matches(("north", "alpha"), [("north", "beta")])
        assert not matches(("south", "alpha"), [("north",)])

    def test_nothing_selected_matches_nothing(self):
        """The "keeps every row" case is handled by never calling this —
        an empty selection here is genuinely no match."""
        assert not matches(("north",), [])

    def test_leaf_values_dedupe_in_order(self):
        assert leaf_values([("n", "a"), ("s", "a"), ("s", "b")]) == ["a", "b"]

    def test_path_label_reads_as_a_breadcrumb(self):
        assert path_label(("north", "alpha")) == "north > alpha"

    @pytest.mark.parametrize("text,expected", [
        ("north > alpha", ("north", "alpha")),
        ("north>alpha", ("north", "alpha")),
        ("north", ("north",)),
        ("", ()),
    ])
    def test_parse_path(self, text, expected):
        assert parse_path(text) == expected


class TestTree:
    def test_paths_nest_into_levels(self):
        roots = build_tree([("n", "a"), ("n", "b"), ("s", "c")])
        assert [r.value for r in roots] == ["n", "s"]
        assert [c.value for c in roots[0].children] == ["a", "b"]
        assert roots[0].children[0].path == ("n", "a")

    def test_order_of_arrival_is_kept(self):
        """Introspection hands the paths over sorted; re-sorting here would
        be a second opinion about the order the card shows."""
        roots = build_tree([("s",), ("n",)])
        assert [r.value for r in roots] == ["s", "n"]

    def test_counts_land_on_the_level_they_belong_to(self):
        roots = build_tree([("n", "a")], {("n",): 7, ("n", "a"): 3})
        assert roots[0].count == 7
        assert roots[0].children[0].count == 3

    def test_walk_yields_parents_first(self):
        roots = build_tree([("n", "a"), ("n", "b")])
        assert [n.path for n in roots[0].walk()] == \
            [("n",), ("n", "a"), ("n", "b")]


class TestOptions:
    def test_depth_follows_the_columns(self):
        assert SlicerOptions(["a", "b"], []).depth == 2

    def test_depth_is_never_zero(self):
        """A standalone slicer with no column named still has one level of
        values to draw."""
        assert SlicerOptions([], []).depth == 1

    def test_len_is_the_number_of_paths(self):
        assert len(SlicerOptions(["a"], [("x",), ("y",)])) == 2
