"""Deactivating and locking a node (ideas C1/C2).

Two separate guards that are easy to conflate. *Deactivate* is about the
run: the node and everything downstream of it is skipped, which is how you
try a graph without one branch. *Lock* is about editing: params, code and
position freeze so a working node cannot be nudged, and the run is not
affected at all.

Both are per-node state that survives a save, and both are undoable.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry
from flograph.core.serialization import graph_to_dict, graph_from_dict
from flograph.engine.scheduler import build_plan
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.node_item import DEACTIVATED_OPACITY
from flograph.ui.commands import SetActiveCommand, SetLockedCommand

from .conftest import make_node


# ------------------------------------------------------------- core state

class TestDefaultsAndSetters:
    def test_a_new_node_is_active_and_unlocked(self):
        node = make_node()
        assert node.active is True
        assert node.locked is False

    def test_setters_emit(self, chain_graph):
        graph, nodes = chain_graph
        seen = []
        graph.events.active_changed.connect(lambda n, v: seen.append(("a", v)))
        graph.events.locked_changed.connect(lambda n, v: seen.append(("l", v)))
        graph.set_active(nodes[0].id, False)
        graph.set_locked(nodes[0].id, True)
        assert seen == [("a", False), ("l", True)]
        assert nodes[0].active is False and nodes[0].locked is True


# --------------------------------------------------------------- the run

class TestDeactivateSkipsTheSubgraph:
    def test_all_three_run_when_all_are_active(self, chain_graph):
        graph, nodes = chain_graph
        assert build_plan(graph, list(graph.nodes)) == [n.id for n in nodes]

    def test_a_deactivated_node_and_its_descendants_are_dropped(self,
                                                                chain_graph):
        graph, nodes = chain_graph
        graph.set_active(nodes[1].id, False)
        # b is off, so c — which would have consumed b's output — goes too
        assert build_plan(graph, list(graph.nodes)) == [nodes[0].id]

    def test_deactivating_the_tail_leaves_the_head_alone(self, chain_graph):
        graph, nodes = chain_graph
        graph.set_active(nodes[2].id, False)
        assert build_plan(graph, list(graph.nodes)) == [nodes[0].id,
                                                        nodes[1].id]

    def test_an_unrelated_branch_is_untouched(self):
        """Deactivation follows the wires, not the whole canvas."""
        graph = Graph()
        wired = [make_node() for _ in range(2)]
        loner = make_node()
        for node in (*wired, loner):
            graph.add_node(node)
        graph.connect(wired[0].id, "value", wired[1].id, "value")
        graph.set_active(wired[0].id, False)
        assert build_plan(graph, list(graph.nodes)) == [loner.id]

    def test_reactivating_restores_the_plan(self, chain_graph):
        graph, nodes = chain_graph
        graph.set_active(nodes[1].id, False)
        graph.set_active(nodes[1].id, True)
        assert build_plan(graph, list(graph.nodes)) == [n.id for n in nodes]

    def test_locking_does_not_affect_the_run(self, chain_graph):
        graph, nodes = chain_graph
        graph.set_locked(nodes[1].id, True)
        assert build_plan(graph, list(graph.nodes)) == [n.id for n in nodes]


# ----------------------------------------------------------- persistence

class TestRoundTrip:
    def test_both_flags_survive_a_save(self, registry, chain_graph):
        graph, nodes = chain_graph
        graph.set_active(nodes[0].id, False)
        graph.set_locked(nodes[1].id, True)
        loaded = graph_from_dict(graph_to_dict(graph), registry)
        assert loaded.node(nodes[0].id).active is False
        assert loaded.node(nodes[0].id).locked is False
        assert loaded.node(nodes[1].id).active is True
        assert loaded.node(nodes[1].id).locked is True

    def test_a_file_written_before_these_existed_loads_harmlessly(
            self, registry, chain_graph):
        graph, nodes = chain_graph
        data = graph_to_dict(graph)
        for entry in data["graph"]["nodes"]:
            del entry["active"]
            del entry["locked"]
        loaded = graph_from_dict(data, registry)
        assert all(n.active and not n.locked for n in loaded.nodes.values())


# ---------------------------------------------------------------- canvas

@pytest.fixture
def scene(qtbot, registry):
    graph = Graph()
    node = make_node()
    graph.add_node(node)
    sc = NodeGraphScene(graph, QUndoStack(), registry=registry)
    return graph, node, sc.node_items[node.id]


class TestOnTheCanvas:
    def test_deactivating_fades_the_item(self, scene):
        graph, node, item = scene
        assert item.opacity() == 1.0
        graph.set_active(node.id, False)
        assert item.opacity() == pytest.approx(DEACTIVATED_OPACITY)
        graph.set_active(node.id, True)
        assert item.opacity() == 1.0

    def test_the_padlock_only_shows_when_locked(self, scene):
        graph, node, item = scene
        assert not item._lock_badge.isVisible()
        graph.set_locked(node.id, True)
        assert item._lock_badge.isVisible()
        graph.set_locked(node.id, False)
        assert not item._lock_badge.isVisible()

    def test_a_locked_node_refuses_to_move(self, scene):
        graph, node, item = scene
        item.setPos(10.0, 10.0)
        graph.set_locked(node.id, True)
        item.setPos(500.0, 500.0)
        assert (item.pos().x(), item.pos().y()) == (10.0, 10.0)
        graph.set_locked(node.id, False)
        item.setPos(500.0, 500.0)
        assert (item.pos().x(), item.pos().y()) == (500.0, 500.0)

    def test_the_padlock_actually_paints_something(self, scene):
        """Guards the bug this badge was born from: a QGraphicsSimpleTextItem
        holding the lock emoji reports a sensible boundingRect and then paints
        nothing at all, because colour-emoji fonts do not render through that
        path. Measuring the item would not have caught it — only painting
        does."""
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtCore import QRectF
        from flograph.ui.canvas.node_item import LockBadge

        graph, node, item = scene
        graph.set_locked(node.id, True)
        badge = item._lock_badge
        rect = badge.boundingRect()
        image = QImage(int(rect.width()) + 4, int(rect.height()) + 4,
                       QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        painter.translate(2 - rect.left(), 2 - rect.top())
        badge.paint(painter, None)
        painter.end()
        inked = sum(1 for y in range(image.height())
                    for x in range(image.width())
                    if image.pixelColor(x, y).alpha() > 0)
        assert inked > 20, f"the padlock drew {inked} pixels"

    def test_a_locked_node_says_so_on_hover(self, scene):
        graph, node, item = scene
        graph.set_locked(node.id, True)
        assert "Unlock" in item.toolTip()

    def test_state_from_disk_is_applied_when_the_item_is_built(
            self, qtbot, registry):
        """A node loaded already deactivated must not paint at full opacity
        until something happens to it."""
        graph = Graph()
        node = make_node()
        node.active = False
        node.locked = True
        graph.add_node(node)
        sc = NodeGraphScene(graph, QUndoStack(), registry=registry)
        item = sc.node_items[node.id]
        assert item.opacity() == pytest.approx(DEACTIVATED_OPACITY)
        assert item._lock_badge.isVisible()


# ------------------------------------------------------------------ undo

class TestUndo:
    def test_deactivate_undoes(self, chain_graph):
        graph, nodes = chain_graph
        stack = QUndoStack()
        stack.push(SetActiveCommand(graph, nodes[0].id, False))
        assert nodes[0].active is False
        stack.undo()
        assert nodes[0].active is True
        stack.redo()
        assert nodes[0].active is False

    def test_lock_undoes(self, chain_graph):
        graph, nodes = chain_graph
        stack = QUndoStack()
        stack.push(SetLockedCommand(graph, nodes[0].id, True))
        assert nodes[0].locked is True
        stack.undo()
        assert nodes[0].locked is False

    def test_the_commands_are_named_for_what_they_did(self, chain_graph):
        graph, nodes = chain_graph
        assert SetActiveCommand(graph, nodes[0].id,
                                False).text() == "deactivate node"
        assert SetLockedCommand(graph, nodes[0].id, True).text() == "lock node"


# ------------------------------------------------------- editing surfaces

class TestEditingIsFrozen:
    def test_the_properties_grid_is_disabled_while_locked(self, qtbot,
                                                          chain_graph):
        from flograph.ui.properties.params_panel import ParamsPanel
        graph, nodes = chain_graph
        panel = ParamsPanel(graph, QUndoStack())
        qtbot.addWidget(panel)
        panel.set_node(nodes[0].id)
        assert panel.tree.isEnabled()
        graph.set_locked(nodes[0].id, True)
        assert not panel.tree.isEnabled()
        graph.set_locked(nodes[0].id, False)
        assert panel.tree.isEnabled()

    def test_a_node_already_locked_opens_disabled(self, qtbot, chain_graph):
        from flograph.ui.properties.params_panel import ParamsPanel
        graph, nodes = chain_graph
        graph.set_locked(nodes[0].id, True)
        panel = ParamsPanel(graph, QUndoStack())
        qtbot.addWidget(panel)
        panel.set_node(nodes[0].id)
        assert not panel.tree.isEnabled()

    def test_the_code_editor_goes_read_only(self, qtbot, registry,
                                            chain_graph):
        from flograph.ui.editor.editor_dock import EditorPanel
        graph, nodes = chain_graph
        dock = EditorPanel(graph, QUndoStack(), registry)
        qtbot.addWidget(dock)
        dock.set_node(nodes[0].id)
        assert not dock.editor.isReadOnly()
        graph.set_locked(nodes[0].id, True)
        assert dock.editor.isReadOnly()
        assert not dock._apply_btn.isEnabled()
        graph.set_locked(nodes[0].id, False)
        assert not dock.editor.isReadOnly()
        assert dock._apply_btn.isEnabled()

    def test_the_code_is_still_readable_while_locked(self, qtbot, registry,
                                                     chain_graph):
        """Read-only, not disabled — you can still scroll and copy it."""
        from flograph.ui.editor.editor_dock import EditorPanel
        graph, nodes = chain_graph
        graph.set_locked(nodes[0].id, True)
        dock = EditorPanel(graph, QUndoStack(), registry)
        qtbot.addWidget(dock)
        dock.set_node(nodes[0].id)
        assert dock.editor.isEnabled()
        assert dock.editor.toPlainText() == nodes[0].source


# ---------------------------------------------------------------- freeze

class _FakeCache:
    """Just the one question build_plan asks of a cache."""

    def __init__(self, cached=()):
        self._cached = set(cached)

    def has(self, node_id: str) -> bool:
        return node_id in self._cached


class TestFreezeSkipsOnlyItself:
    def test_a_frozen_node_is_skipped_but_the_rest_still_runs(self,
                                                              chain_graph):
        """The whole point, and the opposite of deactivating."""
        graph, nodes = chain_graph
        graph.set_frozen(nodes[0].id, True)
        cache = _FakeCache([nodes[0].id])
        assert build_plan(graph, list(graph.nodes), cache) == [nodes[1].id,
                                                               nodes[2].id]

    def test_a_frozen_node_with_nothing_cached_runs_once(self, chain_graph):
        """You cannot pause something that has not produced anything yet."""
        graph, nodes = chain_graph
        graph.set_frozen(nodes[0].id, True)
        assert build_plan(graph, list(graph.nodes),
                          _FakeCache()) == [n.id for n in nodes]

    def test_dirtiness_does_not_break_the_pin(self, chain_graph):
        """A pin a stray edit could knock loose would not be worth setting."""
        graph, nodes = chain_graph
        graph.set_frozen(nodes[0].id, True)
        graph.mark_dirty(nodes[0].id)
        cache = _FakeCache([nodes[0].id])
        assert nodes[0].id not in build_plan(graph, list(graph.nodes), cache)

    def test_unfreezing_puts_it_back(self, chain_graph):
        graph, nodes = chain_graph
        graph.set_frozen(nodes[0].id, True)
        graph.set_frozen(nodes[0].id, False)
        cache = _FakeCache([nodes[0].id])
        assert build_plan(graph, list(graph.nodes), cache) == [n.id
                                                               for n in nodes]

    def test_freezing_clears_the_fingerprint_on_release(self, chain_graph):
        graph, nodes = chain_graph
        graph.set_frozen(nodes[0].id, True, "abc")
        assert nodes[0].frozen_fingerprint == "abc"
        graph.set_frozen(nodes[0].id, False)
        assert nodes[0].frozen_fingerprint is None


class TestFrozenFingerprints:
    def test_a_frozen_node_hashes_to_a_constant(self, chain_graph):
        """Which is what lets the pin survive a reopen at all."""
        from flograph.engine.cache_persistence import node_fingerprint
        graph, nodes = chain_graph
        graph.set_frozen(nodes[0].id, True)
        before = node_fingerprint(graph, nodes[0].id, {})
        graph.set_param(nodes[0].id, "value", "changed") \
            if nodes[0].spec.param("value") else None
        nodes[0].params["anything"] = "different"
        assert node_fingerprint(graph, nodes[0].id, {}) == before

    def test_an_edit_above_a_pin_does_not_invalidate_below_it(self,
                                                              chain_graph):
        """b is frozen, so c's cached output was computed from a value that
        has not moved — editing a must not force c to recompute."""
        from flograph.engine.cache_persistence import node_fingerprint
        graph, nodes = chain_graph
        graph.set_frozen(nodes[1].id, True)
        before = node_fingerprint(graph, nodes[2].id, {})
        nodes[0].params["something"] = "new"
        assert node_fingerprint(graph, nodes[2].id, {}) == before

    def test_unfreezing_restores_the_real_hash(self, chain_graph):
        from flograph.engine.cache_persistence import node_fingerprint
        graph, nodes = chain_graph
        real = node_fingerprint(graph, nodes[0].id, {})
        graph.set_frozen(nodes[0].id, True)
        assert node_fingerprint(graph, nodes[0].id, {}) != real
        graph.set_frozen(nodes[0].id, False)
        assert node_fingerprint(graph, nodes[0].id, {}) == real


class TestStalePins:
    def test_a_pinned_source_node_is_never_stale(self, chain_graph):
        """The case freezing is mostly for: nothing upstream to move."""
        from flograph.engine.cache_persistence import (freeze_fingerprint,
                                                       stale_frozen)
        graph, nodes = chain_graph
        graph.set_frozen(nodes[0].id, True,
                         freeze_fingerprint(graph, nodes[0].id))
        nodes[2].params["downstream"] = "irrelevant"
        assert stale_frozen(graph) == []

    def test_a_pin_whose_inputs_moved_is_flagged(self, chain_graph):
        from flograph.engine.cache_persistence import (freeze_fingerprint,
                                                       stale_frozen)
        graph, nodes = chain_graph
        graph.set_frozen(nodes[1].id, True,
                         freeze_fingerprint(graph, nodes[1].id))
        assert stale_frozen(graph) == []
        nodes[0].params["upstream"] = "moved"
        assert stale_frozen(graph) == [nodes[1].id]

    def test_an_unfrozen_node_is_never_reported(self, chain_graph):
        from flograph.engine.cache_persistence import stale_frozen
        graph, nodes = chain_graph
        nodes[0].params["moved"] = True
        assert stale_frozen(graph) == []


class TestFreezeRoundTrip:
    def test_the_pin_survives_a_save(self, registry, chain_graph):
        graph, nodes = chain_graph
        graph.set_frozen(nodes[0].id, True, "fp-1")
        loaded = graph_from_dict(graph_to_dict(graph), registry)
        assert loaded.node(nodes[0].id).frozen is True
        assert loaded.node(nodes[0].id).frozen_fingerprint == "fp-1"

    def test_an_older_file_loads_unfrozen(self, registry, chain_graph):
        graph, nodes = chain_graph
        data = graph_to_dict(graph)
        for entry in data["graph"]["nodes"]:
            del entry["frozen"]
            del entry["frozen_fingerprint"]
        loaded = graph_from_dict(data, registry)
        assert all(not n.frozen for n in loaded.nodes.values())


class TestFreezeOnTheCanvas:
    def test_the_pause_glyph_shows_only_when_frozen(self, scene):
        graph, node, item = scene
        assert not item._freeze_badge.isVisible()
        graph.set_frozen(node.id, True)
        assert item._freeze_badge.isVisible()
        graph.set_frozen(node.id, False)
        assert not item._freeze_badge.isVisible()

    def test_the_pause_glyph_paints_something(self, scene):
        from PySide6.QtGui import QImage, QPainter
        graph, node, item = scene
        graph.set_frozen(node.id, True)
        badge = item._freeze_badge
        rect = badge.boundingRect()
        image = QImage(int(rect.width()) + 4, int(rect.height()) + 4,
                       QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        painter.translate(2 - rect.left(), 2 - rect.top())
        badge.paint(painter, None)
        painter.end()
        inked = sum(1 for y in range(image.height())
                    for x in range(image.width())
                    if image.pixelColor(x, y).alpha() > 0)
        assert inked > 20, f"the pause glyph drew {inked} pixels"

    def test_a_stale_pin_ambers(self, scene):
        from flograph.ui import theme
        graph, node, item = scene
        graph.set_frozen(node.id, True)
        assert item._freeze_badge.colour == theme.NODE_SUBTEXT
        item.set_frozen(True, stale=True)
        assert item._freeze_badge.colour == theme.PIN_STALE

    def test_badges_pack_left_and_do_not_overlap(self, scene):
        """Either badge alone sits in the same first slot; together they
        stand side by side."""
        graph, node, item = scene
        graph.set_frozen(node.id, True)
        alone = item._freeze_badge.pos().x()
        graph.set_frozen(node.id, False)
        graph.set_locked(node.id, True)
        assert item._lock_badge.pos().x() == alone
        graph.set_frozen(node.id, True)
        gap = abs(item._lock_badge.pos().x() - item._freeze_badge.pos().x())
        assert gap >= item._lock_badge.W

    def test_frozen_state_from_disk_is_applied_on_build(self, qtbot,
                                                        registry):
        graph = Graph()
        node = make_node()
        node.frozen = True
        graph.add_node(node)
        sc = NodeGraphScene(graph, QUndoStack(), registry=registry)
        assert sc.node_items[node.id]._freeze_badge.isVisible()


class TestFreezeUndo:
    def test_freeze_undoes_and_records_a_fingerprint(self, chain_graph):
        from flograph.ui.commands import SetFrozenCommand
        graph, nodes = chain_graph
        stack = QUndoStack()
        stack.push(SetFrozenCommand(graph, nodes[0].id, True))
        assert nodes[0].frozen is True
        assert nodes[0].frozen_fingerprint is not None
        stack.undo()
        assert nodes[0].frozen is False
        assert nodes[0].frozen_fingerprint is None

    def test_redo_reuses_the_original_fingerprint(self, chain_graph):
        """Otherwise redo would quietly launder a pin that should read as
        stale, by re-freezing it against whatever is true now."""
        from flograph.ui.commands import SetFrozenCommand
        graph, nodes = chain_graph
        stack = QUndoStack()
        stack.push(SetFrozenCommand(graph, nodes[1].id, True))
        first = nodes[1].frozen_fingerprint
        stack.undo()
        nodes[0].params["moved"] = "since"
        stack.redo()
        assert nodes[1].frozen_fingerprint == first


class TestThePinSurvivesDirtying:
    """Both of these were live bugs the first time the scenario was run
    end to end, and neither showed up in a unit test of build_plan."""

    def _engine_graph(self):
        from flograph.engine import ExecutionEngine
        graph = Graph()
        nodes = [make_node() for _ in range(2)]
        for node in nodes:
            graph.add_node(node)
        graph.connect(nodes[0].id, "value", nodes[1].id, "value")
        return graph, nodes, ExecutionEngine(graph)

    def test_dirtying_a_frozen_node_does_not_evict_its_cache(self):
        """The engine evicts a node's cache the moment it goes dirty. For a
        frozen node that would destroy the pinned value itself, and the node
        would quietly run again on the next pass."""
        graph, nodes, engine = self._engine_graph()
        engine.cache.set(nodes[0].id, {"value": 1}, 0.0)
        graph.mark_clean(nodes[0].id)
        graph.set_frozen(nodes[0].id, True)
        graph.mark_dirty(nodes[0].id)
        assert engine.cache.has(nodes[0].id)
        assert nodes[0].id not in build_plan(graph, list(graph.nodes),
                                             engine.cache)

    def test_an_unfrozen_node_still_loses_its_cache_when_dirtied(self):
        """The exemption is for frozen nodes only."""
        graph, nodes, engine = self._engine_graph()
        engine.cache.set(nodes[0].id, {"value": 1}, 0.0)
        graph.mark_clean(nodes[0].id)
        graph.mark_dirty(nodes[0].id)
        assert not engine.cache.has(nodes[0].id)

    def test_unfreezing_leaves_the_node_dirty_so_it_reruns(self):
        """Releasing a pin is how you ask for the expensive thing to happen
        again — if the node came back clean, the next run would find nothing
        to do and change nothing."""
        graph, nodes, engine = self._engine_graph()
        engine.cache.set(nodes[0].id, {"value": 1}, 0.0)
        graph.mark_clean(nodes[0].id)
        graph.set_frozen(nodes[0].id, True)
        graph.set_frozen(nodes[0].id, False)
        assert nodes[0].dirty
        assert not engine.cache.has(nodes[0].id)
        assert nodes[0].id in build_plan(graph, list(graph.nodes),
                                         engine.cache)


class TestFrozenOnTheMinimap:
    """The minimap has no room for a badge, so colour is the only channel
    it has to say the same thing the canvas says with a pause glyph."""

    def _item(self, graph, node_id):
        return graph, node_id

    def test_a_frozen_node_reads_as_held(self, scene):
        from flograph.ui import theme
        from flograph.ui.canvas.minimap import _state_color
        graph, node, item = scene
        assert _state_color(item) != theme.PIN_HELD
        graph.set_frozen(node.id, True)
        assert _state_color(item) == theme.PIN_HELD

    def test_a_stale_pin_reads_as_stale(self, scene):
        from flograph.ui import theme
        from flograph.ui.canvas.minimap import _state_color
        graph, node, item = scene
        graph.set_frozen(node.id, True)
        item.set_frozen(True, stale=True)
        assert _state_color(item) == theme.PIN_STALE

    def test_frozen_outranks_a_finished_status(self, scene):
        """The status of a skipped node is stale by definition — a green
        "done" is the wrong thing to say about a node nobody is refreshing.
        """
        from flograph.core.node import NodeStatus
        from flograph.ui import theme
        from flograph.ui.canvas.minimap import _state_color
        graph, node, item = scene
        graph.set_status(node.id, NodeStatus.DONE)
        assert _state_color(item) == theme.status_color(NodeStatus.DONE)
        graph.set_frozen(node.id, True)
        assert _state_color(item) == theme.PIN_HELD

    def test_an_error_still_outranks_a_pin(self, scene):
        from flograph.core.node import NodeStatus
        from flograph.ui import theme
        from flograph.ui.canvas.minimap import _state_color
        graph, node, item = scene
        graph.set_frozen(node.id, True)
        graph.set_status(node.id, NodeStatus.ERROR, "boom")
        assert _state_color(item) == theme.status_color(NodeStatus.ERROR)

    def test_a_pin_outranks_the_users_own_colour(self, scene):
        """State beats organisation, which is how status already behaves."""
        from flograph.ui import theme
        from flograph.ui.canvas.minimap import _state_color
        graph, node, item = scene
        graph.set_color(node.id, "#ff00ff")
        tinted = _state_color(item)
        graph.set_frozen(node.id, True)
        assert _state_color(item) == theme.PIN_HELD != tinted

    def test_an_ordinary_node_is_unchanged(self, scene):
        from flograph.ui import theme
        from flograph.ui.canvas.minimap import _state_color
        graph, node, item = scene
        assert _state_color(item) == theme.NODE_HEADER.lighter(150)

    def test_the_held_colour_is_distinct_from_every_status(self):
        """It has to be told apart at four pixels across."""
        from flograph.core.node import NodeStatus
        from flograph.ui import theme
        for status in NodeStatus:
            assert theme.PIN_HELD != theme.status_color(status)
        assert theme.PIN_HELD != theme.PIN_STALE


class TestDeactivatedAndLockedOnTheMinimap:
    """Three states, two channels. Fill says what is happening in the run,
    border says the node is protected — so they can be read together."""

    def test_a_deactivated_node_is_faded_not_recoloured(self, scene):
        from flograph.ui.canvas.minimap import _node_brush, _state_color
        from flograph.ui.canvas.node_item import DEACTIVATED_OPACITY
        graph, node, item = scene
        assert _node_brush(item).alphaF() == pytest.approx(1.0)
        graph.set_active(node.id, False)
        faded = _node_brush(item)
        # QColor keeps alpha as an 8-bit int, so 0.35 returns as 89/255
        assert faded.alphaF() == pytest.approx(DEACTIVATED_OPACITY,
                                               abs=0.005)
        # same hue as before — only the alpha moved
        assert faded.rgb() == _state_color(item).rgb()

    def test_the_fade_matches_the_canvas(self, scene):
        """One source of truth, so the two views cannot drift apart."""
        from flograph.ui.canvas.minimap import _node_brush
        graph, node, item = scene
        graph.set_active(node.id, False)
        assert _node_brush(item).alphaF() == pytest.approx(item.opacity(),
                                                           abs=0.005)

    def test_a_deactivated_frozen_node_keeps_the_pin_colour(self, scene):
        from flograph.ui import theme
        from flograph.ui.canvas.minimap import _node_brush
        graph, node, item = scene
        graph.set_frozen(node.id, True)
        graph.set_active(node.id, False)
        assert _node_brush(item).rgb() == theme.PIN_HELD.rgb()

    def test_a_locked_node_gets_an_outline(self, scene):
        from PySide6.QtCore import Qt
        from flograph.ui.canvas.minimap import _node_pen
        graph, node, item = scene
        assert _node_pen(item) == Qt.NoPen
        graph.set_locked(node.id, True)
        pen = _node_pen(item)
        assert pen != Qt.NoPen and pen.width() >= 1

    def test_locking_does_not_touch_the_fill(self, scene):
        """The whole reason it lives on the border: it must not displace a
        state that says something about the run."""
        from flograph.ui.canvas.minimap import _node_brush
        graph, node, item = scene
        before = _node_brush(item)
        graph.set_locked(node.id, True)
        assert _node_brush(item) == before

    def test_all_three_at_once_stay_legible(self, scene):
        """Locked, frozen and deactivated together: the pin colour survives
        in the fill, the fade survives on top of it, and the lock is on the
        border where neither can hide it."""
        from PySide6.QtCore import Qt
        from flograph.ui import theme
        from flograph.ui.canvas.minimap import _node_brush, _node_pen
        from flograph.ui.canvas.node_item import DEACTIVATED_OPACITY
        graph, node, item = scene
        graph.set_frozen(node.id, True)
        graph.set_locked(node.id, True)
        graph.set_active(node.id, False)
        fill = _node_brush(item)
        assert fill.rgb() == theme.PIN_HELD.rgb()
        assert fill.alphaF() == pytest.approx(DEACTIVATED_OPACITY,
                                              abs=0.005)
        assert _node_pen(item) != Qt.NoPen
