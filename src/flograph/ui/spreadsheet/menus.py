"""The grid's right-click menus — on a cell, a row number, a column header —
and the plumbing that puts a menu or a small dialog in the right place.

Each menu is laid out under small headings (CLIPBOARD, ROWS, SORT &
FILTER, …) so the commands read as groups rather than one long list, and
every entry is one of `SheetActions`' actions: hover it and its tooltip
says what it will do. The menus offer what makes sense where the click was
— a row number's menu is about rows — but the same action does the same
thing from anywhere.

A menu for a grid on a canvas card is opened as a window parented to the
view the card is drawn in, never as a child of the card: Qt would embed it
in the scene, clipped by the card, placed by meaningless coordinates and
never dismissed by a click elsewhere (see canvas/popup_lift.py).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (QInputDialog, QLabel, QMenu, QWidget,
                               QWidgetAction)


def real_window(widget: QWidget) -> Optional[QWidget]:
    """The real top-level window `widget` is seen in — the canvas view's
    window for a widget on a card, the widget's own window otherwise."""
    from ..canvas.popup_lift import where_it_looks
    seen = where_it_looks(widget)
    if seen is not None:
        return seen[0].window()
    return widget.window()


def global_pos(widget: QWidget, pos: QPoint) -> QPoint:
    """Where `pos` (in `widget`'s coordinates) is on screen — through the
    view drawing the card when there is one, at the zoom it is drawn at."""
    from ..canvas.popup_lift import where_it_looks
    seen = where_it_looks(widget)
    if seen is None:
        return widget.mapToGlobal(pos)
    _view, rect = seen
    scale_x = rect.width() / max(widget.width(), 1)
    scale_y = rect.height() / max(widget.height(), 1)
    return rect.topLeft() + QPoint(int(pos.x() * scale_x),
                                   int(pos.y() * scale_y))


def menu_stylesheet() -> str:
    """The grid's own chrome, not the desktop's: these menus belong to a
    dark grid whatever the window around it is, and the glyphs are drawn
    for a dark ground (canvas/popup_lift does the same for card lists)."""
    from .. import theme
    return (f"QMenu {{ background: {theme.NODE_BODY.name()};"
            f" color: #e5e7eb; border: 1px solid #3c3f49; padding: 4px 0; }}"
            "QMenu::item { padding: 4px 28px 4px 10px; }"
            "QMenu::item:selected { background: #3b4a7a; }"
            "QMenu::item:disabled { color: #6b7080; }"
            "QMenu::separator { height: 1px; background: #3c3f49;"
            " margin: 4px 8px; }"
            "QMenu::icon { padding-left: 6px; }")


def new_menu(widget: QWidget, title: str = "") -> QMenu:
    menu = QMenu(title, real_window(widget))
    menu.setToolTipsVisible(True)
    menu.setStyleSheet(menu_stylesheet())
    return menu


def exec_menu(menu: QMenu, widget: QWidget, pos: QPoint) -> None:
    menu.exec(global_pos(widget, pos))


def heading(menu: QMenu, text: str) -> None:
    """A small grey caption over a group of entries."""
    label = QLabel(text.upper())
    label.setStyleSheet("QLabel { color: #8b909c; font-size: 7.5pt;"
                        " font-weight: 600; letter-spacing: 1px;"
                        " padding: 6px 12px 2px 12px; }")
    action = QWidgetAction(menu)
    action.setDefaultWidget(label)
    action.setEnabled(False)
    menu.addAction(action)


def submenu(menu: QMenu, title: str, icon=None) -> QMenu:
    sub = menu.addMenu(title)
    sub.setToolTipsVisible(True)
    if icon is not None:
        sub.setIcon(icon)
    return sub


def ask_text(widget: QWidget, title: str, label: str, text: str = ""
             ) -> Optional[str]:
    """A one-line question, as a real window over whatever the grid is in."""
    value, ok = QInputDialog.getText(real_window(widget), title, label,
                                     text=text)
    return value.strip() if ok and value.strip() else None


# ------------------------------------------------------------- the menus

def _type_menu(menu: QMenu, actions) -> None:
    from flograph.core.sheet import COLUMN_TYPES
    from .icons import sheet_icon
    sub = submenu(menu, "Column Type", sheet_icon("col_type"))
    for col_type in COLUMN_TYPES:
        sub.addAction(actions[f"type_{col_type}"])


def _number_menu(menu: QMenu, view) -> None:
    from .actions import fill_number_format_menu
    from .icons import sheet_icon
    sub = submenu(menu, "Number Format", sheet_icon("format"))
    fill_number_format_menu(sub, view)


def _cf_menu(menu: QMenu, view) -> None:
    if not view.host.can_format():
        return
    from .cond_format import fill_menu
    from .icons import sheet_icon
    sub = submenu(menu, "Conditional Formatting", sheet_icon("cond_format"))
    fill_menu(sub, view)


def _freeze_menu(menu: QMenu, actions) -> None:
    from .icons import sheet_icon
    sub = submenu(menu, "Freeze", sheet_icon("freeze"))
    for name in ("freeze", "freeze_row", "freeze_col", "unfreeze"):
        sub.addAction(actions[name])


def _apply_section(menu: QMenu, view) -> None:
    """Submit / Discard, only while there is something held."""
    if view.host.pending_text():
        menu.addSeparator()
        heading(menu, view.host.pending_text())
        menu.addAction(view.actions["submit"])
        menu.addAction(view.actions["discard"])


