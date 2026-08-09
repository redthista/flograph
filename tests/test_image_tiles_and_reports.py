"""Image nodes on a dashboard page, and in a report.

Both were places an Image node could be *named* but not shown: it wasn't in
TILE_ABLE_KINDS at all, and a report embed fell through every branch of
render_value to format_scalar, printing the payload dict as text.
"""
import base64

import pytest
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from flograph.core import NodeRegistry, Page, Tile
from flograph.ui import mainwindow as mod
from flograph.ui.commands import AddPageCommand, AddTileCommand
from flograph.ui.canvas.node_item import IMAGE_TYPE
from flograph.ui.dashboard.tile_item import (
    TILE_ABLE_KINDS, TITLE_H, default_tile_port, default_tile_size,
    is_tile_able,
)
from flograph.ui.mainwindow import MainWindow


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


@pytest.fixture
def png_file(tmp_path):
    path = tmp_path / "logo.png"
    image = QImage(200, 100, QImage.Format_RGB32)
    image.fill(QColor("#3366cc"))
    assert image.save(str(path), "PNG")
    return str(path)


def add_page(window, page_id="p1"):
    window.undo_stack.push(
        AddPageCommand(window.graph, Page(id=page_id, title="Board")))


def add_image_node(window, path, **params):
    node = window.registry.instantiate(IMAGE_TYPE, pos=(0, 0))
    node.params.update(path=path, **params)
    window.graph.add_node(node)
    return node


def add_tile(window, node, page_id="p1", tile_id="t1", port="image"):
    tile = Tile(id=tile_id, node_id=node.id, port=port)
    window.undo_stack.push(AddTileCommand(window.graph, page_id, tile))
    return window._dashboard_pages[page_id].scene.tile_items[tile_id]


def _paint(item, width=420, height=340) -> QImage:
    canvas = QImage(width, height, QImage.Format_ARGB32)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    from PySide6.QtWidgets import QStyleOptionGraphicsItem
    item.paint(painter, QStyleOptionGraphicsItem(), None)
    painter.end()
    return canvas


def _has_colour(image: QImage, colour: str, tolerance: int = 24) -> bool:
    want = QColor(colour)
    for y in range(0, image.height(), 3):
        for x in range(0, image.width(), 3):
            got = QColor(image.pixelColor(x, y))
            if got.alpha() == 0:
                continue
            if (abs(got.red() - want.red()) <= tolerance
                    and abs(got.green() - want.green()) <= tolerance
                    and abs(got.blue() - want.blue()) <= tolerance):
                return True
    return False


# --------------------------------------------------------------- dashboard

class TestImageIsTileAble:
    def test_kind_is_allowed_on_a_page(self, registry):
        assert "image" in TILE_ABLE_KINDS
        node = registry.instantiate(IMAGE_TYPE, pos=(0, 0))
        assert is_tile_able(node)

    def test_default_port_is_the_image_output(self, registry):
        node = registry.instantiate(IMAGE_TYPE, pos=(0, 0))
        assert default_tile_port(node) == "image"

    def test_default_size_follows_the_node_s_own_card(self, registry):
        node = registry.instantiate(IMAGE_TYPE, pos=(0, 0))
        node.params.update(width=500, height=400)
        assert default_tile_size(node) == (500.0, 400.0 + TITLE_H)


