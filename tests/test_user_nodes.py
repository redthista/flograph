"""User-saved node library: metadata rewriting, directory scan, file ops,
and the save -> reload -> serialize round trip."""
from __future__ import annotations

import json

import pytest

from flograph.core import NodeRegistry, parse_spec, serialization
from flograph.core.graph import Graph
from flograph.core import user_nodes

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

    @pytest.mark.parametrize("label", ["Café — x", "Sum Σ", "Rows → Cols",
                                       "Temp °C", "Chart 📊"])
    def test_non_ascii_label_rewrites_cleanly(self, label):
        """ast column offsets count UTF-8 bytes, not characters. Treating them
        as characters spliced the dict apart, so the node saved to disk but
        never loaded again."""
        src = SAMPLE.replace('"label": "Read CSV"', f'"label": "{label}"')
        out = user_nodes.set_node_metadata(src, "New Name", "grp")
        spec = parse_spec(out, "user.grp.new_name")
        assert spec.label == "New Name"
        assert spec.category == "grp"

    def test_single_line_node_dict_with_non_ascii(self):
        src = ('NODE = {"label": "Café — x", "category": "Text", '
               '"inputs": [], "outputs": [("o", "string")]}\n\n'
               'def run(ctx):\n    return "1"\n')
        out = user_nodes.set_node_metadata(src, "Renamed", "grp")
        spec = parse_spec(out, "user.grp.renamed")
        assert spec.label == "Renamed" and spec.category == "grp"

    def test_never_returns_unparseable_source(self):
        """The rewrite is discarded if it somehow fails to parse: a mangled
        node would save happily and then vanish from the library."""
        out = user_nodes.set_node_metadata(SAMPLE, "A — B", "IO")
        import ast as _ast
        _ast.parse(out)


