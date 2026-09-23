"""Read-only data tables you can copy out of.

The sheet page has had a proper clipboard for a while — TSV for anything,
HTML for Excel's rich paste, and an internal format so formulas survive an
in-app round trip. The *data* tables did not: the views on node cards,
dashboard tiles and the inspector were plain QTableViews, and Qt gives those
no copy handling whatsoever. Ctrl+C did nothing, and the column names — the
thing you most want when the destination is a spreadsheet — could not be
got out at all.

One subclass serves all four places rather than four sets of key handling.
It puts both flavours on the clipboard at once, so a text editor gets tab-
separated values and Excel gets a real table.

Values are taken from `Qt.EditRole`, falling back to `Qt.DisplayRole`. That
distinction is the whole reason a copy is not just a screen scrape: the
display rounds floats to six significant figures so a column reads cleanly,
and pasting those into a spreadsheet would silently discard precision from
every number in the table.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QEvent, QItemSelection, QItemSelectionModel, QObject, QSettings, Qt,
    QTimer, Signal,
)
from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QHeaderView, QMenu, QMessageBox, QStyleOptionViewItem, QTableView,
    QToolTip,
)

from flograph.core import perf
from flograph.core.table_picks import Picks, parse_picks

from .spreadsheet.clipboard import block_to_html, block_to_tsv

# Above this, copying the whole table is worth a confirmation: a few million
# cells is a string of hundreds of megabytes and a noticeable pause, and
# nobody means to do it by mistake.
CONFIRM_ROWS = 50_000

# Column-fit bounds for the read-only view. A column is sized to the wider of
# its header and its visible content, then held between these: MIN keeps a
# column of short values wide enough to still show its name, MAX stops one
# long value or a long header from eating the whole viewport.
MIN_COL_WIDTH = 52
MAX_COL_WIDTH = 360
#: A column drawn as a bar with its value hidden (`units bar blue only`)
#: has no text to be sized from, and would otherwise fit to its header —
#: leaving the bar, which is the entire point of the column, a few pixels
#: long. Wide enough for the difference between two lengths to read.
BAR_ONLY_WIDTH = 110
#: A sparkline beside a value, and one standing on its own (in a column
#: of its own, or on a line above or below the value). Alone it takes the
#: cell's width, so the column is what decides how long the line reads.
SPARK_BESIDE_WIDTH = 64
SPARK_ALONE_WIDTH = 120
#: How tall a picture with no size of its own is measured at — a line.
PICTURE_LINE_HEIGHT = 18
# How many of the paged-in rows the content measure samples. The model is
# lazy (500-row pages), and measuring every cell through the item delegate
# costs ~190 ms for a wide frame — far too much to spend on every graph run
# for every table card. A sample of the first rows sizes a column well
# enough; a stray wide value further down is a manual drag away.
FIT_SAMPLE_ROWS = 50

_ORG = "flograph"
_APP = "flograph"
#: Settings ▸ General ▸ Appearance ▸ Data text size: the point size for
#: every read-only data table.
TEXT_SIZE_SETTING = "tables/text_size_pt"
#: What the shared grid look has always used, and so what "Default" means
#: for a table on a card, a tile or the sheet's toolbar preview.
GRID_FONT_PT = 8.5
#: What Smaller/Larger on the table's own menu will go down and up to.
MIN_TEXT_PT = 5.0
MAX_TEXT_PT = 20.0
#: Step for one Smaller/Larger.
TEXT_PT_STEP = 0.5
#: Room a row needs beyond the text itself. Qt's own default section size
#: is generous — deliberately, for a touch-sized list — and a data table
#: asked to fit more on screen wants the tighter one.
ROW_PADDING = 5
#: How long a selection has to sit still before it is committed as a pick.
#: Long enough that Ctrl+clicking three cells is one re-run, not three.
PICK_SETTLE_MS = 200


class _TextSizeNotifier(QObject):
    """One signal every open data table listens to, so changing the size in
    Settings re-fonts what is already on screen instead of only the next
    table built."""
    changed = Signal()


_text_size_notifier = _TextSizeNotifier()


def table_text_size() -> float:
    """The configured point size for data tables, or 0.0 for "whatever the
    theme picks" — which is the app font in the inspector and GRID_FONT_PT
    on a card or tile."""
    try:
        return float(QSettings(_ORG, _APP).value(TEXT_SIZE_SETTING, 0.0) or 0.0)
    except (TypeError, ValueError):      # a hand-edited settings file
        return 0.0


def set_table_text_size(points: float) -> None:
    """Store the size and push it at every table already open."""
    QSettings(_ORG, _APP).setValue(TEXT_SIZE_SETTING, float(points))
    _text_size_notifier.changed.emit()


def cell_text(index) -> str:
    """One cell as it should land on the clipboard."""
    value = index.data(Qt.EditRole)
    if value is None:
        value = index.data(Qt.DisplayRole)
    return "" if value is None else str(value)


def headers_for(model, columns: list[int]) -> list[str]:
    """The header row a copy carries: the columns' real names.

    A `label` rule renames a header on screen, and the values below it are
    copied raw — so pairing the presentation header with the real values
    would produce a block that says one thing and means another.
    """
    real = getattr(model, "column_name", None)
    if real is not None:
        return [str(real(col)) for col in columns]
    return [str(model.headerData(col, Qt.Horizontal, Qt.DisplayRole) or "")
            for col in columns]


def selection_block(view: QTableView, with_headers: bool) -> list[list[str]]:
    """The selected cells as a rectangle of strings.

    A gappy selection is compacted to the rows and columns that were
    actually selected, so picking rows 1 and 4 copies them next to each
    other rather than dragging along the rows between. Cells inside that
    grid which were not selected come out blank. This is what a spreadsheet
    does, and the alternative — refusing — is an error message about
    something the user cannot see they did.
    """
    indexes = view.selectionModel().selectedIndexes() if view.selectionModel() else []
    if not indexes:
        return []
    rows = sorted({i.row() for i in indexes})
    columns = sorted({i.column() for i in indexes})
    model = view.model()
    picked = {(i.row(), i.column()): cell_text(i) for i in indexes}
    block = [[picked.get((row, col), "") for col in columns] for row in rows]
    if with_headers:
        block.insert(0, headers_for(model, columns))
    return block


def whole_block(view: QTableView, with_headers: bool = True) -> list[list[str]]:
    """Every row of the model, headers included.

    Goes to the source frame when the model exposes one, because the model
    itself only knows about the rows it has paged in — copying "the whole
    table" off a lazily loaded view would otherwise hand back the first
    five hundred rows and say nothing about it.
    """
    model = view.model()
    if model is None:
        return []
    frame = getattr(model, "dataframe", None)
    if callable(frame):
        return _frame_block(frame(), with_headers)
    columns = list(range(model.columnCount()))
    block = [[cell_text(model.index(row, col)) for col in columns]
             for row in range(model.rowCount())]
    if with_headers:
        block.insert(0, headers_for(model, columns))
    return block


def _frame_block(df, with_headers: bool) -> list[list[str]]:
    block = [["" if v is None else str(v) for v in row]
             for row in df.astype(object).where(df.notna(), None).values.tolist()]
    if with_headers:
        block.insert(0, [str(c) for c in df.columns])
    return block


def put_on_clipboard(block: list[list[str]]) -> bool:
    """Both formats at once. False when there was nothing to copy."""
    if not block:
        return False
    from PySide6.QtCore import QMimeData

    data = QMimeData()
    data.setText(block_to_tsv(block))
    data.setHtml(block_to_html(block))
    clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        return False
    clipboard.setMimeData(data)
    return True


def full_row_count(view: QTableView) -> int:
    model = view.model()
    if model is None:
        return 0
    frame = getattr(model, "dataframe", None)
    return len(frame()) if callable(frame) else model.rowCount()


def tooltip_host(widget, global_pos):
    """The widget a tooltip at `global_pos` should be shown against.

    Normally `widget` itself. But a table on a canvas card or a dashboard
    tile is embedded in a QGraphicsProxyWidget and has no window of its
    own, and a tooltip shown against it is placed as if it had none — on
    Wayland, at the top of the page (AA3). The graphics view drawing the
    card is a real window, and the pointer's position is already in its
    terms, so the tooltip is shown against that view instead.
    """
    proxy = widget.window().graphicsProxyWidget()
    scene = proxy.scene() if proxy is not None else None
    if scene is None:
        return widget
    views = scene.views()
    # the canvas's minimap is a second view of the same scene: take the
    # one the pointer is actually over
    for view in views:
        viewport = view.viewport()
        if viewport.rect().contains(viewport.mapFromGlobal(global_pos)):
            return viewport
    return views[0].viewport() if views else widget


#: How wide a tooltip is allowed to get, in characters. A cell can hold a
#: paragraph, and a tooltip of one long line is drawn as one long line —
#: Qt word-wraps a tooltip only when its text might be rich text, and a
#: value out of a table is not rich text and must not be treated as any
#: (it is somebody's data, and `<b>` in a cell is a `<b>` in a cell).
#: So the wrapping is done here, in characters rather than pixels, which
#: is the unit the text is in and needs no font to measure.
TOOLTIP_WRAP = 72


def wrap_tooltip(text: str, width: int = TOOLTIP_WRAP) -> str:
    """A tooltip broken into lines no wider than `width`.

    Paragraphs are kept — the cut-short value is offered under the note a
    rule wrote, with a blank line between them, and that blank line is
    what says they are two different things. A word longer than the whole
    width (a URL, an id) is broken rather than allowed to run off the
    screen, which is the case the wrapping exists for.
    """
    import textwrap
    lines: list = []
    for paragraph in str(text).split("\n"):
        lines.extend(textwrap.wrap(paragraph, width,
                                   break_long_words=True,
                                   break_on_hyphens=False) or [""])
    return "\n".join(lines)


def show_tooltip(global_pos, text: str, widget) -> None:
    QToolTip.showText(global_pos, wrap_tooltip(text),
                      tooltip_host(widget, global_pos))


class TooltipHeader(QHeaderView):
    """The column header, showing its tooltip where the pointer is — see
    `tooltip_host` for why a plain QHeaderView cannot, on a card."""

    def viewportEvent(self, event) -> bool:
        if event.type() != QEvent.ToolTip:
            return super().viewportEvent(event)
        model = self.model()
        logical = self.logicalIndexAt(event.pos())
        text = (model.headerData(logical, self.orientation(), Qt.ToolTipRole)
                if model is not None and logical >= 0 else None)
        if text:
            show_tooltip(event.globalPos(), str(text), self.viewport())
        else:
            QToolTip.hideText()
        return True


class DataTableView(QTableView):
    """A read-only table that answers Ctrl+C and offers a copy menu.

    Ctrl+C on a selection copies that selection, and includes the column
    names when the selection spans whole columns — selecting three cells in
    the middle of a frame does not want a header row, and selecting a
    column plainly does. With nothing selected it copies the whole table,
    headers and all, which is the case the menu is really there for.

    On a Show Table set to filter on click, the selection is also a *pick*
    (see core/table_picks.py): `picks_committed` carries it out as the
    node's `selected` text, and `set_picks` puts one back after a run.
    """

    #: The table's pick changed — the new `selected` text, "" for none.
    #: Only ever emitted once set_pick_mode has turned picking on.
    picks_committed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        # Draws data bars and icon glyphs when the model carries a
        # conditional-format style; a pure pass-through otherwise, so this is
        # harmless on the inspector / spec views that never have one.
        from .table_delegate import ConditionalFormatDelegate
        self.setItemDelegate(ConditionalFormatDelegate(self))

        # Replaced before anything attaches to it. Set up the way QTableView
        # sets up its own: clickable, and lighting up with the selection.
        header = TooltipHeader(Qt.Horizontal, self)
        header.setSectionsClickable(True)
        header.setHighlightSections(True)
        self.setHorizontalHeader(header)

        from .table_sort import HeaderSortCycler
        self._sort_cycler = HeaderSortCycler(self.horizontalHeader())
        self._sort_cycler.sortRequested.connect(self._sort_requested)

        # Click to filter. Off until a Show Table's card turns it on, so the
        # inspector's and every other data table keep a plain selection.
        self._pick_mode = "nothing"
        self._pick_by = "cell"             # or "row": a click takes the row
        self._picks_text = ""
        self._applying_picks = False       # our own select(), not a click
        self._header_pressed = False       # a plain header click: a sort
        self._last_gesture = "cell"        # what select one keeps
        self._pick_timer = QTimer(self)
        self._pick_timer.setSingleShot(True)
        self._pick_timer.setInterval(PICK_SETTLE_MS)
        self._pick_timer.timeout.connect(self._commit_picks)
        header.viewport().installEventFilter(self)
        self.verticalHeader().viewport().installEventFilter(self)

        # The font the theme gave this view, kept so that going back to
        # "Default" in Settings restores it rather than a guess at it.
        self._theme_font = QFont(self.font())
        self._wraps = False                # set from the model in setModel
        # Rows sized to what is in them (a `wrap`, a mark on a line of its
        # own, a tall spark) — and which of them have been measured. Only
        # the rows in view are, as they come into view (_size_rows_in_view).
        self._sizes_rows = False
        self._sized_rows: set = set()
        self._sizing = False
        # a column drag resizes many times; re-measure once it pauses
        self._resize_rows_later = QTimer(self)
        self._resize_rows_later.setSingleShot(True)
        self._resize_rows_later.setInterval(0)
        self._resize_rows_later.timeout.connect(self._remeasure_rows)
        self.verticalScrollBar().valueChanged.connect(
            lambda _v: self._size_rows_in_view())
        header.sectionResized.connect(
            lambda *_: self._sizes_rows and self._resize_rows_later.start())
        self._points_in_force = float(self._theme_font.pointSizeF())
        self._apply_text_size()
        _text_size_notifier.changed.connect(self._apply_text_size)

    # -------------------------------------------------------- text size

    def _apply_text_size(self, refit: bool = True) -> None:
        """Font and row height from Settings ▸ General ▸ Data text size.

        Two routes, because a data table gets its look from two places: the
        inspector's tables are plain widgets, so setFont is the whole story,
        while the tables on cards and tiles carry the shared grid stylesheet
        — and a stylesheet's `font-size` beats any font set on the widget.
        For those the stylesheet is re-applied instead, through
        style_scroll_area so the view keeps its scroll-blitting.
        """
        points = table_text_size()
        font = QFont(self._theme_font)
        if points > 0:
            font.setPointSizeF(points)
        self.setFont(font)
        self.horizontalHeader().setFont(font)
        self.verticalHeader().setFont(font)

        sheet = self.styleSheet()
        if "gridline-color" in sheet and "font-size" in sheet:
            from . import theme
            theme.style_scroll_area(self, theme.grid_stylesheet())
            points = points or GRID_FONT_PT
            font.setPointSizeF(points)
        # The size actually on screen, whichever route painted it — what
        # Smaller/Larger steps from.
        self._points_in_force = points or font.pointSizeF()

        # A `wrap` rule sizes each row to its own content and must keep
        # doing that; every other table gets the tight height for this font
        # — or the height a `height` line asked for, which may be tighter
        # still (a compact table), so the header's own minimum is lowered to
        # let it.
        model = self.model()
        asked = (getattr(model, "row_height", lambda: None)()
                 if model is not None else None)
        header = self.verticalHeader()
        if asked:
            header.setMinimumSectionSize(min(header.minimumSectionSize(),
                                             int(asked)))
        if not self._wraps:
            header.setDefaultSectionSize(
                int(asked) if asked
                else QFontMetrics(font).height() + ROW_PADDING)
        if refit and self.model() is not None \
                and self.model().columnCount() > 0:
            self.fit_columns_to_data()
        # a new font is a new height for every row measured so far
        if getattr(self, "_sizes_rows", False):
            self._remeasure_rows()

    def _sort_requested(self, column: int, mode: str) -> None:
        model = self.model()
        if model is None:
            return
        model.sort(column, None if mode == "clear"
                   else (Qt.AscendingOrder if mode == "asc"
                         else Qt.DescendingOrder))

    # ----------------------------------------------------- column widths

    def setModel(self, model) -> None:
        """Set the model and fit the columns to it.

        A plain QTableView does no auto-sizing at all, so every column here
        sat at Qt's 100 px default — narrower than many headers, and the
        header is the thing you most want intact when the table is headed
        for a spreadsheet. Fitting on setModel is the one place all four
        callers (node cards, dashboard tiles, the inspector, the spec view)
        pass through.
        """
        super().setModel(model)
        self._sort_cycler.reset()
        self._apply_wrapping(model)
        if model is not None and model.columnCount() > 0:
            self.fit_columns_to_data()
        if model is not None:
            # a new selection model comes with every model; a sort resets
            # the model, which empties the selection, and scrolling pages
            # rows in that the pick has not highlighted yet
            self.selectionModel().selectionChanged.connect(
                self._selection_changed)
            model.modelReset.connect(self._show_picks)
            model.rowsInserted.connect(self._show_picks)
            model.modelReset.connect(self._remeasure_rows)
            model.layoutChanged.connect(self._remeasure_rows)
            model.rowsInserted.connect(
                lambda *_: self._size_rows_in_view())
            self._show_picks()

    def _apply_wrapping(self, model) -> None:
        """A `wrap` rule lets a row grow to fit its text.

        Measured here, a screenful at a time (`_size_rows_in_view`), not
        left to Qt's `ResizeToContents`: that re-measures *every* loaded row
        through the delegate on every layout — each page fetched, each sort,
        each scroll — which on a long wrapped table was seconds a time
        (AE3). A row out of view keeps the default height until it is
        scrolled to. It costs nothing until a rule asks for it.
        """
        wraps = bool(model is not None
                     and getattr(model, "wraps_text", lambda: False)())
        self._wraps = wraps
        # A mark above or below a value, or a tall spark, needs the same
        # thing wrapping does: rows sized by what is in them. Kept apart
        # from `_wraps`, which also means "nothing is cut short" to the
        # tooltip, and a taller row says nothing about that.
        grows = bool(model is not None
                     and getattr(model, "grows_rows", lambda: False)())
        self._sizes_rows = wraps or grows
        self._sized_rows = set()
        self.verticalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._apply_text_size(refit=False)   # row height for this font

    def rows_size_to_content(self) -> bool:
        """Do this table's rows grow to what is in them?"""
        return self._sizes_rows

    def _remeasure_rows(self) -> None:
        """Forget every measured row — the order, the widths or the font
        changed — and measure the ones in view again."""
        if not self._sizes_rows:
            return
        self._sized_rows = set()
        self._size_rows_in_view()

    def _size_rows_in_view(self) -> None:
        """Size the rows a screen shows, from the top one in view down,
        each once until something makes it stale."""
        model = self.model()
        if not self._sizes_rows or model is None or self._sizing:
            return
        count = model.rowCount()
        if not count:
            return
        self._sizing = True
        try:
            row = max(self.rowAt(0), 0)
            room = max(self.viewport().height(), 1)
            filled = 0
            # bounded: a screen is rarely a hundred rows, and a view with
            # no geometry yet must not measure the whole table either
            for row in range(row, min(count, row + 200)):
                if row not in self._sized_rows:
                    self._sized_rows.add(row)
                    self.resizeRowToContents(row)
                filled += self.rowHeight(row)
                if filled > room:
                    break
        finally:
            self._sizing = False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # a wider view is wider columns only if they stretch; either way a
        # taller one shows rows nobody measured yet
        self._size_rows_in_view()

    @perf.timed('table: fit columns')
    def fit_columns_to_data(self) -> None:
        """Size each column to the wider of its header and its sampled
        content, clamped to [MIN_COL_WIDTH, MAX_COL_WIDTH] — unless a
        `width` rule named it, which wins outright."""
        model = self.model()
        if model is None:
            return
        from .table_delegate import BAR_ROLE, DECOR_ROLE
        header = self.horizontalHeader()
        metrics = QFontMetrics(self.font())
        rows = min(model.rowCount(), FIT_SAMPLE_ROWS)
        # a `width` rule is an instruction, not a hint: it is set as asked
        # and the content is not consulted, which is the whole point of
        # asking for a fixed column
        layout = getattr(model, "column_layout", None)
        for col in range(model.columnCount()):
            fixed = layout(col) if layout is not None else None
            if fixed is not None and fixed.width:
                self.setColumnWidth(col, fixed.width)
                continue
            width = header.sectionSizeHint(col)
            icon_pad = 0
            bar_only = False
            spark_width = 0
            for row in range(rows):
                index = model.index(row, col)
                text = model.data(index, Qt.DisplayRole)
                if text:
                    width = max(width, metrics.horizontalAdvance(str(text)) + 16)
                elif model.data(index, BAR_ROLE) is not None:
                    bar_only = True
                decor = model.data(index, DECOR_ROLE)
                if decor is not None:
                    # each mark standing beside the value needs room of its
                    # own — a cell may carry one on each side — while an
                    # `above` / `below` one costs the row height instead,
                    # and a lozenge costs only its padding
                    marks, pill, _ink = decor
                    beside = 0
                    for d in marks:
                        spark = getattr(d, "spark", None)
                        if spark is not None:
                            # a spark is as wide as it was asked to be, and
                            # one standing alone wants a column's worth
                            if d.where in ("left", "right"):
                                beside += (spark.width
                                           or SPARK_BESIDE_WIDTH) + 6
                            else:
                                spark_width = max(spark_width, spark.width
                                                  or SPARK_ALONE_WIDTH)
                        elif getattr(d, "image", None):
                            # as wide as its shape makes it, at the height
                            # it is drawn
                            from flograph.core.images import picture_aspect
                            # a picture fits its row, and a `height` line
                            # makes the row — and so the picture — bigger
                            asked = getattr(model, "row_height",
                                            lambda: None)()
                            tall = d.size or max(PICTURE_LINE_HEIGHT,
                                                 (asked or 0) - 4)
                            wide = round(tall * picture_aspect(d.image))
                            if d.where in ("left", "right"):
                                beside += wide + 6
                            else:
                                spark_width = max(spark_width, wide + 10)
                        elif d.where in ("left", "right", "in"):
                            beside += 24
                    icon_pad = max(icon_pad,
                                   beside + (14 if pill else 0))
            if bar_only:
                width = max(width, BAR_ONLY_WIDTH)
            width = max(width, spark_width)
            self.setColumnWidth(
                col, max(MIN_COL_WIDTH, min(width + icon_pad, MAX_COL_WIDTH)))

    # --------------------------------------------------------- tooltips

    def viewportEvent(self, event) -> bool:
        """Show the whole value when a cell had to be cut short.

        Qt only offers the tooltip the *model* supplies, and a model cannot
        know how wide its column ended up — so a truncated cell simply had
        no way to say what it was hiding. The view can: it asks the
        delegate for the room the value actually got, measures the text in
        the same font, and offers a tooltip only when it did not fit.

        Only when. A tooltip on a cell you can already read in full is
        noise, and noise is what stops people reading the ones that matter.

        A `tooltip` rule's note comes from the model and is shown whether
        or not anything was cut — see `_tooltip_text` for what happens
        when a cell has both.
        """
        if event.type() != QEvent.ToolTip:
            return super().viewportEvent(event)
        text = self._tooltip_text(self.indexAt(event.pos()))
        if text:
            show_tooltip(event.globalPos(), text, self.viewport())
        else:
            QToolTip.hideText()
        return True

    def _tooltip_text(self, index) -> str:
        """What this cell says when you rest on it.

        Two things want the one tooltip: a `tooltip` rule's note, which
        the model supplies, and the full value of a cell that had to be
        cut short, which only the view can work out. A cell can have both,
        and showing one would lose the other — so both are shown, the note
        first, because it is the thing somebody deliberately wrote.
        """
        model = self.model()
        if model is None or not index.isValid():
            return ""
        note = model.data(index, Qt.ToolTipRole)
        note = str(note) if note else ""
        cut = self._elided_value(index)
        if note and cut:
            # quoted, so the value reads as the cell's own words rather
            # than as a second sentence of the note
            return f"{note}\n\n“{cut}”"
        return note or cut

    def _elided_value(self, index) -> str:
        """The full text of a cell whose value did not fit, or ""."""
        model = self.model()
        if model is None or not index.isValid():
            return ""
        if getattr(model, "wraps_text", lambda: False)():
            # `wrap` exists precisely so that nothing is cut off; measuring
            # a wrapped cell on one line would fire on text that is
            # perfectly readable, several lines down
            return ""
        text = model.data(index, Qt.DisplayRole)
        if text in (None, ""):
            return ""
        delegate = self.itemDelegate()
        if not hasattr(delegate, "value_area"):
            return ""
        option = QStyleOptionViewItem()
        self.initViewItemOption(option)
        option.rect = self.visualRect(index)
        area = delegate.value_area(option, index)
        if area is None:
            # a decoration stands where the value would be: the value is
            # not shortened, it is deliberately not shown
            return ""
        text = str(text)
        metrics = QFontMetrics(option.font)
        return text if metrics.horizontalAdvance(text) > area.width() else ""

    def keyPressEvent(self, event) -> None:
        """Ctrl+C here rather than through a QShortcut.

        A shortcut would be the obvious way and does not work: the table on
        a node card lives inside a QGraphicsProxyWidget, and an embedded
        widget is not in the window focus chain that Qt matches shortcuts
        against — so the shortcut silently never fires on exactly the table
        people reach for first. Key events do arrive, because the canvas
        view forwards them once a proxy widget has focus.
        """
        if event.matches(QKeySequence.Copy):
            self.copy_selection()
            event.accept()
            return
        if event.matches(QKeySequence.SelectAll):
            self.selectAll()
            event.accept()
            return
        if (event.key() == Qt.Key_Escape and self._pick_mode != "nothing"
                and self._picks_text):
            self.clear_picks()
            event.accept()
            return
        super().keyPressEvent(event)

    # ----------------------------------------------------- click to filter

    def pick_mode(self) -> str:
        return self._pick_mode

    def picks_text(self) -> str:
        return self._picks_text

    def set_pick_mode(self, mode: str) -> None:
        """Turn click-to-filter on ("select one" / "select many") or off.
        Turning it off leaves the selection alone — it is just a selection
        again."""
        mode = mode if mode in ("select one", "select many") else "nothing"
        if mode == self._pick_mode:
            return
        self._pick_mode = mode
        self._pick_timer.stop()
        self._apply_pick_behaviour()
        self._show_picks()

    def set_pick_by(self, by: str) -> None:
        """What a click picks: "cell", or the whole "row"."""
        by = "row" if by == "row" else "cell"
        if by == self._pick_by:
            return
        self._pick_by = by
        self._pick_timer.stop()
        self._apply_pick_behaviour()
        self._show_picks()

    def _apply_pick_behaviour(self) -> None:
        """Row mode is Qt's own row selection — a click, a Ctrl+click and a
        drag all take whole rows, and the highlight runs end to end. Only
        while picking is on: a table that just copies keeps its cells."""
        rows = self._pick_mode != "nothing" and self._pick_by == "row"
        self.setSelectionBehavior(QTableView.SelectRows if rows
                                  else QTableView.SelectItems)

    def set_picks(self, text: str) -> None:
        """Show a pick that arrived from outside — the param after an undo,
        a hand edit, or the other view of the same node. Never emitted back
        out."""
        text = str(text or "")
        if text == self._picks_text:
            return
        self._pick_timer.stop()
        self._picks_text = text
        self._show_picks()

    def clear_picks(self) -> None:
        self._put_picks(Picks())

    def _put_picks(self, picks: Picks) -> None:
        """Make `picks` the table's pick: highlight it, and say so if it is
        a change."""
        self._pick_timer.stop()
        text = picks.to_json()
        changed = text != self._picks_text
        self._picks_text = text
        self._show_picks()
        if changed:
            self.picks_committed.emit(text)

    def _show_picks(self, *_) -> None:
        """Select what the pick matched: its rows, its columns, and every
        cell holding a picked value — not just the one clicked, so the card
        shows what the filter will keep. Guarded, so it is not taken for a
        click."""
        model = self.model()
        selection_model = self.selectionModel()
        if (self._pick_mode == "nothing" or model is None
                or selection_model is None
                or not hasattr(model, "pick_texts")):
            return
        picks = parse_picks(self._picks_text)
        rows, cols = model.rowCount(), model.columnCount()
        selection = QItemSelection()

        def select_runs(first_col: int, last_col: int, hits: list) -> None:
            start = prev = None
            for row in hits:
                if start is not None and row == prev + 1:
                    prev = row
                    continue
                if start is not None:
                    selection.select(model.index(start, first_col),
                                     model.index(prev, last_col))
                start = prev = row
            if start is not None:
                selection.select(model.index(start, first_col),
                                 model.index(prev, last_col))

        if picks and rows and cols:
            if picks.rows:
                select_runs(0, cols - 1, model.rows_labelled(picks.rows))
            seen: set = set()
            # row mode shows rows and nothing else — see active_picks
            for col in range(cols if self._pick_by == "cell" else 0):
                name = model.column_name(col)
                if name in seen:
                    continue           # the filter reads the first of a name
                seen.add(name)
                if name in picks.columns:
                    selection.select(model.index(0, col),
                                     model.index(rows - 1, col))
                elif name in picks.cells:
                    select_runs(col, col,
                                model.rows_matching(col, picks.cells[name]))
        self._applying_picks = True
        try:
            selection_model.select(selection,
                                   QItemSelectionModel.ClearAndSelect)
        finally:
            self._applying_picks = False

    def _selection_changed(self, *_) -> None:
        if (self._applying_picks or self._header_pressed
                or self._pick_mode == "nothing"):
            return
        self._pick_timer.start()

    def _commit_picks(self, force: bool = False) -> None:
        """The selection has settled: make it the pick."""
        if self._pick_mode == "nothing" or self.model() is None:
            return
        if not force and QGuiApplication.mouseButtons() & Qt.LeftButton:
            self._pick_timer.start()  # a drag still going: wait for its end
            return
        picks = self._picks_from_selection()
        if self._pick_mode == "select one":
            picks = self._only_the_last(picks)
        self._put_picks(picks)

    def _settle_pending(self) -> None:
        """A click is about to act on the pick: commit the one still waiting
        on its timer first, or the click would act on the pick before it."""
        if self._pick_timer.isActive():
            self._commit_picks(force=True)

    def _picks_from_selection(self) -> Picks:
        """Read the selection as a pick. Columns only ever come from a
        Ctrl+click on a header, so a column counts only if it was picked
        that way and is still selected; a row counts when all of it is
        selected; everything else selected is cells."""
        model = self.model()
        selection_model = self.selectionModel()
        rows, cols = model.rowCount(), model.columnCount()
        if selection_model is None or not rows or not cols:
            return Picks()
        if self._pick_by == "row":
            picked = sorted({i.row() for i in selection_model.selectedIndexes()})
            if len(picked) == rows:
                return Picks()             # every row: Select All
            return Picks(rows=[model.row_label(r) for r in picked])
        names = [model.column_name(c) for c in range(cols)]
        first_of: dict[str, int] = {}
        for col, name in enumerate(names):
            first_of.setdefault(name, col)
        kept = parse_picks(self._picks_text).columns
        picked_cols = {c for c in range(cols) if names[c] in kept
                       and selection_model.isColumnSelected(c)}
        free = cols - len(picked_cols)
        by_row: dict[int, set] = {}
        for index in selection_model.selectedIndexes():
            if index.column() not in picked_cols:
                by_row.setdefault(index.row(), set()).add(index.column())
        columns = [names[c] for c in sorted(picked_cols)]
        full = sorted(r for r, cs in by_row.items()
                      if free > 1 and len(cs) >= free)
        if full and len(full) == rows:
            # Every row: Select All, or a Ctrl+A on the way to a copy. All
            # of it filters nothing, and a pick of every label would be a
            # very long way of saying so.
            return Picks(columns=columns)
        full_set = set(full)
        per_column: dict[int, list] = {}
        for row, cs in by_row.items():
            if row in full_set:
                continue
            for col in cs:
                per_column.setdefault(col, []).append(row)
        cells: dict[str, list] = {}
        for col in sorted(per_column):
            name = names[col]
            texts = model.pick_texts(col, sorted(per_column[col]))
            merged = dict.fromkeys(cells.get(name, []))
            merged.update(dict.fromkeys(texts))
            cells[name] = list(merged)
        labels = []
        for row in full:
            # a row the cells already match adds nothing to the filter —
            # the rows add to what the cells keep
            if cells and all(
                    model.pick_texts(first_of[name], [row])[0] in values
                    for name, values in cells.items()):
                continue
            labels.append(model.row_label(row))
        return Picks(cells=cells, rows=labels, columns=columns)

    def _only_the_last(self, picks: Picks) -> Picks:
        """Select one: whatever was clicked last, and nothing else."""
        model = self.model()
        current = self.currentIndex()
        if (not picks or not current.isValid()
                or not self.selectionModel().isSelected(current)):
            return Picks()
        if self._last_gesture == "row" or self._pick_by == "row":
            return Picks(rows=[model.row_label(current.row())])
        col = current.column()
        return Picks(cells={model.column_name(col):
                            model.pick_texts(col, [current.row()])})

    def _toggle_column(self, col: int) -> None:
        """Ctrl+click on a header: that column in or out of the pick."""
        self._settle_pending()
        name = self.model().column_name(col)
        picks = parse_picks(self._picks_text)
        self._last_gesture = "column"
        if self._pick_mode == "select one":
            alone = picks.columns == [name] and not picks.cells \
                and not picks.rows
            picks = Picks() if alone else Picks(columns=[name])
        elif name in picks.columns:
            picks.columns = [c for c in picks.columns if c != name]
        else:
            picks.columns = [*picks.columns, name]
        self._put_picks(picks)

    def _unpick_row(self, row: int, modifiers) -> bool:
        """A plain click on the one picked row lets every row through."""
        if modifiers & (Qt.ControlModifier | Qt.ShiftModifier):
            return False
        picks = parse_picks(self._picks_text)
        if ((picks.cells and self._pick_by == "cell")
                or picks.rows != [self.model().row_label(row)]):
            return False
        self._put_picks(Picks(columns=picks.columns))
        return True

    def _unpick_cell(self, index, modifiers) -> bool:
        """Clicking a picked value again: a plain click on the only one
        clears the pick, the way clicking a chart's selected bar does; a
        Ctrl+click takes that value out of a longer pick, from every cell
        showing it."""
        if self._pick_by == "row":
            # a click anywhere on the one picked row is a click on the row
            return self._unpick_row(index.row(), modifiers)
        model = self.model()
        name = model.column_name(index.column())
        picks = parse_picks(self._picks_text)
        values = picks.cells.get(name)
        if name in picks.columns or not values:
            return False
        text = model.pick_texts(index.column(), [index.row()])[0]
        if text not in values:
            return False
        held = modifiers & (Qt.ControlModifier | Qt.ShiftModifier)
        if held == Qt.ControlModifier:
            rest = [v for v in values if v != text]
            if rest:
                picks.cells[name] = rest
            else:
                del picks.cells[name]
        elif (not held and values == [text] and len(picks.cells) == 1
              and not picks.rows):
            picks.cells = {}
        else:
            return False
        self._put_picks(picks)
        return True

    def mousePressEvent(self, event) -> None:
        if (self._pick_mode != "nothing" and self.model() is not None
                and event.button() == Qt.LeftButton):
            self._settle_pending()
            self._last_gesture = "cell"
            index = self.indexAt(event.position().toPoint())
            if index.isValid() and self._unpick_cell(index,
                                                     event.modifiers()):
                event.accept()
                return
        super().mousePressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        """The headers' half of picking, watched from here because a click
        on a header is handled by the header, not the table.

        A column is picked with Ctrl+click, which is eaten so it does not
        also sort. A plain click still sorts — but Qt selects the column on
        the press anyway, so the pick is put back on the release. A row's
        header needs nothing special: Qt selects the row, and the selection
        becomes the pick as any other does.
        """
        if self._pick_mode != "nothing" and self.model() is not None:
            kind = event.type()
            columns = self.horizontalHeader()
            if watched is columns.viewport():
                if (kind == QEvent.MouseButtonPress
                        and event.button() == Qt.LeftButton):
                    col = columns.logicalIndexAt(event.position().toPoint())
                    if (col >= 0 and self._pick_by == "cell"
                            and event.modifiers() & Qt.ControlModifier):
                        self._toggle_column(col)
                        return True
                    self._settle_pending()
                    self._header_pressed = True
                elif kind == QEvent.MouseButtonRelease and self._header_pressed:
                    self._header_pressed = False
                    self._show_picks()
            elif watched is self.verticalHeader().viewport():
                if (kind == QEvent.MouseButtonPress
                        and event.button() == Qt.LeftButton):
                    row = self.verticalHeader().logicalIndexAt(
                        event.position().toPoint())
                    if row >= 0:
                        self._settle_pending()
                        self._last_gesture = "row"
                        if self._unpick_row(row, event.modifiers()):
                            return True
        return super().eventFilter(watched, event)

    # ------------------------------------------------------------- copying

    def _selection_spans_whole_columns(self) -> bool:
        model = self.selectionModel()
        if model is None or self.model() is None:
            return False
        rows = {i.row() for i in model.selectedIndexes()}
        return len(rows) >= self.model().rowCount() > 0

    def copy_selection(self) -> bool:
        """Ctrl+C: the selection, or the whole table when there is none."""
        model = self.selectionModel()
        if model is None or not model.hasSelection():
            return self.copy_all()
        return put_on_clipboard(
            selection_block(self, self._selection_spans_whole_columns()))

    def copy_selection_with_headers(self) -> bool:
        model = self.selectionModel()
        if model is None or not model.hasSelection():
            return self.copy_all()
        return put_on_clipboard(selection_block(self, True))

    def copy_all(self) -> bool:
        rows = full_row_count(self)
        if rows > CONFIRM_ROWS and not self._confirm_large(rows):
            return False
        return put_on_clipboard(whole_block(self, True))

    def _confirm_large(self, rows: int) -> bool:
        answer = QMessageBox.question(
            self, "Copy whole table",
            f"This table has {rows:,} rows. Copying all of it may take a "
            f"moment and use a lot of memory.\n\nCopy anyway?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    # ---------------------------------------------------------------- menu

    def build_menu(self) -> QMenu:
        menu = QMenu(self)
        has_selection = (self.selectionModel() is not None
                         and self.selectionModel().hasSelection())
        copy = menu.addAction("Copy")
        copy.setShortcut(QKeySequence.Copy)
        copy.setEnabled(has_selection)
        copy.triggered.connect(self.copy_selection)

        with_headers = menu.addAction("Copy with Column Names")
        with_headers.setEnabled(has_selection)
        with_headers.triggered.connect(self.copy_selection_with_headers)

        menu.addSeparator()
        everything = menu.addAction("Copy Whole Table")
        everything.setEnabled(self.model() is not None
                              and self.model().columnCount() > 0)
        everything.triggered.connect(self.copy_all)

        select_all = menu.addAction("Select All")
        select_all.setShortcut(QKeySequence.SelectAll)
        select_all.setEnabled(everything.isEnabled())
        select_all.triggered.connect(self.selectAll)

        if self._pick_mode != "nothing":
            # the way out of a filter that is keeping nothing you want
            clear = menu.addAction("Clear Selection")
            clear.setEnabled(bool(self._picks_text))
            clear.triggered.connect(self.clear_picks)

        # Where you look for it: you are already looking at the table that
        # is too big. The same preference as Settings ▸ General, so it holds
        # for every data table and across restarts.
        menu.addSeparator()
        # built with an explicit parent rather than menu.addMenu(str):
        # that returns a QMenu nothing on the Python side holds, and
        # shiboken collects the wrapper out from under its owner
        sizes = QMenu("Text Size", menu)
        menu.addMenu(sizes)
        smaller = sizes.addAction("Smaller")
        smaller.triggered.connect(
            lambda: self.nudge_text_size(-TEXT_PT_STEP))
        larger = sizes.addAction("Larger")
        larger.triggered.connect(lambda: self.nudge_text_size(TEXT_PT_STEP))
        sizes.addSeparator()
        default = sizes.addAction("Default")
        default.setEnabled(table_text_size() > 0)
        default.triggered.connect(lambda: set_table_text_size(0.0))
        return menu

    def nudge_text_size(self, delta: float) -> None:
        """One step smaller or larger, from the size in force now.

        Which for "Default" is whatever this table happens to be showing,
        so the first step down is a step down from what is on screen rather
        than a jump to somewhere else."""
        points = table_text_size() or self._points_in_force
        set_table_text_size(
            max(MIN_TEXT_PT, min(MAX_TEXT_PT, points + delta)))

    def _show_menu(self, pos) -> None:
        from . import menu_guard
        if menu_guard.settling():
            return   # leftovers of a menu that just closed — see menu_guard
        self.build_menu().exec(self.viewport().mapToGlobal(pos))
