"""M6: save/open through the main window, copy/paste/duplicate, dirty title."""
import json

import pytest
from PySide6.QtWidgets import QApplication

from flopy.core import NodeRegistry
from flopy.core.serialization import graph_to_dict
from flopy.ui.mainwindow import MainWindow


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
    const = reg.instantiate("flopy.util.constant", pos=(0, 0))
    script = reg.instantiate("flopy.scripting.python_script", pos=(200, 0))
    win.graph.add_node(const)
    win.graph.add_node(script)
    win.graph.connect(const.id, "value", script.id, "in1")
    return const, script


class TestSaveOpen:
    def test_save_and_reopen_reproduces_graph(self, window, tmp_path):
        build_small_project(window)
        before = graph_to_dict(window.graph)
        path = str(tmp_path / "proj.flopy")
        window._project_path = path
        assert window._save()
        assert window.undo_stack.isClean()

        window._replace_graph(__import__("flopy.core", fromlist=["Graph"]).Graph())
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

        path = str(tmp_path / "cached.flopy")
        window._project_path = path
        assert window._save()
        assert (tmp_path / "cached.flopy.cache" / "manifest.json").exists()

        from flopy.core import Graph
        window._replace_graph(Graph())
        assert window.open_path(path, confirm=False)

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

        path = str(tmp_path / "stale.flopy")
        window._project_path = path
        assert window._save()

        # edit the upstream node's param *after* saving the cache, then save
        # again — its fingerprint (and its downstream's) must now miss
        window.graph.set_param(const.id, "value", "edited")
        assert window._save()

        from flopy.core import Graph
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
        bad = tmp_path / "bad.flopy"
        bad.write_text("{broken")
        assert not window.open_path(str(bad), confirm=False)

    def test_recent_files_tracked(self, window, tmp_path):
        path = str(tmp_path / "r.flopy")
        window._project_path = path
        window._save()
        assert path in window._recent_files()

    def test_title_reflects_dirty_state(self, window, registry):
        from flopy.ui.commands import AddNodeCommand
        assert not window.isWindowModified()
        node = registry.instantiate("flopy.util.constant")
        window.undo_stack.push(AddNodeCommand(window.graph, node))
        assert window.isWindowModified()


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
