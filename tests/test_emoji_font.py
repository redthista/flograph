"""An emoji typed into a conditional-formatting rule paints as itself.

The bug these guard: Qt draws *nothing* for a colour emoji when the font it
resolves to cannot be rasterised — the cell reserves the width and comes
out blank, which reads as the rule not working. `ui.emoji_font` finds a
family that does draw it.

Machines without any working emoji font are a real configuration (a bare
container), and there the honest answer is a blank glyph — those tests skip
rather than fail.
"""
import pandas as pd
import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontInfo, QImage, QPainter

from flograph.core.table_format import parse_rules
from flograph.ui.data_table import DataTableView
from flograph.ui.emoji_font import (
    PROBE_GLYPH, emoji_family, paints, with_emoji,
)
from flograph.ui.inspector.pandas_model import PandasModel

pytestmark = pytest.mark.usefixtures("qapp")


def _needs_emoji_font():
    if emoji_family() is None:
        pytest.skip("no emoji font on this machine that Qt can rasterise")


def _ink(image: QImage, rect: QRect, background: int) -> int:
    """Pixels inside `rect` that are not `background` — the cell's own fill,
    sampled from a part of the cell nothing is drawn in."""
    return sum(image.pixel(x, y) != background
               for x in range(rect.left(), rect.right())
               for y in range(rect.top(), rect.bottom()))


class TestFontProbe:
    def test_the_chosen_family_really_draws_the_glyph(self):
        _needs_emoji_font()
        assert paints(QFont(emoji_family()), PROBE_GLYPH)

    def test_an_emoji_paints_once_the_fallback_is_on_the_font(self, qapp):
        _needs_emoji_font()
        assert paints(with_emoji(qapp.font()), PROBE_GLYPH)

    def test_ordinary_text_keeps_its_own_font(self, qapp):
        """The fallback goes on the *end* of the family list — the UI font
        still sets the words, or a table of numbers would come out in an
        emoji face."""
        base = qapp.font()
        assert QFontInfo(with_emoji(base)).family() == QFontInfo(base).family()

    def test_a_font_that_can_already_draw_emoji_is_returned_untouched(self):
        _needs_emoji_font()
        native = QFont(emoji_family())
        assert with_emoji(native) is native

    def test_paints_is_false_for_a_blank_string(self, qapp):
        assert not paints(qapp.font(), " ")


class TestTableDelegate:
    """The whole point: an `iconmap` rule with an emoji leaves ink in the
    cell's icon box, where before the fix it left an empty gap."""

    def _icon_ink(self, qtbot, rules_text) -> int:
        """Ink in the `flag` cell of row 0.

        `flag` holds an empty string, so the only thing that can put a mark
        in that cell is the rule's icon — no value text to mistake for one.
        """
        frame = pd.DataFrame({"sla": ["breach"], "flag": [""]})
        view = DataTableView()
        view.setModel(PandasModel(frame, rules=parse_rules(rules_text)))
        view.setColumnWidth(1, 120)
        view.resize(320, 90)
        qtbot.addWidget(view)
        # the viewport, not the widget: visualRect is in viewport coordinates
        image = view.viewport().grab().toImage()
        cell = view.visualRect(view.model().index(0, 1))
        box = cell.adjusted(2, 2, -2, -2)
        # the far end of the cell: same fill, nothing drawn on it
        background = image.pixel(cell.right() - 4, cell.center().y())
        return _ink(image, box, background)

    def test_an_emoji_icon_is_drawn(self, qtbot):
        _needs_emoji_font()
        assert self._icon_ink(
            qtbot, "flag iconmap sla: breach=\U0001f525 red") > 0

    def test_a_plain_glyph_icon_is_still_drawn(self, qtbot):
        assert self._icon_ink(qtbot, "flag iconmap sla: breach=✗ red") > 0

    def test_the_measurement_sees_nothing_without_an_icon_rule(self, qtbot):
        """Sanity check on the measurement itself: what the two tests above
        count is the glyph, and an empty cell really does read as empty."""
        assert self._icon_ink(qtbot, "sla format s") == 0


class TestReportDocument:
    def test_a_report_document_can_draw_an_emoji(self):
        """A rule's icon has to survive into the PDF as well as the grid."""
        _needs_emoji_font()
        from flograph.ui.report.render import _document

        document = _document()
        assert paints(document.defaultFont(), PROBE_GLYPH)

    def test_a_report_table_renders_its_emoji_icon(self):
        from flograph.core.table_html import frame_to_html
        from flograph.ui.report.render import REPORT_CSS, _document

        _needs_emoji_font()
        frame = pd.DataFrame({"sla": ["breach"], "growth": [-4]})
        html = frame_to_html(
            frame, parse_rules("growth iconmap sla: breach=\U0001f525 red"),
            [], max_rows=10, width=300)
        document = _document()
        document.setDefaultStyleSheet(REPORT_CSS)
        document.setHtml(html)
        document.setTextWidth(320)

        image = QImage(320, int(document.size().height()) + 4,
                       QImage.Format_RGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        document.drawContents(painter)
        painter.end()
        # the fire is the only red thing in the table
        reds = sum(QColor(image.pixel(x, y)).red()
                   > QColor(image.pixel(x, y)).blue() + 40
                   for x in range(image.width())
                   for y in range(image.height()))
        assert reds > 0


class TestWizard:
    def test_the_icon_field_can_show_what_was_typed(self, qtbot):
        from flograph.ui.properties.table_rule_wizard import RuleBuilder

        _needs_emoji_font()
        builder = RuleBuilder(["sla", "growth"])
        qtbot.addWidget(builder)
        field = builder._map.cellWidget(0, 1)
        assert paints(field.font(), PROBE_GLYPH)

    def test_the_rule_preview_can_show_what_was_typed(self, qtbot):
        from flograph.ui.properties.table_rule_wizard import RuleBuilder

        _needs_emoji_font()
        builder = RuleBuilder(["sla", "growth"])
        qtbot.addWidget(builder)
        assert paints(builder._preview.font(), PROBE_GLYPH)
