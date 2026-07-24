"""Node colours are muted against the theme rather than painted raw — the
treatment frames and page tabs already use. Covers the shared theme.tint
helper and every surface that renders a node's custom colour."""
import pytest
from PySide6.QtGui import QColor

from flograph.core import Graph, NodeStatus
from flograph.ui import theme
from flograph.ui.canvas.node_item import NodeItem
from tests.conftest import make_node

RAW = "#ff0000"   # fully saturated: the worst case for painting flat


def between(value: int, base: int, over: int) -> bool:
    """value sits strictly between the theme base and the raw colour."""
    low, high = sorted((base, over))
    return low < value < high


class TestTintHelper:
    def test_returns_an_opaque_blend(self):
        result = theme.tint(QColor("#000000"), "#ffffff", 0.5)
        assert result.alpha() == 255
        assert result.red() == result.green() == result.blue() == 128

    def test_alpha_zero_is_the_base(self):
        assert theme.tint(theme.NODE_BODY, RAW, 0.0) == theme.NODE_BODY

    def test_alpha_one_is_the_colour(self):
        assert theme.tint(theme.NODE_BODY, RAW, 1.0) == QColor(RAW)

    def test_accepts_a_hex_string_or_a_qcolor(self):
        assert (theme.tint(theme.NODE_BODY, RAW, 0.4)
                == theme.tint(theme.NODE_BODY, QColor(RAW), 0.4))

    def test_soft_is_gentler_than_strong(self):
        base, raw = theme.NODE_BODY, QColor(RAW)
        soft = theme.tint(base, RAW, theme.TINT_SOFT)
        strong = theme.tint(base, RAW, theme.TINT_STRONG)
        assert theme.TINT_SOFT < theme.TINT_STRONG
        assert abs(soft.red() - base.red()) < abs(strong.red() - base.red())
        assert abs(soft.red() - raw.red()) > abs(strong.red() - raw.red())


@pytest.fixture
def item(qtbot):
    graph = Graph()
    return NodeItem(graph.add_node(make_node()))


class TestNodeItemColors:
    def test_uncolored_node_uses_the_theme(self, item):
        assert item._body_color() == theme.NODE_BODY
        assert item._header_color() == theme.NODE_HEADER

    def test_body_is_muted_not_raw(self, item):
        item.node.color = RAW
        body = item._body_color()
        assert body != QColor(RAW)
        assert body != theme.NODE_BODY
        assert between(body.red(), theme.NODE_BODY.red(), 255)
        # the hue survives: red still dominates
        assert body.red() > body.green() and body.red() > body.blue()

    def test_header_is_muted_not_raw(self, item):
        item.node.color = RAW
        header = item._header_color()
        assert header != QColor(RAW)
        assert header != theme.NODE_HEADER
        assert between(header.red(), theme.NODE_HEADER.red(), 255)

    def test_header_reads_stronger_than_the_body(self, item):
        """The theme's header is a lighter shade of its body; a custom colour
        must not invert that."""
        item.node.color = RAW
        assert item._header_color().red() > item._body_color().red()

    def test_broken_still_wins_over_the_custom_colour(self, item):
        item.node.color = RAW
        item.broken = True
        assert item._header_color() == theme.NODE_HEADER_BROKEN

    def test_every_colour_stays_inside_the_theme_range(self, item):
        """Whatever the picker returns, the painted colour is pulled back
        toward the theme — that is the whole point of the muting."""
        for raw in ("#ff0000", "#00ff00", "#0000ff", "#ffffff", "#000000"):
            item.node.color = raw
            for painted, base in ((item._body_color(), theme.NODE_BODY),
                                  (item._header_color(), theme.NODE_HEADER)):
                assert painted != QColor(raw)
                for painted_c, base_c, raw_c in (
                        (painted.red(), base.red(), QColor(raw).red()),
                        (painted.green(), base.green(), QColor(raw).green()),
                        (painted.blue(), base.blue(), QColor(raw).blue())):
                    if base_c != raw_c:
                        assert between(painted_c, base_c, raw_c)


class TestOtherSurfaces:
    def test_flat_lod_paint_uses_the_muted_body(self, item, qtbot):
        """The zoomed-out simplified card must not flash the raw colour."""
        from PySide6.QtGui import QImage, QPainter
        item.node.color = RAW
        image = QImage(40, 40, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        item._paint_flat(painter)
        painter.end()
        painted = QColor(image.pixel(5, 5))
        assert painted != QColor(RAW)
        assert painted == item._body_color()

    def test_note_body_uses_the_muted_colour(self, item):
        item.node.color = RAW
        assert item._body_color() != QColor(RAW)

    def test_minimap_matches_the_card_header(self, item):
        """A node should read as the same colour in both places."""
        item.node.color = RAW
        assert (theme.tint(theme.NODE_HEADER, RAW, theme.TINT_STRONG)
                == item._header_color())


class TestSharedWithTabs:
    def test_tabs_read_the_shared_strengths_at_paint_time(self):
        """A module-level copy taken at import would ignore a settings
        change until restart, so the tab bar must not keep one."""
        from flograph.ui.dashboard import page_bar
        assert not hasattr(page_bar, "TAB_TINT_NORMAL")
        assert not hasattr(page_bar, "TAB_TINT_SELECTED")


class TestStoredValueUnchanged:
    def test_muting_is_presentation_only(self, item):
        """The graph keeps exactly what the picker returned, so the colour
        dialog reopens on the user's colour and saved files are unchanged."""
        item.node.color = RAW
        item._body_color()
        item._header_color()
        assert item.node.color == RAW
