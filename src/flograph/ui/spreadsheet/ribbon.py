"""The Table's ribbon: Excel's tabs-and-groups toolbar, drawn in the
canvas's own colours.

Two sizes, one set of commands (actions.SheetActions):

* **full** — the pop-out editor and a wide dashboard tile. Each group has a
  large button for its main command (icon over label) and small ones beside
  it (icon and label), with the group's name underneath, as in Office.
* **compact** — a canvas card, where every pixel is the grid's. One line of
  icon buttons per tab, separated by hairlines; the tooltip is the label
  and the explanation. It wraps rather than clips when the card is narrow.

"auto" picks full while the groups fit across and compact once they don't,
so a tile switches as it is resized.

Auto-apply sits on the tab strip, on every tab. On (the default) every edit
goes into the flow as it is made; off, edits wait and **Submit** (F9) sends
them. While edits wait, an amber strip under the ribbon says how many and
that the flow is still using the table as last submitted — amber is the
canvas's colour for "out of date" — with Discard beside it. Submit sits on
the tab strip of a full ribbon and in the amber strip of a compact one.

Double-click a tab, or press the chevron, to fold the ribbon down to its
tabs (remembered per size); click a tab to open it again.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QPoint, QSettings, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPolygon
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QSizePolicy, QStackedWidget, QToolButton,
                               QToolTip, QVBoxLayout, QWidget)

from .icons import AMBER, sheet_icon

_ORG = "flograph"
_APP = "flograph"
_COLLAPSED_KEY = "table_node/ribbon_collapsed_{size}"

_BG = "#25272e"
_TAB_BG = "#1f2026"
_LINE = "#14151a"
_HOVER = "#34363f"
_PRESSED = "#3a3d47"
_TEXT = "#d6d8de"
_DIM = "#8b909c"
_ACCENT = "#7c6cf6"   # theme.BUTTON_ACCENT — the active tab

def _stylesheet(compact: bool) -> str:
    size = "8pt" if compact else "8.5pt"
    tab_pad = "3px 6px 4px 6px" if compact else "4px 12px 5px 12px"
    btn_pad = "1px" if compact else "2px 4px"
    return f"""
QWidget#sheet_ribbon {{ background: {_BG}; }}
QWidget#ribbon_tabs {{ background: {_TAB_BG};
    border-bottom: 1px solid {_LINE}; }}
QToolButton#ribbon_tab {{ background: transparent; border: none;
    color: {_DIM}; font-size: {size}; padding: {tab_pad};
    border-bottom: 2px solid transparent; }}
QToolButton#ribbon_tab:hover {{ color: {_TEXT}; }}
QToolButton#ribbon_tab:checked {{ color: #f3f4f6; font-weight: 600;
    border-bottom: 2px solid {_ACCENT}; }}
QToolButton#ribbon_btn {{ background: transparent;
    border: 1px solid transparent; border-radius: 4px; color: {_TEXT};
    font-size: {size}; padding: {btn_pad}; }}
QToolButton#ribbon_btn:hover {{ background: {_HOVER};
    border-color: #3c3f49; }}
QToolButton#ribbon_btn:pressed {{ background: {_PRESSED}; }}
QToolButton#ribbon_btn:checked {{ background: rgba(96,165,250,0.18);
    border-color: rgba(96,165,250,0.55); }}
QToolButton#ribbon_btn:disabled {{ color: #5d616c; }}
QLabel#ribbon_caption {{ color: {_DIM}; font-size: 7.5pt; }}
QFrame#ribbon_sep {{ color: #3a3d47; }}
QToolButton#ribbon_submit {{ background: #1f6f43; color: #eafff2;
    border: 1px solid #22c55e; border-radius: 4px; font-size: {size};
    font-weight: 600; padding: 1px 8px; margin: 2px 0; }}
QToolButton#ribbon_submit:hover {{ background: #23824e; }}
QToolButton#ribbon_submit:disabled {{ background: transparent;
    color: #5d616c; border-color: #3a3d47; font-weight: 400; }}
QWidget#ribbon_pending {{ background: rgba(234,179,8,0.13);
    border-top: 1px solid rgba(234,179,8,0.45);
    border-bottom: 1px solid rgba(234,179,8,0.45); }}
