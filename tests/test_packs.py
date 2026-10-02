"""Node packs: manifest, discovery, install/link, the lib import hook, the
registry, saving/opening flows that use one, and the library section."""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

from flograph.core import Graph, NodeRegistry, packs, serialization

NODE_SRC = '''
NODE = {"label": "Doubler", "category": "Maths", "version": "1.0",
        "inputs": [("x", "number")], "outputs": [("y", "number")]}

def run(ctx, x):
    from flograph_packs.{pid} import helper
    return {{"y": helper.double(x)}}
'''


def make_pack(where: Path, pack_id: str = "demo_pack", version: str = "0.1.0",
              requires=(), name: str = "Demo Pack") -> Path:
    root = where / pack_id
    (root / "nodes" / "extra").mkdir(parents=True)
    (root / "lib").mkdir()
    reqs = ", ".join(f'"{r}"' for r in requires)
    (root / "pack.toml").write_text(
        f'[pack]\nid = "{pack_id}"\nname = "{name}"\nversion = "{version}"\n'
        f'description = "for tests"\nrequires = [{reqs}]\n', encoding="utf-8")
    (root / "nodes" / "doubler.py").write_text(
        NODE_SRC.replace("{pid}", pack_id).replace("{{", "{").replace("}}", "}"),
        encoding="utf-8")
    (root / "nodes" / "extra" / "echo.py").write_text(
        'NODE = {"label": "Echo", "category": "Other", "version": "1.0",\n'
        '        "inputs": [("v", "any")], "outputs": [("v", "any")]}\n'
        'def run(ctx, v):\n    return {"v": v}\n', encoding="utf-8")
    (root / "nodes" / "_private.py").write_text("x = 1\n", encoding="utf-8")
    (root / "lib" / "helper.py").write_text(
        "CALLS = []\n\ndef double(x):\n    CALLS.append(x)\n    return x * 2\n",
        encoding="utf-8")
    return root


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    d = tmp_path / "user"
    d.mkdir()
    monkeypatch.setenv("FLOGRAPH_USER_DIR", str(d))
    monkeypatch.delenv("FLOGRAPH_PACKS", raising=False)
    return d


class TestManifest:
    def test_reads_fields(self, tmp_path):
        pack = packs.read_manifest(make_pack(tmp_path, requires=["numpy>=1"]))
        assert (pack.id, pack.name, pack.version) == ("demo_pack", "Demo Pack",
                                                      "0.1.0")
        assert pack.requires == ["numpy>=1"]

    @pytest.mark.parametrize("bad, needle", [
        ('[pack]\nid = "Bad-Id"\nversion = "1"\n', "lower_snake_case"),
        ('[pack]\nid = "ok"\n', "version is required"),
        ('id = "ok"\n', "[pack] table"),
        ('[pack\n', "pack.toml"),
    ])
    def test_rejects_bad_manifest(self, tmp_path, bad, needle):
        (tmp_path / "pack.toml").write_text(bad, encoding="utf-8")
        with pytest.raises(packs.PackError, match=None) as info:
            packs.read_manifest(tmp_path)
        assert needle in str(info.value)

    def test_node_files_and_type_ids(self, tmp_path):
        pack = packs.read_manifest(make_pack(tmp_path))
        ids = [tid for tid, _ in pack.node_files()]
        assert ids == ["pack.demo_pack.doubler", "pack.demo_pack.extra.echo"]
        assert packs.pack_id_of("pack.demo_pack.extra.echo") == "demo_pack"
        assert packs.pack_id_of("flograph.util.constant") is None


class TestDiscovery:
    def test_installed_linked_and_env(self, tmp_path, user_dir, monkeypatch):
        make_pack(packs.packs_dir(user_dir), "installed_one")
        repo = tmp_path / "repo"
        make_pack(repo, "linked_a")
        make_pack(repo, "linked_b")
        packs.link(user_dir, repo)               # a folder *of* packs
        env = tmp_path / "env"
        make_pack(env, "from_env")
        monkeypatch.setenv("FLOGRAPH_PACKS", str(env / "from_env"))
        found, errors = packs.discover(user_dir)
        assert errors == []
        assert {p.id: p.source for p in found} == {
            "from_env": "env", "linked_a": "linked", "linked_b": "linked",
            "installed_one": "installed"}

    def test_duplicate_id_keeps_first_and_reports(self, tmp_path, user_dir):
        make_pack(packs.packs_dir(user_dir), "same")
        make_pack(tmp_path / "dev", "same", version="9.9")
        packs.link(user_dir, tmp_path / "dev" / "same")
        found, errors = packs.discover(user_dir)
        assert [p.version for p in found] == ["9.9"]     # linked wins
        assert len(errors) == 1 and "already provided" in errors[0][1]

    def test_bad_manifest_is_reported_not_fatal(self, user_dir):
        bad = packs.packs_dir(user_dir) / "broken"
        bad.mkdir(parents=True)
        (bad / "pack.toml").write_text("[pack]\n", encoding="utf-8")
        make_pack(packs.packs_dir(user_dir), "fine")
        found, errors = packs.discover(user_dir)
        assert [p.id for p in found] == ["fine"]
        assert errors and errors[0][0] == bad

    def test_link_rejects_folder_without_packs(self, tmp_path, user_dir):
        with pytest.raises(packs.PackError):
            packs.link(user_dir, tmp_path)


