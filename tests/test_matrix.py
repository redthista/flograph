"""Show Table as a matrix (X1): the table pivots inside the card, and a
rule can read the rows before the pivot as well as the cells after it."""
import dataclasses

import pandas as pd
import pytest

from flograph.core import Graph, NodeRegistry
from flograph.core.matrix import build_matrix, pivot
from flograph.core.table_format import (
    column_matches, column_stats, evaluate_column, evaluate_rows,
    rules_from_style, split_rules, style_payload)

KPI = pd.DataFrame({
    "metric": ["Uptime", "Uptime", "Latency", "Latency"],
    "quarter": ["Q1", "Q2", "Q1", "Q2"],
    "value": [99.9, 97.0, 120.0, 180.0],
    "status": ["ok", "breach", "ok", "breach"],
    "note": ["", "outage 3 May", "", "new region"],
})


def rules(text: str) -> dict:
    return style_payload({"format_rules": text})


def styled(built, cell: str) -> list:
    """What the card draws down `cell`: every column rule that touches it,
    later ones over earlier, through the same core the card uses."""
    frame = built.frame
    out = [None] * len(frame)
    column_rules, _row = split_rules(rules_from_style(built.style))
    for rule in column_rules:
        if rule.columns and not column_matches(rule.columns, cell):
            continue
        for i, style in enumerate(evaluate_column(
                frame[cell], [rule], column_stats(frame[cell]), frame=frame)):
            if style is not None:
                out[i] = style.over(out[i])
    return out


def icons(styles) -> list:
    return [s.decorations[0].text if s and s.decorations else None
            for s in styles]


class TestThePivot:

    def test_the_pivot_nodes_names(self):
        out = pivot(KPI, ["metric"], ["quarter"], ["value"])
        assert list(out.columns) == ["metric", "Q1", "Q2"]
        assert list(out["metric"]) == ["Uptime", "Latency"]

    def test_two_values_keep_their_prefix(self):
        out = pivot(KPI.assign(n=1), ["metric"], ["quarter"], ["value", "n"])
        assert {"value_Q1", "n_Q2"} <= set(out.columns)


class TestAMatrix:

    def test_rows_down_the_side_columns_across(self):
        built = build_matrix(KPI, ["metric"], ["quarter"], ["value"])
        assert list(built.frame.columns) == ["metric", "Q1", "Q2"]
        assert built.frame.loc[1, "Q2"] == 180.0
        assert built.style["hide"] == []

    def test_left_empty_the_values_are_the_numbers_no_rule_reads(self):
        table = KPI.assign(check=[1, 0, 1, 0])
        built = build_matrix(table, ["metric"], ["quarter"], style=rules(
            "value iconmap check: 1=✓ green, 0=✗ red"))
        shown = [c for c in built.frame.columns if "·" not in c]
        assert shown == ["metric", "Q1", "Q2"], \
            "the checker column feeds the icon; it is not a value"

    def test_the_settings_it_needs_say_so(self):
        with pytest.raises(ValueError, match="Rows"):
            build_matrix(KPI, [], ["quarter"])
        with pytest.raises(ValueError, match="Columns"):
            build_matrix(KPI, ["metric"], [])
        with pytest.raises(ValueError, match="nope"):
            build_matrix(KPI, ["nope"], ["quarter"])


class TestARuleReadingTheRowsBeforeThePivot:

    def test_an_icon_decided_by_another_column(self):
        built = build_matrix(KPI, ["metric"], ["quarter"], ["value"],
                             style=rules("value iconmap status: "
                                         "breach=✗ red, ok=✓ green"))
        assert icons(styled(built, "Q1")) == ["✓", "✓"]
        assert icons(styled(built, "Q2")) == ["✗", "✗"]
        # what it read rides along, hidden
        assert "status · Q1" in built.frame.columns
        assert "status · Q1" in built.style["hide"]

    def test_a_highlight_tested_on_another_column(self):
        built = build_matrix(KPI, ["metric"], ["quarter"], ["value"],
                             style=rules("value if status = breach => bg red"))
        assert all(s is not None and s.bg for s in styled(built, "Q2"))
        assert styled(built, "Q1") == [None, None]

    def test_a_note_from_another_column(self):
        built = build_matrix(KPI, ["metric"], ["quarter"], ["value"],
                             style=rules("value tooltip note"))
        assert [s.tooltip if s else None for s in styled(built, "Q2")] == [
            "outage 3 May", "new region"]
        assert styled(built, "Q1") == [None, None], "a blank note is none"

    def test_a_whole_row_flagged_by_another_column(self):
        table = KPI.assign(status=["ok", "ok", "ok", "breach"])
        built = build_matrix(table, ["metric"], ["quarter"], ["value"],
                             style=rules("status = breach => row red"))
        _cols, row_rules = split_rules(rules_from_style(built.style))
        flags = evaluate_rows(built.frame, row_rules)
        assert flags[0] is None and flags[1] is not None and flags[1].bg