class TestSlugAndTypeId:
    def test_slugify(self):
        assert user_nodes.slugify("My Cleaner!") == "my_cleaner"
        assert user_nodes.slugify("  ") == "node"

    def test_split_type_id(self):
        assert user_nodes.split_type_id("user.stem") == (None, "stem")
        assert user_nodes.split_type_id("user.grp.stem") == ("grp", "stem")
        with pytest.raises(user_nodes.UserNodeError):
            user_nodes.split_type_id("flograph.io.read_csv")


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

    def test_non_ascii_name_survives_save_and_scan(self, tmp_path):
        """The reported bug end to end: saved to disk, missing from the
        library, because the written file no longer parsed."""
        type_id = user_nodes.write_user_node(tmp_path, None, "Café — x", SAMPLE)
        reg = NodeRegistry()
        errors = reg.load_user_nodes(tmp_path)
        assert errors == []
        assert reg.get(type_id).label == "Café — x"

    def test_non_ascii_group_and_rename_and_move(self, tmp_path):
        type_id = user_nodes.write_user_node(tmp_path, "grp", "Rows → Cols",
                                             SAMPLE)
        type_id = user_nodes.rename_user_node(tmp_path, type_id, "Σ Sum")
        type_id = user_nodes.move_user_node(tmp_path, type_id, None)
        reg = NodeRegistry()
        assert reg.load_user_nodes(tmp_path) == []
        assert reg.get(type_id).label == "Σ Sum"

    def test_undecodable_file_skips_itself_only(self, tmp_path):
        (tmp_path / "good.py").write_text(SAMPLE, encoding="utf-8")
        # a node script saved under a non-UTF-8 locale on another machine
        (tmp_path / "legacy.py").write_bytes(
            SAMPLE.replace("Read CSV", "Caf\xe9").encode("cp1252"))
        reg = NodeRegistry()
        errors = reg.load_user_nodes(tmp_path)
        assert reg.maybe_get("user.good") is not None
        assert [p.name for p, _ in errors] == ["legacy.py"]

    def test_overwrite_guard(self, tmp_path):
        user_nodes.write_user_node(tmp_path, None, "Dup", SAMPLE)
        with pytest.raises(user_nodes.UserNodeExistsError):
            user_nodes.write_user_node(tmp_path, None, "Dup", SAMPLE)
        user_nodes.write_user_node(tmp_path, None, "Dup", SAMPLE, overwrite=True)

    @pytest.mark.parametrize("source", ["", "NODE = 5\n", "def run(ctx:\n"])
    def test_unloadable_source_is_refused_not_written(self, tmp_path, source):
        """Better a failed save than a file that occupies the name and never
        shows up in the library."""
        with pytest.raises(user_nodes.UserNodeError) as exc:
            user_nodes.write_user_node(tmp_path, None, "Broken", source)
        assert not isinstance(exc.value, user_nodes.UserNodeExistsError)
        assert not (tmp_path / "broken.py").exists()

    def test_missing_package_still_saves(self, tmp_path):
        """A top-level import this machine lacks is the machine's state, not a
        broken script — it loads as a placeholder and must stay saveable."""
        src = SAMPLE.replace("def run(ctx):",
                             "import definitely_not_installed_xyz\n\n\ndef run(ctx):")
        type_id = user_nodes.write_user_node(tmp_path, None, "Needs Pkg", src)
        assert (tmp_path / "needs_pkg.py").exists()
        assert type_id == "user.needs_pkg"

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
        assert reg.maybe_get("flograph.io.read_csv") is not None


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
        assert not node.forked  # linked to the library spec, not a fork

        project = tmp_path / "p.flograph"
        serialization.save(graph, project)
        # the library script travels inside the file for portability...
        assert "def run(ctx)" in project.read_text()

        # ...but on a machine that has the user node, the instance relinks
        # to the library rather than loading as a fork of an identical script
        loaded = serialization.load(project, reg)
        loaded_node = next(iter(loaded.nodes.values()))
        assert loaded_node.type_id == type_id
        assert not loaded_node.spec.broken
        assert not loaded_node.forked
        assert loaded_node.spec is reg.get(type_id)

    def test_user_node_travels_to_a_machine_without_it(self, tmp_path):
        """The whole point: a project using a custom node opens and runs on
        someone else's machine, where that user node was never installed."""
        nodes_dir = tmp_path / "nodes"
        nodes_dir.mkdir()
        type_id = user_nodes.write_user_node(nodes_dir, "grp", "My Node", SAMPLE)

        author = NodeRegistry()
        author.load_builtins()
        author.load_user_nodes(nodes_dir)
        graph = Graph()
        graph.add_node(author.instantiate(type_id))
        project = tmp_path / "p.flograph"
        serialization.save(graph, project)

        recipient = NodeRegistry()
        recipient.load_builtins()  # but no load_user_nodes
        loaded = serialization.load(project, recipient)
        node = next(iter(loaded.nodes.values()))
        assert not node.spec.broken
        assert node.type_id == type_id
        assert node.label == "My Node"  # write_user_node stamps the name in
        assert node.spec.param("value") is not None
        # kept as a local copy the recipient can inspect / adopt
        assert node.forked
        # and re-saving keeps carrying it
        again = tmp_path / "again.flograph"
        serialization.save(loaded, again)
        assert "def run(ctx)" in again.read_text()

    def test_pre_feature_file_without_embedded_code_still_breaks(self, tmp_path):
        """A .flograph written before this feature has "code": null for its
        user nodes. On a machine without the node there is nothing to fall
        back to, so it must still open as a broken placeholder, not crash."""
        legacy = {
            "schema": serialization.SCHEMA_VERSION,
            "graph": {"nodes": [{"id": "n1", "type": "user.grp.gone",
                                 "pos": [0, 0], "params": {}, "code": None}],
                      "connections": [], "frames": [], "pages": []},
        }
        project = tmp_path / "legacy.flograph"
        project.write_text(json.dumps(legacy))
        loaded = serialization.load(project, NodeRegistry())
        assert next(iter(loaded.nodes.values())).spec.broken

    def test_diverged_fork_is_not_relinked(self, tmp_path):
        """A user node placed, then hand-edited on the canvas: its embedded
        code differs from the library, so it stays a fork even where the
        library node exists."""
        nodes_dir = tmp_path / "nodes"
        nodes_dir.mkdir()
        type_id = user_nodes.write_user_node(nodes_dir, None, "Thing", SAMPLE)
        reg = NodeRegistry()
        reg.load_builtins()
        reg.load_user_nodes(nodes_dir)

        graph = Graph()
        node = reg.instantiate(type_id)
        graph.add_node(node)
        graph.set_code(node.id, SAMPLE.replace('"Read CSV"', '"Edited"'))

        project = tmp_path / "p.flograph"
        serialization.save(graph, project)
        loaded = serialization.load(project, reg)
        loaded_node = next(iter(loaded.nodes.values()))
        assert loaded_node.forked
        assert loaded_node.label == "Edited"


class TestSaveFlowIntegration:
    def test_save_as_user_node_from_window(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path))
        from flograph.ui import mainwindow as mw

        reg = NodeRegistry()
        reg.load_builtins()
        win = mw.MainWindow(reg)
        win.confirm_close = False
        qtbot.addWidget(win)

        node = reg.instantiate("flograph.util.constant")
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

    def test_embedded_code_that_wont_parse_here_stays_openable(self, tmp_path):
        """If the embedded copy itself won't load on the recipient's machine
        (a missing import, most often), the node holds its code and the
        reason — the rest of the project still opens, and re-saving writes
        the code back untouched."""
        project = tmp_path / "p.flograph"
        project.write_text(json.dumps({
            "schema": serialization.SCHEMA_VERSION,
            "graph": {"nodes": [{
                "id": "n1", "type": "user.grp.needs_pkg", "pos": [0, 0],
                "params": {},
                "code": "import _totally_missing_pkg\n"
                        "NODE = {'label': 'X', 'category': 'grp'}\n"
                        "def run(ctx): return 1\n",
            }], "connections": [], "frames": [], "pages": []},
        }))
        loaded = serialization.load(project, NodeRegistry())
        node = next(iter(loaded.nodes.values()))
        assert node.spec.broken
        assert node.code_override is not None  # re-saving writes it back
