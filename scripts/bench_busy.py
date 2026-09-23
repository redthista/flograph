"""Benchmark a busy flow the way a user feels it: how long the window freezes.

`bench_graph.py` measures graph operations as the node count grows. This one
measures what happens *around* a run of a realistic heavy flow: long tables
with conditional formatting, Plotly charts on the canvas and on dashboard
pages (one of them hidden), a report card and a report page with a long
table. It prints:

- how long a run takes from Run to the window going idle;
- the longest single freeze of the GUI thread in that time, and how many
  freezes passed the "you notice it" line (`ui.perf.NOTICE_S`);
- where the GUI thread's time went, by `core.perf.timed` label;
- the bill for what was put off while out of sight: showing a dashboard
  page, and scrolling the report card into view;
- one sort of a formatted 50k-row table;
- save + reopen of the project (the open half is the freezing half);
- Stop on a node that ignores cancellation: how long until the run ends.

Every optimisation under chunk AE is run against this, before and after.

Usage:
    python scripts/bench_busy.py              # 50,000 rows
    python scripts/bench_busy.py 200000       # any row count

Runs offscreen; needs no display. Writes only into a temporary folder.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("FLOGRAPH_MEMORY_ADAPT", "0")
# Offscreen has no GPU to give Chromium; without these the web cards
# lose their GL context and the process aborts.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
os.environ.setdefault("QT_OPENGL", "software")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

GEN_SRC = '''
NODE = {
    "label": "Bench Data",
    "category": "Bench",
    "version": "1.0",
    "inputs": [],
    "outputs": [("table", "dataframe")],
}
PARAMS = [{"name": "rows", "type": "int", "default": 50000},
          {"name": "seed", "type": "int", "default": 0}]
def run(ctx):
    import numpy as np
    import pandas as pd
    n = ctx.params["rows"]
    rng = np.random.default_rng(ctx.params["seed"])
    regions = np.array(["north", "south", "east", "west", "central"])
    products = np.array([f"product {i}" for i in range(40)])
    frame = pd.DataFrame({
        "id": np.arange(n),
        "region": regions[rng.integers(0, len(regions), n)],
        "product": products[rng.integers(0, len(products), n)],
        "revenue": rng.normal(1000, 400, n).round(2),
        "units": rng.integers(-20, 200, n),
        "score": rng.integers(0, 100, n),
        "status": np.where(rng.random(n) < 0.1, "fail", "ok"),
        "note": ["a fairly long free-text note that needs wrapping " * 2] * n,
    })
    for m in range(1, 13):
        frame[f"m{m:02d}"] = rng.normal(100, 30, n).round(1)
    return {"table": frame}
'''

SLEEPER_SRC = '''
NODE = {
    "label": "Bench Sleeper",
    "category": "Bench",
    "version": "1.0",
    "inputs": [],
    "outputs": [("value", "any")],
}
PARAMS = [{"name": "seconds", "type": "float", "default": 8.0}]
def run(ctx):
    import time
    time.sleep(ctx.params["seconds"])   # never checks for Stop, like a SQL read
    return {"value": 1}
'''

TABLE_RULES = [
    "revenue scale green\nunits bar blue\nscore icons traffic",
    "revenue scale red yellow green\nstatus = fail => row red",
    "score >= 90 => bg green, bold\nunits bar blue only",
    "trend spark from m01..m12",
    "region spark area teal right from m01..m12\nrevenue scale green",
    "wrap\nrevenue scale green",
    "product scale green by revenue\nunits icons arrows",
    "revenue scale green\nunits scale blue\nscore scale red\nm01 bar green",
    "m01 scale green\nm02 scale green\nm03 scale green\nm04 scale green",
    "status = fail => row red\nscore < 10 => bg red",
    "revenue bar green\nscore icons check",
    "units bar blue\nrevenue scale green\ntrend spark bars from m01..m06",
]
PLOTLY = [("bar", "region", "revenue"), ("line", "id", "revenue"),
          ("scatter", "revenue", "units"), ("bar", "product", "units"),
          ("area", "id", "score"), ("line", "id", "m01"),
          ("bar", "region", "units"), ("scatter", "score", "revenue")]


def pump(app, seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def wait_for(app, signal, timeout):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    got = []
    signal.connect(lambda *a: (got.append(a), loop.quit()))
    QTimer.singleShot(int(timeout * 1000), loop.quit)
    loop.exec()
    return bool(got)


def build(win, rows):
    from flograph.core import Page, Tile

    graph, reg = win.graph, win.registry
    gen = reg.instantiate("bench.gen", pos=(-900, 0))
    graph.add_node(gen)
    graph.set_param(gen.id, "rows", rows)

    tables, charts = [], []
    for i, rules in enumerate(TABLE_RULES):
        node = reg.instantiate("flograph.viz.show_table",
                               pos=((i % 4) * 700, (i // 4) * 600))
        graph.add_node(node)
        graph.set_label(node.id, f"Table {i}")
        graph.set_param(node.id, "format_rules", rules)
        graph.connect(gen.id, "table", node.id, "table")
        tables.append(node)
    matrix = reg.instantiate("flograph.viz.show_table", pos=(0, 1900))
    graph.add_node(matrix)
    graph.set_label(matrix.id, "Matrix")
    graph.set_param(matrix.id, "mode", "matrix")
    graph.set_param(matrix.id, "matrix_rows", "product")
    graph.set_param(matrix.id, "matrix_columns", "region")
    graph.set_param(matrix.id, "matrix_values", "revenue")
    graph.set_param(matrix.id, "format_rules", "* scale green")
    graph.connect(gen.id, "table", matrix.id, "table")
    tables.append(matrix)

    for i, (kind, x, y) in enumerate(PLOTLY):
        node = reg.instantiate("flograph.viz.show_plotly",
                               pos=(3000 + (i % 4) * 700, (i // 4) * 600))
        graph.add_node(node)
        graph.set_label(node.id, f"Chart {i}")
        graph.set_param(node.id, "kind", kind)
        graph.set_param(node.id, "x", x)
        graph.set_param(node.id, "y", y)
        graph.connect(gen.id, "table", node.id, "table")
        charts.append(node)

    report = reg.instantiate("flograph.viz.report_card", pos=(0, 2600))
    graph.add_node(report)
    graph.set_param(report.id, "text",
                    "# Card report\n\n![[a|rows=500]]\n\n![[b]]\n")
    graph.connect(tables[0].id, "table", report.id, "a")
    graph.connect(charts[0].id, "figure", report.id, "b")

    # Two dashboard pages; only one can be the current page, so the other
    # is the "hidden page" case.
    for p in range(2):
        page = graph.add_page(Page(id=f"dash{p}", title=f"Dash {p}"))
        for t in range(4):
            node = charts[p * 4 + t]
            graph.add_tile(page.id, Tile(id=f"c{p}{t}", node_id=node.id,
                                         port="figure",
                                         rect=(t * 430, 0, 420, 320)))
            node = tables[p * 4 + t]
            graph.add_tile(page.id, Tile(id=f"t{p}{t}", node_id=node.id,
                                         port="table",
                                         rect=(t * 430, 340, 420, 320)))
    graph.add_page(Page(id="rep", title="Report", kind="report",
                        body="# Page report\n\n![[Table 1|rows=500]]\n\n"
                             "![[Chart 1]]\n"))
    return gen, tables


def perf_table(title):
    from flograph.core import perf
    rows = sorted(perf.tallies().items(), key=lambda kv: -kv[1].total)
    print(f"\n{title}")
    print(f"  {'label':<34}{'calls':>7}{'total':>11}{'longest':>11}")
    for label, t in rows:
        if t.total < 0.001:
            continue
        print(f"  {label:<34}{t.count:>7}{t.total * 1000:>9.0f}ms"
              f"{t.longest * 1000:>9.0f}ms")


def main(argv):
    rows = int(argv[1]) if len(argv) > 1 else 50_000

    from PySide6.QtCore import Qt, QSettings
    from PySide6.QtWidgets import QApplication

    scratch = Path(tempfile.mkdtemp(prefix="flograph-bench-"))
    for fmt in (QSettings.NativeFormat, QSettings.IniFormat):
        QSettings.setPath(fmt, QSettings.UserScope, str(scratch / "settings"))

    app = QApplication.instance() or QApplication([])

    from flograph.core import NodeRegistry, parse_spec, perf
    from flograph.ui.mainwindow import MainWindow
    from flograph.ui.perf import StallWatchdog

    registry = NodeRegistry()
    registry.load_builtins()
    registry.register(parse_spec(GEN_SRC, "bench.gen"))
    registry.register(parse_spec(SLEEPER_SRC, "bench.sleeper"))

    win = MainWindow(registry)
    win.confirm_close = False
    win.resize(1600, 1000)
    win.show()
    pump(app, 0.5)

    gen, tables = build(win, rows)
    pump(app, 0.5)
    dog = StallWatchdog()
    dog.start()

    def section(title):
        perf.reset()
        dog.reset()
        return time.perf_counter()

    def freezes(start):
        # the watchdog hears about a freeze on its first tick after it; a
        # freeze that ended inside the last pump has not been ticked yet
        pump(app, 0.3)
        print(f"  wall {time.perf_counter() - start:6.2f}s | longest freeze "
              f"{dog.longest * 1000:6.0f}ms ({dog.longest_label or '?'}) | "
              f"freezes >{int(1000 * 0.2)}ms: {dog.count}")

    # -- cold run -------------------------------------------------------
    start = section("run")
    win.engine.run_all()
    ok = wait_for(app, win.engine.run_finished, 300)
    pump(app, 1.5)                        # let deferred card work land
    print(f"\n== Run all ({rows:,} rows, {len(win.graph.nodes)} nodes)"
          f"{'' if ok else ' — TIMED OUT'}")
    freezes(start)
    perf_table("GUI-thread time by label")

    # -- warm re-run: the generator's seed changes, everything re-runs ---
    start = section("rerun")
    win.graph.set_param(gen.id, "seed", 1)
    win.engine.run_all()
    wait_for(app, win.engine.run_finished, 300)
    pump(app, 1.5)
    print("\n== Re-run after an upstream change")
    freezes(start)
    perf_table("GUI-thread time by label")

    # -- what out-of-sight work costs when it comes into sight -----------
    # AE2 put these off until they are looked at; this is the bill when
    # they are.
    start = section("show page")
    win.page_bar.select_page("dash0")
    pump(app, 1.5)
    print("\n== Show a dashboard page (4 charts, 4 formatted tables)")
    freezes(start)
    perf_table("GUI-thread time by label")
    win.page_bar.select_page(None)
    pump(app, 0.5)

    report_item = next(i for i in win.scene.node_items.values()
                       if getattr(i, "report_card", False))
    start = section("report")
    win.view.center_on_scene(report_item.sceneBoundingRect().center())
    pump(app, 1.5)
    print("\n== Scroll the report card into view")
    freezes(start)
    perf_table("GUI-thread time by label")
    win.view.center_on_scene(win.scene.node_items[tables[0].id]
                             .sceneBoundingRect().center())
    pump(app, 0.5)

    # -- sort a formatted card ------------------------------------------
    item = win.scene.node_items[tables[0].id]
    view = item._table_viewer_view
    start = section("sort")
    view.sortByColumn(3, Qt.DescendingOrder)
    view.viewport().repaint()
    print(f"\n== Sort a formatted {rows:,}-row card: "
          f"{(time.perf_counter() - start) * 1000:.0f}ms")

    # -- save, then reopen ----------------------------------------------
    path = str(scratch / "bench.flograph")
    win._project_path = path
    start = time.perf_counter()
    win._save()
    while win._cache_save_signals is not None:
        pump(app, 0.05)
    print(f"\n== Save: {time.perf_counter() - start:.2f}s")
    start = section("open")
    win.open_path(path, confirm=False)
    opened = time.perf_counter() - start
    pump(app, 3.0)
    print(f"\n== Open: {opened:.2f}s until open_path returned")
    freezes(start)
    perf_table("GUI-thread time by label")

    # -- Stop on a node that never checks -------------------------------
    sleeper = registry.instantiate("bench.sleeper", pos=(-900, 800))
    win.graph.add_node(sleeper)
    print(f"\n  (engine active before Stop test: {win.engine.active})")
    win.engine.run_targets([sleeper.id])
    pump(app, 0.5)
    ended = []
    win.engine.run_finished.connect(lambda *a: ended.append(time.perf_counter()))
    print(f"  (sleeper status: {win.graph.nodes[sleeper.id].status}, "
          f"active: {win.engine.active})")
    start = time.perf_counter()
    win.engine.cancel()
    while not ended and time.perf_counter() - start < 30:
        pump(app, 0.01)
    print(f"\n== Stop with a node that ignores cancel: "
          f"{(ended[0] if ended else time.perf_counter()) - start:.2f}s "
          f"until the run ended")

    dog.stop()
    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