class TestInstall:
    def test_zip_round_trip(self, tmp_path, user_dir):
        src = packs.read_manifest(make_pack(tmp_path / "src"))
        (src.root / "__pycache__").mkdir()
        (src.root / "__pycache__" / "junk.pyc").write_bytes(b"x")
        archive = packs.export_zip(src, tmp_path / "demo.zip")
        names = zipfile.ZipFile(archive).namelist()
        assert "demo_pack/pack.toml" in names
        assert not any("__pycache__" in n for n in names)
        pack = packs.install(user_dir, archive)
        assert pack.root == packs.packs_dir(user_dir) / "demo_pack"
        assert (pack.root / "nodes" / "doubler.py").is_file()
        # leftovers of the unpack never stay behind
        assert [p.name for p in packs.packs_dir(user_dir).iterdir()] == [
            "demo_pack"]

    def test_existing_needs_replace(self, tmp_path, user_dir):
        packs.install(user_dir, make_pack(tmp_path / "a"))
        newer = make_pack(tmp_path / "b", version="0.2.0")
        with pytest.raises(packs.PackExistsError):
            packs.install(user_dir, newer)
        assert packs.install(user_dir, newer, replace=True).version == "0.2.0"

    def test_zip_slip_refused(self, tmp_path, user_dir):
        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("pack.toml", '[pack]\nid="evil"\nversion="1"\n')
            z.writestr("../../escaped.txt", "nope")
        with pytest.raises(packs.PackError, match="outside"):
            packs.install(user_dir, archive)
        assert not (tmp_path / "escaped.txt").exists()

    def test_not_a_zip(self, tmp_path, user_dir):
        bogus = tmp_path / "x.zip"
        bogus.write_text("hello")
        with pytest.raises(packs.PackError, match="not a zip"):
            packs.install(user_dir, bogus)

    def test_uninstall_installed_and_unlink_linked(self, tmp_path, user_dir):
        installed = packs.install(user_dir, make_pack(tmp_path / "a"))
        packs.uninstall(user_dir, installed)
        assert not installed.root.exists()
        dev = make_pack(tmp_path / "dev", "dev_pack")
        (linked,) = packs.link(user_dir, dev)
        packs.uninstall(user_dir, linked)
        assert dev.exists()                       # never deletes a checkout
        assert packs.discover(user_dir)[0] == []


class TestRequirements:
    def test_missing_and_present(self, tmp_path):
        pack = packs.read_manifest(make_pack(
            tmp_path, requires=["pytest", "surely-not-a-real-package-xyz"]))
        assert packs.missing_requirements(pack) == [
            "surely-not-a-real-package-xyz"]

    def test_version_specifier_when_packaging_available(self, tmp_path):
        pytest.importorskip("packaging")
        pack = packs.read_manifest(make_pack(tmp_path, requires=["pytest>=999"]))
        assert packs.missing_requirements(pack) == ["pytest>=999"]


class TestRegistry:
    def test_loads_nodes_and_lib_imports(self, tmp_path, user_dir):
        packs.link(user_dir, make_pack(tmp_path / "dev", "reg_pack"))
        reg = NodeRegistry()
        reg.load_builtins()
        assert reg.load_installed_packs(user_dir) == []
        spec = reg.get("pack.reg_pack.doubler")
        assert spec.pack == "reg_pack" and not spec.builtin
        assert reg.packs["reg_pack"].name == "Demo Pack"
        # the run() imports the pack's lib through the hook
        from flograph.core.script import compile_run
        run = compile_run(spec.source, "n1")
        assert run(None, x=4) == {"y": 8}
        helper = sys.modules["flograph_packs.reg_pack.helper"]
        assert helper.CALLS == [4]
        # ...and the module is shared: a second instance sees the same state
        compile_run(spec.source, "n2")(None, x=1)
        assert helper.CALLS == [4, 1]

    def test_disabled_pack_registers_nothing(self, tmp_path, user_dir):
        packs.link(user_dir, make_pack(tmp_path / "dev", "off_pack"))
        packs.set_enabled(user_dir, "off_pack", False)
        reg = NodeRegistry()
        reg.load_installed_packs(user_dir)
        assert reg.maybe_get("pack.off_pack.doubler") is None
        assert "off_pack" in reg.packs and "off_pack" in reg.disabled_packs

    def test_bad_node_skipped_rest_loads(self, tmp_path, user_dir):
        root = make_pack(tmp_path / "dev", "half_pack")
        (root / "nodes" / "bad.py").write_text("NODE = 3\n", encoding="utf-8")
        packs.link(user_dir, root)
        reg = NodeRegistry()
        errors = reg.load_installed_packs(user_dir)
        assert [p.name for p, _ in errors] == ["bad.py"]
        assert reg.maybe_get("pack.half_pack.doubler") is not None

    def test_user_node_reload_keeps_packs(self, tmp_path, user_dir):
        packs.link(user_dir, make_pack(tmp_path / "dev", "keep_pack"))
        reg = NodeRegistry()
        reg.load_installed_packs(user_dir)
        reg.reload_user_nodes(tmp_path / "no-user-nodes")
        assert reg.maybe_get("pack.keep_pack.doubler") is not None

    def test_reload_packs_drops_removed(self, tmp_path, user_dir):
        dev = make_pack(tmp_path / "dev", "gone_pack")
        packs.link(user_dir, dev)
        reg = NodeRegistry()
        reg.load_installed_packs(user_dir)
        packs.unlink(user_dir, dev)
        reg.load_installed_packs(user_dir)
        assert reg.maybe_get("pack.gone_pack.doubler") is None


