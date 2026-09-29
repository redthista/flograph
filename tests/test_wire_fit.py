"""Ranking the palette a dropped wire opens (core.wire_fit), and the
`suggest` port option it reads."""
import pytest

from flograph.core import (NodeRegistry, NodeScriptError, PortDirection,
                           PortSpec, PortType, parse_spec)
from flograph.core.wire_fit import (EXACT, LOOSE, SUGGESTED, best_port,
                                    wire_fit)


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def _input(registry, type_id, name):
    return next(p for p in registry.get(type_id).inputs if p.name == name)


def _output(registry, type_id, name):
    return next(p for p in registry.get(type_id).outputs if p.name == name)


class TestTiers:
    def test_a_style_input_ranks_its_style_node_first(self, registry):
        port = _input(registry, "flograph.viz.show_plotly", "style")
        fit = lambda t: wire_fit(registry.get(t), port,
                                 "flograph.viz.show_plotly")
        assert fit("flograph.viz.plotly_style") == SUGGESTED
        # a Table Style hands on an object too, so it is a type match —
        # just not the style node this port asked for
        assert fit("flograph.viz.table_style") == EXACT
        assert fit("flograph.transform.filter_rows") == LOOSE

    def test_forward_the_new_nodes_input_is_what_asks(self, registry):
        port = _output(registry, "flograph.viz.table_style", "style")
        fit = lambda t: wire_fit(registry.get(t), port,
                                 "flograph.viz.table_style")
        assert fit("flograph.viz.show_table") == SUGGESTED
        assert fit("flograph.viz.show_plotly") != SUGGESTED

    def test_a_node_that_cannot_take_the_wire_is_left_out(self, registry):
        port = _output(registry, "flograph.io.read_csv", "table")
        assert wire_fit(registry.get("flograph.io.read_csv"), port,
                        "flograph.io.read_csv") is None     # no inputs

    def test_from_an_any_port_nothing_is_loose(self, registry):
        port = PortSpec("x", PortType.ANY, PortDirection.INPUT)
        tiers = {wire_fit(spec, port, "") for spec in registry.all()}
        assert LOOSE not in tiers

    def test_exact_beats_widening_to_object(self, registry):
        port = PortSpec("x", PortType.OBJECT, PortDirection.INPUT)
        # a table only widens to object; a style node puts out an object
        assert wire_fit(registry.get("flograph.io.read_csv"), port,
                        "") == LOOSE
        assert wire_fit(registry.get("flograph.viz.visual_style"), port,
                        "") == EXACT


class TestBestPort:
    def test_the_asked_for_port_beats_an_earlier_any_port(self, registry):
        port = _input(registry, "flograph.viz.show_plotly", "style")
        chosen = best_port(registry.get("flograph.viz.plotly_style"), port,
                           "flograph.viz.show_plotly")
        assert chosen.name == "style"

    def test_forward_the_input_that_asked(self, registry):
        port = _output(registry, "flograph.viz.plotly_style", "style")
        chosen = best_port(registry.get("flograph.viz.show_plotly"), port,
                           "flograph.viz.plotly_style")
        assert chosen.name == "style"

    def test_same_name_then_same_type_then_first(self, registry):
        port = PortSpec("table", PortType.DATAFRAME, PortDirection.OUTPUT)
        chosen = best_port(registry.get("flograph.viz.show_plotly"), port,
                           "")
        assert chosen.name == "table"

    def test_none_when_nothing_fits(self, registry):
        port = _output(registry, "flograph.io.read_csv", "table")
        assert best_port(registry.get("flograph.io.read_csv"), port,
                         "") is None


class TestEverySuggestionResolves:
    def test_each_suggested_type_is_a_real_node(self, registry):
        """A typo in `suggest` would rank nothing and fail silently."""
        known = {spec.type_id for spec in registry.all()}
        for spec in registry.all():
            for port in spec.inputs:
                for type_id in port.suggest:
                    assert type_id in known, (spec.type_id, port.name,
                                              type_id)

    def test_every_suggestion_can_actually_be_wired(self, registry):
        for spec in registry.all():
            for port in spec.inputs:
                for type_id in port.suggest:
                    assert best_port(registry.get(type_id), port,
                                     spec.type_id) is not None, \
                        (spec.type_id, port.name, type_id)


def _script(port):
    return (f"NODE = {{'label': 'X', 'category': 'Util', 'version': '1.0',"
            f" 'inputs': [{port}], 'outputs': []}}\n"
            f"def run(ctx, **inputs):\n    return {{}}\n")


class TestTheOption:
    def test_parsed_onto_the_port(self):
        spec = parse_spec(_script(
            "('s', 'object', {'suggest': ['a.b', 'c.d']})"), "user.x")
        assert spec.inputs[0].suggest == ("a.b", "c.d")

    def test_defaults_to_nothing(self):
        spec = parse_spec(_script("('s', 'object')"), "user.x")
        assert spec.inputs[0].suggest == ()

    @pytest.mark.parametrize("bad", ["'a.b'", "[1]", "{'a': 1}"])
    def test_must_be_a_list_of_ids(self, bad):
        with pytest.raises(NodeScriptError, match="suggest"):
            parse_spec(_script(f"('s', 'object', {{'suggest': {bad}}})"),
                       "user.x")

    def test_only_on_an_input(self):
        source = ("NODE = {'label': 'X', 'category': 'Util', "
                  "'version': '1.0', 'inputs': [], 'outputs': "
                  "[('s', 'object', {'suggest': ['a.b']})]}\n"
                  "def run(ctx):\n    return {}\n")
        with pytest.raises(NodeScriptError, match="goes on an input"):
            parse_spec(source, "user.x")
