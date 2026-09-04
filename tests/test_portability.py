"""Can you hand somebody a single .flograph and have it just work?

That is the product's central promise — a flow becomes a thing you send to
someone who does not have your data, your custom nodes, or your folder
layout, and they see what you saw. This file pins that end to end, and,
just as importantly, pins where it *stops*: the two seams below are real
and are the honest answer to "is it 100% portable".

The recipient here has a different directory, a different filename, no
source CSV, and no user-node library. Nothing may re-run.
"""
from __future__ import annotations

import shutil

import pytest

from flograph.core import NodeRegistry, user_nodes
from flograph.engine import cache_persistence

CUSTOM_NODE = '''"""Tag Rows

Adds a constant column, so the recipient's column pickers have something
that only the custom node could have produced.
"""
NODE = {
    "label": "Tag Rows",
    "category": "Custom",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [{"name": "tag", "type": "string", "default": "hello"}]


def run(ctx, table):
    out = table.copy()
    out["tag"] = ctx.params["tag"]
    return out
'''

# The smallest valid PNG, for the linked-vs-embedded distinction.
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d4944415478da63fccf00000302010049b1b1c40000"
    "000049454e44ae426082")
PNG_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    from flograph.ui import mainwindow as mod
    ini_path = str(tmp_path / "settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


def _window(qtbot, reg):
    from flograph.ui import mainwindow as mod
    win = mod.MainWindow(reg)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def _save_bundle(window) -> None:
    """What File ▸ Save does, on this thread. Not `save_cache` — that is the
    legacy side-car writer, and a side-car is a second file that a copy of
    the .flograph leaves behind. Testing portability through it would prove
    the opposite of what the app actually does."""
    plan = cache_persistence.plan_project_save(
        window.graph, window.engine.cache, window.engine.history)
    cache_persistence.write_project(
        str(window._project_path), plan, compress=True)


def test_a_flow_handed_over_opens_complete_and_runs_nothing(
        qtbot, registry, tmp_path):
    author = tmp_path / "author"
    author.mkdir()
    nodes_dir = author / "nodes"
    nodes_dir.mkdir()
    csv = author / "data.csv"
    csv.write_text("region,value\n" +
                   "".join(f"r{i % 3},{i}\n" for i in range(30)))

    type_id = user_nodes.write_user_node(
        nodes_dir, "grp", "Tag Rows", CUSTOM_NODE)
    author_reg = NodeRegistry()
    author_reg.load_builtins()
    author_reg.load_user_nodes(nodes_dir)

    win = _window(qtbot, author_reg)
    graph = win.graph
    reader = graph.add_node(author_reg.instantiate("flograph.io.read_csv"))
    graph.set_param(reader.id, "path", str(csv))
    custom = graph.add_node(author_reg.instantiate(type_id))
    graph.connect(reader.id, "table", custom.id, "table")

    made = {"reader": reader.id, "custom": custom.id}
    for name, tid in (("chart", "flograph.viz.show_plot"),
                      ("table", "flograph.viz.show_table"),
                      ("slicer", "flograph.viz.slicer"),
                      ("kpi", "flograph.viz.card"),
                      ("linked", "flograph.io.table")):
        node = graph.add_node(author_reg.instantiate(tid))
        graph.connect(custom.id, "table", node.id, "table")
        made[name] = node.id
    graph.set_param(made["slicer"], "column", "region")
    graph.set_param(made["kpi"], "column", "value")

    picture = graph.add_node(author_reg.instantiate("flograph.viz.image"))
    graph.set_param(picture.id, "path", PNG_DATA_URI)   # pasted, so inlined
    made["image"] = picture.id

    report = graph.add_node(author_reg.instantiate("flograph.viz.report_card"))
    graph.connect(made["chart"], "figure", report.id, "a")
    graph.set_param(report.id, "text", "# R\n\n![[a]]\n")
    made["report"] = report.id

    with qtbot.waitSignal(win.engine.run_finished, timeout=60000) as blocker:
        win.engine.run_all()
    assert blocker.args == [True], "the author's own run must succeed"
    win._project_path = str(author / "myflow.flograph")
    _save_bundle(win)

    # --- the trip: one file, to a different folder, under a different name
    recipient = tmp_path / "recipient" / "deep"
    recipient.mkdir(parents=True)
    carried = recipient / "renamed-by-colleague.flograph"
    shutil.copy2(win._project_path, carried)
    shutil.rmtree(author)      # no CSV, no node library, no original file

    fresh = NodeRegistry()
    fresh.load_builtins()      # deliberately NOT load_user_nodes
    reopened = _window(qtbot, fresh)
    assert reopened.open_path(str(carried), confirm=False) is True
    engine = reopened.engine

    card_ids = [made[n] for n in ("chart", "table", "slicer", "kpi",
                                  "linked", "image", "report")]
    qtbot.waitUntil(lambda: all(engine.cache.is_resident(i)
                                for i in card_ids), timeout=20000)

    for name, node_id in made.items():
        node = reopened.graph.nodes[node_id]
        assert engine.cache.get(node_id) is not None, f"{name}: cache lost"
        assert not node.dirty, f"{name}: reopened dirty"
        assert not node.spec.broken, f"{name}: spec broken"
    # the custom node came across as a local fork of the embedded script
    assert reopened.graph.nodes[made["custom"]].forked

    from flograph.engine import upstream_columns
    from flograph.engine.introspect import slicer_options
    assert slicer_options(reopened.graph, engine.cache, made["slicer"])
    # "tag" exists only because the custom node ran on the author's machine
    assert "tag" in upstream_columns(
        reopened.graph, engine.cache, made["chart"])
    assert not engine.active, "the recipient's machine must not have re-run"


class TestWherePortabilityStops:
    """The two seams. Both are by design; both are what someone asking
    "is it 100% portable?" actually needs told."""

    def test_a_linked_image_file_is_a_reference_not_a_copy(
            self, qtbot, registry, tmp_path):
        """A pasted picture inlines as a data: URI and travels. One pointed
        at a file on disk stays a pointer — right-click ▸ Embed Image in the
        File is what converts it."""
        author = tmp_path / "author"
        author.mkdir()
        pic = author / "logo.png"
        pic.write_bytes(PNG_BYTES)

        win = _window(qtbot, registry)
        node = win.graph.add_node(registry.instantiate("flograph.viz.image"))
        win.graph.set_param(node.id, "path", str(pic))
        win._project_path = str(author / "p.flograph")
        _save_bundle(win)

        carried = tmp_path / "carried.flograph"
        shutil.copy2(win._project_path, carried)
        pic.unlink()

        reopened = _window(qtbot, registry)
        assert reopened.open_path(str(carried), confirm=False) is True
        stored = next(iter(reopened.graph.nodes.values())).params.get("path")
        assert stored == str(pic), "the path travelled"
        assert not pic.exists(), "...but the bytes it points at did not"

    def test_viewing_needs_no_data_but_re_running_does(
            self, qtbot, registry, tmp_path):
        """The handed-over flow is fully viewable from its cache. Pressing
        Run is a different question: the CSV is the author's file and was
        never in the bundle."""
        author = tmp_path / "author"
        author.mkdir()
        csv = author / "data.csv"
        csv.write_text("region,value\nr0,1\nr1,2\n")

        win = _window(qtbot, registry)
        reader = win.graph.add_node(
            registry.instantiate("flograph.io.read_csv"))
        win.graph.set_param(reader.id, "path", str(csv))
        table = win.graph.add_node(
            registry.instantiate("flograph.viz.show_table"))
        win.graph.connect(reader.id, "table", table.id, "table")
        with qtbot.waitSignal(win.engine.run_finished, timeout=30000) as one:
            win.engine.run_all()
        assert one.args == [True]
        win._project_path = str(author / "p.flograph")
        _save_bundle(win)

        carried = tmp_path / "carried.flograph"
        shutil.copy2(win._project_path, carried)
        csv.unlink()

        reopened = _window(qtbot, registry)
        assert reopened.open_path(str(carried), confirm=False) is True
        # viewable: the cached frame came across
        assert reopened.engine.cache.get(table.id) is not None
        assert not reopened.graph.node(table.id).dirty

        # ...but a forced recompute cannot invent the file back
        for node_id in list(reopened.graph.nodes):
            reopened.graph.mark_dirty(node_id)
        with qtbot.waitSignal(reopened.engine.run_finished,
                              timeout=30000) as two:
            reopened.engine.run_all()
        assert two.args == [False], "Run still needs the source data"
