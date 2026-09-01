"""General app Settings window (Tools > Settings…, Ctrl+,): a category list
on the left, one page per category on the right. Start here when adding a new
app-wide preference instead of a one-off menu toggle — add a page to the
`pages` dict in __init__ and it shows up in the nav automatically, sorted
alphabetically alongside the rest.

Non-modal and live-apply: pages bind straight to the setting they control
(e.g. an existing QAction's checked state, or MainWindow.set_lod_*) so a
toggle here takes effect immediately, the way it would from a menu — there's
no separate Save step.
"""
from __future__ import annotations

import platform

from PySide6.QtCore import QSize, Qt, qVersion
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QKeySequenceEdit, QLineEdit, QMessageBox, QPushButton, QSpinBox,
    QStackedWidget, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from .canvas import grid


def _flograph_version() -> str:
    import importlib.metadata
    try:
        return importlib.metadata.version("flograph")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


#: Roughly how many characters a tooltip line should hold before wrapping.
#: Qt only word-wraps a *rich text* tooltip, and then to whatever width it
#: fancies — which for these explanations is one line most of the way across
#: the screen. Wrapping them ourselves is the only way to get a readable
#: measure, and 68 is about a comfortable line of prose.
TOOLTIP_WRAP = 68


def wrapped_tooltip(text: str) -> str:
    """An explanation as a several-line tooltip rather than one long line.

    Returned as rich text with explicit breaks: Qt treats a plain string as
    a single unbreakable line, so the paragraph-length hints these settings
    carry ran off the edge of the screen.
    """
    import html
    import textwrap
    lines = textwrap.wrap(" ".join(text.split()), width=TOOLTIP_WRAP) or [""]
    # quote=False: this is body text, not an attribute value, and escaping
    # every apostrophe to &#x27; only makes the source unreadable
    return ("<qt>"
            + "<br>".join(html.escape(line, quote=False) for line in lines)
            + "</qt>")