QLabel#ribbon_pending_text {{ color: #fde68a; font-size: {size}; }}
"""


class RibbonButton(QToolButton):
    """A ribbon button for one action. `label` names it for where it sits
    ("Insert Above" in the Rows group — "Above" would be a riddle anywhere
    else). `menu` makes it open a list built on each click, drawn with a
    small caret. Its tooltip — the action's explanation — is shown where the
    pointer is, even on a canvas card (see data_table.tooltip_host).

    It mirrors the action rather than taking it as its default action: a
    default action rewrites the button's text on every change to the
    action, which would throw the label away."""

    def __init__(self, action, size: str, menu: Optional[Callable] = None,
                 label: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ribbon_btn")
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.NoFocus)   # the grid keeps the keyboard
        self._action = action
        self._label = label
        self._menu_builder = menu
        self._size = size
        if size == "large":
            self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            self.setIconSize(QSize(24, 24))
            self.setMinimumWidth(50)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        elif size == "small":
            self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self.setIconSize(QSize(16, 16))
        else:
            self.setToolButtonStyle(Qt.ToolButtonIconOnly)
            self.setIconSize(QSize(16, 16))
        self.setCheckable(action.isCheckable() and menu is None)
        action.changed.connect(self._sync)
        action.toggled.connect(self._toggled)
        self.clicked.connect(self._clicked)
        self._sync()

    def _sync(self) -> None:
        import shiboken6
        if not shiboken6.isValid(self):
            return
        action = self._action
        self.setIcon(action.icon())
        self.setText(self._label or action.iconText())
        self.setToolTip(action.toolTip())
        self.setEnabled(action.isEnabled())
        if self.isCheckable() and self.isChecked() != action.isChecked():
            self.setChecked(action.isChecked())

    def _toggled(self, on: bool) -> None:
        import shiboken6
        if (shiboken6.isValid(self) and self.isCheckable()
                and self.isChecked() != on):
            self.setChecked(on)

    def _clicked(self) -> None:
        if self._menu_builder is not None:
            self._open_menu()
        elif self._action.isCheckable():
            self._action.setChecked(self.isChecked())
        else:
            self._action.trigger()

    def _open_menu(self) -> None:
        from .menus import exec_menu, new_menu
        built = new_menu(self)
        self._menu_builder(built)
        if not built.isEmpty():
            exec_menu(built, self, QPoint(0, self.height()))

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        if self._menu_builder is not None and self._size != "large":
            hint.setWidth(hint.width() + 7)
        return hint

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._menu_builder is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(_DIM if self.isEnabled() else "#5d616c"))
        if self._size == "large":
            x, y = self.width() / 2, self.height() - 4
        else:
            x, y = self.width() - 5, self.height() / 2 + 1
        painter.drawPolygon(QPolygon([QPoint(int(x - 3), int(y - 2)),
                                      QPoint(int(x + 3), int(y - 2)),
                                      QPoint(int(x), int(y + 1))]))

    def event(self, event) -> bool:
        if event.type() == event.Type.ToolTip:
            from ..data_table import tooltip_host
            text = self.toolTip()
            if text:
                QToolTip.showText(event.globalPos(), text,
                                  tooltip_host(self, event.globalPos()))
            else:
                QToolTip.hideText()
            return True
        return super().event(event)


class _Group(QWidget):
    """One captioned group of a full-size ribbon page: a large button, then
    columns of up to three small ones."""

    def __init__(self, caption: str, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 1)
        outer.setSpacing(1)
        self._row = QHBoxLayout()
        self._row.setSpacing(2)
        outer.addLayout(self._row, 1)
        label = QLabel(caption)
        label.setObjectName("ribbon_caption")
        label.setAlignment(Qt.AlignHCenter)
        outer.addWidget(label)
        self._column: Optional[QVBoxLayout] = None

    def add_large(self, button: QToolButton) -> None:
        self._column = None
        self._row.addWidget(button)

    def add_small(self, button: QToolButton) -> None:
        if self._column is None or self._column.count() >= 3:
            self._column = QVBoxLayout()
            self._column.setSpacing(0)
            self._row.addLayout(self._column)
        self._column.addWidget(button)

    def finish(self) -> None:
        if self._column is not None:
            self._column.addStretch(1)


def _separator() -> QFrame:
    line = QFrame()
    line.setObjectName("ribbon_sep")
    line.setFrameShape(QFrame.VLine)
    line.setFrameShadow(QFrame.Plain)
    return line


class _LooseStack(QStackedWidget):
    """A stack that asks for no width of its own. The full-size pages are
    wide, and a stack holding them would otherwise set the ribbon's — and
    so the window's — minimum width to theirs: the window could then never
    be made narrow enough for the ribbon to switch to its compact size."""

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())


class SheetRibbon(QWidget):
    """The ribbon for one SpreadsheetView."""

    collapsed_changed = Signal(bool)

    def __init__(self, view, size: str = "auto", parent=None) -> None:
        """`size` is "compact" (a card), "full", or "auto" — full while the
        groups fit across, compact once they don't (a narrow tile)."""
        super().__init__(parent)
        self.setObjectName("sheet_ribbon")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._view = view
        self._size = size
        self._collapsed = False
        compact = size == "compact"
        self._compact = compact
        self._size_key = "compact" if compact else "full"
        self.setStyleSheet(_stylesheet(compact))
        actions = view.actions
        self._actions = actions

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- the tab strip
        strip = QWidget()
        strip.setObjectName("ribbon_tabs")
        strip.setAttribute(Qt.WA_StyledBackground, True)
        tabs = QHBoxLayout(strip)
        tabs.setContentsMargins(2, 0, 3, 0)
        tabs.setSpacing(0)
        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self._stacks = {"full": _LooseStack(), "compact": QStackedWidget()}
        self._tab_buttons: list[QToolButton] = []
        self._tab_titles: list[tuple[str, str]] = []
        for index, (title, short, groups) in enumerate(self._pages()):
            self._tab_titles.append((title, short))
            button = QToolButton()
            button.setObjectName("ribbon_tab")
            button.setText(short if compact else title)
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.setToolTip(f"{title.replace('&&', '&')} — double-click "
                              "to fold the ribbon")
            self._tab_group.addButton(button, index)
            tabs.addWidget(button)
            self._tab_buttons.append(button)
            for kind, stack in self._stacks.items():
                if kind == "full" and compact:
                    continue
                stack.addWidget(self._build_page(groups, kind == "compact"))
        self._active = "compact" if compact else "full"
        self._stack = self._stacks[self._active]
        self._tab_group.idClicked.connect(self._tab_clicked)
        for button in self._tab_buttons:
            button.installEventFilter(self)
        tabs.addStretch(1)

        # Auto-apply always sits on the tab strip. Submit sits there too on
        # a full ribbon; on a card there is no room, so it rides in the
        # amber strip, which only shows while there is something to submit.
        self._auto = RibbonButton(actions["auto"],
                                  "icon" if compact else "small")
        self._submit = RibbonButton(actions["submit"], "small",
                                    label="Submit")
        self._submit.setObjectName("ribbon_submit")
        self._submit.setIconSize(QSize(14, 14))
        tabs.addWidget(self._auto)
        if not compact:
            tabs.addWidget(self._submit)
        self._fold = QToolButton()
        self._fold.setObjectName("ribbon_btn")
        self._fold.setAutoRaise(True)
        self._fold.setFocusPolicy(Qt.NoFocus)
        self._fold.setIconSize(QSize(14, 14))
        self._fold.clicked.connect(lambda: self.set_collapsed(
            not self.collapsed))
        tabs.addWidget(self._fold)
        outer.addWidget(strip)
        for kind, stack in self._stacks.items():
            outer.addWidget(stack)
            stack.setVisible(kind == self._active)

        # ---- the "not submitted" strip
        self._pending = QWidget()
        self._pending.setObjectName("ribbon_pending")
        self._pending.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(self._pending)
        row.setContentsMargins(8, 1, 4, 1)
        row.setSpacing(6)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {AMBER.name()};")
        self._pending_text = QLabel()
        self._pending_text.setObjectName("ribbon_pending_text")
        self._pending_text.setWordWrap(not compact)
        row.addWidget(dot)
        row.addWidget(self._pending_text, 1)
        self._discard = RibbonButton(actions["discard"], "small",
                                     label="Discard")
        row.addWidget(self._discard)
        if compact:
            row.addWidget(self._submit)
        outer.addWidget(self._pending)

        self._tab_buttons[0].setChecked(True)
        self._tab_clicked(0)
        stored = QSettings(_ORG, _APP).value(
            _COLLAPSED_KEY.format(size=self._size_key), False)
        self._collapsed = str(stored).lower() in ("true", "1")
        self._apply_collapsed()
        actions.listen(self.sync)
        self.sync()

    # ------------------------------------------------------------- pages

    def _pages(self):
        builders = {
            "insert_menu": self._fill_insert_menu,
            "delete_menu": self._fill_delete_menu,
            "type_menu": self._fill_type_menu,
            "function_menu": self._fill_function_menu,
            "freeze_menu": self._fill_freeze_menu,
            "fill_menu": self._fill_fill_menu,
            "ink_menu": self._fill_ink_menu,
            "select_menu": self._fill_select_menu,
            "number_menu": self._fill_number_menu,
            "cf_menu": self._fill_cf_menu,
            "total_menu": self._fill_total_menu,
        }

        def m(builder, action, label):
            return (action, label, builders[builder])

        home = [
            ("Clipboard", [("paste", "Paste"), ("cut", "Cut"),
                           ("copy", "Copy"),
                           ("paste_values", "Paste Values"),
                           ("paste_special", "Paste Special"),
                           ("copy_headers", "Copy + Headers")]),
            ("Undo", [("undo", "Undo"), ("redo", "Redo")]),
            ("Cells", [m("insert_menu", "row_above", "Insert"),
                       m("delete_menu", "row_delete", "Delete"),
                       ("clear", "Clear")]),
            ("Font", [("row", [("fmt_b", ""), ("fmt_i", ""),
                               ("fmt_u", "")]),
                      ("row", [m("fill_menu", "fill_color", ""),
                               m("ink_menu", "font_color", "")]),
                      ("row", [("align_left", ""), ("align_center", ""),
                               ("align_right", ""),
                               ("clear_formats", "")])]),
            ("Number", [m("number_menu", "number_format", "Format"),
                        ("row", [("fmt_currency", ""),
                                 ("fmt_percent", ""),
                                 ("fmt_thousands", "")]),
                        ("row", [("dec_more", ""), ("dec_less", "")])]),
            ("Editing", [("fill_down", "Fill Down"),
                         ("fill_right", "Fill Right"),
                         m("select_menu", "find", "Find && Select"),
                         ("replace", "Replace")]),
        ]
        rows_cols = [
            ("Rows", [("row_above", "Insert Above"),
                      ("row_below", "Insert Below"), ("row_delete", "Delete"),
                      ("row_up", "Move Up"), ("row_down", "Move Down"),
                      ("select_row", "Select Rows")]),
            ("Columns", [("col_left", "Insert Left"),
                         ("col_right", "Insert Right"),
                         ("col_delete", "Delete"),
                         ("col_move_left", "Move Left"),
                         ("col_move_right", "Move Right"),
                         ("select_col", "Select Columns")]),
            ("Names", [("header", "Row → Names"), ("rename", "Rename")]),
        ]
        data = [
            ("Sort & Filter", [("filter", "Filter"),
                               ("sort_asc", "Sort A → Z"),
                               ("sort_desc", "Sort Z → A"),
                               ("sort_custom", "Custom Sort"),
                               ("filter_clear", "Clear Filters")]),
            ("Styles", [m("cf_menu", "cond_format", "Conditional"),
                        ("cf_manage", "Manage Rules")]),
            ("Totals", [("totals_row", "Total Row"),
                        m("total_menu", "total_menu", "Total")]),
            ("Column", [m("type_menu", "col_type", "Type"),
                        ("dropdown", "Dropdown List"),
                        ("split", "Text to Columns"),
                        ("dedupe", "Remove Duplicates")]),
            ("Check", [("validation", "Validation"),
                       ("next_problem", "Next Problem")]),
        ]
        # Excel keeps notes on Review; a tab of their own also keeps the
        # Data tab narrow enough for the full editor's labelled layout
        review = [
            ("Notes", [("note_edit", "New Note"),
                       ("note_delete", "Delete Note"),
                       ("note_next", "Next Note")]),
            ("Check", [("next_problem", "Next Problem"),
                       ("select_problems", "Problem Cells"),
                       ("select_notes", "Cells with Notes")]),
        ]
        view = [
            ("Freeze", [m("freeze_menu", "freeze", "Freeze"),
                        ("freeze_row", "Top Row"),
                        ("freeze_col", "First Column"),
                        ("unfreeze", "Unfreeze")]),
            ("Size", [("fit", "Fit Width"), ("fit_all", "Fit All")]),
            ("Show", [("show_formulas", "Formulas")]),
        ]
        if self._view.host.can_open_editor():
            view.append(("Window", [("open_editor", "Full Editor")]))
        formulas = [
            ("Functions", [m("function_menu", "insert_function",
                             "Insert Function"),
                           ("reference", "Reference")]),
            ("Check", [("show_formulas", "Show Formulas")]),
        ]
        return [("Home", "Home", home),
                ("Rows && Columns", "Rows", rows_cols),
                ("Data", "Data", data), ("Review", "Review", review),
                ("View", "View", view),
                ("Formulas", "fx", formulas)]

    def _build_page(self, groups, compact: bool) -> QWidget:
        page = QWidget()
        if compact:
            from ..flow_layout import FlowLayout
            layout = FlowLayout(page, margin=2, spacing=0)
            first = True
            for _caption, entries in groups:
                if not first:
                    sep = _separator()
                    sep.setFixedSize(7, 18)
                    layout.addWidget(sep)
                first = False
                for entry in entries:
                    for one in (entry[1] if entry[0] == "row" else [entry]):
                        layout.addWidget(self._button(one, "icon"))
            return page
        layout = QHBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        for index, (caption, entries) in enumerate(groups):
            if index:
                layout.addWidget(_separator())
            group = _Group(caption)
            for position, entry in enumerate(entries):
                if entry[0] == "row":
                    group.add_small(self._icon_row(entry[1]))
                elif position == 0:
                    group.add_large(self._button(entry, "large"))
                else:
                    group.add_small(self._button(entry, "small"))
            group.finish()
            layout.addWidget(group)
        layout.addStretch(1)
        return page

    def _icon_row(self, entries) -> QWidget:
        """Icon-only buttons side by side in one small slot — Excel's
        B I U strip."""
        strip = QWidget()
        row = QHBoxLayout(strip)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        for entry in entries:
            row.addWidget(self._button(entry, "icon"))
        row.addStretch(1)
        return strip

    def _button(self, entry, size: str) -> RibbonButton:
        name, label = entry[0], entry[1]
        builder = entry[2] if len(entry) > 2 else None
        return RibbonButton(self._actions[name], size, menu=builder,
                            label=label)

    # ----------------------------------------------------- dropdown lists

    def _fill_insert_menu(self, menu) -> None:
        for name in ("row_above", "row_below", "col_left", "col_right"):
            menu.addAction(self._actions[name])

    def _fill_delete_menu(self, menu) -> None:
        for name in ("row_delete", "col_delete", "clear"):
            menu.addAction(self._actions[name])

    def _fill_type_menu(self, menu) -> None:
        from flograph.core.sheet import COLUMN_TYPES
        for col_type in COLUMN_TYPES:
            menu.addAction(self._actions[f"type_{col_type}"])

    def _fill_total_menu(self, menu) -> None:
        from .totals import fill_total_menu
        fill_total_menu(menu, self._view, self._view.target_columns())

    def _fill_cf_menu(self, menu) -> None:
        from .cond_format import fill_menu
        fill_menu(menu, self._view)

    def _fill_number_menu(self, menu) -> None:
        from .actions import fill_number_format_menu
        fill_number_format_menu(menu, self._view)

    def _fill_select_menu(self, menu) -> None:
        from .menus import fill_select_menu
        fill_select_menu(menu, self._view)

    def _fill_fill_menu(self, menu) -> None:
        from .actions import fill_color_menu
        fill_color_menu(menu, self._view, ink=False)

    def _fill_ink_menu(self, menu) -> None:
        from .actions import fill_color_menu
        fill_color_menu(menu, self._view, ink=True)

    def _fill_freeze_menu(self, menu) -> None:
        for name in ("freeze", "freeze_row", "freeze_col", "unfreeze"):
            menu.addAction(self._actions[name])

    def _fill_function_menu(self, menu) -> None:
        """Every function, a submenu per category, each entry saying what
        it does — hover for its arguments and an example."""
        from flograph.core.sheet import FUNCTION_CATEGORIES, FUNCTION_HELP
        from .actions import tip
        from .menus import submenu
        for category in FUNCTION_CATEGORIES:
            entries = sorted((e for e in FUNCTION_HELP if e[4] == category),
                             key=lambda e: e[0])
            if not entries:
                continue
            sub = submenu(menu, category)
            for name, signature, what, example, _cat in entries:
                short = what if len(what) <= 48 else what[:46] + "…"
                action = sub.addAction(f"{name}\t{short}")
                action.setToolTip(tip(signature, f"{what}<br>e.g. "
                                                 f"<code>{example}</code>"))
                action.triggered.connect(
                    lambda _=False, n=name: self._view.start_formula(
                        f"={n}("))

    # ------------------------------------------------------------ state

    def eventFilter(self, watched, event) -> bool:
        if (event.type() == event.Type.MouseButtonDblClick
                and watched in self._tab_buttons):
            self.set_collapsed(not self.collapsed)
            return True
        return super().eventFilter(watched, event)

    def _tab_clicked(self, index: int) -> None:
        for stack in self._stacks.values():
            if stack.count() > index:
                stack.setCurrentIndex(index)
        if self._collapsed:
            self.set_collapsed(False)

    def _full_width(self) -> int:
        stack = self._stacks["full"]
        return max((stack.widget(i).sizeHint().width()
                    for i in range(stack.count())), default=0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._choose_size()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # the pages' widths are only right once styled, which is after the
        # first resize: look again when the ribbon is actually on screen
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._choose_size)

    def _choose_size(self) -> None:
        import shiboken6
        if self._size != "auto" or not shiboken6.isValid(self):
            return
        wanted = "full" if self.width() >= self._full_width() else "compact"
        if wanted != self._active:
            self._active = wanted
            self._stack = self._stacks[wanted]
            # the tab strip shrinks with it, or its long names would hold
            # the whole ribbon wider than the tile it is in
            compact = wanted == "compact"
            for button, (title, short) in zip(self._tab_buttons,
                                              self._tab_titles):
                button.setText(short if compact else title)
            self._auto.setToolButtonStyle(
                Qt.ToolButtonIconOnly if compact
                else Qt.ToolButtonTextBesideIcon)
            self._apply_collapsed()

    @property
    def active_size(self) -> str:
        return self._active

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, flag: bool) -> None:
        if flag == self._collapsed:
            return
        self._collapsed = flag
        QSettings(_ORG, _APP).setValue(
            _COLLAPSED_KEY.format(size=self._size_key), flag)
        self._apply_collapsed()
        self.collapsed_changed.emit(flag)

    def _apply_collapsed(self) -> None:
        for kind, stack in self._stacks.items():
            stack.setVisible(kind == self._active and not self._collapsed)
        self._fold.setIcon(sheet_icon(
            "chevron_down" if self._collapsed else "chevron_up"))
        self._fold.setToolTip("Show the ribbon" if self._collapsed
                              else "Fold the ribbon down to its tabs")

    def show_tab(self, index: int) -> None:
        self._tab_buttons[index].setChecked(True)
        self._tab_clicked(index)

    def sync(self) -> None:
        """Re-read the host: held or live, and what is waiting."""
        host = self._view.host
        can_hold = host.can_hold()
        held = can_hold and host.mode() == "submit"
        pending = host.pending_text() if held else ""
        self._auto.setVisible(can_hold)
        self._submit.setVisible(held and (bool(pending)
                                          or not self._compact))
        self._discard.setVisible(bool(pending))
        self._pending.setVisible(bool(pending))
        if pending:
            self._pending_text.setText(
                pending if self._compact else
                f"{pending} — the flow is still using the table as it was "
                "last submitted. Submit (F9) sends your edits on.")
            self._pending.setToolTip(
                "Edits wait here until you Submit, so a big flow isn't "
                "re-run for every cell. They are saved with the project, "
                "and Undo works on them as usual.")