class TestSaveLoad:
    def test_flow_records_packs_and_round_trips(self, tmp_path, user_dir):
        packs.link(user_dir, make_pack(tmp_path / "dev", "flow_pack"))
        reg = NodeRegistry()
        reg.load_builtins()
        reg.load_installed_packs(user_dir)
        graph = Graph()
        node = reg.instantiate("pack.flow_pack.doubler")
        graph.add_node(node)
        data = serialization.graph_to_dict(graph)
        assert data["packs"] == {"flow_pack": {"name": "Demo Pack",
                                               "version": "0.1.0"}}
        # a pack node carries no code: the pack ships it, not the flow
        assert data["graph"]["nodes"][0]["code"] is None
        again = serialization.graph_from_dict(data, reg)
        assert again.node(node.id).spec.pack == "flow_pack"

    def test_flow_without_packs_has_no_key(self):
        reg = NodeRegistry()
        reg.load_builtins()
        graph = Graph()
        graph.add_node(reg.instantiate("flograph.util.constant"))
        assert "packs" not in serialization.graph_to_dict(graph)

    def test_missing_pack_names_itself(self):
        data = {"schema": serialization.SCHEMA_VERSION,
                "packs": {"absent_pack": {"name": "Absent Things",
                                          "version": "2.0"}},
                "graph": {"nodes": [{"id": "a",
                                     "type": "pack.absent_pack.thing",
                                     "pos": [0, 0], "params": {}}],
                          "connections": []}}
        reg = NodeRegistry()
        graph = serialization.graph_from_dict(data, reg)
        node = graph.node("a")
        assert node.spec.broken
        assert "Absent Things 2.0 node pack" in node.status_message
        assert "Tools ▸ Node Packs" in node.status_message


class TestExamples:
    def test_pack_examples_join_the_examples_list(self, tmp_path, user_dir):
        from flograph.ui.start_screen import example_entries
        root = make_pack(tmp_path / "dev", "ex_pack", name="Ex Pack")
        (root / "examples").mkdir()
        (root / "examples" / "1 First try.flograph").write_text("{}")
        packs.link(user_dir, root)
        NodeRegistry().load_installed_packs(user_dir)
        titles = [t for t, _ in example_entries()]
        assert titles[-1].startswith("Ex Pack ▸ ")
        packs.set_enabled(user_dir, "ex_pack", False)
        NodeRegistry().load_installed_packs(user_dir)
        assert not any(t.startswith("Ex Pack") for t, _ in example_entries())


class TestCli:
    def test_link_list_disable(self, tmp_path, user_dir, capsys):
        from flograph.pack_cli import main
        dev = make_pack(tmp_path / "dev", "cli_pack")
        assert main(["link", str(dev)]) == 0
        assert main(["list"]) == 0
        out = capsys.readouterr().out
        assert "cli_pack" in out and "2 nodes" in out
        assert main(["disable", "cli_pack"]) == 0
        main(["list"])
        assert "(disabled)" in capsys.readouterr().out
        assert main(["remove", "nope"]) == 1


class TestLibrarySection:
    def test_pack_gets_its_own_section(self, qtbot, tmp_path, user_dir):
        from flograph.ui.canvas.palette import LibraryTree
        from flograph.ui.favorites import Favorites

        packs.link(user_dir, make_pack(tmp_path / "dev", "ui_pack",
                                       name="UI Pack"))
        reg = NodeRegistry()
        reg.load_builtins()
        reg.load_installed_packs(user_dir)
        from PySide6.QtCore import QSettings
        favorites = Favorites(QSettings(str(tmp_path / "fav.ini"),
                                        QSettings.IniFormat))
        tree = LibraryTree(reg, favorites)
        qtbot.addWidget(tree)
        tops = {tree.topLevelItem(i).text(0): tree.topLevelItem(i)
                for i in range(tree.topLevelItemCount())}
        assert "UI Pack" in tops
        section = tops["UI Pack"]
        # two categories in the pack -> one branch each
        branches = sorted(section.child(i).text(0)
                          for i in range(section.childCount()))
        assert branches == ["Maths", "Other"]
