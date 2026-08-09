"""Animated images playing inside a rendered report.

A QTextDocument has no animated image type — images are static resources
registered under a URL. Animation means swapping the resource behind that
URL per frame and marking the one character it occupies dirty. What matters
here is that frames actually advance, that print never animates, and that a
movie can never outlive the document it writes into.
"""
import base64

import pytest
from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtGui import QColor, QImage, QTextDocument

from flograph.core.report import IMAGE_TOKEN_URL
from flograph.ui.report.animate import ReportAnimator, image_positions
from flograph.ui.report.render import render_body

# 4x4 two-frame animated GIF (red frame, blue frame), looping.
ANIMATED_GIF = base64.b64decode(
    "R0lGODlhBAAEAIAAAP8AAAAA/yH/C05FVFNDQVBFMi4wAwEAAAAh+QQAMgAAACwAAAAABAAE"
    "AAACBwQAAAAAACgAIfkEADIAAAAsAAAAAAQABAAAAgdMkiRJkiQpADs=")


@pytest.fixture(autouse=True)
def _app(qapp):
    return qapp


def _still_png() -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    image = QImage(40, 20, QImage.Format_RGB32)
    image.fill(QColor("#3366cc"))
    store = QByteArray()
    buffer = QBuffer(store)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(store)


def _payload(data: bytes, mime: str) -> dict:
    from flograph.core.images import to_data_uri
    return {"path": None, "mime": mime, "bytes": data,
            "data_uri": to_data_uri(data, mime), "source": ""}


def _render(value, for_print=False):
    return render_body("![[pic]]", lambda ref, port: (value, None, ""),
                       image_scale=2.0 if for_print else 1.0)


