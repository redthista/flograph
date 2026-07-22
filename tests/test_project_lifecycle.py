"""M6: save/open through the main window, copy/paste/duplicate, dirty title."""
import json

import pytest
from PySide6.QtWidgets import QApplication, QMenu

from flograph.core import NodeRegistry
from flograph.core.serialization import graph_to_dict
from flograph.ui import mainwindow as mw
from flograph.ui.mainwindow import MainWindow


def _pick_menu_action(monkeypatch, text):
    """Context menus are built as `QMenu(...)` then driven with a blocking
    `.exec()` -- under the offscreen QPA platform that popup never gets a
    click and hangs forever. Patching QMenu.exec directly doesn't help:
    PySide dispatches the compiled method regardless of what's assigned on
    the class. Swapping in a real subclass (a genuine Python override) does
    take effect, so patch the `QMenu` name mainwindow.py resolves at call
    time to one that skips the popup and returns the named action."""
    class _Picker(QMenu):
        def exec(self, *args):
            return next((a for a in self.actions() if a.text() == text), None)
    monkeypatch.setattr(mw, "QMenu", _Picker)


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False  # no unsaved-changes modal at teardown close()
    qtbot.addWidget(win)
    return win


def build_small_project(win):
    reg = win.registry
    const = reg.instantiate("flograph.util.constant", pos=(0, 0))
    script = reg.instantiate("flograph.scripting.python_script", pos=(200, 0))
    win.graph.add_node(const)
    win.graph.add_node(script)
    win.graph.connect(const.id, "value", script.id, "in1")
    return const, script


class TestSaveOpen:
    def test_save_and_reopen_reproduces_graph(self, window, tmp_path):
        build_small_project(window)
        before = graph_to_dict(window.graph)
        path = str(tmp_path / "proj.flograph")
        window._project_path = path
        assert window._save()
        assert window.undo_stack.isClean()

        window._replace_graph(__import__("flograph.core", fromlist=["Graph"]).Graph())
        assert not window.graph.nodes

        assert window.open_path(path, confirm=False)
        assert graph_to_dict(window.graph) == before
        assert all(n.dirty for n in window.graph.nodes.values())
        # scene mirrored the load
        assert set(window.scene.node_items) == set(window.graph.nodes)
        assert set(window.scene.connection_items) == set(window.graph.connections)

    def test_save_reopen_restores_run_nodes_from_cache(self, qtbot, window, tmp_path):
        const, script = build_small_project(window)
        with qtbot.waitSignal(window.engine.run_finished, timeout=20000):
            window.engine.run_targets([const.id, script.id])
        assert not const.dirty and not script.dirty

        path = str(tmp_path / "cached.flograph")
        window._project_path = path
        assert window._save()
        assert (tmp_path / "cached.flograph.cache" / "manifest.json").exists()

        from flograph.core import Graph
        window._replace_graph(Graph())
        assert window.open_path(path, confirm=False)

        # cache blobs are unpickled on a pool thread; wait for it to land
        qtbot.waitUntil(lambda: window._cache_load_signals is None, timeout=5000)

        reloaded_const = window.graph.nodes[const.id]
        reloaded_script = window.graph.nodes[script.id]
        assert not reloaded_const.dirty
        assert not reloaded_script.dirty
        assert window.engine.cache.get(const.id) is not None
        assert window.engine.cache.get(script.id) is not None

    def test_save_reopen_after_param_edit_only_that_chain_dirty(
            self, qtbot, window, tmp_path):
        const, script = build_small_project(window)
        with qtbot.waitSignal(window.engine.run_finished, timeout=20000):
            window.engine.run_targets([const.id, script.id])

        path = str(tmp_path / "stale.flograph")
        window._project_path = path
        assert window._save()

        # edit the upstream node's param *after* saving the cache, then save
        # again — its fingerprint (and its downstream's) must now miss
        window.graph.set_param(const.id, "value", "edited")
        assert window._save()

        from flograph.core import Graph
        window._replace_graph(Graph())
        assert window.open_path(path, confirm=False)

        reloaded_const = window.graph.nodes[const.id]
        reloaded_script = window.graph.nodes[script.id]
        assert reloaded_const.dirty
        assert reloaded_script.dirty

    def test_open_bad_file_fails_gracefully(self, window, tmp_path, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "critical",
                            staticmethod(lambda *a, **k: None))
        bad = tmp_path / "bad.flograph"
        bad.write_text("{broken")
        assert not window.open_path(str(bad), confirm=False)

    def test_open_file_with_unknown_node_type_loads_as_broken_card(
            self, window, tmp_path):
        const, script = build_small_project(window)
        good_node_ids = {const.id, script.id}

        data = graph_to_dict(window.graph)
        data["graph"]["nodes"].append({
            "id": "gone", "type": "flograph.missing.plugin_node", "pos": [400, 0],
            "params": {}, "code": None, "label": None,
        })
        path = tmp_path / "has_broken.flograph"
        path.write_text(json.dumps(data))

        assert window.open_path(str(path), confirm=False)
        # the rest of the file loaded untouched alongside the broken node
        assert good_node_ids <= set(window.graph.nodes)
        assert window.graph.nodes["gone"].spec.broken
        # scene built a card for it too, without raising
        assert window.scene.node_items["gone"].broken

    def test_recent_files_tracked(self, window, tmp_path):
        path = str(tmp_path / "r.flograph")
        window._project_path = path
        window._save()
        assert path in window._recent_files()

    def test_title_reflects_dirty_state(self, window, registry):
        from flograph.ui.commands import AddNodeCommand
        assert not window.isWindowModified()
        node = registry.instantiate("flograph.util.constant")
        window.undo_stack.push(AddNodeCommand(window.graph, node))
        assert window.isWindowModified()


