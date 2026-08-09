"""The Image node: its run(), its canvas card, and pasting from the clipboard.

Fixtures build real image files (Qt writes them) rather than shipping
binaries, so the suite stays text-only and the formats are whatever the
running Qt actually supports.
"""
import base64

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter

from flograph.core import NodeRegistry
from flograph.ui.canvas.image_card import (
    CardImage, MAX_DECODE_PIXELS, is_svg, target_size,
)
from flograph.ui.canvas.node_item import IMAGE_TYPE, NodeItem, card_kind

# ------------------------------------------------------------------ fixtures

@pytest.fixture(autouse=True)
def _app(qapp):
    """QPixmap and QMovie both need a QGuiApplication, and most tests here
    build one or the other without ever going near a widget."""
    return qapp


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def _solid(width: int, height: int, colour: str = "#3366cc") -> QImage:
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor(colour))
    return image


@pytest.fixture
def png_file(tmp_path):
    path = tmp_path / "solid.png"
    assert _solid(200, 100).save(str(path), "PNG")
    return str(path)


@pytest.fixture
def big_png_file(tmp_path):
    """Deliberately larger than any card it will be shown on."""
    path = tmp_path / "big.png"
    assert _solid(2400, 1600, "#cc3366").save(str(path), "PNG")
    return str(path)


@pytest.fixture
def svg_file(tmp_path):
    path = tmp_path / "mark.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60">'
        '<rect width="120" height="60" fill="#22aa55"/></svg>')
    return str(path)


# A hand-built 4x4 two-frame animated GIF89a (red frame, blue frame, looping).
# Embedded rather than generated because Qt ships a GIF *reader* but not
# always a GIF writer, and the animated path is exactly what needs covering.
ANIMATED_GIF = base64.b64decode(
    "R0lGODlhBAAEAIAAAP8AAAAA/yH/C05FVFNDQVBFMi4wAwEAAAAh+QQAMgAAACwAAAAABAAE"
    "AAACBwQAAAAAACgAIfkEADIAAAAsAAAAAAQABAAAAgdMkiRJkiQpADs=")


@pytest.fixture
def gif_file(tmp_path):
    """A two-frame animated GIF on disk."""
    if "gif" not in [bytes(f).decode()
                     for f in QImageReader.supportedImageFormats()]:
        pytest.skip("this Qt build has no GIF image plugin")
    path = tmp_path / "loop.gif"
    path.write_bytes(ANIMATED_GIF)
    return str(path)


def _make_item(registry, **params):
    node = registry.instantiate(IMAGE_TYPE, pos=(0.0, 0.0))
    node.params.update(params)
    return NodeItem(node)


def _render(item, width=400, height=340) -> QImage:
    """Paint a NodeItem into an offscreen image and hand back the pixels."""
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


# ------------------------------------------------------------------ the node

class TestImageNodeSpec:
    def test_registers_as_an_image_card(self, registry):
        spec = registry.get(IMAGE_TYPE)
        assert spec.card == "image"
        assert [p.name for p in spec.outputs] == ["image"]
        # the optional input is what lets an upstream node supply the picture
        assert spec.inputs[0].name == "source"
        assert spec.inputs[0].optional

    def test_declares_the_params_the_card_reads(self, registry):
        names = {p.name for p in registry.get(IMAGE_TYPE).params}
        assert {"path", "fit", "scale", "animate", "background",
                "width", "height"} <= names

    def test_card_kind_resolves(self, registry):
        node = registry.instantiate(IMAGE_TYPE, pos=(0, 0))
        assert card_kind(node) == "image"


