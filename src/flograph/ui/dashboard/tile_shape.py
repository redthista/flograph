"""A dashboard tile's shape: the Shape menu, and the Size and Shape dialog.

A tile is a free rectangle until it is given a shape. Once stated — a named
one from the menu, or numbers typed into the dialog — the shape is stored on
the tile as `Tile.aspect`, and from then on a resize drag keeps it (see
TileItem._drag_aspect). The arithmetic is `core.aspect`, which a report
embed's `ratio=` reads through as well, so "16:9" means the same on both
kinds of page.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QLabel, QMenu, QSpinBox,
                               QVBoxLayout)

from flograph.core.aspect import (PRESETS, format_aspect, keep_aspect,
                                  parse_shape, preset_for, same_aspect)

from ..commands import SetTileShapeCommand
from .tile_item import MIN_H, MIN_W

#: The menu's two choices that are not a shape. Strings, so a caller can
#: tell them from an aspect — always a float — at a glance.
ANY = "any"
SIZE = "size"

#: The largest side the dialog offers, in page pixels: far past any screen,
#: and small enough that a slip on the keyboard does not make a tile whose
#: far edge nobody can find.
MAX_SIDE = 10000


def resizable(items) -> list:
    """The tiles a shape can apply to — all but Action Buttons, which are
    a fixed size here as they are on the canvas."""
    return [item for item in items if item._kind() != "button"]


def shared_aspect(items):
    """The shape every one of `items` has: an aspect, None when none of
    them has one — and False when they disagree, so a mixed selection ticks
    nothing rather than whichever tile happened to be first."""
    first = items[0].tile.aspect
    if all(same_aspect(item.tile.aspect, first) for item in items):
        return first
    return False


def add_shape_menu(menu, items) -> dict:
    """Add a Shape submenu for `items` to `menu`.

    Returns {action: choice}, where a choice is an aspect, ANY or SIZE. The
    shape the tiles already have is ticked — including one typed into the
    dialog that is none of the named ones, so the menu never shows a shaped
    tile as free.
    """
    # Parented explicitly. `menu.addMenu("Shape")` hands back a menu that
    # only Python owns, which is deleted the moment this function returns —
    # leaving the tile menu a Shape entry with nothing behind it.
    submenu = QMenu("Shape", menu)
    menu.addMenu(submenu)
    items = resizable(items)
    if not items:
        submenu.setEnabled(False)
        return {}
    current = shared_aspect(items)
    choices: dict = {}

    free = submenu.addAction("Any Shape")
    free.setCheckable(True)
    free.setChecked(current is None)
    choices[free] = ANY
    submenu.addSeparator()
    for name, width, height in PRESETS:
        # the tab puts the ratio in the shortcut column, so the numbers line
        # up down the right of the menu instead of trailing ragged names
        action = submenu.addAction(f"{name}\t{width}:{height}")
        action.setCheckable(True)
        action.setChecked(bool(current)
                          and same_aspect(current, width / height))
        choices[action] = width / height
    if current and preset_for(current) is None:
        custom = submenu.addAction(f"Custom\t{format_aspect(current)}")
        custom.setCheckable(True)
        custom.setChecked(True)
        choices[custom] = current
    submenu.addSeparator()
    choices[submenu.addAction("Size and Shape…")] = SIZE
    return choices


def reshaped(rect: tuple, aspect: Optional[float]) -> tuple:
    """`rect` given `aspect`: it keeps its place and its width, and the
    height follows — the way a report's `ratio=` works from the width it is
    placed at. None leaves it exactly as it is."""
    if aspect is None:
        return tuple(rect)
    x, y, width, height = rect
    width, height = keep_aspect(width, height, aspect, "width", (MIN_W, MIN_H))
    return (x, y, width, height)


def apply_choice(scene, anchor, items, choice, parent=None) -> bool:
    """Carry out a Shape menu choice on the selected tiles, as one undo
    step. `anchor` is the tile that was right-clicked, whose size the
    dialog starts from. Returns whether anything changed."""
    items = resizable(items)
    if not items:
        return False
    if choice == SIZE:
        seed = anchor if anchor in items else items[0]
        answer = ask_size(parent, seed, len(items))
        if answer is None:
            return False
        (width, height), aspect = answer
        changes = [(item.tile.id, (*item.tile.rect[:2], width, height),
                    aspect) for item in items]
        text = "size tile" if len(items) == 1 else "size tiles"
    else:
        aspect = None if choice == ANY else choice
        changes = [(item.tile.id, reshaped(item.tile.rect, aspect), aspect)
                   for item in items]
        text = "free tile shape" if aspect is None else "shape tile"
    tiles = scene.graph.page(scene.page_id).tiles
    changes = [(tile_id, rect, aspect) for tile_id, rect, aspect in changes
               if (tuple(tiles[tile_id].rect), tiles[tile_id].aspect)
               != (tuple(rect), aspect)]
    if not changes:
        return False
    scene.undo_stack.push(SetTileShapeCommand(
        scene.graph, scene.page_id, changes, text))
    return True


def ask_size(parent, item, count: int):
    """Open the dialog on `item`'s size and shape. ((width, height), aspect)
    when accepted, None when not."""
    dialog = TileSizeDialog(tuple(item.tile.rect[2:]), item.tile.aspect,
                            count, parent)
    if not dialog.exec():
        return None
    return dialog.values()


def shape_text(aspect: Optional[float]) -> str:
    """How the dialog writes a shape in its Shape box."""
    if aspect is None:
        return "Any"
    row = preset_for(aspect)
    if row is not None:
        return f"{row[1]}:{row[2]}  {row[0]}"
    return format_aspect(aspect)


class TileSizeDialog(QDialog):
    """A tile's size in page pixels, and the shape it keeps.

    With a shape, the two sizes move together: typing a width works out
    the height, typing a height works out the width, and choosing a shape
    keeps the width and works out the height — the same rule the menu
    follows. The Shape box takes a shape the way a report's `ratio=` does
    (`16:9`, `4x3`, `1.5`), or one of the names.
    """

    def __init__(self, size: tuple, aspect: Optional[float], count: int = 1,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Size and Shape")
        self._aspect = aspect
        self._syncing = False

        self.shape_box = QComboBox()
        self.shape_box.setEditable(True)
        self.shape_box.addItem("Any")
        for name, width, height in PRESETS:
            self.shape_box.addItem(f"{width}:{height}  {name}")
        self.shape_box.setEditText(shape_text(aspect))

        self.width_box = self._side_box(MIN_W, size[0])
        self.height_box = self._side_box(MIN_H, size[1])

        form = QFormLayout()
        form.addRow("Shape", self.shape_box)
        form.addRow("Width", self.width_box)
        form.addRow("Height", self.height_box)

        self.problem = QLabel()
        self.problem.setWordWrap(True)
        self.problem.hide()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._ok = buttons.button(QDialogButtonBox.Ok)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.problem)
        if count > 1:
            layout.addWidget(QLabel(f"Applies to all {count} selected tiles."))
        layout.addWidget(buttons)

        self.shape_box.editTextChanged.connect(self._on_shape)
        self.width_box.valueChanged.connect(lambda _: self._follow("width"))
        self.height_box.valueChanged.connect(lambda _: self._follow("height"))

    @staticmethod
    def _side_box(minimum: float, value: float) -> QSpinBox:
        box = QSpinBox()
        box.setRange(int(minimum), MAX_SIDE)
        box.setSuffix(" px")
        box.setValue(round(value))
        return box

    def _on_shape(self, text: str) -> None:
        ok, aspect = parse_shape(text)
        self._ok.setEnabled(ok)
        self.problem.setVisible(not ok)
        if not ok:
            self.problem.setText(
                f"“{text.strip()}” is not a shape — try 16:9 or 1.5")
            return
        self._aspect = aspect
        self._follow("width")

    def _follow(self, lead: str) -> None:
        """Bring the other side into line with `lead`, when there is a
        shape to keep. The guard is for the side being set: its own
        valueChanged would otherwise answer back."""
        if self._syncing or self._aspect is None:
            return
        width, height = keep_aspect(
            self.width_box.value(), self.height_box.value(), self._aspect,
            lead, (MIN_W, MIN_H))
        self._syncing = True
        try:
            self.width_box.setValue(round(width))
            self.height_box.setValue(round(height))
        finally:
            self._syncing = False

    def values(self) -> "tuple[tuple[float, float], Optional[float]]":
        """((width, height), aspect) as the dialog stands."""
        return ((float(self.width_box.value()),
                 float(self.height_box.value())), self._aspect)
