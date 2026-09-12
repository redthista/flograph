"""The inspector: click a node (or a wire) and see the cached data flowing
through it — table view for DataFrames, figure canvas for plots, pretty repr
for everything else. One tab per output port, with a stale watermark when the
node needs a re-run.

The panel spends as little height on chrome as it can. Everything it has to
say about the value — which node, which port, what type, how big, how long
it took — goes on one line, and that line sits in the empty stretch of a tab
bar that is on screen anyway rather than taking a row of its own. A node with
a single output port (nearly all of them) gets no port tab bar either: one
tab is not a choice, and the port's name is on the info line. So there is one
row above the data, where there used to be four.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QSizePolicy, QTabBar,
                               QTabWidget, QVBoxLayout, QWidget)

from flograph.core import Connection, Graph
from flograph.engine import ExecutionEngine, summarize

from .spec_view import is_tabular, spec_view_for
from .view_for import view_for as _view_for

#: Tighter than the app's tabs: these bars are the panel's only chrome and
#: sit directly over the data, so every pixel they give back is a row of it.
COMPACT_TABS = "QTabBar::tab { padding: 2px 10px; font-size: 8pt; }"


class _ElidedLabel(QLabel):
    """Keeps the whole text — for its tooltip, and for anyone reading it
    back — while painting only as much of it as the width allows, ending in
    an ellipsis.

    The room beside a tab bar swings with the panel's width and with how
    many tabs there are, and a plain QLabel in that space either demands
    width it cannot have or has its text cut off mid-character.
    """

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setText(self, text: str) -> None:       # noqa: N802 — Qt override
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, event) -> None:        # noqa: N802 — Qt override
        painter = QPainter(self)
        # palette(mid) is the dim-label colour the rest of the app uses;
        # painted rather than styled, because a stylesheet's colour is not
        # something a hand-rolled drawText picks up.
        painter.setPen(self.palette().color(QPalette.Mid))
        metrics = QFontMetrics(self.font())
        painter.drawText(
            self.rect(), int(self.alignment() | Qt.AlignVCenter),
            metrics.elidedText(self.text(), Qt.ElideRight, self.width()))
        painter.end()


class InspectorPanel(QWidget):
    #: Kept clear between the last tab and the start of the info line.
    INFO_GAP = 12
    #: Narrower than this and there is no point in a line of text at all.
    INFO_FLOOR = 48

    def __init__(self, graph: Graph, engine: ExecutionEngine, parent=None) -> None:
        super().__init__(parent)
        self._graph = graph
        self._engine = engine
        self._node_id: Optional[str] = None
        self._port_filter: Optional[str] = None  # set when inspecting a wire
        # What the info line is made of, kept apart so that switching port
        # tabs can re-say it for the port now showing.
        self._label = ""
        self._timing = ""
        self._meta: dict[str, str] = {}
        self._watched_bar: Optional[QTabBar] = None

        self._header = _ElidedLabel("Nothing selected")
        self._header.setStyleSheet("font-size: 8pt;")
        self._stale = QLabel("STALE — re-run to refresh")
        self._stale.setStyleSheet(
            "color: #eab308; font-weight: bold; font-size: 8pt;")
        self._stale.hide()

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(COMPACT_TABS)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # The info line is placed by hand over the empty stretch of
        # whichever tab bar is showing — see _place_info — as a child of
        # that bar. Not QTabWidget's own corner slot: that gives a widget
        # exactly its size hint and asks for the hint while the freshly
        # built bar is still at its constructed size, which drew the line
        # over the tabs on a panel's first showing.
        self._info = QWidget(self)
        info = QHBoxLayout(self._info)
        info.setContentsMargins(6, 0, 6, 0)
        info.setSpacing(8)
        info.addWidget(self._header, 1)
        info.addWidget(self._stale)

        # Reserves the one row for the case with no tab bar to ride on (a
        # single port holding something that is not a table); hidden
        # otherwise, and empty either way — the line itself is placed over
        # it, not put inside it.
        self._strip = QWidget()
        self._strip.setFixedHeight(self._info.sizeHint().height() + 3)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._strip)
        layout.addWidget(self._tabs, 1)

        engine.node_succeeded.connect(self._on_node_ran)
        engine.node_failed.connect(self._on_node_ran)
        graph.events.dirty_changed.connect(self._on_dirty_changed)
        graph.events.node_removed.connect(self._on_node_removed)

    # -------------------------------------------------------------- targets

    def show_node(self, node_id: Optional[str]) -> None:
        self._node_id = node_id
        self._port_filter = None
        self._refresh()

    def show_wire(self, conn: Connection) -> None:
        """Inspect the value flowing on a wire = its source port's cache."""
        self._node_id = conn.src_node
        self._port_filter = conn.src_port
        self._refresh()

    # ----------------------------------------------------------- info line

    def resizeEvent(self, event) -> None:       # noqa: N802 — Qt override
        super().resizeEvent(event)
        self._place_info()

    def showEvent(self, event) -> None:         # noqa: N802 — Qt override
        super().showEvent(event)
        self._place_info()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — Qt override
        """Re-place the line when the bar it rides changes size.

        The line's width is the bar's, less the tabs — and a bar built
        during a refresh is not sized until the panel's layout runs, which
        is after anything the refresh itself can measure. Watching it
        settles that without a deferred timer, which a test cannot see.
        """
        if obj is self._watched_bar and event.type() in (
                QEvent.Resize, QEvent.Show):
            self._place_info()
        return False

    def _info_bar(self) -> Optional[QTabBar]:
        """The tab bar the info line rides on, or None when there is none.

        The port tabs when a node has several ports; otherwise the one
        port's own Data/Spec bar. A lone non-tabular value — a figure, a
        string — has no bar, and there the line gets the strip.
        """
        if self._tabs.count() == 0:      # nothing selected, or no ports
            return None
        if not self._tabs.tabBar().isHidden():
            return self._tabs.tabBar()
        page = self._tabs.currentWidget()
        sub = page.findChild(QTabWidget) if page is not None else None
        return sub.tabBar() if sub is not None else None

    def _place_info(self) -> None:
        """Put the info line after the last tab, or in the strip.

        Placed rather than laid out, and inside the bar rather than beside
        it: in document mode the bar is stretched across the panel and
        everything past its last tab is empty, so the line goes there. As
        the bar's own child it needs no coordinates but the bar's — a bar
        built during a refresh has not been put in its final place yet, and
        measuring across the panel meant placing the line from where the
        bar was rather than where it ended up.
        """
        bar = self._info_bar()
        height = self._info.sizeHint().height()
        if bar is None:
            self._park_info()
            return
        if self._info.parentWidget() is not bar:
            self._info.setParent(bar)
        if bar is not self._watched_bar:
            self._watched_bar = bar
            # remove first: the port tab bar is the panel's own and comes
            # back around, and a second filter on it would place the line
            # twice per event
            bar.removeEventFilter(self)
            bar.installEventFilter(self)
        self._strip.hide()
        used = bar.tabRect(bar.count() - 1).right() + 1 if bar.count() else 0
        left = used + self.INFO_GAP
        width = bar.width() - left
        self._info.setGeometry(left, max(0, (bar.height() - height) // 2),
                               max(0, width), height)
        self._info.setVisible(width >= self.INFO_FLOOR)
        self._info.raise_()

    def _park_info(self) -> None:
        """The line on a row of its own, as a child of the panel again.

        Both for the case with no tab bar to ride, and before the pages are
        dropped: a bar carrying the line is the line's parent, and would
        take it down with it.
        """
        self._watched_bar = None
        if self._info.parentWidget() is not self:
            self._info.setParent(self)
        self._strip.show()
        rect = self._strip.geometry()
        self._info.setGeometry(rect.x(), rect.y(), rect.width(),
                               self._info.sizeHint().height())
        self._info.show()
        self._info.raise_()

    def _sync_header(self) -> None:
        """Say it all on one line: node, port, type, size, time.

        With more than one output port the type and size belong to the port
        being looked at, so the line is re-said when its tab changes.
        """
        if not self._meta:
            return
        if len(self._meta) == 1:
            port, meta = next(iter(self._meta.items()))
        else:
            port = self._tabs.tabText(self._tabs.currentIndex())
            meta = self._meta.get(port, "")
        parts = [self._label, f"wire {port}" if self._port_filter else port,
                 meta, self._timing]
        self._header.setText(" · ".join(part for part in parts if part))

    def _on_tab_changed(self, index: int) -> None:
        self._sync_header()
        self._place_info()          # another page, so possibly another bar

    # -------------------------------------------------------------- refresh

    def _clear_tabs(self) -> None:
        """Drop every page, deleting the widgets rather than just removing the
        tabs.

        QTabWidget.clear() detaches pages without deleting them, so a panel
        that is refilled on every selection would otherwise keep every node's
        widgets — and whatever they are displaying, DataFrames included — alive
        as orphaned children of the tab widget forever. Draining with an
        explicit deleteLater is what actually lets the previous node's data go.
        """
        # The bar carrying the info line is about to go, and it is the
        # line's parent: take the line back first, or it goes too.
        self._park_info()
        while self._tabs.count():
            widget = self._tabs.widget(0)
            self._tabs.removeTab(0)
            widget.deleteLater()

    def _refresh(self) -> None:
        self._clear_tabs()
        self._meta = {}
        self._label = self._timing = ""
        if self._node_id is None or self._node_id not in self._graph.nodes:
            self._header.setText("Nothing selected")
            self._stale.hide()
            self._place_info()
            return
        node = self._graph.node(self._node_id)
        entry = self._engine.cache.get(self._node_id)
        self._stale.setVisible(node.dirty and entry is not None)

        ports = [p for p in node.spec.outputs
                 if self._port_filter is None or p.name == self._port_filter]
        if not ports:
            self._header.setText(f"{node.label} — no output ports")
            self._place_info()
            return

        # A single port is not a choice to offer: its tab bar would be a row
        # holding nothing but the port's name, which the info line says.
        self._tabs.tabBar().setVisible(len(ports) > 1)

        if entry is None:
            self._header.setText(f"{node.label} — not computed yet")
            for port in ports:
                placeholder = QLabel("Run the graph to see this output.")
                placeholder.setAlignment(Qt.AlignCenter)
                placeholder.setStyleSheet("color: palette(mid);")
                self._tabs.addTab(placeholder, port.name)
            self._place_info()
            return

        self._label = node.label
        self._timing = f"computed in {entry.wall_time * 1000:.0f} ms"
        # Looking at a node is the moment its value has to be real. A project
        # opens without loading anything, so this may be the read that brings
        # the value back off disk — one node, because the user asked for it,
        # which is the trade the lazy open is making.
        outputs = self._engine.cache.outputs_for(self._node_id)
        for port in ports:
            value = outputs.get(port.name)
            self._meta[port.name] = f"{port.type.value} · {summarize(value)}"
            host = QWidget()
            host_layout = QVBoxLayout(host)
            host_layout.setContentsMargins(0, 0, 0, 0)
            host_layout.setSpacing(0)
            if is_tabular(value):
                # table values get a column spec next to the data
                sub = QTabWidget()
                sub.setDocumentMode(True)
                sub.setStyleSheet(COMPACT_TABS)
                sub.addTab(_view_for(value, embed_figures=False), "Data")
                self._add_lazy_spec_tab(sub, self._node_id, port.name)
                host_layout.addWidget(sub, 1)
            else:
                host_layout.addWidget(_view_for(value, embed_figures=False), 1)
            self._tabs.addTab(host, port.name)

        self._sync_header()
        self._place_info()

    def on_cache_cleared(self) -> None:
        """Caches were reset: re-read the selected node.

        The entry is gone, so the panel drops whatever big value it was
        displaying back to the placeholder instead of pinning it until the
        user happens to select something else."""
        self._refresh()

    def _add_lazy_spec_tab(self, sub: QTabWidget, node_id: str, port_name: str) -> None:
        """Column stats (nunique/min/max) walk the whole table, which is slow
        for large data — build the Spec tab only once the user opens it,
        instead of on every node click.

        The value is fetched from the cache when the tab is opened, not
        captured at construction: a closure that pins the whole DataFrame
        keeps it alive as long as the widget is, which is exactly the sort of
        retention that made "reset caches" unable to reclaim anything."""
        placeholder = QLabel("Spec loads when this tab is opened —\n"
                              "can be slow for very large tables.")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color: palette(mid);")
        spec_host = QWidget()
        spec_layout = QVBoxLayout(spec_host)
        spec_layout.setContentsMargins(0, 0, 0, 0)
        spec_layout.addWidget(placeholder)
        spec_index = sub.addTab(spec_host, "Spec")

        def build_spec(index: int) -> None:
            if index != spec_index:
                return
            sub.currentChanged.disconnect(build_spec)
            spec_layout.removeWidget(placeholder)
            placeholder.deleteLater()
            value = self._engine.cache.outputs_for(node_id).get(port_name)
            if is_tabular(value):
                spec_layout.addWidget(spec_view_for(value))
            else:
                spec_layout.addWidget(QLabel("No table to spec."))

        sub.currentChanged.connect(build_spec)

    # --------------------------------------------------------------- events

    def _on_node_ran(self, node_id: str, *args) -> None:
        if node_id == self._node_id:
            self._refresh()

    def _on_dirty_changed(self, node_id: str, dirty: bool) -> None:
        if node_id == self._node_id:
            node = self._graph.nodes.get(node_id)
            has_cache = self._engine.cache.has(node_id)
            self._stale.setVisible(bool(node and node.dirty and has_cache))

    def _on_node_removed(self, node_id: str) -> None:
        if node_id == self._node_id:
            self.show_node(None)
