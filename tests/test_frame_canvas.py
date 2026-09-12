"""G13: a frame turned into a model canvas, and back.

The frame stays one frame in the graph. What changes is where its contents
live — a canvas of their own — and how it draws: a node-like box with
declared ports. The wires are the same wires throughout.

Settings kept off the real store — see test_ab_dashboard_nav.py."""
import pytest
from PySide6.QtCore import QPointF, QRectF, QSettings

from flograph.core import Frame, FramePort
from flograph.core.page_nav import CANVAS_KIND
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.ui import mainwindow as mw
from flograph.ui.commands import SetFrameCanvasCommand
from flograph.ui.mainwindow import MainWindow

TABLE = "flograph.io.table"
FILTER = "flograph.transform.filter_rows"
JOIN = "flograph.transform.join"


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mw, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


@pytest.fixture
def flow(window, registry):
    """A frame holding two nodes, fed from outside on the left and feeding
    a node outside on the right — two wires crossing its edge."""
    graph = window.graph
    source = registry.instantiate(TABLE, pos=(-500, 150))
    inside_a = registry.instantiate(FILTER, pos=(150, 120))
    inside_b = registry.instantiate(FILTER, pos=(350, 250))
    after = registry.instantiate(JOIN, pos=(1200, 150))
    for node in (source, inside_a, inside_b, after):
        graph.add_node(node)
    graph.add_frame(Frame(id="f1", title="Cleaning", rect=(0, 0, 600, 400)))
    graph.connect(source.id, "table", inside_a.id, "table")
    graph.connect(inside_a.id, "filtered", inside_b.id, "table")
    graph.connect(inside_b.id, "filtered", after.id, "left")
    return source, inside_a, inside_b, after


def _canvas_of(window) -> str:
    return window.graph.frames["f1"].own_canvas


class TestTurningAFrameIntoACanvas:
    def test_its_contents_move_to_a_canvas_of_their_own(self, window, flow):
        source, inside_a, inside_b, after = flow
        window._frame_to_canvas("f1")
        canvas_id = _canvas_of(window)
        assert canvas_id in window.graph.pages
        assert window.graph.pages[canvas_id].kind == CANVAS_KIND
        assert window.graph.pages[canvas_id].title == "Cleaning"
        moved = {n.id for n in window.graph.nodes.values()
                 if n.canvas == canvas_id}
        assert moved == {inside_a.id, inside_b.id}
        assert window.graph.nodes[source.id].canvas == ""
        assert window.graph.nodes[after.id].canvas == ""

    def test_the_wires_are_the_same_wires(self, window, flow):
        before = {(c.src_node, c.src_port, c.dst_node, c.dst_port)
                  for c in window.graph.connections.values()}
        window._frame_to_canvas("f1")
        after = {(c.src_node, c.src_port, c.dst_node, c.dst_port)
                 for c in window.graph.connections.values()}
        assert after == before

    def test_a_port_is_declared_for_every_crossing_wire(self, window, flow):
        source, inside_a, inside_b, _after = flow
        window._frame_to_canvas("f1")
        ports = window.graph.frames["f1"].ports
        assert {(p.node_id, p.port, p.side) for p in ports} == {
            (inside_a.id, "table", "input"),
            (inside_b.id, "filtered", "output")}
        assert all(p.name for p in ports)

    def test_the_box_draws_as_a_node_and_stops_folding(self, window, flow):
        window._frame_to_canvas("f1")
        item = window.scene.frame_items["f1"]
        assert item.is_canvas
        assert not item.collapsed
        width, height = item.display_size()
        assert (width, height) != (600, 400)     # a box, not a region
        item.toggle_collapsed()                  # nothing to fold
        assert not window.graph.frames["f1"].collapsed

    def test_a_crossing_wire_is_pinned_to_the_box(self, window, flow):
        _source, inside_a, inside_b, _after = flow
        window._frame_to_canvas("f1")
        pins = list(window.scene._frame_pins.values())
        assert {pin.node_id for pin in pins} == {inside_a.id, inside_b.id}
        names = {pin.label_text() for pin in pins}
        assert names == {p.name for p in window.graph.frames["f1"].ports}
        for pin in pins:
            assert pin.frame_item.frame.id == "f1"

    def test_its_ports_show_on_the_canvas_they_lead_into(self, window, flow):
        """Inside the box's canvas, a wire that leaves it would otherwise
        stop at a port with nothing beyond and nothing naming it."""
        window._frame_to_canvas("f1")
        canvas_id = _canvas_of(window)
        assert not window.scene._edge_markers      # nothing to say out here
        window.page_bar.select_page(canvas_id)
        declared = {p.name: p for p in window.graph.frames["f1"].ports}
        markers = {key[1]: marker
                   for key, marker in window.scene._edge_markers.items()}
        assert set(markers) == set(declared)
        for name, marker in markers.items():
            assert marker.side == declared[name].side
            assert marker.isVisible()
        window.page_bar.select_page(None)
        assert not window.scene._edge_markers

    def test_double_clicking_the_box_asks_for_its_canvas(self, window, flow,
                                                         qtbot):
        window._frame_to_canvas("f1")
        item = window.scene.frame_items["f1"]
        with qtbot.waitSignal(item.canvas_requested) as caught:
            item.canvas_requested.emit("f1")
        assert caught.args == ["f1"]
        window._open_frame_canvas("f1")
        assert window.page_bar.current_page_id() == _canvas_of(window)

    def test_closing_its_tab_only_puts_the_view_away(self, window, flow):
        """The canvas belongs to the box, not to the tab: closing the tab
        leaves everything where it is, and opening the box brings it back
        on the same canvas id."""
        _source, inside_a, _inside_b, _after = flow
        window._frame_to_canvas("f1")
        canvas_id = _canvas_of(window)
        window._delete_page(canvas_id)
        assert canvas_id not in window.graph.pages
        assert window.graph.frames["f1"].own_canvas == canvas_id
        assert window.graph.nodes[inside_a.id].canvas == canvas_id
        window._open_frame_canvas("f1")
        assert canvas_id in window.graph.pages
        assert window.page_bar.current_page_id() == canvas_id

    def test_a_declared_port_with_no_wire_still_gets_a_pin(self, window, flow):
        """Declaring an interface is how you wire *into* a box before its
        inside is connected, so the pin has to exist before the wire."""
        _source, inside_a, _inside_b, _after = flow
        window._frame_to_canvas("f1")
        frame = window.graph.frames["f1"]
        window.undo_stack.push(SetFrameCanvasCommand(
            window.graph, "f1", frame.own_canvas,
            ports=frame.ports + (FramePort(name="rejects",
                                           node_id=inside_a.id,
                                           port="rejected", side="output"),),
            box_size=(frame.rect[2], frame.rect[3])))
        pins = {pin.label_text(): pin
                for pin in window.scene._frame_pins.values()}
        assert "rejects" in pins
        assert pins["rejects"].node_id == inside_a.id
        assert pins["rejects"].conn_id == ""      # standing on its own
        assert pins["rejects"].side == "src"


