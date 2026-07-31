"""Benchmark the graph and canvas operations that scale with graph size.

Every optimisation aimed at "the app feels slow with a lot of nodes" should
be shown against this rather than argued about: run it, keep the numbers,
run it again after. It measures the operations that sit on interactive
paths — a repaint, a keystroke in a param field, building a run plan — not
throughput of anything a node does.

Usage:
    python scripts/bench_graph.py            # default 100, 300, 600
    python scripts/bench_graph.py 100 1000   # any sizes you like

Runs offscreen; needs no display.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

NODE_SRC = """
NODE = {
    "label": "Bench",
    "category": "Bench",
    "inputs": [("a", "any", {"optional": True}), ("b", "any", {"optional": True})],
    "outputs": [("v", "any"), ("w", "any")],
}
PARAMS = [{"name": "txt", "type": "string", "default": ""}]
def run(ctx, a, b):
    return {"v": 1, "w": 2}
"""

# Wide enough that a repaint has to cover real ground, but laid out on a
# grid so the scene's bounding rect stays proportional to the node count.
COLUMNS = 25
COL_STEP = 200.0
ROW_STEP = 140.0


def _time(fn, repeats=1):
    start = time.perf_counter()
    for _ in range(repeats):
        result = fn()
    return (time.perf_counter() - start) / repeats, result


def build_graph(spec, n):
    """A chain: every node feeds the next, so upstream/downstream walks have
    real depth to cover. A star or a grid of islands would flatter the
    traversals into looking free."""
    from flograph.core import Graph, NodeInstance

    graph = Graph()
    first = previous = None
    for i in range(n):
        node = graph.add_node(NodeInstance.create(
            spec, pos=((i % COLUMNS) * COL_STEP, (i // COLUMNS) * ROW_STEP)))
        if previous is not None:
            graph.connect(previous.id, "v", node.id, "a")
        else:
            first = node
        previous = node
    return graph, first, previous


def bench(n):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter, QUndoStack

    from flograph.core import NodeRegistry, parse_spec
    from flograph.engine import cache_persistence
    from flograph.engine.scheduler import build_plan
    from flograph.ui.canvas.scene import NodeGraphScene

    spec = parse_spec(NODE_SRC, "bench.node")
    registry = NodeRegistry()
    registry.register(spec)

    build, (graph, first, last) = _time(lambda: build_graph(spec, n))
    row = {"n": n, "build": build}

    row["topo_order"], _ = _time(graph.topo_order, 3)
    row["upstream"], _ = _time(lambda: graph.upstream(last.id), 3)
    row["build_plan"], _ = _time(lambda: build_plan(graph, [last.id]), 3)
    row["fingerprint"], _ = _time(
        lambda: cache_persistence.node_fingerprint(graph, last.id, {}), 3)

    # One keystroke: set_param marks the whole downstream cone dirty, so it
    # goes to the *first* node — typing into the last one has nothing below
    # it and would measure nothing. Nodes are re-marked clean between passes
    # so every pass pays for the full walk.
    def keystroke(i=[0]):
        i[0] += 1
        graph.set_param(first.id, "txt", "x" * (i[0] % 16 + 1))
        for node in graph.nodes.values():
            node.dirty = False

    for node in graph.nodes.values():
        node.dirty = False
    row["set_param"], _ = _time(keystroke, 10)

    scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
    image = QImage(1600, 1000, QImage.Format_ARGB32)
    painter = QPainter(image)
    bounds = scene.itemsBoundingRect()
    row["repaint"], _ = _time(
        lambda: scene.render(painter, target=QRectF(0, 0, 1600, 1000),
                             source=bounds), 5)
    painter.end()

    # One model query per port. paint() no longer does this — the answer is
    # cached on the PortItem — so this is not a share of a frame any more;
    # it is kept as a direct read on how the edge lookups themselves scale.
    ports = [(node.id, port) for node in graph.nodes.values()
             for port in (*node.spec.inputs, *node.spec.outputs)]

    def scan():
        for node_id, port in ports:
            scene.is_port_connected(node_id, port)

    row["port_scan"], _ = _time(scan, 3)
    row["ports"] = len(ports)
    return row


COLUMNS_OUT = [
    ("topo_order", "topo_order"),
    ("upstream", "upstream"),
    ("build_plan", "build_plan"),
    ("fingerprint", "fingerprint"),
    ("set_param", "set_param/key"),
    ("repaint", "full repaint"),
    ("port_scan", "port query x all"),
]


def main(argv):
    sizes = [int(a) for a in argv[1:]] or [100, 300, 600]

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    rows = [bench(n) for n in sizes]

    width = max(len(label) for _, label in COLUMNS_OUT) + 2
    header = "".join(f"{n:>12}" for n in sizes)
    print(f"{'nodes':<{width}}{header}")
    print("-" * (width + 12 * len(sizes)))
    for key, label in COLUMNS_OUT:
        cells = "".join(f"{row[key] * 1000:>10.1f}ms" for row in rows)
        print(f"{label:<{width}}{cells}")
    print()
    for row in rows:
        print(f"n={row['n']:<5d} {row['ports']:>5d} ports | "
              f"{1 / row['repaint']:5.1f} fps ceiling on a full-scene repaint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
