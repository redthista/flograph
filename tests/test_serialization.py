import json

import pytest

from flograph.core import Frame, Graph, GraphError, NodeStatus, Page, Tile
from flograph.core.serialization import (
    SCHEMA_VERSION, graph_from_dict, graph_to_dict, load, save,
)


def build_project_graph(registry) -> Graph:
    graph = Graph()
    const = registry.instantiate("flograph.util.constant", pos=(0, 0))
    script = registry.instantiate("flograph.scripting.python_script", pos=(200, 50))
    graph.add_node(const)
    graph.add_node(script)
    graph.set_param(const.id, "value", "hello")
    graph.connect(const.id, "value", script.id, "in1")
    graph.add_frame(Frame(id="f1", title="Stage 1", rect=(0, 0, 400, 300)))
    return graph


def test_round_trip_dict_equality(registry):
    graph = build_project_graph(registry)
    data = graph_to_dict(graph)
    restored = graph_from_dict(json.loads(json.dumps(data)), registry)
    assert graph_to_dict(restored) == data


def test_loaded_nodes_are_dirty_and_idle(registry):
    graph = build_project_graph(registry)
    for node_id in graph.nodes:
        graph.mark_clean(node_id)
        graph.set_status(node_id, NodeStatus.DONE)
    restored = graph_from_dict(graph_to_dict(graph), registry)
    for node in restored.nodes.values():
        assert node.dirty and node.status == NodeStatus.IDLE


def test_forked_code_survives_round_trip(registry):
    graph = build_project_graph(registry)
    script = next(n for n in graph.nodes.values()
                  if n.type_id == "flograph.scripting.python_script")
    graph.set_code(script.id, """
NODE = {"label": "Custom", "category": "Scripting",
        "inputs": [("in1", "any", {"optional": True})],
        "outputs": [("out1", "any"), ("extra", "number")]}
def run(ctx, in1):
    return {"out1": in1, "extra": 1}
""")
    restored = graph_from_dict(graph_to_dict(graph), registry)
    restored_script = restored.nodes[script.id]
    assert restored_script.forked
    assert restored_script.label == "Custom"
    assert restored_script.spec.output("extra") is not None


def test_file_save_load(registry, tmp_path):
    graph = build_project_graph(registry)
    path = tmp_path / "project.flograph"
    save(graph, path)
    restored = load(path, registry)
    assert graph_to_dict(restored) == graph_to_dict(graph)


def test_bad_json_rejected(registry, tmp_path):
    path = tmp_path / "broken.flograph"
    path.write_text("{not json")
    with pytest.raises(GraphError, match="invalid JSON"):
        load(path, registry)


def test_newer_schema_rejected(registry):
    with pytest.raises(GraphError, match="newer than this flograph"):
        graph_from_dict({"schema": SCHEMA_VERSION + 1, "graph": {}}, registry)


def test_unknown_type_becomes_broken_placeholder(registry):
    data = {"schema": 1, "graph": {"nodes": [
        {"id": "x", "type": "flograph.gone.mystery", "pos": [0, 0],
         "params": {"note": "kept"}, "code": None, "label": None},
    ], "connections": [], "frames": []}}
    graph = graph_from_dict(data, registry)
    node = graph.nodes["x"]
    assert node.spec.broken
    assert node.type_id == "flograph.gone.mystery"
    assert node.status == NodeStatus.ERROR
    assert node.params == {"note": "kept"}


def test_legacy_flopy_type_ids_load(registry):
    data = {"schema": 1, "graph": {"nodes": [
        {"id": "x", "type": "flopy.util.constant", "pos": [0, 0],
         "params": {}, "code": None, "label": None},
    ], "connections": [], "frames": []}}
    graph = graph_from_dict(data, registry)
    node = graph.nodes["x"]
    assert node.type_id == "flograph.util.constant"
    assert not node.spec.broken


def test_broken_node_keeps_its_wiring(registry):
    const = registry.instantiate("flograph.util.constant", pos=(0, 0))
    data = {"schema": 1, "graph": {"nodes": [
        {"id": const.id, "type": const.type_id, "pos": [0, 0],
         "params": dict(const.params), "code": None, "label": None},
        {"id": "y", "type": "flograph.gone.mystery", "pos": [200, 0],
         "params": {}, "code": None, "label": None},
    ], "connections": [
        {"id": "c1", "src": [const.id, "value"], "dst": ["y", "in1"]},
    ], "frames": []}}
    restored = graph_from_dict(data, registry)
    broken = restored.nodes["y"]
    assert broken.spec.input("in1") is not None
    assert len(restored.connections) == 1


def test_rest_of_graph_still_loads_alongside_a_broken_node(registry):
    graph = build_project_graph(registry)
    data = graph_to_dict(graph)
    data["graph"]["nodes"].append(
        {"id": "z", "type": "flograph.gone.mystery", "pos": [400, 0],
         "params": {}, "code": None, "label": None})
    restored = graph_from_dict(data, registry)
    assert len(restored.nodes) == 3
    assert restored.nodes["z"].spec.broken


class TestPageSerialization:
    def test_pages_round_trip(self, registry):
        graph = build_project_graph(registry)
        const_id = next(iter(graph.nodes))
        graph.add_page(Page(id="p1", title="Sales"))
        graph.add_tile("p1", Tile(id="t1", node_id=const_id, port="value",
                                  rect=(10, 20, 400, 300)))
        graph.add_tile("p1", Tile(id="t2", node_id=const_id))
        graph.add_page(Page(id="p2", title="Ops"))
        data = graph_to_dict(graph)
        restored = graph_from_dict(json.loads(json.dumps(data)), registry)
        assert graph_to_dict(restored) == data
        assert list(restored.pages) == ["p1", "p2"]
        tile = restored.pages["p1"].tiles["t1"]
        assert (tile.node_id, tile.port) == (const_id, "value")
        assert tile.rect == (10.0, 20.0, 400.0, 300.0)
        assert restored.pages["p1"].tiles["t2"].port is None

    def test_file_without_pages_loads(self, registry):
        data = graph_to_dict(build_project_graph(registry))
        del data["graph"]["pages"]
        restored = graph_from_dict(data, registry)
        assert restored.pages == {}

    def test_tile_referencing_missing_node_survives(self, registry):
        graph = build_project_graph(registry)
        graph.add_page(Page(id="p1"))
        graph.add_tile("p1", Tile(id="t1", node_id="deleted-node", port="table"))
        data = graph_to_dict(graph)
        restored = graph_from_dict(data, registry)
        assert restored.pages["p1"].tiles["t1"].node_id == "deleted-node"
        assert graph_to_dict(restored) == data
