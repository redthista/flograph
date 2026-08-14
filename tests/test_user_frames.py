"""The .floframe component library: saving a frame and reading it back."""
import json

import pytest

from flograph.core import user_frames as uf


def payload(label="Filter", param=1, wired=True):
    """A clipboard-shaped fragment: one frame, two nodes, one wire."""
    return {
        "nodes": [
            {"id": "a", "type": "flograph.util.constant", "label": "Load",
             "params": {"value": 1}, "code": None, "pos": [0.0, 0.0]},
            {"id": "b", "type": "flograph.scripting.python_script",
             "label": label, "params": {"n": param}, "code": None,
             "pos": [200.0, 0.0]},
        ],
        "connections": ([{"src": ["a", "out1"], "dst": ["b", "in1"]}]
                        if wired else []),
        "frames": [{"title": "Prep", "rect": [0, 0, 300, 200],
                    "color": "#33415c", "collapsed": True}],
    }


class TestNaming:
    def test_ids_encode_the_layout(self):
        assert uf.frame_id_for(None, "prep") == "frame.prep"
        assert uf.frame_id_for("etl", "prep") == "frame.etl.prep"

    def test_ids_split_back(self):
        assert uf.split_frame_id("frame.prep") == (None, "prep")
        assert uf.split_frame_id("frame.etl.prep") == ("etl", "prep")

    def test_a_node_id_is_rejected(self):
        with pytest.raises(uf.UserFrameError):
            uf.split_frame_id("user.etl.prep")

    def test_names_are_slugged(self):
        assert uf.slugify("Sales Prep!") == "sales_prep"
        assert uf.slugify("???") == "frame"


class TestFingerprint:
    def test_the_same_content_hashes_the_same(self):
        assert uf.content_hash(payload()) == uf.content_hash(payload())

    def test_ids_and_positions_do_not_count(self):
        """Inserting a component regenerates every id and moves it; neither
        means the user changed anything."""
        moved = payload()
        moved["nodes"][0]["id"] = "fresh-uuid"
        moved["nodes"][1]["id"] = "another-uuid"
        moved["connections"] = [{"src": ["fresh-uuid", "out1"],
                                 "dst": ["another-uuid", "in1"]}]
        for node in moved["nodes"]:
            node["pos"] = [999.0, 999.0]
        moved["frames"][0]["rect"] = [500, 500, 300, 200]
        assert uf.content_hash(moved) == uf.content_hash(payload())

    def test_a_changed_param_counts(self):
        assert uf.content_hash(payload(param=2)) != uf.content_hash(payload())

    def test_a_renamed_node_counts(self):
        assert uf.content_hash(payload(label="Sift")) != uf.content_hash(payload())

    def test_rewiring_counts(self):
        assert uf.content_hash(payload(wired=False)) != uf.content_hash(payload())


class TestFiles:
    def test_write_then_scan_and_read(self, tmp_path):
        frame_id = uf.write_user_frame(tmp_path, None, "Sales Prep", payload())
        assert frame_id == "frame.sales_prep"
        found = uf.scan(tmp_path)
        assert [f["id"] for f in found] == ["frame.sales_prep"]
        assert found[0]["name"] == "Sales Prep"
        assert found[0]["group"] is None
        assert found[0]["fingerprint"] == uf.content_hash(payload())

    def test_groups_are_one_level_of_subdirectory(self, tmp_path):
        uf.write_user_frame(tmp_path, "etl", "Prep", payload())
        found = uf.scan(tmp_path)
        assert found[0]["id"] == "frame.etl.prep"
        assert found[0]["group"] == "etl"
        assert (tmp_path / "etl" / "prep.floframe").exists()

    def test_writing_over_an_existing_one_is_refused(self, tmp_path):
        uf.write_user_frame(tmp_path, None, "Prep", payload())
        with pytest.raises(uf.UserFrameError):
            uf.write_user_frame(tmp_path, None, "Prep", payload())
        uf.write_user_frame(tmp_path, None, "Prep", payload(), overwrite=True)

    def test_scanning_an_absent_directory_is_empty(self, tmp_path):
        assert uf.scan(tmp_path / "nope") == []

    def test_a_broken_file_is_skipped_not_fatal(self, tmp_path):
        uf.write_user_frame(tmp_path, None, "Good", payload())
        (tmp_path / "broken.floframe").write_text("{not json")
        (tmp_path / "wrong.floframe").write_text(json.dumps({"hello": 1}))
        assert [f["id"] for f in uf.scan(tmp_path)] == ["frame.good"]

    def test_rename_moves_the_file_and_the_name(self, tmp_path):
        uf.write_user_frame(tmp_path, None, "Prep", payload())
        new_id = uf.rename_user_frame(tmp_path, "frame.prep", "Cleanup")
        assert new_id == "frame.cleanup"
        assert not (tmp_path / "prep.floframe").exists()
        assert uf.scan(tmp_path)[0]["name"] == "Cleanup"

    def test_move_between_groups(self, tmp_path):
        uf.write_user_frame(tmp_path, None, "Prep", payload())
        new_id = uf.move_user_frame(tmp_path, "frame.prep", "etl")
        assert new_id == "frame.etl.prep"
        assert uf.scan(tmp_path)[0]["group"] == "etl"
        back = uf.move_user_frame(tmp_path, new_id, None)
        assert back == "frame.prep"

    def test_delete(self, tmp_path):
        uf.write_user_frame(tmp_path, None, "Prep", payload())
        uf.delete_user_frame(tmp_path, "frame.prep")
        assert uf.scan(tmp_path) == []
        with pytest.raises(uf.UserFrameError):
            uf.delete_user_frame(tmp_path, "frame.prep")

    def test_the_payload_survives_the_round_trip(self, tmp_path):
        uf.write_user_frame(tmp_path, None, "Prep", payload())
        data = uf.read(tmp_path / "prep.floframe")
        assert data["payload"]["frames"][0]["collapsed"] is True
        assert len(data["payload"]["nodes"]) == 2


