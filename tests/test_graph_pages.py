"""Dashboard pages in the core model: Page/Tile CRUD and events (Qt-free)."""
import pytest

from flograph.core import Graph, GraphError, Page, Tile


@pytest.fixture
def graph():
    return Graph()


@pytest.fixture
def page(graph):
    return graph.add_page(Page(id="p1", title="Sales"))


class TestPages:
    def test_add_emits_and_stores(self, graph):
        seen = []
        graph.events.page_added.connect(seen.append)
        page = graph.add_page(Page(id="p1"))
        assert graph.pages == {"p1": page}
        assert seen == [page]
        assert page.title == "Page"

    def test_duplicate_id_rejected(self, graph, page):
        with pytest.raises(GraphError):
            graph.add_page(Page(id="p1"))

    def test_remove_returns_page_with_tiles_intact(self, graph, page):
        graph.add_tile("p1", Tile(id="t1", node_id="n1", port="table"))
        seen = []
        graph.events.page_removed.connect(seen.append)
        popped = graph.remove_page("p1")
        assert popped is page
        assert list(popped.tiles) == ["t1"]
        assert graph.pages == {}
        assert seen == ["p1"]

    def test_remove_unknown_raises(self, graph):
        with pytest.raises(GraphError):
            graph.remove_page("nope")

    def test_rename_emits_changed(self, graph, page):
        seen = []
        graph.events.page_changed.connect(seen.append)
        graph.update_page("p1", title="Revenue")
        assert page.title == "Revenue"
        assert seen == [page]


class TestTiles:
    def test_add_emits_and_stores(self, graph, page):
        seen = []
        graph.events.tile_added.connect(lambda pid, t: seen.append((pid, t)))
        tile = graph.add_tile("p1", Tile(id="t1", node_id="n1", port="figure"))
        assert page.tiles == {"t1": tile}
        assert seen == [("p1", tile)]

    def test_dangling_node_id_is_legal(self, graph, page):
        # tiles may reference deleted nodes; the UI shows a placeholder
        tile = graph.add_tile("p1", Tile(id="t1", node_id="gone"))
        assert tile.node_id == "gone"
        assert tile.port is None

    def test_duplicate_tile_id_rejected(self, graph, page):
        graph.add_tile("p1", Tile(id="t1", node_id="n1"))
        with pytest.raises(GraphError):
            graph.add_tile("p1", Tile(id="t1", node_id="n2"))

    def test_add_to_unknown_page_raises(self, graph):
        with pytest.raises(GraphError):
            graph.add_tile("nope", Tile(id="t1", node_id="n1"))

    def test_remove_returns_tile(self, graph, page):
        tile = graph.add_tile("p1", Tile(id="t1", node_id="n1"))
        seen = []
        graph.events.tile_removed.connect(lambda pid, tid: seen.append((pid, tid)))
        assert graph.remove_tile("p1", "t1") is tile
        assert page.tiles == {}
        assert seen == [("p1", "t1")]

    def test_remove_unknown_raises(self, graph, page):
        with pytest.raises(GraphError):
            graph.remove_tile("p1", "nope")

    def test_update_rect_coerces_floats_and_emits(self, graph, page):
        tile = graph.add_tile("p1", Tile(id="t1", node_id="n1"))
        seen = []
        graph.events.tile_changed.connect(lambda pid, t: seen.append((pid, t)))
        graph.update_tile("p1", "t1", rect=(1, 2, 300, 200))
        assert tile.rect == (1.0, 2.0, 300.0, 200.0)
        assert all(isinstance(v, float) for v in tile.rect)
        assert seen == [("p1", tile)]

    def test_update_without_rect_still_emits(self, graph, page):
        tile = graph.add_tile("p1", Tile(id="t1", node_id="n1"))
        before = tile.rect
        graph.update_tile("p1", "t1")
        assert tile.rect == before
