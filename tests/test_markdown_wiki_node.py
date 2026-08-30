"""The Markdown Wiki node: the contract, the canvas card and the dashboard
tile, and that navigating it never re-runs the flow.

Card/tile checks build an offscreen NodeGraphScene / DashboardScene — never a
shown MainWindow (see the teardown-crash note in the testing memory)."""
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry, compile_run
from flograph.core.graph import Page, Tile
from flograph.core.node import NodeStatus
from flograph.core.script import CARD_KINDS

WIKI = "flograph.viz.markdown_wiki"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def notes(tmp_path):
    (tmp_path / "Home.md").write_text(
        "# Home\n\nStart at [[Setup]].\n", encoding="utf-8")
    (tmp_path / "Setup.md").write_text("# Setup\n\nDo the thing.\n", encoding="utf-8")
    (tmp_path / "_Sidebar.md").write_text(
        "- [[Home]]\n- **Guide**\n  - [[Setup]]\n", encoding="utf-8")
    return tmp_path


class TestContract:
    def test_it_declares_the_wiki_card(self, registry):
        spec = registry.get(WIKI)
        assert spec.card == "wiki"
        assert "wiki" in CARD_KINDS
        assert [p.name for p in spec.outputs] == []

    def test_run_is_a_noop(self, registry):
        run = compile_run(registry.get(WIKI).source, "t")

        class Ctx:
            params = {"folder": ""}

            def log(self, *a):
                pass

        assert run(Ctx(), folder=None) == {}

    def test_page_and_show_nav_are_cosmetic(self, registry):
        spec = registry.get(WIKI)
        assert spec.param("page").cosmetic
        assert spec.param("show_nav").cosmetic


@pytest.fixture
def scene_of(qtbot, registry):
    from flograph.ui.canvas import NodeGraphScene
    made = []

    def build(graph):
        stack = QUndoStack()
        scene = NodeGraphScene(graph, stack, registry=registry)
        made.append((scene, stack))  # keep the C++ objects alive
        return scene

    yield build


class TestCanvasCard:
    def test_the_card_shows_the_bundled_handbook_by_default(self, scene_of, registry):
        graph = Graph()
        node = graph.add_node(registry.instantiate(WIKI))
        item = scene_of(graph).node_items[node.id]
        assert item.wiki_card and item._wiki_view is not None
        assert item._resizable()
        assert item._wiki_view.current_slug() == "home"

    def test_a_folder_param_points_it_at_that_folder(self, scene_of, registry, notes):
        graph = Graph()
        node = graph.add_node(registry.instantiate(WIKI))
        graph.set_param(node.id, "folder", str(notes))
        item = scene_of(graph).node_items[node.id]
        assert set(item._wiki_view._slug_items) == {"home", "setup"}

    def test_following_a_wikilink_persists_the_page_without_a_rerun(
            self, scene_of, registry, notes):
        graph = Graph()
        node = graph.add_node(registry.instantiate(WIKI))
        graph.set_param(node.id, "folder", str(notes))
        node.status = NodeStatus.DONE
        node.dirty = False

        item = scene_of(graph).node_items[node.id]
        item._wiki_view.browser._on_anchor(QUrl("setup.md"))

        assert graph.node(node.id).params["page"] == "setup"
        assert graph.node(node.id).dirty is False  # cosmetic — no re-run

    def test_toggling_the_nav_persists_show_nav(self, scene_of, registry):
        graph = Graph()
        node = graph.add_node(registry.instantiate(WIKI))
        item = scene_of(graph).node_items[node.id]
        item._wiki_view.set_nav_visible(False)
        assert graph.node(node.id).params["show_nav"] is False

    def test_a_persisted_page_is_restored_on_build(self, scene_of, registry, notes):
        graph = Graph()
        node = graph.add_node(registry.instantiate(WIKI))
        graph.set_param(node.id, "folder", str(notes))
        graph.set_param(node.id, "page", "setup")
        item = scene_of(graph).node_items[node.id]
        assert item._wiki_view.current_slug() == "setup"


class TestObsidianVault:
    @pytest.fixture
    def vault(self, tmp_path):
        from PySide6.QtGui import QImage
        (tmp_path / "Home.md").write_text(
            "# Home\n\nSee [[Deep Note]] and ![[pic.png]].\n", encoding="utf-8")
        (tmp_path / "notes").mkdir()
        (tmp_path / "notes" / "Deep Note.md").write_text(
            "# Deep Note\n\n![a chart](../assets/chart.png)\n", encoding="utf-8")
        (tmp_path / "assets").mkdir()
        QImage(20, 20, QImage.Format_RGB32).save(str(tmp_path / "pic.png"))
        QImage(30, 10, QImage.Format_RGB32).save(str(tmp_path / "assets" / "chart.png"))
        (tmp_path / ".obsidian").mkdir()
        (tmp_path / ".obsidian" / "app.md").write_text("# ignore\n", encoding="utf-8")
        return tmp_path

    def test_the_card_shows_a_nested_vault_and_renders_its_images(
            self, scene_of, registry, vault):
        graph = Graph()
        node = graph.add_node(registry.instantiate(WIKI))
        graph.set_param(node.id, "folder", str(vault))
        view = scene_of(graph).node_items[node.id]._wiki_view

        assert set(view._slug_items) == {"home", "deep-note"}  # notes/ recursed
        assert "<img" in view.browser.document().toHtml()      # ![[pic.png]]

        view.browser.show_page("deep-note")
        assert "<img" in view.browser.document().toHtml()      # ../assets/chart.png


class TestDashboardTile:
    def test_the_tile_renders_and_navigates(self, qtbot, registry, notes):
        from flograph.engine import ExecutionEngine
        from flograph.ui.dashboard.dashboard_scene import DashboardScene
        from flograph.ui.dashboard.tile_item import is_tile_able

        graph = Graph()
        node = graph.add_node(registry.instantiate(WIKI))
        graph.set_param(node.id, "folder", str(notes))
        assert is_tile_able(node)
        graph.add_page(Page(id="p1"))
        graph.add_tile("p1", Tile(id="t1", node_id=node.id))
        stack = QUndoStack()
        scene = DashboardScene(graph, ExecutionEngine(graph), stack, "p1")
        try:
            tile = scene.tile_items["t1"]
            assert tile._kind() == "wiki" and tile._wiki_view is not None
            tile._wiki_view.browser._on_anchor(QUrl("setup.md"))
            assert graph.node(node.id).params["page"] == "setup"
        finally:
            scene.dispose()