def fill_select_menu(menu, view) -> None:
    """Find & Select: find, replace, go to, and Excel's quick picks."""
    a = view.actions
    a.refresh()
    for name in ("find", "replace", "goto", "goto_special"):
        menu.addAction(a[name])
    heading(menu, "Select")
    for kind in ("formulas", "constants", "blanks", "errors", "problems",
                 "notes"):
        menu.addAction(a[f"select_{kind}"])


def cell_menu(view, widget: QWidget, pos: QPoint) -> None:
    a = view.actions
    a.refresh()
    menu = new_menu(widget)
    heading(menu, "Clipboard")
    for name in ("cut", "copy", "paste", "paste_values", "paste_special",
                 "paste_transpose", "copy_headers"):
        menu.addAction(a[name])

    heading(menu, "Cells")
    from .icons import sheet_icon
    insert = submenu(menu, "Insert", sheet_icon("row_above"))
    for name in ("row_above", "row_below", "col_left", "col_right"):
        insert.addAction(a[name])
    delete = submenu(menu, "Delete", sheet_icon("row_delete"))
    delete.addAction(a["row_delete"])
    delete.addAction(a["col_delete"])
    menu.addAction(a["clear"])
    menu.addAction(a["fill_down"])
    menu.addAction(a["fill_right"])
    pick = submenu(menu, "Select", sheet_icon("goto_special"))
    for name in ("goto", "goto_special", "select_formulas",
                 "select_constants", "select_blanks", "select_errors",
                 "select_problems", "select_notes"):
        pick.addAction(a[name])

    heading(menu, "Note")
    current = view.currentIndex()
    model = view.sheet_model()
    has_note = bool(model is not None and current.isValid()
                    and model.note(current.row(), current.column()))
    a["note_edit"].setText("Edit Note…" if has_note else "New Note…")
    menu.addAction(a["note_edit"])
    if view.note_targets():
        menu.addAction(a["note_delete"])
    if model is not None and model.note_cells():
        menu.addAction(a["note_next"])

    heading(menu, "Sort & Filter")
    menu.addAction(a["sort_asc"])
    menu.addAction(a["sort_desc"])
    menu.addAction(a["sort_custom"])
    menu.addAction(a["dedupe"])
    if view.has_active_sort:
        menu.addAction(a["sort_clear"])
    menu.addAction(a["filter_value"])
    if view.filtered:
        menu.addAction(a["filter_clear"])

    heading(menu, "Column")
    _type_menu(menu, a)
    _number_menu(menu, view)
    _cf_menu(menu, view)
    menu.addAction(a["dropdown"])
    menu.addAction(a["validation"])
    model = view.sheet_model()
    current = view.currentIndex()
    if (model is not None and current.isValid()
            and model.column_choices(current.column())[0]):
        menu.addAction(a["open_dropdown"])

    heading(menu, "More")
    menu.addAction(a["find"])
    if model is not None and current.isValid() and model.cell_problem(
            current.row(), current.column()):
        menu.addAction(a["next_problem"])
    _freeze_menu(menu, a)
    if view.host.can_open_editor():
        menu.addAction(view.actions["open_editor"])
    _apply_section(menu, view)
    exec_menu(menu, widget, pos)


def row_menu(view, widget: QWidget, pos: QPoint) -> None:
    a = view.actions
    a.refresh()
    menu = new_menu(widget)
    heading(menu, "Rows")
    for name in ("row_above", "row_below", "row_delete"):
        menu.addAction(a[name])
    menu.addAction(a["row_up"])
    menu.addAction(a["row_down"])
    menu.addAction(a["clear"])
    heading(menu, "Clipboard")
    for name in ("cut", "copy", "paste"):
        menu.addAction(a[name])
    heading(menu, "More")
    menu.addAction(a["header"])
    menu.addAction(a["freeze_row"])
    if view.host.can_open_editor():
        menu.addAction(view.actions["open_editor"])
    _apply_section(menu, view)
    exec_menu(menu, widget, pos)


def column_menu(view, widget: QWidget, pos: QPoint) -> None:
    a = view.actions
    a.refresh()
    menu = new_menu(widget)
    heading(menu, "Sort & Filter")
    menu.addAction(a["sort_asc"])
    menu.addAction(a["sort_desc"])
    menu.addAction(a["sort_custom"])
    menu.addAction(a["dedupe"])
    if view.has_active_sort:
        menu.addAction(a["sort_clear"])
    menu.addAction(a["filter"])
    if view.filtered:
        menu.addAction(a["filter_clear"])
    heading(menu, "Columns")
    for name in ("col_left", "col_right", "col_delete",
                 "col_move_left", "col_move_right"):
        menu.addAction(a[name])
    heading(menu, "This Column")
    menu.addAction(a["rename"])
    _type_menu(menu, a)
    _number_menu(menu, view)
    _cf_menu(menu, view)
    menu.addAction(a["dropdown"])
    menu.addAction(a["validation"])
    total = submenu(menu, "Total")
    from .totals import fill_total_menu
    fill_total_menu(total, view, view.target_columns())
    total.addSeparator()
    total.addAction(a["totals_row"])
    menu.addAction(a["fit"])
    menu.addAction(a["fit_all"])
    heading(menu, "More")
    menu.addAction(a["copy_headers"])
    menu.addAction(a["freeze_col"])
    if view.host.can_open_editor():
        menu.addAction(view.actions["open_editor"])
    _apply_section(menu, view)
    exec_menu(menu, widget, pos)
