"""A chart's page script survives the cache.

Show Plotly, Plotly Table and Gantt put their click / lasso / zoom /
double-click handling on the figure as `_flograph_post_script`. A plotly
figure pickles by rebuilding itself from its data, which drops that
attribute — so a chart reopened from a saved project (or read back after a
spill) came up with none of it: the saved lasso still filtered, and a
double-click only zoomed out. See cache_persistence._OutputsPickler.
"""
import io
import pickle

import pandas as pd
import pytest

from flograph.core import Graph, NodeRegistry
from flograph.engine import cache_persistence
from flograph.engine.cache import OutputCache
from flograph.engine.cache_persistence import register_cache, save_cache

SCRIPT = "gd.on('plotly_doubleclick', function () {});"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def _figure(script=SCRIPT):
    go = pytest.importorskip("plotly.graph_objects")
    fig = go.Figure(go.Scatter(x=[1, 2], y=[3, 4]))
    if script:
        fig._flograph_post_script = script
    return fig


def test_a_reopened_project_gives_the_chart_its_script_back(registry, tmp_path):
    graph = Graph()
    const = graph.add_node(registry.instantiate("flograph.util.constant"))
    cache = OutputCache()
    cache.set(const.id, {"value": _figure()}, wall_time=0.01)
    path = tmp_path / "proj.flograph"
    save_cache(graph, cache, path)

    fresh = OutputCache()
    assert register_cache(graph, fresh, path) == [const.id]
    figure = fresh.outputs_for(const.id)["value"]
    assert figure._flograph_post_script == SCRIPT
    assert list(figure.data[0].x) == [1, 2]


def test_everything_else_pickles_as_before():
    buffer = io.BytesIO()
    cache_persistence._dump({"plain": _figure(script=None),
                             "frame": pd.DataFrame({"a": [1, 2]}),
                             "text": "hello"}, buffer)
    back = pickle.loads(buffer.getvalue())
    assert not hasattr(back["plain"], "_flograph_post_script")
    assert back["frame"]["a"].tolist() == [1, 2]
    assert back["text"] == "hello"