class TestSeveralRowsInOneCell:

    TABLE = pd.DataFrame({"metric": ["Uptime"] * 3, "quarter": ["Q1"] * 3,
                          "value": [1.0, 2.0, 3.0],
                          "status": ["ok", "breach", "ok"],
                          "note": ["a", "b", "a"]})

    def build(self, text):
        return build_matrix(self.TABLE, ["metric"], ["quarter"], ["value"],
                            style=rules(text))

    def test_the_values_are_aggregated(self):
        assert self.build("").frame.loc[0, "Q1"] == 6.0

    def test_the_value_listed_first_in_the_map_wins(self):
        worst_first = self.build("value iconmap status: breach=✗ red, ok=✓ green")
        assert icons(styled(worst_first, "Q1")) == ["✗"]
        ok_first = self.build("value iconmap status: ok=✓ green, breach=✗ red")
        assert icons(styled(ok_first, "Q1")) == ["✓"]

    def test_a_highlight_fires_if_any_row_passes(self):
        built = self.build("value if status = breach => bg red")
        assert styled(built, "Q1")[0].bg

    def test_notes_are_joined_once_each(self):
        assert styled(self.build("value tooltip note"), "Q1")[0].tooltip == \
            "a\nb"


class TestARuleAboutTheCellItself:

    def test_it_moves_onto_every_cell_the_value_built(self):
        built = build_matrix(KPI, ["metric"], ["quarter"], ["value"],
                             style=rules("value > 150 => bg red"))
        assert styled(built, "Q1") == [None, None]
        assert styled(built, "Q2")[0] is None and styled(built, "Q2")[1].bg

    def test_a_scale_is_measured_across_the_whole_matrix(self):
        """Per column, 120 would be Q1's top and take the full colour; across
        the matrix 180 is the top, and 120 is not."""
        built = build_matrix(KPI, ["metric"], ["quarter"], ["value"],
                             style=rules("value scale green"))
        top = styled(built, "Q2")[1].bg
        assert styled(built, "Q1")[1].bg != top
        scale = next(r for r in rules_from_style(built.style)
                     if r.mode == "color_scale")
        alone = evaluate_column(built.frame["Q1"],
                                [dataclasses.replace(scale, pool=[])],
                                column_stats(built.frame["Q1"]))
        assert alone[1].bg == top

    def test_a_rule_drawing_in_a_column_the_matrix_lacks_is_said(self):
        built = build_matrix(KPI, ["metric"], ["quarter"], ["value"],
                             style=rules("status colormap: breach=red"))
        assert built.notes and "status" in built.notes[0]
        assert not rules_from_style(built.style)

    def test_a_sort_on_the_value_is_left_out_and_said(self):
        built = build_matrix(KPI, ["metric"], ["quarter"], ["value"],
                             style=rules("value sort desc"))
        assert built.notes
        assert not any(r.mode == "sort"
                       for r in rules_from_style(built.style))

    def test_show_and_hide_follow_the_value(self):
        style = style_payload({"format_rules": "", "show": "metric, value",
                               "hide": "status"})
        built = build_matrix(KPI, ["metric"], ["quarter"], ["value"],
                             style=style)
        assert built.style["show"] == ["metric", "Q1", "Q2"]
        assert built.style["hide"] == [], "status is gone; nothing to hide"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


class TestShowTableAsAMatrix:

    def test_the_card_draws_the_matrix_with_its_icons(self, qtbot, registry,
                                                      tmp_path):
        from flograph.engine import ExecutionEngine
        from flograph.ui.inspector.pandas_model import styled_model

        csv = tmp_path / "kpi.csv"
        KPI.to_csv(csv, index=False)
        graph = Graph()
        engine = ExecutionEngine(graph)
        reader = graph.add_node(registry.instantiate("flograph.io.read_csv"))
        shown = graph.add_node(registry.instantiate("flograph.viz.show_table"))
        graph.set_param(reader.id, "path", str(csv))
        for name, value in (("mode", "matrix"), ("matrix_rows", "metric"),
                            ("matrix_columns", "quarter"),
                            ("matrix_values", "value"),
                            ("format_rules", "value iconmap status: "
                                             "breach=✗ red, ok=✓ green")):
            graph.set_param(shown.id, name, value)
        graph.connect(reader.id, "table", shown.id, "table")
        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_all()
        assert shown.status.value == "done"

        out = engine.cache.outputs_for(shown.id)
        frame, style = out["table"], out["style"]
        assert list(frame.columns)[:3] == ["metric", "Q1", "Q2"]
        model = styled_model(frame, style)
        assert model.columnCount() == 3, "the carried columns stay hidden"
        assert model._cell_style(1, 2).decorations[0].text == "✗"

    def test_a_table_is_still_a_table(self, qtbot, registry, tmp_path):
        from flograph.engine import ExecutionEngine

        csv = tmp_path / "kpi.csv"
        KPI.to_csv(csv, index=False)
        graph = Graph()
        engine = ExecutionEngine(graph)
        reader = graph.add_node(registry.instantiate("flograph.io.read_csv"))
        shown = graph.add_node(registry.instantiate("flograph.viz.show_table"))
        graph.set_param(reader.id, "path", str(csv))
        graph.connect(reader.id, "table", shown.id, "table")
        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_all()
        frame = engine.cache.outputs_for(shown.id)["table"]
        assert list(frame.columns) == list(KPI.columns)
