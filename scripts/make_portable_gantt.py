"""Build dist/gantt_for_0.1.9.flograph — the tutorial with the Gantt node's
whole source inlined on each chart node, so the file opens on a flograph
that has never heard of flograph.viz.gantt.

Generated from the real sources, never hand-edited: re-run it after touching
either half and the portable copy follows.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "src/flograph/core/gantt.py"
NODE = ROOT / "src/flograph/nodes/viz/gantt.py"
TEMPLATE = ROOT / "src/flograph/templates/16_project_gantt.flograph"
OUT = ROOT / "dist/gantt_for_0.1.9.flograph"

HEADER = '''
# ---------------------------------------------------------------------------
# Scheduling, inlined.
#
# In flograph 0.1.10 this half lives in flograph/core/gantt.py and the node
# imports it. That module does not exist in 0.1.9, so this copy carries it —
# which is also what makes this file portable: the node's whole source
# travels inside the project, and nothing has to be installed for it.
# ---------------------------------------------------------------------------
'''


def core_body():
    """The scheduler, minus its module docstring and the __future__ import
    (which is only legal at the top of a module, and this is going at the
    bottom of one)."""
    source = CORE.read_text(encoding="utf-8")
    source = re.sub(r'^""".*?"""\n', "", source, count=1, flags=re.S)
    source = source.replace("from __future__ import annotations\n", "")
    # deque is the only module-level import left, and a node script's top
    # level runs at registry load — so it moves inside its one caller.
    source = source.replace("\nfrom collections import deque\n", "")
    source = source.replace(
        '    """Row indices in an order where every task follows its '
        'predecessors."""\n',
        '    """Row indices in an order where every task follows its '
        'predecessors."""\n    from collections import deque\n\n')
    return source.strip("\n")


def portable_source():
    source = NODE.read_text(encoding="utf-8")
    assert "from flograph.core.gantt import schedule" in source
    source = source.replace("\n    from flograph.core.gantt import schedule\n",
                            "")
    marker = "Gantt Chart\n"
    assert source.startswith('"""' + marker)
    source = source.replace(
        marker,
        marker + "\nA self-contained copy: this node carries its own "
        "scheduling code, so it\nruns on a flograph that does not ship a "
        "Gantt node.\n", 1)
    return source.rstrip("\n") + "\n" + HEADER + core_body() + "\n"


code = portable_source()
compile(code, "<portable gantt>", "exec")          # it must at least parse

doc = json.loads(TEMPLATE.read_text(encoding="utf-8"))
doc["flograph_version"] = "0.1.9"
charts = 0
for node in doc["graph"]["nodes"]:
    if node["type"] == "flograph.viz.gantt":
        node["code"] = code
        charts += 1
assert charts == 4, charts

intro = [n for n in doc["graph"]["nodes"] if n["id"] == "n00_intro"][0]
intro["params"]["text"] = intro["params"]["text"].replace(
    "Only the last chart draws itself",
    "**This is the portable copy.** Each chart carries the Gantt node's own\n"
    "source, so it runs on a flograph with no Gantt node in its library —\n"
    "right-click one and choose Edit Code to read it. It needs `plotly`:\n"
    "Tools > Manage Packages if it is missing.\n\n"
    "Only the last chart draws itself")
intro["params"]["height"] += 120

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
print(f"wrote {OUT}")
print(f"  {charts} chart nodes carry {len(code.splitlines())} lines of source")
print(f"  {len(json.dumps(doc)) / 1024:.0f} KB")
