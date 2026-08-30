"""Node marks — the drawn glyph inside a compact node's square.

The marks are QPainterPath rather than typed characters for the reason the
Visuals list learned the hard way (see TestVisualGlyphs there): a glyph can
measure fine and paint nothing. Drawing is not immune to that either — a mark
whose path is degenerate, or whose coordinates land outside the rect, is just
as invisible — so every one of them is painted and its ink counted.
"""
import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QUndoStack

from flograph.core import Graph
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.ui.canvas import NodeGraphScene, marks
from flograph.ui.canvas.node_item import card_kind

BACKGROUND = QColor("#2a2c33")
FOREGROUND = QColor("#e5e7eb")
# The size a mark is actually drawn at on the canvas: a 60px square inset by
# COMPACT_MARK_INSET on each side. If it does not read here it does not read.
CANVAS_SIZE = 28


def ink(name: str, size: int = CANVAS_SIZE) -> int:
    """Pixels a mark changes when painted onto a flat background."""
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(BACKGROUND)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    drawn = marks.draw(name, painter, QRectF(0, 0, size, size), FOREGROUND)
    painter.end()
    if not drawn:
        return -1
    return sum(1 for x in range(size) for y in range(size)
               if image.pixelColor(x, y) != BACKGROUND)


class TestTheLibrary:
    def test_every_listed_mark_can_be_drawn(self, qapp):
        for name in marks.MARK_NAMES:
            assert ink(name) > 0, f"{name} painted nothing"

    def test_marks_stay_legible_at_swatch_size(self, qapp):
        for name in marks.MARK_NAMES:
            assert ink(name, 16) > 0, f"{name} vanishes in the picker"

    def test_no_mark_is_a_blob_or_a_speck(self, qapp):
        # a mark covering almost none or almost all of its box is a bug in
        # the path, not a design choice
        for name in marks.MARK_NAMES:
            coverage = ink(name) / (CANVAS_SIZE ** 2)
            assert 0.05 < coverage < 0.75, f"{name} covers {coverage:.0%}"

    def test_an_unknown_name_draws_nothing_and_says_so(self, qapp):
        image = QImage(28, 28, QImage.Format_ARGB32)
        image.fill(BACKGROUND)
        painter = QPainter(image)
        assert marks.draw("no-such-mark", painter,
                          QRectF(0, 0, 28, 28), FOREGROUND) is False
        painter.end()
        assert all(image.pixelColor(x, y) == BACKGROUND
                   for x in range(28) for y in range(28))

    def test_every_name_has_a_picker_label(self):
        assert set(marks.MARK_LABELS) == set(marks.MARK_NAMES)

    def test_category_defaults_all_exist(self):
        for category, name in marks.CATEGORY_MARKS.items():
            assert name in marks.MARK_NAMES, category
        assert marks.FALLBACK_MARK in marks.MARK_NAMES


class TestResolution:
    def test_every_plain_builtin_resolves_to_a_drawable_mark(
            self, qapp, registry):
        seen = 0
        for spec in registry.all():
            node = registry.instantiate(spec.type_id)
            if card_kind(node) is not None:
                continue   # cards have no square to put a mark in
            seen += 1
            assert ink(marks.mark_for(node)) > 0, spec.type_id
        assert seen > 20, "expected the whole transform/io library here"

    def test_the_category_decides_by_default(self, registry):
        cases = {
            "flograph.transform.sort": "arrows",
            "flograph.io.read_csv": "page",
            "flograph.util.constant": "dot",
            "flograph.scripting.python_script": "brackets",
        }
        for type_id, expected in cases.items():
            assert marks.mark_for(registry.instantiate(type_id)) == expected

    def test_an_override_wins_over_the_category(self, registry):
        node = registry.instantiate("flograph.transform.sort")
        node.mark = "funnel"
        assert marks.mark_for(node) == "funnel"

    def test_an_override_naming_a_mark_we_no_longer_ship_degrades(
            self, registry):
        node = registry.instantiate("flograph.transform.sort")
        node.mark = "retired-in-some-later-version"
        assert marks.mark_for(node) == "arrows"

    def test_an_unknown_category_falls_back(self):
        # A locally parsed spec, not a registry one: specs are shared by
        # every instance of their type and the registry fixture is
        # session-scoped, so renaming a builtin's category here would leak
        # into every later test in the run.
        from flograph.core import NodeInstance, parse_spec
        node = NodeInstance.create(parse_spec(
            'NODE = {"label": "Odd", "category": "Something Nobody Has "\n'
            '        "Heard Of", "inputs": [], "outputs": []}\n'
            'def run(ctx):\n    return None\n', "test.odd"))
        assert marks.mark_for(node) == marks.FALLBACK_MARK