@pytest.fixture
def library(tmp_path, monkeypatch):
    """Point the library at a tmp dir so nothing touches the real profile."""
    monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path))
    return tmp_path / "frames"


class TestSaveAndInsert:
    """The round trip through the window: save a frame, drop it back in."""

    @pytest.fixture
    def window(self, qtbot, library):
        from flograph.core import NodeRegistry
        from flograph.ui.mainwindow import MainWindow
        reg = NodeRegistry()
        reg.load_builtins()
        win = MainWindow(reg)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def _build_frame(self, window):
        from flograph.core import Frame
        from flograph.ui.commands import AddFrameCommand, AddNodeCommand
        node = window.registry.instantiate("flograph.scripting.python_script",
                                           pos=(50.0, 50.0))
        window.undo_stack.push(AddNodeCommand(window.graph, node))
        frame = Frame(id="f1", rect=(0.0, 0.0, 300.0, 200.0), title="Prep")
        window.undo_stack.push(AddFrameCommand(window.graph, frame))
        return frame, node

    def test_save_then_insert_makes_an_independent_copy(self, window, library,
                                                        monkeypatch):
        from PySide6.QtCore import QPointF
        from PySide6.QtWidgets import QInputDialog
        from flograph.core import user_frames as uf
        frame, node = self._build_frame(window)
        monkeypatch.setattr(QInputDialog, "getText",
                            staticmethod(lambda *a, **k: ("Prep", True)))
        window._save_frame_as_component("f1")

        assert [e["id"] for e in uf.scan(library)] == ["frame.prep"]
        # the frame we saved from is stamped as an instance of what it became
        assert window.graph.frames["f1"].source == "frame.prep"
        assert window.graph.frames["f1"].source_fingerprint

        before_nodes = len(window.graph.nodes)
        window._insert_component_at("frame.prep", QPointF(900.0, 900.0))
        assert len(window.graph.frames) == 2
        assert len(window.graph.nodes) == before_nodes + 1
        new_frame = next(f for f in window.graph.frames.values()
                         if f.id != "f1")
        # a copy, but one that remembers where it came from
        assert new_frame.source == "frame.prep"
        assert new_frame.source_fingerprint == \
            window.graph.frames["f1"].source_fingerprint
        # and it landed where it was dropped, not at the paste offset
        assert new_frame.rect[0] == pytest.approx(900.0)
        assert new_frame.rect[1] == pytest.approx(900.0)

    def test_insert_is_one_undo_step(self, window, library, monkeypatch):
        from PySide6.QtCore import QPointF
        from PySide6.QtWidgets import QInputDialog
        self._build_frame(window)
        monkeypatch.setattr(QInputDialog, "getText",
                            staticmethod(lambda *a, **k: ("Prep", True)))
        window._save_frame_as_component("f1")
        depth = window.undo_stack.index()
        window._insert_component_at("frame.prep", QPointF(900.0, 900.0))
        assert window.undo_stack.index() == depth + 1
        window.undo_stack.undo()
        assert len(window.graph.frames) == 1

    def test_a_collapsed_frame_saves_and_inserts_collapsed(self, window,
                                                           library, monkeypatch):
        from PySide6.QtCore import QPointF
        from PySide6.QtWidgets import QInputDialog
        from flograph.ui.commands import SetFrameCollapsedCommand
        self._build_frame(window)
        window.undo_stack.push(
            SetFrameCollapsedCommand(window.graph, "f1", True))
        monkeypatch.setattr(QInputDialog, "getText",
                            staticmethod(lambda *a, **k: ("Prep", True)))
        window._save_frame_as_component("f1")
        window._insert_component_at("frame.prep", QPointF(900.0, 900.0))
        new_frame = next(f for f in window.graph.frames.values()
                         if f.id != "f1")
        assert new_frame.collapsed is True

    def test_a_fresh_insert_reads_pristine_and_an_edit_detaches(
            self, window, library, monkeypatch):
        """The whole pristine-vs-detached test, with no per-node bookkeeping:
        hash what the instance is now and compare with what it was stamped
        from."""
        from PySide6.QtCore import QPointF
        from PySide6.QtWidgets import QInputDialog
        from flograph.core import user_frames as uf
        from flograph.ui.commands import SetLabelCommand
        self._build_frame(window)
        monkeypatch.setattr(QInputDialog, "getText",
                            staticmethod(lambda *a, **k: ("Prep", True)))
        window._save_frame_as_component("f1")
        window._insert_component_at("frame.prep", QPointF(900.0, 900.0))
        new_frame = next(f for f in window.graph.frames.values()
                         if f.id != "f1")

        window.scene.clearSelection()
        window.scene.frame_items[new_frame.id].setSelected(True)
        pristine = uf.content_hash(window._selection_payload())
        assert pristine == new_frame.source_fingerprint

        inner = window._frame_node_ids_by_id(new_frame.id)[0]
        window.undo_stack.push(SetLabelCommand(window.graph, inner, "Renamed"))
        window.scene.clearSelection()
        window.scene.frame_items[new_frame.id].setSelected(True)
        assert uf.content_hash(window._selection_payload()) != \
            new_frame.source_fingerprint
