"""Pictures in a table: base64 pasted into a rule, or read from a column.

Tested where each layer can be wrong on its own: recognising a picture
(core/images — a word is not one, a logo is), the rule (parsing, which
column it reads, the one it hides), the page (the `<img>` a report prints,
and the tile it has to draw itself) and the card (the model, the delegate's
pixels, the row's height), then the Rules dialog that writes it.
"""
import base64
import struct
import zlib

import pandas as pd
import pytest

from flograph.core import images
from flograph.core.table_format import (
    Decoration, abbreviate_pictures, column_matches, column_stats,
    evaluate_column, parse_rule_lines, parse_rules, rule_summary,
    spark_projection, style_payload, style_report)
from flograph.core.table_html import frame_to_html


def png(width, height, rgb=(200, 30, 30)):
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0,
                                         0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


RED = base64.b64encode(png(40, 20)).decode()           # 2:1
SQUARE = base64.b64encode(png(16, 16, (30, 30, 200))).decode()
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 12">'
       '<rect width="24" height="12" fill="#cc0000"/></svg>')

FRAME = pd.DataFrame({
    "name": ["Acme", "Globex", "Initech"],
    "logo": [RED, None, "no picture here"],
    "status": ["ok", "late", "ok"],
})


def styles(frame, text, column):
    rules = [r for r in parse_rules(text)
             if r.mode != "hide" and column_matches(r.columns, column)]
    return evaluate_column(frame[column], rules, column_stats(frame[column]),
                           frame=frame)


# ------------------------------------------------------ what is a picture

class TestRecognisingAPicture:
    def test_bare_base64_becomes_a_data_address(self):
        uri = images.picture_uri(RED)
        assert uri.startswith("data:image/png;base64,iVBOR")

    def test_a_data_address_is_one(self):
        assert images.picture_uri("data:image/png;base64," + RED)

    def test_the_url_safe_alphabet_is_turned_standard(self):
        safe = RED.replace("+", "-").replace("/", "_").rstrip("=")
        uri = images.picture_uri(safe)
        assert uri and "-" not in uri and "_" not in uri
        assert images.picture_dimensions(uri) == (40, 20)

    def test_a_wrapped_paste_is_still_one(self):
        wrapped = "\n".join(RED[i:i + 76] for i in range(0, len(RED), 76))
        assert images.picture_uri(wrapped)

    def test_raw_bytes_are_one(self):
        assert images.picture_uri(png(2, 2)).startswith("data:image/png")

    def test_svg_markup_is_one(self):
        uri = images.picture_uri(SVG)
        assert uri.startswith("data:image/svg+xml;base64,")
        assert images.picture_dimensions(uri) == (24.0, 12.0)

    @pytest.mark.parametrize("value", [
        "hello", "A" * 100, 12, 3.5, None, "a sentence with spaces in it",
        base64.b64encode(b"just some text, long enough to pass").decode(),
        "<b>not svg</b>" * 4])
    def test_everything_else_is_not(self, value):
        assert images.picture_uri(value) is None

    def test_dimensions_from_the_header(self):
        assert images.picture_dimensions(images.picture_uri(RED)) == (40, 20)
        gif = b"GIF89a" + struct.pack("<HH", 7, 9) + b"\x00" * 20
        assert images.picture_dimensions(images.to_data_uri(
            gif, "image/gif")) == (7, 9)

    def test_an_aspect_is_held_to_a_sensible_range(self):
        banner = base64.b64encode(png(400, 10)).decode()
        assert images.picture_aspect(images.picture_uri(banner)) == 5.0
        assert images.picture_aspect(images.picture_uri(RED)) == 2.0


# -------------------------------------------------------------- the rule