class TestPersistence:
    def test_a_mark_survives_save_and_load(self, registry):
        graph = Graph()
        node = registry.instantiate("flograph.transform.sort")
        graph.add_node(node)
        graph.set_mark(node.id, "funnel", "")
        restored = graph_from_dict(graph_to_dict(graph), registry)
        assert restored.nodes[node.id].mark == "funnel"
        assert restored.nodes[node.id].mark_text == ""

    def test_mark_text_survives_save_and_load(self, registry):
        graph = Graph()
        node = registry.instantiate("flograph.util.constant")
        graph.add_node(node)
        graph.set_mark(node.id, "", "2024")
        restored = graph_from_dict(graph_to_dict(graph), registry)
        assert restored.nodes[node.id].mark_text == "2024"

    def test_a_file_written_before_marks_existed_loads_clean(self, registry):
        graph = Graph()
        node = registry.instantiate("flograph.transform.sort")
        graph.add_node(node)
        data = graph_to_dict(graph)
        for entry in data["graph"]["nodes"]:
            entry.pop("mark", None)
            entry.pop("mark_text", None)
        restored = graph_from_dict(data, registry)
        assert restored.nodes[node.id].mark == ""
        assert restored.nodes[node.id].mark_text == ""


def paint(item) -> QImage:
    """Render one node item, so the lazy bits (a mark image's decode, an
    animation's QMovie) actually happen."""
    canvas = QImage(200, 200, QImage.Format_ARGB32)
    canvas.fill(BACKGROUND)
    painter = QPainter(canvas)
    item.scene().render(painter)
    painter.end()
    return canvas


def _still(tmp_path, size=(1200, 900)):
    path = tmp_path / "big.png"
    image = QImage(*size, QImage.Format_ARGB32)
    image.fill(QColor("#7c6cf6"))
    image.save(str(path))
    return path


def _animated(tmp_path, frames=4, size=96):
    """A real animated GIF. Written with Pillow because Qt has no GIF
    writer — which is also why an animated mark is stored as its original
    bytes rather than being downscaled."""
    PIL = pytest.importorskip("PIL")
    from PIL import Image, ImageDraw
    path = tmp_path / "anim.gif"
    images = []
    for i in range(frames):
        frame = Image.new("RGB", (size, size), (24, 25, 30))
        ImageDraw.Draw(frame).ellipse(
            (8 + i * 4, 8, size - 8 - i * 4, size - 8),
            fill=(240 - i * 40, 80 + i * 40, 120))
        images.append(frame.convert("P", palette=Image.ADAPTIVE))
    images[0].save(str(path), save_all=True, append_images=images[1:],
                   duration=120, loop=0)
    return path