class TestImageNodeRun:
    def _run(self, registry, fake_ctx, params, **inputs):
        source = registry.get(IMAGE_TYPE).source
        namespace = {}
        exec(compile(source, "<test>", "exec"), namespace)
        return namespace["run"](fake_ctx(params), **inputs)

    def test_reads_a_png_and_reports_its_mime(self, registry, fake_ctx,
                                              png_file):
        out = self._run(registry, fake_ctx, {"path": png_file})["image"]
        assert out["mime"] == "image/png"
        assert out["path"] == png_file
        assert out["bytes"].startswith(b"\x89PNG")
        assert out["data_uri"].startswith("data:image/png;base64,")

    def test_data_uri_round_trips(self, registry, fake_ctx, png_file):
        import base64
        out = self._run(registry, fake_ctx, {"path": png_file})["image"]
        encoded = out["data_uri"].split(",", 1)[1]
        assert base64.b64decode(encoded) == out["bytes"]

    def test_svg_is_sniffed_by_content(self, registry, fake_ctx, svg_file):
        out = self._run(registry, fake_ctx, {"path": svg_file})["image"]
        assert out["mime"] == "image/svg+xml"

    def test_wired_source_beats_the_param(self, registry, fake_ctx, png_file,
                                          svg_file):
        out = self._run(registry, fake_ctx, {"path": svg_file},
                        source=png_file)["image"]
        assert out["path"] == png_file

    def test_no_source_is_a_helpful_error(self, registry, fake_ctx):
        with pytest.raises(ValueError, match="no image given"):
            self._run(registry, fake_ctx, {"path": ""})

    def test_missing_file_is_a_helpful_error(self, registry, fake_ctx):
        with pytest.raises(FileNotFoundError, match="not found"):
            self._run(registry, fake_ctx, {"path": "/nope/absent.png"})

    def test_accepts_bare_base64(self, registry, fake_ctx, png_file):
        import base64 as b64
        raw = open(png_file, "rb").read()
        out = self._run(registry, fake_ctx,
                        {"path": b64.b64encode(raw).decode()})["image"]
        assert out["bytes"] == raw
        assert out["mime"] == "image/png"
        assert out["path"] is None   # it never was a file

    def test_accepts_a_data_uri(self, registry, fake_ctx, png_file):
        import base64 as b64
        raw = open(png_file, "rb").read()
        uri = f"data:image/png;base64,{b64.b64encode(raw).decode()}"
        out = self._run(registry, fake_ctx, {"path": uri})["image"]
        assert out["bytes"] == raw
        assert out["path"] is None

    def test_echoes_the_source_back_for_the_card(self, registry, fake_ctx,
                                                 png_file):
        out = self._run(registry, fake_ctx, {"path": ""},
                        source=png_file)["image"]
        assert out["source"] == png_file


# ------------------------------------------------------------------- sizing

class TestTargetSize:
    NATURAL = QSize(200, 100)
    BOX = QSize(300, 300)

    def test_fit_stays_inside_the_box(self):
        size = target_size(self.NATURAL, self.BOX, "Fit")
        assert size.width() <= self.BOX.width()
        assert size.height() <= self.BOX.height()
        assert size == QSize(300, 150)  # aspect kept

    def test_fill_covers_the_box(self):
        size = target_size(self.NATURAL, self.BOX, "Fill")
        assert size.width() >= self.BOX.width()
        assert size.height() >= self.BOX.height()
        assert size == QSize(600, 300)  # aspect kept, overflows

    def test_stretch_matches_the_box_exactly(self):
        assert target_size(self.NATURAL, self.BOX, "Stretch") == self.BOX

    def test_original_ignores_the_box(self):
        assert target_size(self.NATURAL, self.BOX, "Original size") == self.NATURAL

    def test_scale_multiplies_whichever_mode(self):
        assert target_size(self.NATURAL, self.BOX, "Fit", 0.5) == QSize(150, 75)
        assert target_size(self.NATURAL, self.BOX, "Original size", 2.0) == \
            QSize(400, 200)

    def test_scale_is_clamped(self):
        huge = target_size(self.NATURAL, self.BOX, "Original size", 99.0)
        assert huge == QSize(800, 400)  # SCALE_MAX = 4.0

    def test_is_svg(self):
        assert is_svg("/x/a.svg") and is_svg("/x/A.SVGZ")
        assert not is_svg("/x/a.png")


# --------------------------------------------------------------- decoding

class TestCardImageDecode:
    def test_natural_size_read_without_decoding(self, png_file):
        image = CardImage(lambda: None)
        image.set_source(png_file, "Fit", True)
        assert image.natural_size() == QSize(200, 100)
        assert not image.error

    def test_big_image_decodes_at_card_size_not_source_size(self, big_png_file):
        """The whole point of the card: a 2400x1600 source on a small card
        must not allocate a 2400x1600 buffer."""
        image = CardImage(lambda: None)
        image.set_source(big_png_file, "Fit", True)
        image._ensure(QSize(320, 200), 1.0)
        decoded = image._pixmap
        assert decoded is not None
        assert decoded.width() <= 340   # card-sized, not source-sized
        assert decoded.height() <= 220

    def test_decode_is_cached_between_paints(self, png_file):
        image = CardImage(lambda: None)
        image.set_source(png_file, "Fit", True)
        image._ensure(QSize(320, 200), 1.0)
        first = image._pixmap
        image._ensure(QSize(320, 200), 1.0)
        assert image._pixmap is first  # same object: no re-decode

    def test_changing_size_re_decodes(self, png_file):
        image = CardImage(lambda: None)
        image.set_source(png_file, "Fit", True)
        image._ensure(QSize(320, 200), 1.0)
        first = image._pixmap
        image._ensure(QSize(640, 400), 1.0)
        assert image._pixmap is not first

    def test_original_size_respects_the_memory_budget(self, big_png_file):
        image = CardImage(lambda: None)
        image.set_source(big_png_file, "Original size", True)
        image._ensure(QSize(100, 100), 4.0)
        decoded = image._pixmap
        assert decoded is not None
        assert decoded.width() * decoded.height() <= MAX_DECODE_PIXELS

    def test_missing_file_reports_an_error(self, tmp_path):
        image = CardImage(lambda: None)
        image.set_source(str(tmp_path / "gone.png"), "Fit", True)
        image.natural_size()
        assert image.error

    def test_svg_is_kept_as_vectors(self, svg_file):
        image = CardImage(lambda: None)
        image.set_source(svg_file, "Fit", True)
        assert image.natural_size() == QSize(120, 60)
        image._ensure(QSize(400, 400), 1.0)
        assert image._svg is not None
        assert image._pixmap is None  # never rasterised into a buffer