def _spin(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class TestRenderCollectsAnimations:
    def test_an_animated_gif_is_collected(self):
        rendered = _render(_payload(ANIMATED_GIF, "image/gif"))
        assert rendered.animations                  # index -> bytes
        assert rendered.animations[0] == ANIMATED_GIF

    def test_a_still_image_is_not(self):
        """A PNG has nothing to animate, and must not get a timer."""
        rendered = _render(_payload(_still_png(), "image/png"))
        assert rendered.animations == {}

    def test_print_never_animates(self):
        """Paper gets the poster frame — collecting movie bytes for a PDF
        would only build timers nobody can see."""
        rendered = _render(_payload(ANIMATED_GIF, "image/gif"), for_print=True)
        assert rendered.animations == {}
        # ...but the picture itself is still there
        assert rendered.image_widths

    def test_a_data_uri_animation_is_collected_too(self):
        from flograph.core.images import to_data_uri
        rendered = _render(to_data_uri(ANIMATED_GIF, "image/gif"))
        assert rendered.animations[0] == ANIMATED_GIF


class TestImagePositions:
    def test_finds_each_embedded_image(self):
        rendered = _render(_payload(ANIMATED_GIF, "image/gif"))
        found = image_positions(rendered.document)
        assert IMAGE_TOKEN_URL.format(0) in found
        assert isinstance(found[IMAGE_TOKEN_URL.format(0)], int)

    def test_a_document_with_no_images_finds_none(self):
        document = QTextDocument()
        document.setHtml("<p>just words</p>")
        assert image_positions(document) == {}


class TestReportAnimator:
    def _animator(self, rendered, frames):
        return ReportAnimator(rendered.document, rendered.animations,
                              rendered.image_widths,
                              on_frame=lambda: frames.append(1))

    def test_frames_advance_and_reach_the_document(self):
        rendered = _render(_payload(ANIMATED_GIF, "image/gif"))
        frames = []
        animator = self._animator(rendered, frames)
        assert animator.has_animations()
        url = QUrl(IMAGE_TOKEN_URL.format(0))
        animator.start()
        _spin(1200)
        animator.dispose()
        assert frames, "no frames were delivered"
        resource = rendered.document.resource(
            QTextDocument.ImageResource, url)
        assert isinstance(resource, QImage) and not resource.isNull()

    def test_pausing_stops_costing_frames(self):
        rendered = _render(_payload(ANIMATED_GIF, "image/gif"))
        frames = []
        animator = self._animator(rendered, frames)
        animator.start()
        _spin(700)
        animator.set_playing(False)
        settled = len(frames)
        _spin(700)
        assert len(frames) == settled
        animator.dispose()

    def test_dispose_is_idempotent_and_stops_everything(self):
        rendered = _render(_payload(ANIMATED_GIF, "image/gif"))
        frames = []
        animator = self._animator(rendered, frames)
        animator.start()
        animator.dispose()
        animator.dispose()          # must not raise
        settled = len(frames)
        _spin(500)
        assert len(frames) == settled

    def test_no_animations_means_no_movies(self):
        rendered = _render(_payload(_still_png(), "image/png"))
        animator = ReportAnimator(rendered.document, rendered.animations,
                                  rendered.image_widths)
        assert not animator.has_animations()
        animator.dispose()


class TestReportPageAnimates:
    def test_the_preview_builds_and_disposes_an_animator(self, qtbot,
                                                          tmp_path):
        """End to end through the page: a report embedding an animated image
        gets an animator, and re-rendering replaces rather than leaks it."""
        from flograph.core import Graph, NodeRegistry, Page
        from flograph.ui.canvas.node_item import IMAGE_TYPE
        from PySide6.QtGui import QUndoStack

        gif = tmp_path / "loop.gif"
        gif.write_bytes(ANIMATED_GIF)

        registry = NodeRegistry()
        registry.load_builtins()
        graph = Graph()
        node = registry.instantiate(IMAGE_TYPE, pos=(0, 0))
        node.label_override = "Loop"
        node.params["path"] = str(gif)
        graph.add_node(node)
        graph.add_page(Page(id="r1", kind="report", body="![[Loop]]"))

        # A report embed reads a node's *cached output*, so — unlike the
        # canvas card, which draws from the param — the flow has to have run.
        # This is that run.
        from flograph.engine.cache import OutputCache
        cache = OutputCache()
        cache.set(node.id, {"image": _payload(ANIMATED_GIF, "image/gif")},
                  0.01)

        class _Engine:
            def __init__(self, cache):
                from flograph.core.events import Event
                self.cache = cache
                self.node_succeeded = Event()
                self.node_failed = Event()

        from flograph.ui.report.report_page import ReportPage
        engine = _Engine(cache)
        page = ReportPage(graph, engine, QUndoStack(), "r1")
        qtbot.addWidget(page)
        page.refresh_preview()
        assert page._animator is not None
        assert page._animator.has_animations()

        first = page._animator
        page.refresh_preview()
        assert page._animator is not first   # replaced, not stacked
        page.dispose()
        assert page._animator is None


class TestReportTileAnimates:
    """A Report card put on a dashboard page.

    This was the one place a report's gif stayed on its first frame: the
    tile rendered the same document the canvas card and the report page do,
    but never built an animator for it. Maximizing made it worse — the
    maximized copy is a *clone* of the document, so even an animator on the
    tile could not have driven it.
    """

    @pytest.fixture
    def board(self, qtbot, tmp_path, monkeypatch):
        from PySide6.QtCore import QSettings
        from flograph.core import NodeRegistry, Page, Tile
        from flograph.ui import mainwindow as mod
        from flograph.ui.canvas.node_item import IMAGE_TYPE
        from flograph.ui.commands import AddPageCommand, AddTileCommand
        from flograph.ui.mainwindow import MainWindow

        ini = str(tmp_path / "s.ini")
        monkeypatch.setattr(
            mod, "QSettings",
            lambda *a, **k: QSettings(ini, QSettings.IniFormat))
        registry = NodeRegistry()
        registry.load_builtins()
        window = MainWindow(registry)
        window.confirm_close = False
        qtbot.addWidget(window)

        image = registry.instantiate(IMAGE_TYPE, pos=(0, 0))
        window.graph.add_node(image)
        card = registry.instantiate("flograph.viz.report_card", pos=(400, 0))
        card.params["text"] = "![[a]]"
        window.graph.add_node(card)
        window.graph.connect(image.id, "image", card.id, "a")
        window.engine.cache.set(
            image.id, {"image": _payload(ANIMATED_GIF, "image/gif")}, 0.01)

        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="p1", title="B")))
        window.undo_stack.push(AddTileCommand(
            window.graph, "p1", Tile(id="t1", node_id=card.id, port="text")))
        page = window._dashboard_pages["p1"]
        yield window, page, page.scene.tile_items["t1"]
        # qtbot deletes the window from the C++ side, which takes the tile's
        # browser with it while the movies are still running. dispose() is
        # idempotent, so tests that already disposed are fine.
        for item in list(page.scene.tile_items.values()):
            item.dispose()

    def test_the_tile_builds_an_animator(self, board):
        _window, _page, tile = board
        assert tile._report_animator is not None
        assert tile._report_animator.has_animations()

    def test_re_rendering_replaces_it_rather_than_stacking(self, board):
        _window, _page, tile = board
        first = tile._report_animator
        tile.refresh_content()
        assert tile._report_animator is not first
        assert first._movies == []          # the old one was disposed

    def test_a_still_image_gets_no_animator(self, board):
        window, _page, tile = board
        node = next(n for n in window.graph.nodes.values()
                    if n.type_id.endswith(".image"))
        window.engine.cache.set(
            node.id, {"image": _payload(_still_png(), "image/png")}, 0.01)
        tile.refresh_content()
        assert tile._report_animator is None

    def test_maximizing_gives_the_copy_its_own_animator(self, board):
        """The overlay shows a clone of the document, and the tile's
        animator writes into the original — so the clone needs its own or
        it sits on whichever frame it was cloned mid-loop."""
        _window, page, tile = board
        page.scene.toggle_fullscreen("t1")
        overlay = page.view.fullscreen_overlay
        assert overlay is not None
        assert overlay.content._animator is not None
        assert overlay.content._animator.has_animations()
        # ...and it is not the tile's, which writes into a different document
        assert overlay.content._animator is not tile._report_animator

    def test_the_hidden_tile_stops_spending_frames_while_maximized(self, board):
        from PySide6.QtGui import QMovie
        _window, page, tile = board
        page.scene.toggle_fullscreen("t1")
        assert not any(m.state() == QMovie.Running
                       for m in tile._report_animator._movies)

    def test_restoring_disposes_the_copy_and_resumes_the_tile(self, board):
        _window, page, tile = board
        page.scene.toggle_fullscreen("t1")
        content = page.view.fullscreen_overlay.content
        page.scene.exit_fullscreen()
        # disposed *before* the widget is deleted: a movie still writing
        # into a deleted document is a crash, not a stale picture
        assert content._animator is None
        assert tile._report_animator is not None

    def test_a_page_nobody_is_looking_at_costs_nothing(self, board):
        from PySide6.QtGui import QMovie
        _window, page, tile = board
        page.scene.set_animations_playing(False)
        assert not any(m.state() == QMovie.Running
                       for m in tile._report_animator._movies)
        page.scene.set_animations_playing(True)
        assert all(m.state() == QMovie.Running
                   for m in tile._report_animator._movies)

    def test_removing_the_tile_stops_its_movies(self, board):
        from flograph.ui.commands import RemoveTileCommand
        window, _page, tile = board
        window.undo_stack.push(RemoveTileCommand(window.graph, "p1", "t1"))
        assert tile._report_animator is None

    def test_closing_the_page_stops_its_movies(self, board):
        _window, page, tile = board
        page.dispose()
        assert tile._report_animator is None