class TestImageMarks:
    def test_a_big_still_is_scaled_down_and_re_encoded(self, qapp, tmp_path):
        from flograph.core.images import resolve_source
        uri = marks.encode_mark_image(str(_still(tmp_path)))
        data, mime, _path = resolve_source(uri)
        image = QImage()
        image.loadFromData(data)
        assert mime == "image/png"
        assert max(image.width(), image.height()) == marks.MARK_IMAGE_MAX_PX
        assert image.width() == 128 and image.height() == 96  # aspect kept
        # small enough to live inside a project file without bloating it
        assert len(data) < 50_000

    def test_a_small_still_is_not_upscaled(self, qapp, tmp_path):
        from flograph.core.images import resolve_source
        uri = marks.encode_mark_image(str(_still(tmp_path, (40, 40))))
        data, _mime, _path = resolve_source(uri)
        image = QImage()
        image.loadFromData(data)
        assert (image.width(), image.height()) == (40, 40)

    def test_an_animation_is_kept_as_it_is(self, qapp, tmp_path):
        from flograph.core.images import resolve_source
        path = _animated(tmp_path)
        uri = marks.encode_mark_image(str(path))
        data, mime, _path = resolve_source(uri)
        assert mime == "image/gif"
        assert data == path.read_bytes()

    def test_an_oversized_animation_is_refused_with_a_reason(
            self, qapp, tmp_path, monkeypatch):
        monkeypatch.setattr(marks, "MARK_IMAGE_MAX_BYTES", 10)
        with pytest.raises(marks.MarkImageError) as excinfo:
            marks.encode_mark_image(str(_animated(tmp_path)))
        assert "KB" in str(excinfo.value)

    def test_a_file_that_is_not_an_image_is_refused(self, qapp, tmp_path):
        path = tmp_path / "notes.txt"
        path.write_text("this is not a picture")
        with pytest.raises(marks.MarkImageError):
            marks.encode_mark_image(str(path))

    def test_the_node_draws_the_picture(self, qtbot, registry, tmp_path):
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        node = registry.instantiate("flograph.transform.sort")
        graph.add_node(node)
        scene.push_node_mark(node.id, "", "",
                             marks.encode_mark_image(str(_still(tmp_path))))
        item = scene.node_items[node.id]
        image = item._mark_card_image()
        assert image.has_content() and not image.error

    def test_an_animation_plays_and_pauses_when_unwatched(
            self, qtbot, registry, tmp_path):
        from PySide6.QtGui import QMovie
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        node = registry.instantiate("flograph.transform.sort")
        graph.add_node(node)
        scene.push_node_mark(node.id, "", "",
                             marks.encode_mark_image(str(_animated(tmp_path))))
        item = scene.node_items[node.id]
        image = item._mark_card_image()
        assert image.is_animated()
        # Nothing is decoded until the mark is first painted — the same
        # laziness that lets a project full of images open zoomed out without
        # reading a pixel — so the movie does not exist before this.
        assert image._movie is None
        paint(item)
        assert image._movie.state() == QMovie.Running

        item.set_lod(True)          # zoomed out past the detail threshold
        assert image._movie.state() == QMovie.Paused
        item.set_lod(False)
        assert image._movie.state() == QMovie.Running

        graph.set_preview_enabled(node.id, False)
        assert image._movie.state() == QMovie.Paused

    def test_removing_the_node_stops_the_animation(self, qtbot, registry,
                                                   tmp_path):
        """A QMovie still delivering frames into a deleted item is a crash,
        not a leak."""
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        node = registry.instantiate("flograph.transform.sort")
        graph.add_node(node)
        scene.push_node_mark(node.id, "", "",
                             marks.encode_mark_image(str(_animated(tmp_path))))
        item = scene.node_items[node.id]
        item._mark_card_image()
        graph.remove_node(node.id)
        assert item._mark_image is None

    def test_a_picture_beats_text_and_a_mark(self, qtbot, registry, tmp_path):
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        node = registry.instantiate("flograph.transform.sort")
        graph.add_node(node)
        uri = marks.encode_mark_image(str(_still(tmp_path)))
        graph.set_mark(node.id, "funnel", "42", uri)
        item = scene.node_items[node.id]
        assert item._mark_card_image().has_content()

    def test_it_survives_a_round_trip(self, registry, qapp, tmp_path):
        graph = Graph()
        node = registry.instantiate("flograph.transform.sort")
        graph.add_node(node)
        uri = marks.encode_mark_image(str(_still(tmp_path)))
        graph.set_mark(node.id, "", "", uri)
        restored = graph_from_dict(graph_to_dict(graph), registry)
        assert restored.nodes[node.id].mark_image == uri


class TestLibraryIcons:
    def test_every_row_carries_its_category_mark(self, qtbot, registry):
        from PySide6.QtCore import QSettings
        from flograph.ui.canvas.palette import LibraryTree
        from flograph.ui.favorites import Favorites
        tree = LibraryTree(registry, Favorites(QSettings("flograph", "t")))
        qtbot.addWidget(tree)
        checked = 0
        for i in range(tree.topLevelItemCount()):
            section = tree.topLevelItem(i)
            for j in range(section.childCount()):
                child = section.child(j)
                if child.data(0, Qt.UserRole) is None:
                    continue   # a user-node group, not a node
                assert not child.icon(0).isNull()
                checked += 1
        assert checked > 20

    def test_the_icon_matches_what_the_node_will_wear(self, qapp, registry):
        from flograph.ui.canvas.palette import spec_icon
        spec = registry.get("flograph.transform.sort")
        assert marks.mark_for_category(spec.category) == "arrows"
        assert not spec_icon(spec).isNull()

    def test_icons_are_cached_rather_than_re_rasterised(self, qapp, registry):
        from flograph.ui.canvas.palette import spec_icon
        a = spec_icon(registry.get("flograph.transform.sort"))
        b = spec_icon(registry.get("flograph.transform.join"))
        assert a is b   # same category, same mark, one pixmap