class TestParsing:
    def test_a_column_of_its_own_pictures(self):
        (rule,) = parse_rules("logo image")
        assert rule.mode == "image" and rule.source is None

    def test_every_option(self):
        (rule,) = parse_rules(
            "name image right 32px circle on white from logo hide")
        assert (rule.columns, rule.source, rule.glyph_where) == (
            ["name"], "logo", "right")
        assert rule.picture_size == 32 and rule.picture_shape == "circle"
        assert rule.picture_tile == "#ffffff" and rule.take_sources == "hide"

    def test_options_written_after_the_column_are_still_options(self):
        (rule,) = parse_rules("name image from logo hide circle on black 24px")
        assert rule.source == "logo" and rule.take_sources == "hide"
        assert rule.picture_shape == "circle" and rule.picture_size == 24
        assert rule.picture_tile == "#000000"

    def test_a_quoted_column_keeps_the_words(self):
        (rule,) = parse_rules('name image from "logo circle"')
        assert rule.source == "logo circle" and rule.picture_shape is None

    def test_picture_as_a_synonym(self):
        assert parse_rules("logo picture")[0].mode == "image"

    @pytest.mark.parametrize("text, words", [
        ("name image from", "needs the column"),
        ("logo image hide", "name it"),
        ("name image huge from logo", "don't understand 'huge'"),
        ("name image 2px from logo", "outside"),
        ("name image on from logo", "needs a colour"),
    ])
    def test_mistakes_say_what_is_wrong(self, text, words):
        (_raw, rule, error) = parse_rule_lines(text)[0]
        assert rule is None and words in error

    def test_a_column_called_image_is_still_a_column(self):
        assert parse_rules("hide image")[0].mode == "hide"
        assert parse_rules("image scale green")[0].columns == ["image"]

    def test_a_pasted_data_address_survives_the_commas_of_a_map(self):
        (rule,) = parse_rules(
            f"status iconmap circle: ok=data:image/png;base64,{RED}, "
            f"late=✗ red")
        assert set(rule.mapping) == {"ok", "late"}
        assert rule.mapping["ok"][0] == RED
        assert rule.picture_shape == "circle"

    def test_a_picture_as_a_highlight_icon(self):
        (rule,) = parse_rules(f"status = late => icon {SQUARE} right 28px "
                              f"amber circle")
        assert rule.glyph == SQUARE and rule.picture_size == 28
        assert rule.picture_shape == "circle" and rule.glyph_where == "right"

    def test_a_long_line_is_shortened_for_show(self):
        text = abbreviate_pictures(f"status = late => icon {RED}")
        assert RED not in text and "‹picture · " in text

    def test_the_summary_says_picture(self):
        (rule,) = parse_rules(f"status = late => icon {RED}")
        assert "a picture" in rule_summary(rule) and RED not in rule_summary(
            rule)
        (rule,) = parse_rules("name image circle from logo hide")
        assert rule_summary(rule) == (
            "name  ·  picture from “logo”, circle, that column hidden")

    def test_a_decoration_round_trips(self):
        d = Decoration(image=images.picture_uri(RED), where="right", size=30,
                       tile="#ffffff", shape="circle")
        assert Decoration.from_dict(d.to_dict()) == d


class TestEvaluation:
    def test_its_own_pictures_stand_in_for_the_text(self):
        cells = styles(FRAME, "logo image", "logo")
        assert cells[0].hide_value and cells[0].decorations[0].where == "in"
        assert cells[0].decorations[0].image.startswith("data:image/png")
        # a blank and a word are left to show as they are
        assert cells[1] is None and cells[2] is None

    def test_another_columns_picture_sits_beside_the_value(self):
        cells = styles(FRAME, "name image from logo", "name")
        assert not cells[0].hide_value
        assert cells[0].decorations[0].where == "left"

    def test_a_tile_is_rounded_unless_a_shape_is_named(self):
        (cell, *_rest) = styles(FRAME, "logo image on white", "logo")
        assert (cell.decorations[0].tile, cell.decorations[0].shape) == (
            "#ffffff", "rounded")

    def test_a_mapped_colour_is_the_tile_behind_a_picture(self):
        cells = styles(FRAME, f"status iconmap square: ok={SQUARE} green",
                       "status")
        mark = cells[0].decorations[0]
        assert mark.image and mark.tile == "#5cb85c" and mark.shape == "square"
        assert mark.text == ""

    def test_the_picture_column_is_hidden(self):
        _frame, _rules, hidden = spark_projection(
            FRAME, parse_rules("name image from logo hide"))
        assert hidden == ["logo"]

    def test_the_report_knows_the_column_it_reads(self):
        ok = style_payload({"format_rules": "name image from logo hide"})
        assert style_report(ok, FRAME) == []
        missing = style_payload({"format_rules": "name image from photo"})
        assert "photo" in " ".join(style_report(missing, FRAME))


# -------------------------------------------------------------- the page

