import json

import pytest

from flopy.core import Frame, Graph, GraphError, NodeStatus
from flopy.core.serialization import (
    SCHEMA_VERSION, graph_from_dict, graph_to_dict, load, save,
)


def build_project_graph(registry) -> Graph:
    graph = Graph()
    const = registry.instantiate("flopy.util.constant", pos=(0, 0))
    script = registry.instantiate("flopy.scripting.python_script", pos=(200, 50))
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
                  if n.type_id == "flopy.scripting.python_script")
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
    path = tmp_path / "project.flopy"
    save(graph, path)
    restored = load(path, registry)
    assert graph_to_dict(restored) == graph_to_dict(graph)


def test_bad_json_rejected(registry, tmp_path):
    path = tmp_path / "broken.flopy"
    path.write_text("{not json")
    with pytest.raises(GraphError, match="invalid JSON"):
        load(path, registry)


def test_newer_schema_rejected(registry):
    with pytest.raises(GraphError, match="newer than this flopy"):
        graph_from_dict({"schema": SCHEMA_VERSION + 1, "graph": {}}, registry)


def test_unknown_type_becomes_broken_placeholder(registry):
    data = {"schema": 1, "graph": {"nodes": [
        {"id": "x", "type": "flopy.gone.mystery", "pos": [0, 0],
         "params": {"note": "kept"}, "code": None, "label": None},
    ], "connections": [], "frames": []}}
    graph = graph_from_dict(data, registry)
    node = graph.nodes["x"]
    assert node.spec.broken
    assert node.type_id == "flopy.gone.mystery"
    assert node.status == NodeStatus.ERROR
    assert node.params == {"note": "kept"}


def test_broken_node_keeps_its_wiring(registry):
    const = registry.instantiate("flopy.util.constant", pos=(0, 0))
    data = {"schema": 1, "graph": {"nodes": [
        {"id": const.id, "type": const.type_id, "pos": [0, 0],
         "params": dict(const.params), "code": None, "label": None},
        {"id": "y", "type": "flopy.gone.mystery", "pos": [200, 0],
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
        {"id": "z", "type": "flopy.gone.mystery", "pos": [400, 0],
         "params": {}, "code": None, "label": None})
    restored = graph_from_dict(data, registry)
    assert len(restored.nodes) == 3
    assert restored.nodes["z"].spec.broken