class TestTheCommand:
    def _env(self, registry):
        graph = Graph()
        stack = QUndoStack()
        scene = NodeGraphScene(graph, stack, registry=registry)
        node = registry.instantiate("flograph.transform.sort")
        graph.add_node(node)
        return graph, stack, scene, node

    def test_setting_a_mark_undoes_and_redoes(self, qtbot, registry):
        _graph, stack, scene, node = self._env(registry)
        scene.push_node_mark(node.id, "funnel", "")
        assert (node.mark, node.mark_text) == ("funnel", "")
        stack.undo()
        assert (node.mark, node.mark_text) == ("", "")
        stack.redo()
        assert (node.mark, node.mark_text) == ("funnel", "")

    def test_consecutive_marks_merge_into_one_step(self, qtbot, registry):
        """The dialog applies live, so settling on a mark means pushing one
        per swatch tried. One decision should be one Ctrl+Z."""
        _graph, stack, scene, node = self._env(registry)
        scene.push_node_mark(node.id, "funnel", "")
        scene.push_node_mark(node.id, "overlap", "")
        scene.push_node_mark(node.id, "", "2024")
        assert stack.count() == 1
        assert (node.mark, node.mark_text) == ("", "2024")
        stack.undo()
        assert (node.mark, node.mark_text) == ("", "")

    def test_marks_on_different_nodes_stay_separate(self, qtbot, registry):
        graph, stack, scene, node = self._env(registry)
        other = registry.instantiate("flograph.transform.join")
        graph.add_node(other)
        scene.push_node_mark(node.id, "funnel", "")
        scene.push_node_mark(other.id, "overlap", "")
        assert stack.count() == 2
        stack.undo()
        assert other.mark == "" and node.mark == "funnel"

    def test_colours_do_not_merge(self, qtbot, registry):
        """Unlike the mark: a colour comes through a modal picker, so each is
        already one deliberate act rather than a swatch tried in passing."""
        _graph, stack, scene, node = self._env(registry)
        scene.push_node_color(node.id, "#ff0000")
        scene.push_node_color(node.id, "#00ff00")
        assert stack.count() == 2
        stack.undo()
        assert node.color == "#ff0000"


class TestTheMarkSection:
    """The mark half of the Appearance dialog. It applies live, so what the
    node ends up with *is* the assertion — there is no result to read back."""

    def _env(self, registry, type_id="flograph.transform.filter_rows"):
        from flograph.ui.canvas.appearance_dialog import AppearanceDialog
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        node = registry.instantiate(type_id)
        graph.add_node(node)
        return AppearanceDialog(scene, node.id), node, scene

    def _mark(self, node):
        return (node.mark, node.mark_text, node.mark_image)

    def test_opening_it_changes_nothing(self, qtbot, registry):
        dialog, node, scene = self._env(registry)
        qtbot.addWidget(dialog)
        assert self._mark(node) == ("", "", "")
        assert scene.undo_stack.count() == 0

    def test_it_opens_showing_the_mark_the_node_draws(self, qtbot, registry):
        dialog, node, scene = self._env(registry)
        qtbot.addWidget(dialog)
        scene.push_node_mark(node.id, "funnel", "", "")
        reopened, _n, _s = None, None, None
        from flograph.ui.canvas.appearance_dialog import AppearanceDialog
        reopened = AppearanceDialog(scene, node.id)
        qtbot.addWidget(reopened)
        assert reopened._mark_radio.isChecked()
        assert reopened._swatches.checkedButton().name == "funnel"

    def test_picking_a_swatch_applies_it(self, qtbot, registry):
        dialog, node, _scene = self._env(registry)
        qtbot.addWidget(dialog)
        next(b for b in dialog._swatches.buttons()
             if b.name == "overlap").click()
        assert self._mark(node) == ("overlap", "", "")

    def test_trying_marks_on_is_one_undo_step(self, qtbot, registry):
        """Live-apply would otherwise put sixteen entries on the stack for
        one decision; the command merges instead."""
        dialog, node, scene = self._env(registry)
        qtbot.addWidget(dialog)
        for name in ("overlap", "funnel", "sort_bars", "grid"):
            next(b for b in dialog._swatches.buttons()
                 if b.name == name).click()
        assert node.mark == "grid"
        assert scene.undo_stack.count() == 1
        scene.undo_stack.undo()
        assert self._mark(node) == ("", "", "")

    def test_typing_applies_as_text(self, qtbot, registry):
        dialog, node, _scene = self._env(registry)
        qtbot.addWidget(dialog)
        dialog._text_edit.setText("SQL")
        dialog._text_edit.textEdited.emit("SQL")
        assert self._mark(node) == ("", "SQL", "")

    def test_an_empty_text_box_means_the_default(self, qtbot, registry):
        dialog, node, _scene = self._env(registry)
        qtbot.addWidget(dialog)
        dialog._text_edit.setText("   ")
        dialog._text_edit.textEdited.emit("   ")
        assert self._mark(node) == ("", "", "")

    def test_switching_back_to_default_clears_the_mark(self, qtbot, registry):
        dialog, node, _scene = self._env(registry)
        qtbot.addWidget(dialog)
        next(b for b in dialog._swatches.buttons()
             if b.name == "funnel").click()
        dialog._default_radio.setChecked(True)
        assert self._mark(node) == ("", "", "")

    def test_the_text_field_is_capped(self, qtbot, registry):
        from flograph.ui.canvas.appearance_dialog import MARK_TEXT_MAX
        dialog, _node, _scene = self._env(registry)
        qtbot.addWidget(dialog)
        assert dialog._text_edit.maxLength() == MARK_TEXT_MAX

    def test_a_card_gets_no_mark_section_at_all(self, qtbot, registry):
        """A card has no square to put one in."""
        dialog, _node, _scene = self._env(registry, "flograph.viz.show_plot")
        qtbot.addWidget(dialog)
        assert not dialog._plain
        assert not hasattr(dialog, "_swatches")


