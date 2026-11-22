"""Watch Folder (flograph issue #77) and the NODE["always_run"] flag it
needs: a node whose result lives on disk has to be asked again every run."""
import json
import os
import time

import pytest

from flograph.core import Graph, NodeInstance, parse_spec
from flograph.core.script import NodeScriptError, compile_run
from flograph.engine import ExecutionEngine
from flograph.engine.scheduler import touch_always_run
from tests.conftest import FakeContext

TYPE = "flograph.io.watch_folder"


@pytest.fixture
def watch(registry, tmp_path, monkeypatch):
    monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path / "user"))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    spec = registry.get(TYPE)
    run = compile_run(spec.source, "test-watch")

    def go(**params):
        values = spec.default_params()
        values.update({"folder": str(inbox), "settle_s": 0.0})
        values.update(params)
        ctx = FakeContext(params=values, node_id="w1")
        return run(ctx), ctx
    return inbox, go


def drop(folder, name, text="a,b\n1,2\n", age=0.0):
    path = folder / name
    path.write_text(text)
    if age:
        then = time.time() - age
        os.utime(path, (then, then))
    return path


class TestWatchFolder:
    def test_each_file_is_handed_over_once(self, watch):
        inbox, go = watch
        drop(inbox, "a.csv")
        out, _ = go()
        assert out["count"] == 1
        assert list(out["files"]["name"]) == ["a.csv"]
        assert list(out["files"]["change"]) == ["new"]
        assert go()[0]["count"] == 0          # already seen
        drop(inbox, "b.csv")
        out, _ = go()
        assert out["paths"] == [str(inbox / "b.csv")]

    def test_the_pattern_filters(self, watch):
        inbox, go = watch
        drop(inbox, "a.csv")
        drop(inbox, "notes.txt")
        assert go(pattern="*.csv")[0]["count"] == 1

    def test_subfolders_only_when_asked(self, watch):
        inbox, go = watch
        (inbox / "sub").mkdir()
        drop(inbox / "sub", "deep.csv")
        assert go()[0]["count"] == 0
        assert go(include_subdirs=True)[0]["count"] == 1

    def test_a_rewritten_file_counts_only_in_changed_mode(self, watch):
        inbox, go = watch
        path = drop(inbox, "a.csv", age=60)
        go()
        path.write_text("a,b\n1,2\n3,4\n")
        then = time.time() - 30
        os.utime(path, (then, then))
        assert go(remember=False)[0]["count"] == 0
        out, _ = go(mode="New or changed files")
        assert list(out["files"]["change"]) == ["changed"]

    def test_skipping_the_backlog(self, watch):
        inbox, go = watch
        drop(inbox, "old.csv")
        out, ctx = go(first_run="Skip them")
        assert out["count"] == 0
        assert any("already in" in line for line in ctx.logs)
        drop(inbox, "new.csv")
        assert go(first_run="Skip them")[0]["paths"] == [str(inbox / "new.csv")]

    def test_not_remembering_uses_nothing_up(self, watch):
        inbox, go = watch
        drop(inbox, "a.csv")
        assert go(remember=False)[0]["count"] == 1
        assert go(remember=False)[0]["count"] == 1
        assert go()[0]["count"] == 1

    def test_a_file_still_being_written_waits_for_a_later_look(self, watch):
        inbox, go = watch
        drop(inbox, "busy.csv")                       # touched just now
        assert go(settle_s=60.0)[0]["count"] == 0
        then = time.time() - 120
        os.utime(inbox / "busy.csv", (then, then))
        assert go(settle_s=60.0)[0]["count"] == 1

    def test_a_deleted_file_that_comes_back_is_new_again(self, watch):
        inbox, go = watch
        drop(inbox, "a.csv")
        go()
        (inbox / "a.csv").unlink()
        go()
        drop(inbox, "a.csv")
        assert go()[0]["count"] == 1

    def test_waiting_gives_up_empty(self, watch):
        inbox, go = watch
        out, ctx = go(wait="Wait for a new file", timeout_s=1.0,
                      poll_interval_s=0.2)
        assert out["count"] == 0
        assert any("nothing new" in line for line in ctx.logs)
        assert ctx.fractions                       # the ring moved

    def test_waiting_picks_up_a_file_that_arrives(self, watch):
        import threading

        inbox, go = watch
        timer = threading.Timer(0.4, drop, (inbox, "late.csv"))
        timer.start()
        try:
            out, _ = go(wait="Wait for a new file", timeout_s=20.0,
                        poll_interval_s=0.2)
        finally:
            timer.cancel()
        assert out["paths"] == [str(inbox / "late.csv")]

    def test_a_named_seen_list_is_shared(self, watch, tmp_path):
        inbox, go = watch
        seen = tmp_path / "seen.json"
        drop(inbox, "a.csv")
        go(seen_file=str(seen))
        data = json.loads(seen.read_text())
        assert data["version"] == 1
        [entries] = data["watches"].values()
        assert str(inbox / "a.csv") in entries
        assert go(seen_file=str(seen))[0]["count"] == 0
        # flograph's own list for this node never heard of it
        assert go()[0]["count"] == 1

    def test_another_folder_starts_afresh(self, watch, tmp_path):
        inbox, go = watch
        other = tmp_path / "other"
        other.mkdir()
        drop(inbox, "a.csv")
        drop(other, "a.csv")
        go()
        assert go(folder=str(other))[0]["count"] == 1
        assert go()[0]["count"] == 0

    def test_errors_say_what_to_set(self, watch, tmp_path):
        _inbox, go = watch
        with pytest.raises(ValueError, match="no folder"):
            go(folder="")
        with pytest.raises(ValueError, match="not a folder"):
            go(folder=str(tmp_path / "missing"))
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        with pytest.raises(ValueError, match="delete it to start over"):
            go(seen_file=str(bad))

    def test_it_declares_always_run(self, registry):
        assert registry.get(TYPE).always_run