class TestAnimation:
    def test_still_image_is_not_animated(self, png_file):
        image = CardImage(lambda: None)
        image.set_source(png_file, "Fit", True)
        assert not image.is_animated()

    def test_paused_movie_stops_costing_frames(self, gif_file):
        image = CardImage(lambda: None)
        image.set_source(gif_file, "Fit", True)
        image._ensure(QSize(80, 80), 1.0)
        if image._movie is None:
            pytest.skip("single-frame GIF — nothing to animate")
        image.set_playing(False)
        from PySide6.QtGui import QMovie
        assert image._movie.state() != QMovie.Running


# ------------------------------------------------------------------- card

class TestImageCardPainting:
    def test_card_draws_the_picture(self, registry, png_file):
        item = _make_item(registry, path=png_file, width=300, height=240)
        assert _has_colour(_render(item), "#3366cc")

    def test_card_without_a_file_draws_the_hint_not_a_crash(self, registry):
        item = _make_item(registry, path="")
        _render(item)  # must not raise

    def test_missing_file_paints_an_error_not_a_crash(self, registry, tmp_path):
        item = _make_item(registry, path=str(tmp_path / "absent.png"))
        _render(item)

    def test_svg_card_draws(self, registry, svg_file):
        item = _make_item(registry, path=svg_file, width=300, height=240)
        assert _has_colour(_render(item), "#22aa55")

    def test_geometry_follows_the_size_params(self, registry, png_file):
        item = _make_item(registry, path=png_file, width=500, height=400)
        assert item.width == 500
        assert item.body_height == 400

    def test_card_is_resizable(self, registry, png_file):
        assert _make_item(registry, path=png_file)._resizable()

    def test_changing_the_path_param_reloads_without_a_run(self, registry,
                                                           png_file, svg_file):
        item = _make_item(registry, path=png_file, width=300, height=240)
        _render(item)
        item.node.params["path"] = svg_file
        item.on_params_changed()
        assert _has_colour(_render(item), "#22aa55")

    def test_lod_flattening_pauses_playback(self, registry, png_file):
        item = _make_item(registry, path=png_file)
        item._card_image()          # force the artwork into existence
        item.set_lod(True)
        assert not item._image_should_play()
        item.set_lod(False)
        assert item._image_should_play()

    def test_preview_disabled_pauses_playback(self, registry, png_file):
        item = _make_item(registry, path=png_file)
        item._card_image()
        item.node.canvas_preview_enabled = False
        assert not item._image_should_play()

    def test_artwork_is_lazy(self, registry, png_file):
        """A card never painted never decodes — which is what keeps opening a
        zoomed-out project full of images cheap."""
        item = _make_item(registry, path=png_file)
        assert item._image is None

    def test_a_wired_source_reaches_the_card(self, registry, png_file):
        """With nothing in the param, the card can only learn the source from
        the run — that is the whole point of set_image_result."""
        item = _make_item(registry, path="", width=300, height=240)
        item.set_image_result(png_file)
        assert item._image_source() == png_file
        assert _has_colour(_render(item), "#3366cc")

    def test_picking_a_file_by_hand_overrides_the_last_run(self, registry,
                                                           png_file, svg_file):
        item = _make_item(registry, path="", width=300, height=240)
        item.set_image_result(png_file)
        item.node.params["path"] = svg_file
        item.on_params_changed()
        assert item._image_source() == svg_file

    def test_card_draws_a_base64_param(self, registry, png_file):
        """Base64 in the param renders exactly like a file would."""
        import base64 as b64
        blob = b64.b64encode(open(png_file, "rb").read()).decode()
        item = _make_item(registry, path=blob, width=300, height=240)
        assert _has_colour(_render(item), "#3366cc")

    def test_card_draws_a_data_uri(self, registry, png_file):
        import base64 as b64
        blob = b64.b64encode(open(png_file, "rb").read()).decode()
        item = _make_item(registry, path=f"data:image/png;base64,{blob}",
                          width=300, height=240)
        assert _has_colour(_render(item), "#3366cc")

    def test_card_animates_a_base64_gif(self, registry):
        """The bytes path has to keep its QBuffer alive for as long as the
        movie reads from it — getting that wrong is a segfault, not a test
        failure, so this exercises it deliberately."""
        import base64 as b64
        item = _make_item(registry, path=b64.b64encode(ANIMATED_GIF).decode(),
                          width=200, height=200)
        _render(item)
        image = item._card_image()
        if not image.is_animated():
            pytest.skip("no GIF plugin")
        assert image._movie is not None
        image.set_playing(True)
        image.set_playing(False)

    def test_rubbish_source_paints_an_error_not_a_crash(self, registry):
        item = _make_item(registry, path="not a file and not base64!!")
        _render(item)
        assert item._card_image().error