class TestTurningItBack:
    def test_everything_comes_home_from_the_box_s_corner(self, window, flow):
        """The block lands where the box was standing — down and to the
        right of its corner — rather than back at old coordinates, and the
        region grows to hold it."""
        _source, inside_a, inside_b, _after = flow
        window._frame_to_canvas("f1")
        canvas_id = _canvas_of(window)
        # the box is dragged somewhere else before being turned back
        window.graph.update_frame("f1", rect=(900.0, 500.0, 60.0, 60.0))
        window._canvas_to_frame("f1")

        frame = window.graph.frames["f1"]
        assert frame.own_canvas == "" and frame.ports == ()
        assert canvas_id not in window.graph.pages
        assert (frame.rect[0], frame.rect[1]) == (900.0, 500.0)
        region = QRectF(*frame.rect)
        for node_id in (inside_a.id, inside_b.id):
            node = window.graph.nodes[node_id]
            assert node.canvas == ""
            assert node.pos[0] > 900.0 and node.pos[1] > 500.0
            assert region.contains(QPointF(*node.pos))

    def test_one_undo_reverses_the_whole_conversion(self, window, flow):
        _source, inside_a, _inside_b, _after = flow
        window._frame_to_canvas("f1")
        window.undo_stack.undo()
        frame = window.graph.frames["f1"]
        assert frame.own_canvas == ""
        assert frame.rect == (0.0, 0.0, 600.0, 400.0)
        assert window.graph.nodes[inside_a.id].canvas == ""
        assert not window.graph.pages


class TestSaving:
    def test_a_box_and_its_ports_round_trip(self, window, registry, flow):
        window._frame_to_canvas("f1")
        data = graph_to_dict(window.graph)
        back = graph_from_dict(data, registry)
        frame = back.frames["f1"]
        assert frame.own_canvas == _canvas_of(window)
        assert [(p.name, p.node_id, p.port, p.side) for p in frame.ports] == \
            [(p.name, p.node_id, p.port, p.side)
             for p in window.graph.frames["f1"].ports]
        assert all(isinstance(p, FramePort) for p in frame.ports)

    def test_an_ordinary_frame_says_nothing_about_canvases(self, window,
                                                            registry, flow):
        data = graph_to_dict(window.graph)
        entry = data["graph"]["frames"][0]
        assert "own_canvas" not in entry and "ports" not in entry