class SettingsGrid(QTreeWidget):
    """A settings page as a two-column grid: name on the left, control on
    the right, the way the Properties panel lays a node's params out.

    The pages used to be a vertical run of controls each with a paragraph of
    explanation under it, which grew unreadable as settings were added — a
    lot of scrolling, and no way to see what a page *contains* at a glance.
    The grid puts every setting on one line, and the explanation moves to
    the row's tooltip, which is where the Properties panel already keeps a
    param's description.

    Controls keep their objectName so `SettingsDialog.refresh_from` can
    still find them after a reset — a QTreeWidget's item widgets are
    ordinary children, so findChild reaches them unchanged.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderLabels(["Setting", "Value"])
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.header().setSectionResizeMode(QHeaderView.Interactive)
        self.header().setStretchLastSection(True)
        self.setColumnWidth(0, 250)
        self.setSelectionMode(QTreeWidget.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)   # the controls take focus, not rows
        #: (row, group title, searchable text) for every setting on the page
        self.settings: list[tuple] = []
        #: group titles in declaration order, for the nav tree
        self._group_order: list[str] = []
        self._current_group = ""

    def add_group(self, title: str) -> None:
        """Open a group: record the name for the nav tree and tag the
        settings that follow. Draws nothing.

        Groups used to be tinted heading rows inside the page. Once the nav
        became a tree those headings said the same thing twice, and picking
        a group in the tree now narrows the page to it — so a divider
        between sections that are never shown together has nothing left to
        divide.
        """
        if title not in self._group_order:
            self._group_order.append(title)
        self._current_group = title

    def add(self, label: str, widget: QWidget, hint: str = "") -> QTreeWidgetItem:
        item = QTreeWidgetItem([label, ""])
        tip = wrapped_tooltip(hint or label)
        item.setToolTip(0, tip)
        item.setToolTip(1, tip)
        if hint and not widget.toolTip():
            widget.setToolTip(tip)
        self.addTopLevelItem(item)
        self.setItemWidget(item, 1, widget)
        # Rows are one text line tall by default, which clips anything
        # bigger. QSize needs a non-negative width to count as valid at all,
        # so the widget's own preferred width comes along for the ride even
        # though the column governs the actual width (see ParamsPanel).
        height = max(24, widget.sizeHint().height())
        item.setSizeHint(1, QSize(widget.sizeHint().width(), height))
        # the group title joins the haystack, so "snapping" finds the snap
        # settings and "colour strength" finds the pair under that heading
        self.settings.append((item, self._current_group,
                              f"{label} {hint} {self._current_group}".casefold()))
        return item

    # ------------------------------------------------- scoping + searching

    @staticmethod
    def _hit(entry, group: "str | None", needle: str) -> bool:
        _item, own_group, haystack = entry
        if group is not None and own_group != group:
            return False
        return not needle or needle in haystack

    def apply(self, group: "str | None" = None, search: str = "") -> int:
        """Show only the settings in `group` that match `search`.

        `group` of None means the whole page — what selecting the page
        itself gives you, rather than one of its groups. Returns how many
        rows are left showing.
        """
        needle = search.strip().casefold()
        shown = 0
        for entry in self.settings:
            hit = self._hit(entry, group, needle)
            entry[0].setHidden(not hit)
            shown += hit
        return shown

    def count(self, group: "str | None" = None, search: str = "") -> int:
        """How many settings *would* show, without touching the view."""
        needle = search.strip().casefold()
        return sum(self._hit(entry, group, needle) for entry in self.settings)

    def group_titles(self) -> list:
        return list(self._group_order)


class SettingsDialog(QDialog):
    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        # the shortcuts page reads back from the registry on a reset
        self._window = window
        # Wide enough that the grid never opens with a horizontal scrollbar.
        # The nav takes a fixed 180, the Setting column 250, and the value
        # column has to clear the widest control's own size hint or the view
        # decides its content is wider than its viewport — which at 560 it
        # was, by 18px, for a dialog with nothing to scroll to. It clears
        # from 620; this leaves headroom for a larger font.
        self.resize(720, 560)

        # The nav is a tree, not a flat list: a page's group headings appear
        # under it, so the whole of Settings is visible at a glance and a
        # group can be jumped to directly instead of scrolled for.
        self._nav = QTreeWidget()
        self._nav.setObjectName("settings_nav")
        self._nav.setHeaderHidden(True)
        self._nav.setFixedWidth(180)
        self._nav.setIndentation(12)

        self._search = QLineEdit()
        self._search.setObjectName("settings_search")
        self._search.setPlaceholderText("Search settings…")
        self._search.setClearButtonEnabled(True)

        self._pages = QStackedWidget()
        self._page_index: dict[str, int] = {}
        self._grids: dict[str, SettingsGrid] = {}

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.addWidget(self._search)
        side.addWidget(self._nav, 1)

        layout = QHBoxLayout(self)
        layout.addLayout(side)
        layout.addWidget(self._pages, 1)

        pages = {
            "General": self._build_general_page(window),
            "Canvas": self._build_canvas_page(window),
            "Keyboard Shortcuts": self._build_shortcuts_page(window),
            "Statistics": self._build_stats_page(window),
            "Table Node": self._build_table_node_page(),
            "About": self._build_about_page(),
        }
        for name in sorted(pages):
            self._add_page(name, pages[name])

        self._nav.currentItemChanged.connect(self._on_nav_changed)
        self._search.textChanged.connect(self._on_search)
        self._nav.setCurrentItem(self._nav.topLevelItem(0))

    def refresh_from(self, window) -> None:
        """Re-read every control from the window. The pages bind once at
        build time and live-apply from there, which is right for a user
        turning knobs — but a reset changes the values underneath an already
        open dialog, so it has to be pulled back into sync afterwards."""
        from .spreadsheet import autosize_default_enabled, date_formats_setting

        combo_values = {
            "page_bar_position_combo": ["bottom", "top"].index(
                window.page_bar_position),
            "double_click_action_combo": ["properties", "code",
                                          "rename"].index(
                window.double_click_action),
        }
        checks = {
            "titlebar_compact_checkbox": window.settings.value(
                "window/titlebar_compact", False, type=bool),
            "update_notify_checkbox": window.settings.value(
                "updates/notify", False, type=bool),
            "gpu_viewport_checkbox": window.action_gpu_viewport.isChecked(),
            "lod_enabled_checkbox": window.lod_enabled,
            "snap_enabled_checkbox": window.snap_enabled,
            "grid_visible_checkbox": window.grid_visible,
            "minimap_enabled_checkbox": window.minimap_enabled,
            "compact_nodes_checkbox": window.compact_nodes,
            "port_labels_checkbox": window.port_labels_enabled,
            "flow_pins_checkbox": window.flow_pins_enabled,
            "cache_compression_checkbox": window.cache_compression_enabled,
            "table_autosize_checkbox": autosize_default_enabled(),
            "stats_bar_checkbox": window.stats_bar_enabled,
            "stats_sampling_checkbox": window.stats_sampling_enabled,
        }
        spins = {
            "lod_threshold_spinbox": round(window.lod_threshold * 100),
            "tint_soft_spinbox": round(window.tint_soft * 100),
            "tint_strong_spinbox": round(window.tint_strong * 100),
            "stats_history_spinbox": window.stats_history_limit,
        }
        for name, value in {**combo_values, **checks, **spins}.items():
            widget = self.findChild(QWidget, name)
            if widget is None:
                continue
            # blocked: these setters exist to *push* user intent at the
            # window, and replaying them here would be a no-op at best
            blocked = widget.blockSignals(True)
            try:
                if name in combo_values:
                    widget.setCurrentIndex(value)
                elif name in checks:
                    widget.setChecked(value)
                else:
                    widget.setValue(value)
            finally:
                widget.blockSignals(blocked)

        reveal_edit = self.findChild(QKeySequenceEdit, "reveal_ports_key_edit")
        if reveal_edit is not None:
            blocked = reveal_edit.blockSignals(True)
            try:
                reveal_edit.setKeySequence(
                    QKeySequence(window.reveal_ports_key))
            finally:
                reveal_edit.blockSignals(blocked)

        grid_combo = self.findChild(QComboBox, "grid_step_combo")
        if grid_combo is not None:
            blocked = grid_combo.blockSignals(True)
            try:
                index = grid_combo.findData(window.grid_step)
                grid_combo.setCurrentIndex(max(0, index))
            finally:
                grid_combo.blockSignals(blocked)

        for name, value in (
                ("rubber_band_mode_combo", window.rubber_band_mode),
                ("rubber_band_invert_key_combo",
                 window.rubber_band_invert_key)):
            combo = self.findChild(QComboBox, name)
            if combo is None:
                continue
            blocked = combo.blockSignals(True)
            try:
                combo.setCurrentIndex(max(0, combo.findData(value)))
            finally:
                combo.blockSignals(blocked)

        formats_edit = self.findChild(QLineEdit, "table_date_formats_edit")
        if formats_edit is not None:
            blocked = formats_edit.blockSignals(True)
            try:
                formats_edit.setText(date_formats_setting())
            finally:
                formats_edit.blockSignals(blocked)

        # dependent enablement isn't re-derived by the setters above
        for check_name, dependent in (
                ("lod_enabled_checkbox", "lod_threshold_spinbox"),
                ("snap_enabled_checkbox", "grid_step_combo")):
            check = self.findChild(QWidget, check_name)
            target = self.findChild(QWidget, dependent)
            if check is not None and target is not None:
                target.setEnabled(check.isChecked())

    # ------------------------------------------------------ nav + search

    def page_names(self) -> list:
        """The top-level nav entries, in order."""
        return [self._nav.topLevelItem(i).text(0)
                for i in range(self._nav.topLevelItemCount())]

    def show_page(self, name: str) -> None:
        """Select `name` in the nav — for opening Settings straight onto a
        particular page (the update notice jumps to About this way)."""
        names = self.page_names()
        if name not in names:
            return
        self._search.clear()
        self._nav.setCurrentItem(self._nav.topLevelItem(names.index(name)))

    def _scope(self) -> tuple:
        """(page name, group or None) for whatever the nav has selected."""
        current = self._nav.currentItem()
        if current is None:
            return "", None
        parent = current.parent()
        if parent is None:
            return current.text(0), None
        return parent.text(0), current.text(0)

    def _on_nav_changed(self, current, _previous) -> None:
        """Show the selected page, narrowed to the selected group.

        Picking a group shows *only* that group's settings rather than
        scrolling to it — with the tree carrying the structure, a page that
        still listed everything made the tree decorative.
        """
        if current is None:
            return
        page_name, group = self._scope()
        index = self._page_index.get(page_name)
        if index is None:
            return
        self._pages.setCurrentIndex(index)
        grid = self._grids.get(page_name)
        if grid is not None:
            grid.apply(group, self._search.text())

    def _on_search(self, text: str) -> None:
        """Filter every page at once, and hide the nav entries that no
        longer lead anywhere — a category still listed but empty when you
        click it is worse than no result at all.

        A search is deliberately page-wide: it lands on the *page* of the
        first hit, not a group, because a match found under a group you had
        not selected would otherwise be hidden by that selection — the
        search would appear to find nothing.

        The About page has no settings to match, so it is judged on its own
        name; searching is for finding a control, and it holds none.
        """
        needle = text.strip().casefold()
        first_hit = None
        for i in range(self._nav.topLevelItemCount()):
            entry = self._nav.topLevelItem(i)
            name = entry.text(0)
            grid = self._grids.get(name)
            if grid is None:
                hit = not needle or needle in name.casefold()
            else:
                hit = grid.count(search=text) > 0
                for c in range(entry.childCount()):
                    child = entry.child(c)
                    child.setHidden(
                        not grid.count(child.text(0), search=text))
            entry.setHidden(not hit)
            if hit and first_hit is None:
                first_hit = entry
        current = self._nav.currentItem()
        if needle and first_hit is not None:
            self._nav.setCurrentItem(first_hit)
        elif current is not None and current.isHidden() \
                and first_hit is not None:
            self._nav.setCurrentItem(first_hit)
        # setCurrentItem is a no-op when it is already current, so the page
        # is re-filtered explicitly — otherwise clearing the box would leave
        # the last search's rows hidden
        self._on_nav_changed(self._nav.currentItem(), None)

    def _add_page(self, name: str, page: QWidget) -> None:
        entry = QTreeWidgetItem([name])
        self._nav.addTopLevelItem(entry)
        self._page_index[name] = self._pages.count()
        self._pages.addWidget(page)

        grid = page.findChild(SettingsGrid)
        if grid is not None:
            self._grids[name] = grid
            for title in grid.group_titles():
                entry.addChild(QTreeWidgetItem([title]))
            entry.setExpanded(True)

    @staticmethod
    def _hint(text: str) -> QLabel:
        """A de-emphasized description line under a control. Sized down
        rather than color-dimmed: a measured contrast check found palette
        roles meant for "dim" text (mid, placeholder-text) can drop well
        below readable contrast depending on the desktop theme, while
        full-contrast text at a smaller size reads as secondary everywhere."""
        label = QLabel(text)
        label.setWordWrap(True)
        font = label.font()
        font.setPointSizeF(font.pointSizeF() * 0.9)
        label.setFont(font)
        return label

    @staticmethod
    def _build_general_page(window) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        rows = SettingsGrid()
        layout.addWidget(rows, 1)

        rows.add_group("Window")

        page_bar_combo = QComboBox()
        page_bar_combo.setObjectName("page_bar_position_combo")
        positions = ["bottom", "top"]
        page_bar_combo.addItems([p.capitalize() for p in positions])
        page_bar_combo.setCurrentIndex(positions.index(window.page_bar_position))
        page_bar_combo.currentIndexChanged.connect(
            lambda index: window.set_page_bar_position(positions[index]))
        rows.add("Page bar position", page_bar_combo,
                 "Which edge of the window the Model/page tabs live on.")

        frame_check = QCheckBox("Use flograph's own title bar")
        frame_check.setObjectName("custom_frame_checkbox")
        frame_check.setChecked(window._custom_frame)
        frame_check.toggled.connect(window.set_custom_frame)
        rows.add("Custom window frame", frame_check,
                 "Replace the operating system's title bar with flograph's — "
                 "one bar holding the menu, the open workflow, the run "
                 "actions and the window buttons. Turn off to go back to the "
                 "native title bar and a separate toolbar. Takes effect when "
                 "you next start flograph.")

        compact_check = QCheckBox("Show only icons on the title-bar buttons")
        compact_check.setObjectName("titlebar_compact_checkbox")
        compact_check.setChecked(
            window.settings.value("window/titlebar_compact", False, type=bool))
        compact_check.toggled.connect(window.set_titlebar_compact)
        compact_check.setEnabled(window._custom_frame)
        rows.add("Compact title bar", compact_check,
                 "Drop the text labels from the Run and Save buttons on "
                 "flograph's title bar, keeping the icons — their tooltips "
                 "still say what they do. The workflow name stays. Only "
                 "applies with the custom window frame.")

        rows.add_group("Execution")

        workers_spin = QSpinBox()
        workers_spin.setObjectName("engine_workers_spinbox")
        workers_spin.setRange(0, 32)
        workers_spin.setSpecialValueText("Auto")
        workers_spin.setValue(window.engine_max_workers)
        workers_spin.valueChanged.connect(window.set_engine_max_workers)
        rows.add("Nodes to run at once", workers_spin,
                 "Branches of a flow that do not depend on each other can run "
                 "side by side. Auto picks a number from the machine's cores, "
                 "capped so that a wide flow does not try to hold every "
                 "branch's data in memory at once — lower it if a run is "
                 "using more memory than you have, raise it if the flow is "
                 "mostly waiting on files or the network. 1 runs one node at "
                 "a time, as flograph always did. A node whose code is not "
                 "safe beside others can opt out on its own: right-click it "
                 "and choose Run on its own.")

        rows.add_group("Saving")

        compress_check = QCheckBox("Compress cached results on disk")
        compress_check.setObjectName("cache_compression_checkbox")
        compress_check.setChecked(window.cache_compression_enabled)
        compress_check.toggled.connect(window.set_cache_compression_enabled)
        rows.add("Compress cache", compress_check,
                 "Cached results live in a folder beside the project file. "
                 "Compressed they take a fraction of the room — most for "
                 "tables with text in them — at the cost of a little extra "
                 "time when saving. Turn off if you would rather have raw "
                 "speed; blobs already written either way keep working, and "
                 "old projects read as they always did.")

        rows.add_group("Updates")

        notify_check = QCheckBox("Tell me when a new version is available")
        notify_check.setObjectName("update_notify_checkbox")
        notify_check.setChecked(
            window.settings.value("updates/notify", False, type=bool))
        notify_check.toggled.connect(
            lambda on: window.settings.setValue("updates/notify", bool(on)))
        rows.add("Check for updates", notify_check,
                 "Once a day when flograph starts, check your package index "
                 "for a newer flograph and show a small notice in the corner "
                 "if there is one. Off by default. The check only reads "
                 "version numbers — it never installs anything — and it asks "
                 "the same index you already install from, so it works "
                 "behind a private mirror and stays silent when there is no "
                 "connection. You can also check on demand from the About "
                 "page.")

        rows.add_group("Reset")

        # short labels: in a grid the row name carries the noun, and a
        # button captioned with a whole sentence overflows its column
        layout_btn = QPushButton("Reset…")
        layout_btn.setObjectName("reset_layout_button")
        layout_btn.clicked.connect(
            lambda: SettingsDialog._confirm_reset(page, window, layout=True))
        rows.add("Window layout", layout_btn,
                 "Puts the Library, Properties, Code, Inspector and Log "
                 "panels back where they start, without touching anything "
                 "else. Use this when a panel has been dragged somewhere "
                 "unrecoverable.")

        all_btn = QPushButton("Reset…")
        all_btn.setObjectName("reset_settings_button")
        all_btn.clicked.connect(
            lambda: SettingsDialog._confirm_reset(page, window, layout=False))
        rows.add("All settings", all_btn,
                 "Clears every stored preference — everything on these pages, "
                 "the window layout, the AI assistant settings and the recent "
                 "files list — and applies the defaults straight away. Your "
                 "saved projects are not touched.")

        return page

    @staticmethod
    def _confirm_reset(parent: QWidget, window, layout: bool) -> None:
        """Both resets throw away something the user configured by hand, and
        neither is undoable, so both ask first."""
        if layout:
            title, question = ("Reset window layout",
                               "Put every panel back where it starts?")
        else:
            title, question = (
                "Reset all settings",
                "Clear every stored preference — including the AI settings "
                "and the recent files list — and go back to defaults?\n\n"
                "Saved projects are not affected.")
        confirmed = QMessageBox.question(
            parent, title, question,
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if confirmed != QMessageBox.Yes:
            return
        if layout:
            window.reset_window_layout()
        else:
            window.reset_settings()

    @staticmethod
    def _build_canvas_page(window) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        rows = SettingsGrid()
        layout.addWidget(rows, 1)

        rows.add_group("Display")

        gpu_check = QCheckBox()
        gpu_check.setObjectName("gpu_viewport_checkbox")
        gpu_check.setChecked(window.action_gpu_viewport.isChecked())
        # bind both ways: the checkbox drives the action, and an automatic
        # fallback revert (GL unavailable) drives the checkbox back
        gpu_check.toggled.connect(window.action_gpu_viewport.setChecked)
        window.action_gpu_viewport.toggled.connect(gpu_check.setChecked)
        rows.add("GPU-accelerated canvas (experimental)", gpu_check,
                 "Renders the canvas through OpenGL instead of software "
                 "rasterizing. Off by default; falls back automatically if "
                 "this machine can't provide a working GL context. If a card "
                 "(figure/table/webview) looks wrong after enabling, switch "
                 "it back.")

        lod_check = QCheckBox()
        lod_check.setObjectName("lod_enabled_checkbox")
        lod_check.setChecked(window.lod_enabled)
        rows.add("Simplify nodes when zoomed out", lod_check,
                 "Below the zoom threshold, nodes hide their ports and "
                 "embedded widgets (tables/figures) and paint as a flat "
                 "rectangle — keeps large graphs responsive when zoomed way "
                 "out. Turn off to always render full detail, at the cost of "
                 "that speed.")

        threshold_spin = QSpinBox()
        threshold_spin.setObjectName("lod_threshold_spinbox")
        # 10% is the canvas's minimum zoom (ZOOM_MIN in base_view.py) — below
        # that is a dead value, never reachable. 100% is the normal working
        # view — above that would blank nodes even at everyday zoom, which
        # reads as broken rather than a deliberate "simplify aggressively"
        # choice, so it's left out of the range entirely.
        threshold_spin.setRange(10, 100)
        threshold_spin.setSingleStep(5)
        threshold_spin.setSuffix("%")
        threshold_spin.setValue(round(window.lod_threshold * 100))
        threshold_spin.setEnabled(lod_check.isChecked())
        rows.add("Zoom threshold", threshold_spin,
                 "Simplify nodes below this zoom level (100% = actual size).")

        minimap_check = QCheckBox()
        minimap_check.setObjectName("minimap_enabled_checkbox")
        minimap_check.setChecked(window.minimap_enabled)
        rows.add("Show minimap", minimap_check,
                 "A small overlay in the canvas corner showing all nodes and "
                 "the current viewport — click or drag on it to jump around "
                 "a large graph.")

        compact_check = QCheckBox()
        compact_check.setObjectName("compact_nodes_checkbox")
        compact_check.setChecked(window.compact_nodes)
        rows.add("Compact nodes", compact_check,
                 "Draw ordinary nodes — the ones that are only a step in the "
                 "pipeline, with nothing to show — as a small fixed square "
                 "carrying a mark, with the node's name above it and its "
                 "status light below. Every one is the same size, so the "
                 "canvas reads as the shape of the graph rather than a row "
                 "of differently-sized boxes. Charts, tables and the other "
                 "cards are unaffected: their content is the point of them. "
                 "Turn this off for the older wide box, which prints the "
                 "port names inside the node.")

        ports_check = QCheckBox()
        ports_check.setObjectName("port_labels_checkbox")
        ports_check.setChecked(window.port_labels_enabled)
        rows.add("Show port names", ports_check,
                 "Card nodes (charts, tables, reports) have no room to print "
                 "their port names, so a node with several inputs is a row of "
                 "identical pins. Turn this on to float each name beside its "
                 "pin — inputs to the left, outputs to the right. You can "
                 "also show or hide them for one node at a time by "
                 "right-clicking it, which overrides this setting for that "
                 "node.")

        flow_check = QCheckBox()
        flow_check.setObjectName("flow_pins_checkbox")
        flow_check.setChecked(window.flow_pins_enabled)
        rows.add("Show flow pins", flow_check,
                 "Every node has a small pin off each of its upper corners. "
                 "A wire between two of them is an order edge: it carries no "
                 "data and says only \"run this node after that one\". They "
                 "are hidden unless something is wired to them, since most "
                 "flows never need one — turn this on to keep them in view, "
                 "hold the reveal key above to see them for a moment, or set "
                 "them per node from its Appearance dialog.")

        bars_check = QCheckBox()
        bars_check.setObjectName("scrollbars_checkbox")
        bars_check.setChecked(window.scrollbars_enabled)
        rows.add("Show scroll bars", bars_check,
                 "Horizontal and vertical bars along the canvas edges, "
                 "showing where you are in a large flow and draggable to "
                 "move around. The canvas pans by drag and wheel either way; "
                 "this only adds the bars. Applies to dashboard pages too.")

        dclick_combo = QComboBox()
        dclick_combo.setObjectName("double_click_action_combo")
        for label, value in (("Properties", "properties"), ("Code", "code"),
                             ("Rename", "rename")):
            dclick_combo.addItem(label, value)
        dclick_combo.setCurrentIndex(
            max(0, dclick_combo.findData(window.double_click_action)))
        rows.add("Double-click a node opens", dclick_combo,
                 "What double-clicking a node's body brings up. Its *name* "
                 "always renames, whatever this says — that is what a label "
                 "is for. Notes and buttons always open their properties, "
                 "since their text is a parameter rather than code. "
                 "Ctrl+double-click any node to get both at once in a window "
                 "of its own, which you can leave open beside another "
                 "node's.")

        reveal_edit = QKeySequenceEdit()
        reveal_edit.setObjectName("reveal_ports_key_edit")
        reveal_edit.setMaximumSequenceLength(1)
        reveal_edit.setKeySequence(QKeySequence(window.reveal_ports_key))
        rows.add("Hold to show port names", reveal_edit,
                 "Hold this key over the canvas and every port name appears "
                 "for as long as you hold it, whatever the setting above "
                 "says and whatever any individual node has been set to; let "
                 "go and they all go back to how they were. Nothing is saved "
                 "— it is a look, not a change. A plain key rather than a "
                 "modifier, because Alt belongs to the menu bar; avoid the "
                 "ones the canvas already uses (F frames the selection, Tab "
                 "opens the node search, Space pans).")

        rows.add_group("Drag-select")

        band_combo = QComboBox()
        band_combo.setObjectName("rubber_band_mode_combo")
        for label, value in (
                ("Anything the band touches", "touch"),
                ("Frames only when fully inside", "frames"),
                ("Only what is fully inside", "contain")):
            band_combo.addItem(label, value)
        band_combo.setCurrentIndex(
            max(0, band_combo.findData(window.rubber_band_mode)))
        rows.add("Drag-select catches", band_combo,
                 "How much of an item a rubber band has to cover to select "
                 "it. Touching takes anything the band grazes, which is the "
                 "quickest way to sweep up a row of nodes but also means a "
                 "band drawn inside a frame picks up the frame — and a "
                 "selected frame drags its whole block along, so the next "
                 "move is to Ctrl-click it back off. The middle setting "
                 "keeps the graze for nodes and asks a band to go right "
                 "round a frame before it counts, which is the only place "
                 "the difference bites. The last one asks it of everything, "
                 "so a node half out of the band is left behind too.")

        band_key_combo = QComboBox()
        band_key_combo.setObjectName("rubber_band_invert_key_combo")
        for label, value in (("Ctrl", "ctrl"), ("Alt", "alt"),
                             ("Shift", "shift"), ("Nothing", "none")):
            band_key_combo.addItem(label, value)
        band_key_combo.setCurrentIndex(
            max(0, band_key_combo.findData(window.rubber_band_invert_key)))
        rows.add("Hold for the other rule", band_key_combo,
                 "Hold this as you start the drag and that one band goes by "
                 "the opposite rule: from either of the stricter settings it "
                 "takes everything it crosses — the way the canvas has "
                 "always behaved — and from the loosest it takes only what "
                 "it goes right round. It is live rather than decided at the "
                 "press: press the key part way through a drag and the frame "
                 "you are over joins the selection, let go and it drops out "
                 "again, without moving the mouse. Ctrl and Shift also mean "
                 "*add to what is already selected* during a drag-select, so "
                 "holding one does both at once — with Ctrl that is a single "
                 "gesture, add everything I brush. Alt has no other job "
                 "here, if you would rather keep the two apart.")

        rows.add_group("Snapping")

        grid_check = QCheckBox()
        grid_check.setObjectName("grid_visible_checkbox")
        grid_check.setChecked(window.grid_visible)
        rows.add("Show grid", grid_check,
                 "Draw the background grid on the canvas and dashboard pages. "
                 "Turning it off is purely cosmetic — snapping below is a "
                 "separate setting and keeps working.")

        snap_check = QCheckBox()
        snap_check.setObjectName("snap_enabled_checkbox")
        snap_check.setChecked(window.snap_enabled)
        rows.add("Snap to grid", snap_check,
                 "Snap moves and resizes to the grid (hold Ctrl to bypass). "
                 "Applies to node/frame moves and resizes on the canvas and "
                 "to dashboard tiles.")

        grid_combo = QComboBox()
        grid_combo.setObjectName("grid_step_combo")
        selected = 0
        for index, (name, step) in enumerate(grid.GRID_PRESETS.items()):
            grid_combo.addItem(f"{name} ({int(step)} px)", step)
            if abs(step - window.grid_step) < 0.01:
                selected = index
        grid_combo.setCurrentIndex(selected)
        grid_combo.setEnabled(snap_check.isChecked())
        rows.add("Grid resolution", grid_combo,
                 "How far apart the snap points are.")

        rows.add_group("Custom colour strength")

        soft_spin = QSpinBox()
        soft_spin.setObjectName("tint_soft_spinbox")
        soft_spin.setRange(0, 100)
        soft_spin.setSingleStep(5)
        soft_spin.setSuffix("%")
        soft_spin.setValue(round(window.tint_soft * 100))
        rows.add("Card body, unselected tab", soft_spin,
                 "Colours you pick for nodes, frames and dashboard page tabs "
                 "are laid over the theme rather than painted flat, so they "
                 "come out muted instead of garish. Raise this to let more of "
                 "the picked colour through on large surfaces; 100% paints it "
                 "raw.")

        strong_spin = QSpinBox()
        strong_spin.setObjectName("tint_strong_spinbox")
        strong_spin.setRange(0, 100)
        strong_spin.setSingleStep(5)
        strong_spin.setSuffix("%")
        strong_spin.setValue(round(window.tint_strong * 100))
        rows.add("Node header, selected tab", strong_spin,
                 "The same muting for the smaller strip that has to stand out "
                 "from the body.")

        def _push_tints() -> None:
            window.set_tints(soft_spin.value() / 100.0,
                             strong_spin.value() / 100.0)

        lod_check.toggled.connect(window.set_lod_enabled)
        lod_check.toggled.connect(threshold_spin.setEnabled)
        threshold_spin.valueChanged.connect(
            lambda value: window.set_lod_threshold(value / 100.0))
        minimap_check.toggled.connect(window.set_minimap_enabled)
        def _push_reveal_key(sequence) -> None:
            """A capture field yields a whole QKeySequence; the view compares
            one key code, so take the first chord's key and drop whatever
            modifiers were held with it."""
            if not sequence.count():
                return
            chord = sequence[0]
            key = chord.key() if hasattr(chord, "key") else int(chord)
            window.set_reveal_ports_key(int(key))

        compact_check.toggled.connect(window.set_compact_nodes)
        ports_check.toggled.connect(window.set_port_labels_enabled)
        flow_check.toggled.connect(window.set_flow_pins_enabled)
        bars_check.toggled.connect(window.set_scrollbars_enabled)
        reveal_edit.keySequenceChanged.connect(_push_reveal_key)
        dclick_combo.currentIndexChanged.connect(
            lambda index: window.set_double_click_action(
                dclick_combo.itemData(index)))
        grid_check.toggled.connect(window.set_grid_visible)
        band_combo.currentIndexChanged.connect(
            lambda index: window.set_rubber_band_mode(
                band_combo.itemData(index)))
        band_key_combo.currentIndexChanged.connect(
            lambda index: window.set_rubber_band_invert_key(
                band_key_combo.itemData(index)))
        snap_check.toggled.connect(window.set_snap_enabled)
        snap_check.toggled.connect(grid_combo.setEnabled)
        grid_combo.currentIndexChanged.connect(
            lambda index: window.set_grid_step(grid_combo.itemData(index)))
        soft_spin.valueChanged.connect(lambda _value: _push_tints())
        strong_spin.valueChanged.connect(lambda _value: _push_tints())

        return page

    @staticmethod
    def _build_stats_page(window) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        rows = SettingsGrid()
        layout.addWidget(rows, 1)

        rows.add_group("Status bar")

        bar_check = QCheckBox()
        bar_check.setObjectName("stats_bar_checkbox")
        bar_check.setChecked(window.stats_bar_enabled)
        bar_check.toggled.connect(window.set_stats_bar_enabled)
        rows.add("Show the memory bar", bar_check,
                 "The layered bar beside the memory figures: the project's "
                 "cached outputs inside the flograph process inside the "
                 "whole machine. Turning it off leaves the numbers and the "
                 "run timings, which stay clickable.")

        rows.add_group("Measurement")

        sample_check = QCheckBox()
        sample_check.setObjectName("stats_sampling_checkbox")
        sample_check.setChecked(window.stats_sampling_enabled)
        sample_check.toggled.connect(window.set_stats_sampling_enabled)
        rows.add("Sample memory while nodes run", sample_check,
                 "Reads the process's resident size ten times a second "
                 "during a run and records the peak against whichever node "
                 "was running. This is what catches a step that briefly "
                 "builds something enormous and returns something small. "
                 "Off, the statistics window still reports times and output "
                 "sizes, just not peaks.")

        history_spin = QSpinBox()
        history_spin.setObjectName("stats_history_spinbox")
        history_spin.setRange(1, 200)
        history_spin.setValue(window.stats_history_limit)
        history_spin.valueChanged.connect(window.set_stats_history_limit)
        rows.add("Runs to remember", history_spin,
                 "How many past runs the statistics window keeps, so a node "
                 "that is getting slower can be seen doing it. Held in "
                 "memory for this session only — nothing is written beside "
                 "your project.")

        return page

    def _build_shortcuts_page(self, window) -> QWidget:
        """One row per command: what it does, and the key that does it.

        Live-apply like every other page -- a captured key takes effect on
        the action immediately, with no Save step. The exception is a clash:
        two actions on one key makes Qt fire neither, so a duplicate is
        refused and said so, rather than quietly breaking both commands.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        rows = SettingsGrid()
        layout.addWidget(rows, 1)

        note = QLabel()
        note.setObjectName("shortcut_conflict_note")
        note.setWordWrap(True)
        note.setStyleSheet("color: #c0392b;")
        note.hide()
        layout.addWidget(note)

        self._shortcut_editors: dict[str, QKeySequenceEdit] = {}
        registry = window.shortcuts

        for group in registry.groups():
            rows.add_group(group)
            for entry in registry.entries():
                if entry.group != group:
                    continue
                rows.add(entry.label, self._shortcut_row(registry, entry, note),
                         f"Keyboard shortcut for {entry.label}. Click the "
                         f"field and press the keys you want. Clear it to "
                         f"leave the command available from the menu only.")

        rows.add_group("All shortcuts")
        reset_all = QPushButton("Restore defaults")
        reset_all.setObjectName("shortcuts_reset_all_button")
        reset_all.clicked.connect(registry.reset_all)
        rows.add("Put every shortcut back", reset_all,
                 "Discards every rebind on this page and returns each "
                 "command to the key it shipped with.")

        # the registry is the source of truth: a reset (here or from Reset
        # Settings) has to pull the fields back into line with it
        registry.changed.connect(self._sync_shortcut_editors)
        return page

    def _shortcut_row(self, registry, entry, note) -> QWidget:
        """A capture field plus its own reset, side by side in one cell."""
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        edit = QKeySequenceEdit(entry.binding())
        edit.setObjectName(f"shortcut_edit_{entry.key}")
        # one chord, not a Qt-style multi-step sequence: every shortcut in
        # the app is a single combination, and capturing four of them by
        # accident is a confusing way to lose a binding
        edit.setMaximumSequenceLength(1)
        self._shortcut_editors[entry.key] = edit

        revert = QToolButton()
        revert.setObjectName(f"shortcut_reset_{entry.key}")
        revert.setText("↺")
        revert.setAutoRaise(True)
        revert.setToolTip("Back to the default key")
        revert.clicked.connect(lambda _=False, key=entry.key: registry.reset(key))

        def commit(key=entry.key, field=edit) -> None:
            clash = registry.set_binding(key, field.keySequence())
            if clash is None:
                note.hide()
                return
            note.setText(
                f"{field.keySequence().toString()} is already {clash}'s "
                f"shortcut. Change that one first, or pick another key.")
            note.show()
            # put the field back: leaving the refused key sitting in it
            # would read as though it had been accepted
            field.setKeySequence(registry.entry(key).binding())

        edit.editingFinished.connect(commit)

        row.addWidget(edit, 1)
        row.addWidget(revert)
        return holder

    def _sync_shortcut_editors(self) -> None:
        registry = self._window.shortcuts
        for key, edit in self._shortcut_editors.items():
            entry = registry.entry(key)
            if entry is not None:
                edit.setKeySequence(entry.binding())

    @staticmethod
    def _build_table_node_page() -> QWidget:
        from .spreadsheet import (autosize_default_enabled,
                                  date_formats_setting, set_autosize_default,
                                  set_date_formats_setting)

        page = QWidget()
        layout = QVBoxLayout(page)
        rows = SettingsGrid()
        layout.addWidget(rows, 1)

        autosize_check = QCheckBox()
        autosize_check.setObjectName("table_autosize_checkbox")
        autosize_check.setChecked(autosize_default_enabled())
        autosize_check.toggled.connect(set_autosize_default)
        rows.add("Auto-size columns to content by default", autosize_check,
                 "Table cards and the pop-out editor re-fit every column to "
                 "its content and header after each edit. When off, columns "
                 "keep the widths you drag or fit manually, which are saved "
                 "with the node. Open grids pick the change up on their next "
                 "edit.")

        formats_edit = QLineEdit()
        formats_edit.setObjectName("table_date_formats_edit")
        formats_edit.setPlaceholderText("%d-%b-%y, %d/%m/%Y")
        formats_edit.setText(date_formats_setting())
        formats_edit.textChanged.connect(set_date_formats_setting)
        rows.add("Custom date formats", formats_edit,
                 "Extra date formats for the Table node's date columns, "
                 "comma-separated, in Python strptime notation (%d day, "
                 "%m month number, %b month name, %y two-digit year, "
                 "%Y four-digit year — e.g. 07-Mar-12 is %d-%b-%y). Tried "
                 "before the built-in formats when validating cells and when "
                 "converting a column to the date type, so they win for "
                 "ambiguous dates.")

        return page

    @staticmethod
    def _build_about_page() -> QWidget:
        from flograph import packages

        from . import update_check

        page = QWidget()
        layout = QVBoxLayout(page)

        name_label = QLabel("flograph")
        font = name_label.font()
        font.setPointSizeF(font.pointSizeF() * 1.6)
        font.setBold(True)
        name_label.setFont(font)
        layout.addWidget(name_label)

        layout.addWidget(QLabel(f"Version {_flograph_version()}"))
        layout.addSpacing(8)
        layout.addWidget(SettingsDialog._hint(
            "Visual node-based Python programming environment "
            "(flow-based dataflow, Blueprint-style canvas)."))

        layout.addSpacing(12)
        check_btn = QPushButton("Check for updates")
        check_btn.setObjectName("check_updates_button")
        layout.addWidget(check_btn, 0, Qt.AlignLeft)

        result = QLabel("")
        result.setObjectName("update_result_label")
        result.setWordWrap(True)
        result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(result)

        def on_result(current: str, latest, newer: bool) -> None:
            try:
                check_btn.setEnabled(True)
                if latest is None:
                    result.setText("Couldn't check for updates — no answer "
                                   "from the package index.")
                elif newer:
                    result.setText(
                        f"flograph {latest} is available (you have "
                        f"{current}).\n{packages.upgrade_hint()}\n"
                        "— or use Tools ▸ Manage Packages. Restart "
                        "flograph afterwards.")
                else:
                    result.setText(
                        f"You're on the latest version ({current}).")
            except RuntimeError:
                pass                     # dialog closed before the probe ended

        def do_check() -> None:
            check_btn.setEnabled(False)
            result.setText("Checking…")
            update_check.run_probe(on_result)

        check_btn.clicked.connect(do_check)

        layout.addSpacing(16)
        layout.addWidget(SettingsDialog._hint(
            f"Python {platform.python_version()}  ·  Qt {qVersion()}"))
        layout.addWidget(SettingsDialog._hint(
            "MIT License — https://github.com/redthista/flograph"))

        layout.addStretch(1)
        return page