class TestCacheLoadInProgress:
    """Opening a project restores its cache on a background thread (see
    flograph.engine.cache_worker) so unpickling large blobs doesn't freeze
    the window. These guard the two hazards that introduces: a second
    open/new-project racing the in-flight one, and closing the window
    while a load is still pending."""

    def test_open_refused_while_cache_still_loading(self, window, tmp_path):
        from flograph.engine import CacheLoadSignals
        window._cache_load_signals = CacheLoadSignals()
        try:
            other = str(tmp_path / "other.flograph")
            assert window.open_path(other, confirm=False) is False
        finally:
            # nothing will ever emit `finished` on this stand-in signals
            # object — clear it so qtbot's teardown close() doesn't sit in
            # _wait_for_cache_load until its (generous) timeout
            window._cache_load_signals = None

    def test_new_project_refused_while_cache_still_loading(self, window):
        from flograph.engine import CacheLoadSignals
        build_small_project(window)
        node_ids_before = set(window.graph.nodes)
        window._cache_load_signals = CacheLoadSignals()
        try:
            window._new_project()
            assert set(window.graph.nodes) == node_ids_before
        finally:
            window._cache_load_signals = None

    def test_close_does_not_hang_on_a_finished_signal_queued_before_the_wait(
            self, window):
        """Regression: `finished` is a cross-thread signal, so Qt posts it
        to the event queue against whatever's connected *at emit time*.
        _wait_for_cache_load must not rely on connecting its own listener
        after that post (it would never see an emit that already happened).
        Reproduce the queued-before-connect ordering directly, with no real
        background thread, and confirm close() returns rather than
        blocking forever."""
        from PySide6.QtCore import Qt
        from flograph.engine import CacheLoadSignals

        signals = CacheLoadSignals()
        window._cache_load_signals = signals

        def on_finished():
            window._cache_load_signals = None

        signals.finished.connect(on_finished, Qt.QueuedConnection)
        signals.finished.emit()  # posted now; on_finished hasn't run yet
        assert window._cache_load_signals is signals

        window.close()  # would hang forever pre-fix; must return here
        assert window._cache_load_signals is None


