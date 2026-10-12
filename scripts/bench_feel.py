"""Benchmark how the app *feels*: work per pan frame and per keystroke.

bench_busy.py times a heavy run. This one counts what a gesture costs on a
canvas of Table cards, input controls and 300 plain nodes, plus a 24-tile
dashboard and a report page:

- pan the canvas at 100% and 50%: ribbon-button paints and NodeItem
  boundingRect calls per frame, minimap snapshots;
- drag a node: minimap snapshots during and after, Table refreshes;
- type 20 keys into a report page (Live off): Table refreshes per key;
- drag a dashboard tile, then pan the page: ribbon paints per frame.

Counts, not milliseconds, are the point. The app runs on machines of every
calibre and a fast dev box hides work that grows with the flow; a count
that grows with node or card count on every frame is a bug on any machine.
tests/test_feel_budgets.py holds the same budgets as tests.

Usage:
    python scripts/bench_feel.py            # this checkout's src
    python scripts/bench_feel.py --slow     # pinned to one CPU core: a
                                            # rough stand-in for a low-end
                                            # laptop, for the times beside

Runs offscreen; needs no display. Writes only into a temporary folder.
"""
import collections
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("FLOGRAPH_MEMORY_ADAPT", "0")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "src"))
if "--slow" in sys.argv and hasattr(os, "sched_setaffinity"):
    os.sched_setaffinity(0, {sorted(os.sched_getaffinity(0))[0]})
    print("pinned to one core")
from pathlib import Path
from PySide6.QtCore import QSettings, Qt, QPointF, QPoint, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
T = Path(tempfile.mkdtemp(prefix="flograph-feel-"))
for fmt in (QSettings.NativeFormat, QSettings.IniFormat):
    QSettings.setPath(fmt, QSettings.UserScope, str(T / "settings"))
app = QApplication([])
from flograph.core import NodeRegistry, Page, Tile
from flograph.ui.mainwindow import MainWindow
import flograph.ui.spreadsheet.ribbon as R
from flograph.ui.canvas.node_item import NodeItem
from flograph.ui.spreadsheet.actions import SheetActions
C = collections.Counter()
def wrap(cls, name, key):
    o = getattr(cls, name)
    def w(self, *a, **k):
        C[key] += 1
        return o(self, *a, **k)
    setattr(cls, name, w)
wrap(R.RibbonButton, 'paintEvent', 'ribbon_paint')
wrap(NodeItem, 'boundingRect', 'boundingRect')
wrap(SheetActions, 'refresh', 'table_refresh')
def pump(s):
    e = time.perf_counter() + s
    while time.perf_counter() < e:
        app.processEvents(); time.sleep(0.003)
reg = NodeRegistry(); reg.load_builtins()
win = MainWindow(reg); win.confirm_close = False; win.resize(1600, 1000); win.show(); pump(0.5)
g = win.graph
alltypes = list(reg.type_ids()) if hasattr(reg, 'type_ids') else list(reg._specs)
def tid(s): return next(t for t in alltypes if t.endswith(s))
nodes = []
for n, k in enumerate([tid('io.table')] * 20 + [tid('input.slider')] * 10 + [tid('transform.filter_rows')] * 300):
    node = reg.instantiate(k, pos=((n % 25) * 450, (n // 25) * 400)); g.add_node(node); nodes.append(node)
pump(1.5)
view = win.view; mm = view.minimap
def snaps(): return getattr(mm, 'snapshots', None)
for zoom in (1.0, 0.5):
    view.resetTransform(); view.scale(zoom, zoom); view.centerOn(QPointF(1500, 300)); pump(0.5); C.clear(); s0 = snaps()
    ms = []
    for i in range(40):
        t = time.perf_counter()
        view.scroll_by(-30, 0); view.viewport().repaint(); app.processEvents()
        ms.append((time.perf_counter() - t) * 1000)
    print(f"pan zoom {zoom}: per frame ribbon paints {C['ribbon_paint']/40:.1f}, boundingRect {C['boundingRect']/40:.0f}, minimap snapshots {None if s0 is None else snaps()-s0} | median frame {sorted(ms)[20]:.1f} ms")
view.resetTransform(); view.centerOn(QPointF(2000, 600)); pump(0.5)
item = view.scene().node_items[nodes[60].id]; vp = view.viewport()
st = view.mapFromScene(item.sceneBoundingRect().center())
def send(vp, t, p, b=Qt.LeftButton, bs=Qt.LeftButton):
    app.sendEvent(vp, QMouseEvent(t, QPointF(p), QPointF(vp.mapToGlobal(p)), b, bs, Qt.NoModifier))
C.clear(); s0 = snaps(); send(vp, QEvent.MouseButtonPress, st)
for k in range(1, 31):
    send(vp, QEvent.MouseMove, st + QPoint(5 * k, 2 * k), Qt.NoButton); vp.repaint(); app.processEvents()
send(vp, QEvent.MouseButtonRelease, st + QPoint(150, 60), Qt.LeftButton, Qt.NoButton)
mid = None if s0 is None else snaps() - s0; pump(0.5)
print(f"node drag 30 frames: minimap snapshots during {mid}, after settle {None if s0 is None else snaps()-s0}; table refreshes {C['table_refresh']}; boundingRect/frame {C['boundingRect']/30:.0f}")
g.add_page(Page(id="rp", title="Rep", kind="report", body="# Hello\n"))
pump(0.5); win._on_current_page_changed("rp"); pump(0.8)
rp = [w for w in app.allWidgets() if type(w).__name__ == 'ReportPage'][0]
rp._live_btn.setChecked(False); pump(0.3); rp.editor.setFocus(); C.clear()
ms = []
for ch in "hello world, typing ":
    t = time.perf_counter()
    QTest.keyClick(rp.editor, ch); app.processEvents()
    ms.append((time.perf_counter() - t) * 1000)
print(f"report typing: table refreshes per key {C['table_refresh']/20:.2f} | median key {sorted(ms)[10]:.1f} ms")
g.add_page(Page(id="d1", title="Dash"))
for i in range(24):
    spec = reg.get(nodes[i].type_id) if hasattr(reg, 'get') else reg.spec(nodes[i].type_id)
    g.add_tile("d1", Tile(id=f"t{i}", node_id=nodes[i].id, port=spec.outputs[0].name, rect=((i % 6) * 260, (i // 6) * 230, 250, 220)))
pump(0.5); win._on_current_page_changed("d1"); pump(1.5)
dv = [w for w in win._dashboard_pages["d1"].findChildren(object) if type(w).__name__ == 'DashboardView'][0]
tiles = [i for i in dv.scene().items() if type(i).__name__ == 'TileItem']; it = tiles[0]; vp = dv.viewport()
st = dv.mapFromScene(it.sceneBoundingRect().topLeft() + QPointF(60, 8))
send(vp, QEvent.MouseButtonPress, st); C.clear()
for k in range(1, 31):
    send(vp, QEvent.MouseMove, st + QPoint(4 * k, 3 * k), Qt.NoButton); vp.repaint(); app.processEvents()
send(vp, QEvent.MouseButtonRelease, st + QPoint(120, 90), Qt.LeftButton, Qt.NoButton)
print(f"dashboard tile drag: ribbon paints/frame {C['ribbon_paint']/30:.1f}")
C.clear()
for k in range(30):
    dv.scroll_by(0, -15); vp.repaint(); app.processEvents()
print(f"dashboard pan: ribbon paints/frame {C['ribbon_paint']/30:.1f}")
sys.stdout.flush(); os._exit(0)
