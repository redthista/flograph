"""User-saved node library: metadata rewriting, directory scan, file ops,
and the save -> reload -> serialize round trip."""
from __future__ import annotations

import pytest

from flopy.core import NodeRegistry, parse_spec, serialization
from flopy.core.graph import Graph
from flopy.core import user_nodes

SAMPLE = '''"""My Node

Docstring.
"""
NODE = {
    "label": "Read CSV",
    "category": "IO",
    "inputs": [],
    "outputs": [("value", "string")],
}
PARAMS = [{"name": "value", "type": "string", "default": "x"}]


def run(ctx):
    return ctx.params["value"]
'''


class TestSetMetadata:
    def test_rewrites_label_and_category(self):
        out = user_nodes.set_node_metadata(SAMPLE, "My Cleaner", "cleaning")
        assert '"label": \'My Cleaner\'' in out or "'My Cleaner'" in out
        assert "'cleaning'" in out
        # body untouched
        assert 'return ctx.params["value"]' in out
        assert '"name": "value"' in out
        # re-parses and reflects the new label/category
        spec = parse_spec(out, "user.cleaning.my_cleaner")
        assert spec.label == "My Cleaner"
        assert spec.category == "cleaning"

    def test_non_literal_node_falls_back_verbatim(self):
        src = "NODE = dict(label='x', category='y')\ndef run(ctx):\n    return 1\n"
        assert user_nodes.set_node_metadata(src, "A", "B") == src

    def test_syntax_error_falls_back_verbatim(self):
        src = "NODE = {\n"
        assert user_nodes.set_node_metadata(src, "A", "B") == src


class TestSlugAndTypeId:
    def test_slugify(self):
        assert user_nodes.slugify("My Cleaner!") == "my_cleaner"
        assert user_nodes.slugify("  ") == "node"

    def test_split_type_id(self):
        assert user_nodes.split_type_id("user.stem") == (None, "stem")
        assert user_nodes.split_type_id("user.grp.stem") == ("grp", "stem")
        with pytest.raises(user_nodes.UserNodeError):
            user_nodes.split_type_id("flopy.io.read_csv")


class TestWriteAndLoad:
    def test_write_and_scan_grouped_and_ungrouped(self, tmp_path):
        user_nodes.write_user_node(tmp_path, None, "Top Level", SAMPLE)
        user_nodes.write_user_node(tmp_path, "cleaning", "My Cleaner", SAMPLE)

        reg = NodeRegistry()
        errors = reg.load_user_nodes(tmp_path)
        assert errors == []
        top = reg.get("user.top_level")
        grouped = reg.get("user.cleaning.my_cleaner")
        assert top.group is None and not top.builtin
        assert grouped.group == "cleaning"
        assert grouped.label == "My Cleaner"

    def test_malformed_file_skipped(self, tmp_path):
        (tmp_path / "good.py").write_text(SAMPLE)
        (tmp_path / "bad.py").write_text("NODE = 5\n")  # invalid contract
        reg = NodeRegistry()
        errors = reg.load_user_nodes(tmp_path)
        assert reg.maybe_get("user.good") is not None
        assert reg.maybe_get("user.bad") is None
        assert len(errors) == 1 and errors[0][0].name == "bad.py"

    def test_overwrite_guard(self, tmp_path):
        user_nodes.write_user_node(tmp_path, None, "Dup", SAMPLE)
        with pytest.raises(user_nodes.UserNodeError):
            user_nodes.write_user_node(tmp_path, None, "Dup", SAMPLE)
        user_nodes.write_user_node(tmp_path, None, "Dup", SAMPLE, overwrite=True)

    def test_reload_drops_deleted(self, tmp_path):
        reg = NodeRegistry()
        reg.load_builtins()
        user_nodes.write_user_node(tmp_path, None, "Temp", SAMPLE)
        reg.load_user_nodes(tmp_path)
        assert reg.maybe_get("user.temp") is not None
        user_nodes.delete_user_node(tmp_path, "user.temp")
        reg.reload_user_nodes(tmp_path)
        assert reg.maybe_get("user.temp") is None
        # builtins survive the reload
        assert reg.maybe_get("flopy.io.read_csv") is not None


