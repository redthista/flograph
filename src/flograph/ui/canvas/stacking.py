"""Qt z-value bands for the model canvas.

Each class of item gets its own band, and an item's own stacking index (see
core.layers) is added within it. Bands rather than raw indices because the
classes have a fixed relationship the user must not be able to invert:
frames are backdrops, wires run over them but under the cards they join,
and the wire being dragged sits above everything.

Kept in a leaf module with no imports of its own so every item type can
share the constants without an import cycle through the scene.
"""

# 1000 apart, so a canvas would need a thousand frames (or a thousand nodes)
# before one band could reach into the next.
FRAME_Z = -2000.0
# The dashed line an opted-in Goto/From pair draws. Below the wires on
# purpose: it is an aid to reading the canvas, not part of its wiring, and
# where one crosses a real wire the wire is the thing that must stay legible.
LINK_LINE_Z = -1500.0
WIRE_Z = -1000.0
NODE_Z = 0.0

# A collapsed frame leaves the backdrop band entirely: it is no longer a
# region behind the flow but a single box standing in the middle of it, with
# live pins that have to be clickable. Far above NODE_Z rather than one band
# up, because a node's own stacking index is added to its band and a project
# with a thousand-odd nodes would otherwise start drawing them over the
# collapsed frames.
COLLAPSED_FRAME_Z = 500_000.0

# The wire being dragged, and a tile blown up over a whole dashboard page:
# both are transient states that own the view while they last.
PENDING_WIRE_Z = 1_000_000.0
FULLSCREEN_TILE_Z = 1_000_000.0


def z_for(band: float, index) -> float:
    """The Qt z-value for an item at stacking `index` within `band`."""
    return band + (index or 0)


# One wording and one key for each action everywhere they appear — the model
# canvas, dashboard pages, menus and shortcuts. The keys follow Illustrator
# and Figma, which is what anyone reaching for this will try first.
LAYER_LABELS = {
    "front": "Bring to Front",
    "forward": "Bring Forward",
    "backward": "Send Backward",
    "back": "Send to Back",
}
LAYER_SHORTCUTS = {
    "front": "Ctrl+Shift+]",
    "forward": "Ctrl+]",
    "backward": "Ctrl+[",
    "back": "Ctrl+Shift+[",
}


def layer_action_for(event) -> "str | None":
    """The reorder action a key event asks for, or None.

    Matched on the key rather than through QShortcut so both canvases can
    decline it — an unmovable selection has to fall through to whatever
    handles the key next instead of swallowing it.
    """
    from PySide6.QtCore import Qt

    modifiers = event.modifiers()
    if not modifiers & Qt.ControlModifier:
        return None
    shifted = bool(modifiers & Qt.ShiftModifier)
    # Shift+] is "}" on most layouts, and Qt reports the shifted character
    if event.key() in (Qt.Key_BracketRight, Qt.Key_BraceRight):
        return "front" if shifted else "forward"
    if event.key() in (Qt.Key_BracketLeft, Qt.Key_BraceLeft):
        return "back" if shifted else "backward"
    return None


def add_layer_menu(menu, title: str = "Layer") -> dict:
    """Add the four reorder entries as a submenu of `menu`, returning
    {QAction: action name} for the caller to match against."""
    from PySide6.QtGui import QKeySequence

    submenu = menu.addMenu(title)
    actions = {}
    for name, label in LAYER_LABELS.items():
        entry = submenu.addAction(label)
        # shown only; the shortcut itself lives on the view, so it works
        # without opening a menu first
        entry.setShortcut(QKeySequence(LAYER_SHORTCUTS[name]))
        actions[entry] = name
    return actions