class TestCopyPaste:
    def test_copy_paste_creates_fresh_ids(self, window):
        const, script = build_small_project(window)
        for item in window.scene.node_items.values():
            item.setSelected(True)
        window._copy_selection()
        payload = json.loads(QApplication.clipboard().text())
        assert len(payload["nodes"]) == 2
        assert len(payload["connections"]) == 1

        window._paste()
        assert len(window.graph.nodes) == 4
        assert len(window.graph.connections) == 2
        # pasted nodes are selected and offset
        selected = window.scene.selected_node_items()
        assert len(selected) == 2
        assert all(item.node.id not in (const.id, script.id)
                   for item in selected)
        pasted_positions = {item.node.pos for item in selected}
        assert (30.0, 30.0) in pasted_positions

    def test_paste_is_single_undo_step(self, window):
        build_small_project(window)
        for item in window.scene.node_items.values():
            item.setSelected(True)
        window._copy_selection()
        index = window.undo_stack.index()
        window._paste()
        assert window.undo_stack.index() == index + 1
        window.undo_stack.undo()
        assert len(window.graph.nodes) == 2

    def test_duplicate_without_clipboard(self, window):
        const, _ = build_small_project(window)
        window.scene.node_items[const.id].setSelected(True)
        window._duplicate()
        assert len(window.graph.nodes) == 3

    def test_paste_garbage_clipboard_noop(self, window):
        build_small_project(window)
        QApplication.clipboard().setText("just some text")
        window._paste()
        assert len(window.graph.nodes) == 2

    def test_copy_paste_frame_alone(self, window):
        from flograph.core import Frame
        from flograph.ui.commands import AddFrameCommand
        frame = Frame(id="f1", rect=(500.0, 500.0, 300.0, 200.0),
                      title="Notes", color="#ff0000")
        window.undo_stack.push(AddFrameCommand(window.graph, frame))
        window.scene.frame_items["f1"].setSelected(True)

        window._copy_selection()
        payload = json.loads(QApplication.clipboard().text())
        assert payload["frames"] == [{
            "title": "Notes", "rect": [500.0, 500.0, 300.0, 200.0],
            "color": "#ff0000",
        }]
        assert payload["nodes"] == []

        window._paste()
        assert len(window.graph.frames) == 2
        new_frame = next(f for f in window.graph.frames.values()
                         if f.id != "f1")
        assert new_frame.title == "Notes"
        assert new_frame.color == "#ff0000"
        assert new_frame.rect == (530.0, 530.0, 300.0, 200.0)
        selected = window.scene.selected_frame_items()
        assert len(selected) == 1
        assert selected[0].frame.id == new_frame.id

    def test_copy_paste_frame_carries_contained_nodes(self, window):
        from flograph.core import Frame
        from flograph.ui.commands import AddFrameCommand
        const, script = build_small_project(window)
        center = window.scene.node_items[const.id].sceneBoundingRect().center()
        frame = Frame(id="f1", rect=(center.x() - 100, center.y() - 100,
                                     200.0, 200.0))
        window.undo_stack.push(AddFrameCommand(window.graph, frame))
        # only the frame is selected -- the const node it contains rides
        # along, same as a frame drag
        window.scene.frame_items["f1"].setSelected(True)

        window._copy_selection()
        payload = json.loads(QApplication.clipboard().text())
        assert len(payload["frames"]) == 1
        assert [n["id"] for n in payload["nodes"]] == [const.id]

        window._paste()
        assert len(window.graph.frames) == 2
        assert len(window.graph.nodes) == 3

    def test_frame_context_menu_copy(self, window, monkeypatch):
        from PySide6.QtCore import QPoint
        from flograph.core import Frame
        from flograph.ui.commands import AddFrameCommand
        frame = Frame(id="f1", rect=(0.0, 0.0, 300.0, 200.0), title="Notes")
        window.undo_stack.push(AddFrameCommand(window.graph, frame))
        _pick_menu_action(monkeypatch, "Copy")

        window._show_frame_menu("f1", QPoint(0, 0))

        payload = json.loads(QApplication.clipboard().text())
        assert len(payload["frames"]) == 1
        assert payload["frames"][0]["title"] == "Notes"

    def test_node_context_menu_copy(self, window, monkeypatch):
        from PySide6.QtCore import QPoint
        const, _script = build_small_project(window)
        _pick_menu_action(monkeypatch, "Copy")

        window._show_node_menu(const.id, QPoint(0, 0))

        payload = json.loads(QApplication.clipboard().text())
        assert [n["id"] for n in payload["nodes"]] == [const.id]

    def test_canvas_context_menu_no_paste_without_clipboard(self, window,
                                                             monkeypatch):
        from PySide6.QtCore import QPoint, QPointF
        QApplication.clipboard().setText("")
        seen = {}

        class _Inspector(QMenu):
            def exec(self, *args):
                seen["actions"] = [a.text() for a in self.actions()]
                return None
        monkeypatch.setattr(mw, "QMenu", _Inspector)

        window._show_add_node_menu(QPointF(0, 0), QPoint(0, 0))

        assert "Paste" not in seen["actions"]

    def test_canvas_context_menu_paste_with_clipboard(self, window,
                                                       monkeypatch):
        from PySide6.QtCore import QPoint, QPointF
        const, _script = build_small_project(window)
        window.scene.node_items[const.id].setSelected(True)
        window._copy_selection()
        _pick_menu_action(monkeypatch, "Paste")

        window._show_add_node_menu(QPointF(0, 0), QPoint(0, 0))

        assert len(window.graph.nodes) == 3