class TestImageTile:
    def test_tile_paints_the_picture(self, window, png_file):
        add_page(window)
        item = add_tile(window, add_image_node(window, png_file))
        assert _has_colour(_paint(item), "#3366cc")

    def test_tile_shows_without_running_the_flow(self, window, png_file):
        """The picture is the node's own source, not a computed output, so
        it is on the page before anything has run."""
        add_page(window)
        node = add_image_node(window, png_file)
        item = add_tile(window, node)
        assert window.engine.cache.get(node.id) is None  # never run
        assert item._card_image().has_content()
        assert _has_colour(_paint(item), "#3366cc")

    def test_tile_is_never_marked_stale(self, window, png_file):
        add_page(window)
        node = add_image_node(window, png_file)
        item = add_tile(window, node)
        node.dirty = True
        assert not item._is_stale()

    def test_empty_source_offers_a_prompt_not_a_crash(self, window):
        add_page(window)
        item = add_tile(window, add_image_node(window, ""))
        _paint(item)
        assert item._placeholder.isVisible() or not item._proxy.isHidden()

    def test_changing_the_file_redraws_without_a_run(self, window, png_file,
                                                     tmp_path):
        add_page(window)
        node = add_image_node(window, png_file)
        item = add_tile(window, node)
        other = tmp_path / "other.png"
        image = QImage(80, 80, QImage.Format_RGB32)
        image.fill(QColor("#22aa55"))
        image.save(str(other), "PNG")
        node.params["path"] = str(other)
        item.on_param_changed()
        assert _has_colour(_paint(item), "#22aa55")

    def test_hiding_the_tile_pauses_its_animation(self, window, png_file):
        add_page(window)
        item = add_tile(window, add_image_node(window, png_file))
        item._card_image()          # force the artwork into being
        item.setVisible(False)      # what maximizing another tile does
        assert item._image._playing is False
        item.setVisible(True)
        assert item._image._playing is True

    def test_a_wired_source_reaches_the_tile(self, window, png_file):
        """With an empty param the tile can only learn the source from the
        run's output, the same way the canvas card does."""
        add_page(window)
        node = add_image_node(window, "")
        item = add_tile(window, node)
        window.engine.cache.set(
            node.id, {"image": {"source": png_file, "path": png_file}}, 0.01)
        item.refresh_content()
        assert _has_colour(_paint(item), "#3366cc")


# ------------------------------------------------------------------ reports

class TestReportEmbedsAnImage:
    def _render(self, value):
        from flograph.ui.report.render import render_body
        return render_body("![[pic]]", lambda ref, port: (value, None, ""))

    def _payload(self, path):
        from flograph.core.images import resolve_source, to_data_uri
        data, mime, resolved = resolve_source(path)
        return {"path": resolved, "mime": mime, "bytes": data,
                "data_uri": to_data_uri(data, mime), "source": path}

    def test_payload_renders_as_a_picture_not_a_dict(self, png_file):
        rendered = self._render(self._payload(png_file))
        assert len(rendered.document.allFormats()) > 0
        # the giveaway for the old behaviour: the dict printed as text
        assert "data_uri" not in rendered.document.toPlainText()
        assert "b'" not in rendered.document.toPlainText()

    def test_the_image_reaches_the_document_as_a_resource(self, png_file):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QTextDocument
        rendered = self._render(self._payload(png_file))
        resource = rendered.document.resource(
            QTextDocument.ImageResource, QUrl("embed:0"))
        assert isinstance(resource, QImage)
        assert resource.size() == QImage(png_file).size()

    def test_a_bare_data_uri_string_is_drawn_not_printed(self, png_file):
        uri = self._payload(png_file)["data_uri"]
        rendered = self._render(uri)
        text = rendered.document.toPlainText()
        assert "base64" not in text     # would be the raw string inlined
        assert "iVBOR" not in text

    def test_a_small_picture_is_not_blown_up_to_page_width(self, tmp_path):
        """A chart fills the column; a 60px logo must not be stretched to
        600px and turned into a blurry one."""
        from flograph.ui.report.render import FIGURE_WIDTH, _Resolver
        small = tmp_path / "small.png"
        image = QImage(60, 30, QImage.Format_RGB32)
        image.fill(QColor("#cc3366"))
        image.save(str(small), "PNG")
        resolver = _Resolver(lambda ref, port: (self._payload(str(small)),
                                                None, ""), 1.0, FIGURE_WIDTH,
                             None, None)
        resolver.render_value(self._payload(str(small)), "pic")
        assert resolver.widths == [60]

    def test_a_big_picture_is_capped_at_the_column_width(self, png_file):
        from flograph.ui.report.render import FIGURE_WIDTH, _Resolver
        resolver = _Resolver(lambda ref, port: (None, None, ""), 1.0,
                             FIGURE_WIDTH, None, None)
        resolver.render_value(self._payload(png_file), "pic")
        assert resolver.widths == [min(FIGURE_WIDTH, 200)]

    def test_a_non_image_dict_still_renders_as_before(self):
        rendered = self._render({"not": "an image"})
        assert "not" in rendered.document.toPlainText()
