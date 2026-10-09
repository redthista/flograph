"""The grid's icons are drawn sharp: each glyph is vector-drawn at the size
it is shown at, and only at whole multiples of its 20-point design grid —
a 20 px glyph resampled to 16 or 24 smears every one-pixel line."""
import pytest
from PySide6.QtCore import QSize

from flograph.ui.spreadsheet.icons import GLYPHS, sheet_icon


def _image(name, size, ratio=1.0):
    return sheet_icon(name).pixmap(QSize(size, size), ratio).toImage()


@pytest.mark.parametrize("name", ["cut", "fmt_b", "filter", "freeze"])
def test_a_24px_slot_holds_the_exact_20px_glyph(qapp, name):
    small = _image(name, 20)
    large = _image(name, 24)
    assert large.width() == 24
    assert large.copy(2, 2, 20, 20) == small


def test_hidpi_draws_at_twice_the_grid(qapp):
    image = _image("cut", 20, 2.0)
    assert image.width() == 40 and image.devicePixelRatio() == 2.0


def test_every_glyph_renders(qapp):
    for name in GLYPHS:
        assert not _image(name, 20).isNull(), name


def test_disabled_is_dimmer(qapp):
    from PySide6.QtGui import QIcon
    normal = sheet_icon("cut").pixmap(QSize(20, 20), 1.0, QIcon.Normal)
    disabled = sheet_icon("cut").pixmap(QSize(20, 20), 1.0, QIcon.Disabled)

    def ink(pixmap):
        image = pixmap.toImage()
        return sum(image.pixelColor(x, y).alpha()
                   for x in range(20) for y in range(20))
    assert ink(disabled) < ink(normal) * 0.5