class TestOnPaper:
    def test_a_picture_prints_its_own_shape(self):
        html = frame_to_html(FRAME, parse_rules("name image from logo hide"))
        assert f'src="{images.picture_uri(RED)}" width="26" height="13"' in html
        assert ">logo</th>" not in html

    def test_a_tile_is_css_with_a_marker_for_a_report(self):
        html = frame_to_html(FRAME, parse_rules("logo image circle on white"))
        assert "border-radius:" in html and "background-color:#ffffff" in html
        assert 'data-flograph-tile="#ffffff;circle"' in html

    def render(self, rules):
        from flograph.core import Graph, NodeRegistry
        from flograph.engine.cache import OutputCache
        from flograph.ui.report.render import render_report

        registry = NodeRegistry()
        registry.load_builtins()
        graph, cache = Graph(), OutputCache()
        node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
        graph.set_label(node.id, "Pics")
        cache.set(node.id, {"table": FRAME,
                            "style": style_payload({"format_rules": rules})},
                  0.0)
        return render_report("![[Pics]]", graph, cache).document.toHtml()

    @pytest.mark.usefixtures("qapp")
    def test_it_survives_the_report_pass(self):
        html = self.render("name image from logo hide")
        assert "@@flograph-spark" not in html
        assert "data:image/png;base64," in html

    @pytest.mark.usefixtures("qapp")
    def test_a_report_draws_the_tile_into_the_picture(self):
        """Qt's rich text drops border-radius, background and padding on an
        image, so the report paints them into a PNG of its own."""
        html = self.render("logo image circle on #00aa00 20px")
        assert "data-flograph-tile" not in html
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QColor, QImage
        import re
        src = re.search(r'src="data:image/png;base64,([^"]+)"', html)
        image = QImage.fromData(QByteArray(base64.b64decode(src.group(1))))
        assert not image.isNull()
        assert QColor.fromRgba(image.pixel(0, 0)).alpha() == 0      # cut
        edge = QColor.fromRgba(image.pixel(image.width() // 2, 2))
        assert (edge.red(), edge.green()) == (0, 170)                # tile
        middle = QColor.fromRgba(image.pixel(image.width() // 2,
                                             image.height() // 2))
        assert middle.red() > 150 and middle.green() < 80            # picture


# -------------------------------------------------------------- the card

@pytest.mark.usefixtures("qapp")
class TestOnTheCard:
    def model(self, text, frame=FRAME):
        from flograph.ui.inspector.pandas_model import PandasModel
        return PandasModel(frame, rules=parse_rules(text))

    def test_the_hidden_column_is_gone_and_the_text_is_not_shown(self):
        from PySide6.QtCore import Qt
        model = self.model("logo image")
        assert model.data(model.index(0, 1), Qt.DisplayRole) == ""
        assert model.data(model.index(0, 1), Qt.EditRole) == RED
        hidden = self.model("name image from logo hide")
        assert [hidden.headerData(c, Qt.Horizontal)
                for c in range(hidden.columnCount())] == ["name", "status"]

    def grab(self, qtbot, text, column, width=160, rows=None):
        from flograph.ui.data_table import DataTableView
        view = DataTableView()
        view.setModel(self.model(text))
        view.setColumnWidth(column, width)
        view.resize(600, 200)
        view.show()
        qtbot.addWidget(view)
        qtbot.wait(20)
        return view, view.viewport().grab().toImage(), view.visualRect(
            view.model().index(0, column))

    @staticmethod
    def reds(image, cell):
        from PySide6.QtGui import QColor
        return [(x, y) for x in range(cell.left(), cell.right())
                for y in range(cell.top(), cell.bottom())
                if QColor(image.pixel(x, y)).red() > 150
                and QColor(image.pixel(x, y)).green() < 80]

    def test_the_picture_is_painted(self, qtbot):
        _view, image, cell = self.grab(qtbot, "logo image", 1)
        assert self.reds(image, cell), "no picture was painted"

    def test_a_circle_cuts_the_corners(self, qtbot):
        _view, image, cell = self.grab(qtbot, "logo image 60px circle", 1)
        points = self.reds(image, cell)
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        left, top, bottom = min(xs), min(ys), max(ys)
        # the picture's own top-left corner is outside the stadium it is cut to
        assert (left, top) not in points and (left, bottom) not in points

    def test_a_sized_picture_makes_its_row_taller(self, qtbot):
        from flograph.ui.data_table import DataTableView
        plain, grown = DataTableView(), DataTableView()
        for view, rules in ((plain, "logo image"), (grown, "logo image 48px")):
            qtbot.addWidget(view)
            view.setModel(self.model(rules))
            view.resize(600, 200)
            view.show()
        qtbot.waitUntil(lambda: grown.rowHeight(0) >= 48 > plain.rowHeight(0),
                        timeout=2000)

    def test_a_picture_column_is_as_wide_as_its_pictures(self, qtbot):
        from flograph.ui.data_table import DataTableView
        view = DataTableView()
        qtbot.addWidget(view)
        view.setModel(self.model("logo image 40px"))
        assert view.columnWidth(1) >= 80              # 40px tall, 2:1

    def test_a_decoded_picture_is_kept(self):
        from flograph.ui.table_delegate import picture_pixmap
        uri = images.picture_uri(RED)
        assert picture_pixmap(uri, 20, 10) is picture_pixmap(uri, 20, 10)
        assert picture_pixmap("data:image/png;base64,AAAA", 20, 10) is None


# ------------------------------------------------------------ the dialog

@pytest.mark.usefixtures("qapp")
class TestTheRulesDialog:
    COLUMNS = ["name", "logo", "status"]

    def test_the_pictures_page_writes_a_line_that_comes_back(self, qtbot):
        from flograph.ui.properties.table_rule_wizard import (K_PICTURE,
                                                              RuleBuilder)
        dialog = RuleBuilder(self.COLUMNS)
        qtbot.addWidget(dialog)
        dialog._kind.setCurrentIndex(K_PICTURE)
        dialog._col_edit.setText("name")
        dialog._pic_from.setCurrentIndex(dialog._pic_from.findData("logo"))
        dialog._pic_size.setValue(32)
        dialog._pic_shape.setCurrentIndex(dialog._pic_shape.findData("circle"))
        dialog._pic_tile.set_value("white")
        dialog._pic_hide.setChecked(True)
        line = dialog.line()
        assert line == "name image 32px circle on white from logo hide"
        again = RuleBuilder(self.COLUMNS, rule=parse_rules(line)[0])
        qtbot.addWidget(again)
        assert again.line() == line

    def test_hide_needs_a_picture_column(self, qtbot):
        from flograph.ui.properties.table_rule_wizard import (K_PICTURE,
                                                              RuleBuilder)
        dialog = RuleBuilder(self.COLUMNS)
        qtbot.addWidget(dialog)
        dialog._kind.setCurrentIndex(K_PICTURE)
        dialog._col_edit.setText("logo")
        assert dialog.line() == "logo image"
        assert not dialog._pic_hide.isEnabled()

    def test_a_picture_pasted_into_the_map_goes_in_as_bare_base64(self, qtbot):
        from PySide6.QtWidgets import QTableWidgetItem

        from flograph.ui.properties.table_rule_wizard import (K_ICONS,
                                                              RuleBuilder)
        dialog = RuleBuilder(self.COLUMNS)
        qtbot.addWidget(dialog)
        dialog._kind.setCurrentIndex(K_ICONS)
        dialog._icon_style.setCurrentIndex(dialog._icon_style.findData("map"))
        dialog._col_edit.setText("status")
        dialog._map.setItem(0, 0, QTableWidgetItem("ok"))
        dialog._map.cellWidget(0, 1).setText("data:image/png;base64," + RED)
        dialog._map.setItem(1, 0, QTableWidgetItem("late"))
        dialog._map.cellWidget(1, 1).setText(SVG)
        line = dialog.line()
        assert "data:" not in line and "<svg" not in line
        (rule,) = parse_rules(line)
        assert images.picture_uri(rule.mapping["ok"][0])
        assert images.picture_uri(rule.mapping["late"][0]).startswith(
            "data:image/svg+xml")
        assert dialog._map.cellWidget(0, 1).actions()          # a preview
        assert RED not in dialog._preview.text()

    def test_editing_a_map_rule_raises_nothing(self, qtbot):
        """Loading a map adds rows, and a row's item was set — firing
        cellChanged — before its editors existed."""
        import sys
        from flograph.ui.properties.table_rule_wizard import RuleBuilder
        errors = []
        hook, sys.excepthook = sys.excepthook, lambda *a: errors.append(a)
        try:
            (rule,) = parse_rules(f"status iconmap: ok={RED}, late=✗ red")
            dialog = RuleBuilder(self.COLUMNS, rule=rule)
            qtbot.addWidget(dialog)
        finally:
            sys.excepthook = hook
        assert errors == []
        assert parse_rules(dialog.line())[0].mapping == rule.mapping

    def cell(self, qtbot):
        from flograph.ui.properties.table_rule_wizard import (K_ICONS,
                                                              RuleBuilder)
        dialog = RuleBuilder(self.COLUMNS)
        qtbot.addWidget(dialog)
        dialog._kind.setCurrentIndex(K_ICONS)
        dialog._icon_style.setCurrentIndex(dialog._icon_style.findData("map"))
        return dialog, dialog._map.cellWidget(0, 1)

    def test_a_copied_picture_pastes_in_as_a_small_icon(self, qtbot):
        from PySide6.QtCore import QMimeData, Qt
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication
        big = QImage(800, 400, QImage.Format_ARGB32)
        big.fill(Qt.red)
        mime = QMimeData()
        mime.setImageData(big)
        QApplication.clipboard().setMimeData(mime)
        _dialog, edit = self.cell(qtbot)
        edit.setFocus()
        qtbot.keyClick(edit, Qt.Key_V, Qt.ControlModifier)
        uri = images.picture_uri(edit.text())
        assert uri is not None
        assert max(images.picture_dimensions(uri)) == 128
        assert images.picture_dimensions(uri) == (128, 64)

    def test_copied_text_still_pastes_as_text(self, qtbot):
        from PySide6.QtCore import QMimeData, Qt
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication
        mime = QMimeData()
        mime.setText("✓")
        # an office app puts a rendering of the copied words beside them
        rendering = QImage(40, 20, QImage.Format_ARGB32)
        rendering.fill(Qt.white)
        mime.setImageData(rendering)
        QApplication.clipboard().setMimeData(mime)
        _dialog, edit = self.cell(qtbot)
        edit.setFocus()
        qtbot.keyClick(edit, Qt.Key_V, Qt.ControlModifier)
        assert edit.text() == "✓"


class TestIconSizedPictures:
    @pytest.mark.usefixtures("qapp")
    def test_a_big_picture_is_shrunk_and_a_small_one_kept(self):
        from flograph.ui.image_paste import icon_picture
        shrunk = icon_picture(png(1000, 250))
        assert images.picture_dimensions(shrunk) == (128, 32)
        assert images.picture_dimensions(icon_picture(png(20, 10))) == (20, 10)

    @pytest.mark.usefixtures("qapp")
    def test_svg_is_kept_as_it_is(self):
        from flograph.ui.image_paste import icon_picture
        uri = icon_picture(SVG.encode())
        assert base64.b64decode(uri.split(",", 1)[1]).decode() == SVG

    @pytest.mark.usefixtures("qapp")
    def test_pasted_base64_text_is_shrunk_too(self):
        from PySide6.QtCore import QMimeData
        from flograph.ui.image_paste import icon_source
        mime = QMimeData()
        mime.setText(base64.b64encode(png(600, 600)).decode())
        assert images.picture_dimensions(icon_source(mime)) == (128, 128)
        words = QMimeData()
        words.setText("just words")
        assert icon_source(words) is None

    @pytest.mark.usefixtures("qapp")
    def test_a_copied_picture_file(self, tmp_path):
        from PySide6.QtCore import QMimeData, QUrl
        from flograph.ui.image_paste import icon_source
        path = tmp_path / "logo.png"
        path.write_bytes(png(300, 300))
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        mime.setText(str(path))
        assert images.picture_dimensions(icon_source(mime)) == (128, 128)


class TestReportGridLines:
    """A report cell with a style of its own — a `height`'s padding, a fill —
    lost its grid lines: Qt took the cell's style over the stylesheet's
    border width."""

    def test_a_styled_cell_repeats_its_border(self):
        import re
        html = frame_to_html(FRAME, parse_rules("height 30"))
        cells = re.findall(r"<td[^>]*>", html)
        assert cells and all("border:1px solid #999" in c for c in cells)

    def test_a_plain_cell_is_left_to_the_stylesheet(self):
        import re
        html = frame_to_html(FRAME, parse_rules("status format x"))
        assert not any("style=" in c for c in re.findall(r"<td[^>]*>", html))

    @pytest.mark.usefixtures("qapp")
    def test_the_lines_survive_the_report(self):
        import re
        html = TestOnPaper().render("height 30\nstatus = late => bg red")
        cells = re.findall(r"<td([^>]*)>", html)
        assert cells and all("border-top:1px" in c for c in cells)
