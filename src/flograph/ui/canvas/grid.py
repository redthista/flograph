"""Grid snapping shared by the canvas nodes and dashboard tiles.

Snapping is a pure view preference: the scene carries `snap_enabled` and
`grid_step`, the main window is their sole writer (persisted in QSettings), and
items round their position/size through the helpers here. Holding the bypass
modifier while dragging or resizing turns snapping off for that gesture, the way
Power BI lets you nudge freely off the grid.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

# Snap resolutions offered in the toolbar's grid selector. "Normal" matches
# the fine background grid the canvas has always drawn.
GRID_PRESETS = {"Compact": 10.0, "Normal": 20.0, "Relaxed": 40.0}
DEFAULT_STEP = 20.0

# How far inside a card's right/bottom border still counts as an edge grab.
EDGE_MARGIN = 6.0

# Hold this while dragging/resizing to move freely, ignoring the grid.
BYPASS_MODIFIER = Qt.ControlModifier


def snap(value: float, step: float) -> float:
    """Round a single coordinate to the nearest grid line."""
    if step <= 0:
        return value
    return round(value / step) * step


def snap_point(x: float, y: float, step: float) -> tuple[float, float]:
    return snap(x, step), snap(y, step)


def grid_step(scene) -> float:
    return getattr(scene, "grid_step", DEFAULT_STEP)


def snapping_active(scene, modifiers=None) -> bool:
    """True when this gesture should snap: the scene has it enabled and the
    bypass modifier is not held. Pass the event's modifiers when you have them
    (resize handlers); the move path reads the live keyboard state instead."""
    if scene is None or not getattr(scene, "snap_enabled", False):
        return False
    if modifiers is None:
        modifiers = QApplication.keyboardModifiers()
    return not (modifiers & BYPASS_MODIFIER)