class TestTheAppearanceDialog:
    def _env(self, registry, type_id="flograph.transform.filter_rows"):
        from flograph.ui.canvas.appearance_dialog import AppearanceDialog
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        node = registry.instantiate(type_id)
        graph.add_node(node)
        return AppearanceDialog(scene, node.id), node, scene

    def test_it_replaces_six_menu_entries(self, qtbot, registry):
        dialog, _node, _scene = self._env(registry)
        qtbot.addWidget(dialog)
        assert dialog._shape_combo is not None      # shape
        assert dialog._swatches is not None         # mark
        assert dialog._colour_button is not None    # colour
        assert dialog._labels_combo is not None     # port names

    def test_shape_applies_and_undoes(self, qtbot, registry):
        dialog, node, scene = self._env(registry)
        qtbot.addWidget(dialog)
        item = scene.node_items[node.id]
        assert item._square
        dialog._shape_combo.setCurrentIndex(
            dialog._shape_combo.findData(False))
        assert node.compact_view is False and not item._square
        scene.undo_stack.undo()
        assert node.compact_view is None and item._square

    def test_colour_reset_is_offered_only_when_there_is_one(self, qtbot,
                                                            registry):
        dialog, node, scene = self._env(registry)
        qtbot.addWidget(dialog)
        assert not dialog._colour_reset.isEnabled()
        scene.push_node_color(node.id, "#ff8800")
        dialog._refresh_colour()
        assert dialog._colour_reset.isEnabled()
        dialog._reset_colour()
        assert node.color is None
        assert not dialog._colour_reset.isEnabled()

    def test_collapse_is_offered_only_where_it_means_something(
            self, qtbot, registry):
        """One pin a side is already as gathered as it gets."""
        plain, _node, _scene = self._env(registry)
        qtbot.addWidget(plain)
        assert plain._collapse_check is None
        card, _n, _s = self._env(registry, "flograph.viz.report_card")
        qtbot.addWidget(card)
        assert card._collapse_check is not None

    def test_the_canvas_preview_toggle_moved_in_here(self, qtbot, registry):
        card, node, _scene = self._env(registry, "flograph.viz.show_plot")
        qtbot.addWidget(card)
        assert card._preview_check is not None
        card._preview_check.setChecked(True)  # "fold this node down to an icon"
        assert node.canvas_preview_enabled is False

    def test_a_node_with_no_preview_toggle_is_not_offered_one(
            self, qtbot, registry):
        dialog, _node, _scene = self._env(registry)
        qtbot.addWidget(dialog)
        assert dialog._preview_check is None
