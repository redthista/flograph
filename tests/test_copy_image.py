"""Copy Image: a picture or a matplotlib chart on show goes onto the
clipboard, from the canvas node menu, a dashboard tile or a chart view."""
import base64

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from flograph.core import NodeRegistry, Page, Tile
from flograph.core.images import to_data_uri
from flograph.ui import mainwindow as mod
from flograph.ui.canvas.node_item import IMAGE_TYPE
from flograph.ui.commands import AddPageCommand, AddTileCommand
from flograph.ui.image_paste import (
    copy_base64, copy_figure, copy_picture, is_figure, picture_as_base64,
    picture_mime,
)
from flograph.ui.mainwindow import MainWindow

# two-frame animated GIF, as in test_image_node
ANIMATED_GIF = base64.b64decode(
    "R0lGODlhBAAEAIAAAP8AAAAA/yH/C05FVFNDQVBFMi4wAwEAAAAh+QQAMgAAACwAAAAABAAE"
    "AAACBwQAAAAAACgAIfkEADIAAAAsAAAAAAQABAAAAgdMkiRJkiQpADs=")


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
    image = QImage(20, 10, QImage.Format_RGB32)
    image.fill(QColor("#3366cc"))
    assert image.save(str(path), "PNG")
    return str(path)


@pytest.fixture(autouse=True)
def _empty_clipboard(qapp):
    QApplication.clipboard().clear()
    yield
    QApplication.clipboard().clear()


def _clipboard_image() -> QImage:
    return QApplication.clipboard().mimeData().imageData()


def _figure(colour="#cc3333"):
    from matplotlib.figure import Figure
    fig = Figure(figsize=(2, 1), dpi=50)
    fig.add_subplot().bar([0, 1], [1, 2], color=colour)
    return fig


class TestClipboardData:
    def test_a_gif_keeps_its_own_bytes_beside_the_picture(self):
        mime = picture_mime(ANIMATED_GIF)
        assert not mime.imageData().isNull()
        assert bytes(mime.data("image/gif")) == ANIMATED_GIF

    def test_not_a_picture(self):
        assert picture_mime(b"<html>no</html>") is None
        assert not copy_picture("")
        assert not copy_picture("/no/such/file.png")

    def test_a_file_path(self, png_file):
        assert copy_picture(png_file)
        assert _clipboard_image().size().width() == 20

    def test_a_data_uri(self, png_file):
        with open(png_file, "rb") as handle:
            assert copy_picture(to_data_uri(handle.read(), "image/png"))
        assert not _clipboard_image().isNull()

    def test_a_figure(self):
        assert copy_figure(_figure())
        image = _clipboard_image()
        # 2x1 inches at twice the figure's 50 dpi
        assert (image.width(), image.height()) == (200, 100)

    def test_a_stack_of_figures_is_one_tall_picture(self):
        assert is_figure([_figure(), _figure("#3333cc")])
        assert copy_figure([_figure(), _figure("#3333cc")])
        image = _clipboard_image()
        assert (image.width(), image.height()) == (200, 200)

    def test_not_a_figure(self):
        assert not is_figure("text") and not is_figure([])
        assert not copy_figure(None)


class TestNodeMenu:
    def test_an_image_node_offers_its_picture(self, window, png_file):
        node = window.registry.instantiate(IMAGE_TYPE, pos=(0, 0))
        node.params["path"] = png_file
        window.graph.add_node(node)
        assert window._node_picture(node.id) == ("source", png_file)
        window._copy_node_picture(node.id)
        assert not _clipboard_image().isNull()

    def test_an_empty_image_node_offers_nothing(self, window):
        node = window.registry.instantiate(IMAGE_TYPE, pos=(0, 0))
        window.graph.add_node(node)
        assert window._node_picture(node.id) is None

    def test_other_nodes_offer_nothing(self, window):
        node = window.registry.instantiate(
            "flograph.io.read_csv", pos=(0, 0))
        window.graph.add_node(node)
        assert window._node_picture(node.id) is None


class TestDashboardTile:
    def test_an_image_tile_offers_its_picture(self, window, png_file):
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="p1", title="Board")))
        node = window.registry.instantiate(IMAGE_TYPE, pos=(0, 0))
        node.params["path"] = png_file
        window.graph.add_node(node)
        window.undo_stack.push(AddTileCommand(
            window.graph, "p1", Tile(id="t1", node_id=node.id, port="image")))
        item = window._dashboard_pages["p1"].scene.tile_items["t1"]
        assert item.copyable_picture() == ("source", png_file)


class TestFigureView:
    def test_shown_figures(self, qtbot):
        from flograph.ui.inspector.figure_view import FigureView
        view = FigureView()
        qtbot.addWidget(view)
        assert view.shown_figures() is None
        fig = _figure()
        view.set_figure(fig)
        assert view.shown_figures() is fig
        figs = [_figure(), _figure()]
        view.set_figure(figs)
        assert view.shown_figures() == figs


class TestCopyAsBase64:
    def test_a_file_is_copied_byte_for_byte_as_a_data_uri(self, png_file):
        from flograph.core.images import parse_data_uri
        assert copy_base64("source", png_file)
        text = QApplication.clipboard().text()
        data, kind = parse_data_uri(text)
        assert kind == "image/png"
        with open(png_file, "rb") as handle:
            assert data == handle.read()

    def test_an_embedded_gif_comes_back_unchanged(self):
        uri = to_data_uri(ANIMATED_GIF, "image/gif")
        assert picture_as_base64("source", uri) == uri

    def test_a_chart_as_png(self):
        text = picture_as_base64("figure", _figure())
        assert text.startswith("data:image/png;base64,")

    def test_nothing_to_give(self):
        assert picture_as_base64("source", "") is None
        assert picture_as_base64("source", "/no/such/file.png") is None
        assert not copy_base64("figure", None)

    def test_from_the_node_menu(self, window, png_file):
        node = window.registry.instantiate(IMAGE_TYPE, pos=(0, 0))
        node.params["path"] = png_file
        window.graph.add_node(node)
        window._copy_node_picture(node.id, as_base64=True)
        assert QApplication.clipboard().text().startswith(
            "data:image/png;base64,")