# ------------------------------------------------------------ clipboard paste

class TestClipboardImageBytes:
    def test_prefers_the_raw_flavour_over_re_encoding(self):
        """Taking the clipboard's own GIF bytes is what keeps a pasted
        animation animated — re-encoding the decoded QImage would flatten it
        to a single frame."""
        from PySide6.QtCore import QByteArray, QMimeData
        from flograph.ui.image_paste import clipboard_image_bytes
        mime = QMimeData()
        mime.setData("image/gif", QByteArray(ANIMATED_GIF))
        mime.setImageData(_solid(4, 4))
        data, suffix = clipboard_image_bytes(mime)
        assert suffix == ".gif"
        assert data == ANIMATED_GIF

    def test_falls_back_to_png_for_a_bare_image(self):
        from PySide6.QtCore import QMimeData
        from flograph.ui.image_paste import clipboard_image_bytes
        mime = QMimeData()
        mime.setImageData(_solid(8, 8))
        data, suffix = clipboard_image_bytes(mime)
        assert suffix == ".png"
        assert data.startswith(b"\x89PNG")

    def test_no_image_returns_none(self):
        from PySide6.QtCore import QMimeData
        from flograph.ui.image_paste import clipboard_image_bytes
        mime = QMimeData()
        mime.setText("just some text")
        assert clipboard_image_bytes(mime) is None


class TestSaveImageBytes:
    def test_is_content_addressed(self, tmp_path):
        from flograph.ui.image_paste import save_image_bytes
        first = save_image_bytes(b"abc", ".png", tmp_path)
        second = save_image_bytes(b"abc", ".png", tmp_path)
        assert first == second                       # same bytes, same file
        assert len(list(tmp_path.iterdir())) == 1    # written once

    def test_different_bytes_get_different_files(self, tmp_path):
        from flograph.ui.image_paste import save_image_bytes
        assert (save_image_bytes(b"abc", ".png", tmp_path)
                != save_image_bytes(b"xyz", ".png", tmp_path))

    def test_leaves_no_partial_file_behind(self, tmp_path):
        from flograph.ui.image_paste import save_image_bytes
        save_image_bytes(ANIMATED_GIF, ".gif", tmp_path)
        assert not list(tmp_path.glob("*.part"))


class TestPasteOntoCanvas:
    @pytest.fixture
    def window(self, qtbot, registry, tmp_path, monkeypatch):
        # never touch the real profile: the paste path writes files
        monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path / "profile"))
        from flograph.ui.mainwindow import MainWindow
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def _put_image_on_clipboard(self):
        from PySide6.QtCore import QMimeData
        from PySide6.QtWidgets import QApplication
        mime = QMimeData()
        mime.setImageData(_solid(20, 20))
        QApplication.clipboard().setMimeData(mime)

    def test_paste_creates_an_image_node_pointing_at_a_saved_file(self, window):
        import os
        self._put_image_on_clipboard()
        assert window._paste_clipboard_image() is True
        assert len(window.graph.nodes) == 1
        node = next(iter(window.graph.nodes.values()))
        assert node.type_id == IMAGE_TYPE
        assert os.path.isfile(node.params["path"])

    def test_paste_is_one_undo_step(self, window):
        self._put_image_on_clipboard()
        window._paste_clipboard_image()
        window.undo_stack.undo()
        assert len(window.graph.nodes) == 0

    def test_paste_with_no_image_on_the_clipboard_does_nothing(self, window):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText("not a picture")
        assert window._paste_clipboard_image() is False
        assert len(window.graph.nodes) == 0

    def test_copied_nodes_still_paste_as_nodes(self, window, registry):
        """A picture on the clipboard must never hijack a node copy/paste."""
        from flograph.ui.commands import AddNodeCommand
        node = registry.instantiate("flograph.io.read_csv", pos=(0, 0))
        window.undo_stack.push(AddNodeCommand(window.graph, node))
        window.scene.node_items[node.id].setSelected(True)
        window._copy_selection()
        window._paste()
        types = {n.type_id for n in window.graph.nodes.values()}
        assert types == {"flograph.io.read_csv"}
        assert len(window.graph.nodes) == 2