class TestFileOps:
    def test_rename(self, tmp_path):
        user_nodes.write_user_node(tmp_path, "g", "Old Name", SAMPLE)
        new_id = user_nodes.rename_user_node(tmp_path, "user.g.old_name", "New Name")
        assert new_id == "user.g.new_name"
        assert not (tmp_path / "g" / "old_name.py").exists()
        reg = NodeRegistry()
        reg.load_user_nodes(tmp_path)
        assert reg.get("user.g.new_name").label == "New Name"

    def test_move_between_groups(self, tmp_path):
        user_nodes.write_user_node(tmp_path, "a", "Thing", SAMPLE)
        new_id = user_nodes.move_user_node(tmp_path, "user.a.thing", "b")
        assert new_id == "user.b.thing"
        assert (tmp_path / "b" / "thing.py").exists()
        assert not (tmp_path / "a" / "thing.py").exists()

    def test_move_to_ungrouped(self, tmp_path):
        user_nodes.write_user_node(tmp_path, "a", "Thing", SAMPLE)
        new_id = user_nodes.move_user_node(tmp_path, "user.a.thing", None)
        assert new_id == "user.thing"
        assert (tmp_path / "thing.py").exists()

    def test_list_groups(self, tmp_path):
        user_nodes.create_group(tmp_path, "Alpha")
        user_nodes.write_user_node(tmp_path, "beta", "N", SAMPLE)
        assert user_nodes.list_groups(tmp_path) == ["alpha", "beta"]


class TestRoundTrip:
    def test_user_node_instance_survives_save_load(self, tmp_path):
        nodes_dir = tmp_path / "nodes"
        nodes_dir.mkdir()
        type_id = user_nodes.write_user_node(nodes_dir, "grp", "My Node", SAMPLE)

        reg = NodeRegistry()
        reg.load_builtins()
        reg.load_user_nodes(nodes_dir)

        graph = Graph()
        node = reg.instantiate(type_id)
        graph.add_node(node)
        assert not node.forked  # referenced by type_id, not embedded

        project = tmp_path / "p.flopy"
        serialization.save(graph, project)
        assert '"code": null' in project.read_text()

        loaded = serialization.load(project, reg)
        loaded_node = next(iter(loaded.nodes.values()))
        assert loaded_node.type_id == type_id
        assert not loaded_node.spec.broken

class TestSaveFlowIntegration:
    def test_save_as_user_node_from_window(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setenv("FLOPY_USER_DIR", str(tmp_path))
        from flopy.ui import mainwindow as mw

        reg = NodeRegistry()
        reg.load_builtins()
        win = mw.MainWindow(reg)
        win.confirm_close = False
        qtbot.addWidget(win)

        node = reg.instantiate("flopy.util.constant")
        win.graph.add_node(node)

        class FakeDialog:
            Accepted = mw.SaveUserNodeDialog.Accepted

            def __init__(self, *a, **k):
                pass

            def exec(self):
                return self.Accepted

            def values(self):
                return "My Constant", "utils"

        monkeypatch.setattr(mw, "SaveUserNodeDialog", FakeDialog)
        win._save_as_user_node(node.id)

        assert reg.get("user.utils.my_constant").label == "My Constant"
        # the library dock now shows a User Nodes section containing it
        tree = win.library_tree
        roots = [tree.topLevelItem(i).text(0)
                 for i in range(tree.topLevelItemCount())]
        assert "User Nodes" in roots

    def test_missing_user_node_becomes_broken(self, tmp_path):
        nodes_dir = tmp_path / "nodes"
        nodes_dir.mkdir()
        type_id = user_nodes.write_user_node(nodes_dir, None, "Gone", SAMPLE)
        reg = NodeRegistry()
        reg.load_user_nodes(nodes_dir)
        graph = Graph()
        graph.add_node(reg.instantiate(type_id))
        project = tmp_path / "p.flopy"
        serialization.save(graph, project)

        # a registry without the user node -> broken placeholder, not a crash
        bare = NodeRegistry()
        loaded = serialization.load(project, bare)
        assert next(iter(loaded.nodes.values())).spec.broken