# -- the engine side --------------------------------------------------------

COUNTER = """
NODE = {"label": "Counter", "category": "Test", "always_run": %s,
        "inputs": [], "outputs": [("n", "number")]}
def run(ctx):
    import os
    path = ctx.params["file"]
    n = (int(open(path).read()) if os.path.exists(path) else 0) + 1
    open(path, "w").write(str(n))
    return {"n": n}
"""

READER = """
NODE = {"label": "Read", "category": "Test",
        "inputs": [("n", "number")], "outputs": [("n", "number")]}
def run(ctx, n):
    return {"n": n}
"""


def _add(graph, source, type_id, **params):
    node = NodeInstance.create(parse_spec(source, type_id))
    node.params.update(params)
    graph.add_node(node)
    return node


def _run(qtbot, engine):
    with qtbot.waitSignal(engine.run_finished, timeout=30000) as blocker:
        engine.run_all()
    return blocker.args[0]


class TestAlwaysRun:
    def test_the_flag_must_be_a_bool(self):
        with pytest.raises(NodeScriptError, match="always_run"):
            parse_spec(COUNTER % '"yes"', "test.counter")

    def test_a_clean_always_run_node_runs_again_and_so_does_below(
            self, qtbot, tmp_path):
        graph = Graph()
        watch = _add(graph, COUNTER % "True", "test.watch",
                     file=str(tmp_path / "w"))
        plain = _add(graph, COUNTER % "False", "test.plain",
                     file=str(tmp_path / "p"))
        reader = _add(graph, READER, "test.read")
        graph.connect(watch.id, "n", reader.id, "n")
        engine = ExecutionEngine(graph)
        assert _run(qtbot, engine)
        assert _run(qtbot, engine)
        assert (tmp_path / "w").read_text() == "2"
        assert (tmp_path / "p").read_text() == "1"       # cached as before
        assert engine.cache.get(reader.id).outputs["n"] == 2

    def test_a_frozen_one_stays_pinned(self, qtbot, tmp_path):
        graph = Graph()
        watch = _add(graph, COUNTER % "True", "test.watch",
                     file=str(tmp_path / "w"))
        engine = ExecutionEngine(graph)
        assert _run(qtbot, engine)
        graph.set_frozen(watch.id, True)
        assert touch_always_run(graph, list(graph.nodes), engine.cache,
                                asked=()) == []
        assert not graph.nodes[watch.id].dirty

    def test_only_nodes_the_run_reaches(self, tmp_path):
        graph = Graph()
        watch = _add(graph, COUNTER % "True", "test.watch",
                     file=str(tmp_path / "w"))
        other = _add(graph, READER, "test.read")
        for node in graph.nodes.values():
            node.dirty = False
        assert touch_always_run(graph, [other.id]) == []
        assert touch_always_run(graph, [watch.id]) == [watch.id]
