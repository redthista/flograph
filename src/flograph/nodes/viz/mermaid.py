"""Mermaid Diagram

Render a Mermaid diagram on the canvas — and build one straight from a table.

**Mode**:

  • `template` — write Mermaid yourself in the box; `{{col}}` tokens are
    filled from the first row of the input.
  • `flowchart` — treat the input as an edge list: one arrow per row from
    **From column** to **To column**, optionally labelled by **Label
    column**. An org chart, a state machine, a dependency graph, a Sankey-ish
    flow — from data you already have.
  • `gantt` — one bar per row from **Task**, **Start** and **End** (or
    **Duration** in days), grouped by **Section**.

Two outputs: **html** (renders here and on a dashboard tile; Mermaid is
loaded from a CDN, so this tile needs internet) and **mermaid** (the source
text — wire into Write Text to keep it in version control).
"""
NODE = {
    "label": "Mermaid Diagram",
    "category": "Viz",
    "version": "1.0",
    "card": "webview",
    "inputs": [("data", "dataframe", {"optional": True})],
    "outputs": [("html", "string"), ("mermaid", "string")],
}
PARAMS = [
    {"name": "mode", "type": "choice", "label": "Mode",
     "options": ["template", "flowchart", "gantt"], "default": "template"},
    {"name": "direction", "type": "choice", "label": "Direction",
     "options": ["TD", "LR", "BT", "RL"], "default": "TD",
     "visible_when": {"mode": "flowchart"}},
    {"name": "from_col", "type": "columns", "label": "From column",
     "default": "", "multi": False, "visible_when": {"mode": "flowchart"}},
    {"name": "to_col", "type": "columns", "label": "To column",
     "default": "", "multi": False, "visible_when": {"mode": "flowchart"}},
    {"name": "label_col", "type": "columns", "label": "Label column",
     "default": "", "multi": False, "visible_when": {"mode": "flowchart"}},
    {"name": "task_col", "type": "columns", "label": "Task", "default": "",
     "multi": False, "visible_when": {"mode": "gantt"}},
    {"name": "start_col", "type": "columns", "label": "Start", "default": "",
     "multi": False, "visible_when": {"mode": "gantt"}},
    {"name": "end_col", "type": "columns", "label": "End", "default": "",
     "multi": False, "visible_when": {"mode": "gantt"}},
    {"name": "duration_col", "type": "columns", "label": "Duration (days)",
     "default": "", "multi": False, "visible_when": {"mode": "gantt"}},
    {"name": "section_col", "type": "columns", "label": "Section", "default": "",
     "multi": False, "visible_when": {"mode": "gantt"}},
    {"name": "title", "type": "string", "label": "Title", "default": "",
     "visible_when": {"mode": "gantt"}},
    {"name": "theme", "type": "choice", "label": "Theme",
     "options": ["default", "dark", "neutral", "forest"], "default": "default"},
    {"name": "source", "type": "text", "label": "Mermaid source",
     "default": "flowchart TD\n  A[Start] --> B{OK?}\n  B -->|yes| C[Done]\n  B -->|no| A",
     "visible_when": {"mode": "template"}},
    {"name": "width", "type": "int", "label": "Width", "default": 460,
     "min": 200, "max": 1600},
    {"name": "height", "type": "int", "label": "Height", "default": 360,
     "min": 120, "max": 2000},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

_MERMAID_JS = "https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js"


def _nid(cache, label):
    if label not in cache:
        cache[label] = f"n{len(cache)}"
    return cache[label]


def _esc(text):
    return str(text).replace('"', "'").replace("\n", " ")


def _flowchart(df, p):
    frm = (p.get("from_col") or "").strip()
    to = (p.get("to_col") or "").strip()
    lbl = (p.get("label_col") or "").strip()
    for name, col in (("From column", frm), ("To column", to)):
        if not col:
            raise ValueError(f"flowchart needs '{name}'")
        if col not in df.columns:
            raise ValueError(f"column {col!r} not in the table")
    lines = [f"flowchart {p.get('direction', 'TD')}"]
    ids = {}
    for _, row in df.iterrows():
        a, b = row[frm], row[to]
        if a is None or b is None or (isinstance(a, float) and a != a):
            continue
        ai = _nid(ids, a)
        bi = _nid(ids, b)
        edge = f'  {ai}["{_esc(a)}"] --> '
        if lbl and lbl in df.columns and row[lbl] not in (None, ""):
            edge += f'|{_esc(row[lbl])}| '
        edge += f'{bi}["{_esc(b)}"]'
        lines.append(edge)
    return "\n".join(lines)


def _gantt(df, p):
    task = (p.get("task_col") or "").strip()
    start = (p.get("start_col") or "").strip()
    end = (p.get("end_col") or "").strip()
    dur = (p.get("duration_col") or "").strip()
    if not task or task not in df.columns:
        raise ValueError("gantt needs a valid 'Task' column")
    if not start or start not in df.columns:
        raise ValueError("gantt needs a valid 'Start' column")
    if not ((end and end in df.columns) or (dur and dur in df.columns)):
        raise ValueError("gantt needs an 'End' or a 'Duration (days)' column")
    section = (p.get("section_col") or "").strip()
    lines = ["gantt", "  dateFormat YYYY-MM-DD"]
    if p.get("title"):
        lines.insert(1, f"  title {_esc(p['title'])}")
    current = None
    for i, (_, row) in enumerate(df.iterrows()):
        if section and section in df.columns and row[section] != current:
            current = row[section]
            lines.append(f"  section {_esc(current)}")
        s = str(row[start])[:10]
        if end and end in df.columns and row[end] not in (None, ""):
            span = str(row[end])[:10]
        else:
            span = f"{int(float(row[dur]))}d"
        lines.append(f"  {_esc(row[task])} :t{i}, {s}, {span}")
    return "\n".join(lines)


def _template(df, source):
    import re

    if df is None or not len(df):
        return source
    row = df.iloc[0].to_dict()
    return re.sub(
        r"\{\{\s*([\w.\-]+)\s*\}\}",
        lambda m: str(row.get(m.group(1), m.group(0))),
        source)


def run(ctx, data=None):
    p = ctx.params
    mode = p.get("mode", "template")

    if mode == "flowchart":
        if data is None:
            raise ValueError("flowchart mode needs a table wired into 'data'")
        code = _flowchart(data, p)
    elif mode == "gantt":
        if data is None:
            raise ValueError("gantt mode needs a table wired into 'data'")
        code = _gantt(data, p)
    else:
        code = _template(data, p.get("source") or "")
    if not code.strip():
        raise ValueError("nothing to render — empty diagram")

    theme = p.get("theme", "default")
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>html,body{margin:0;background:transparent}"
        ".mermaid{display:flex;justify-content:center;padding:8px}</style>"
        f"<script src='{_MERMAID_JS}'></script></head><body>"
        f"<pre class='mermaid'>{code}</pre>"
        "<script>mermaid.initialize({startOnLoad:true,theme:'" + theme + "',"
        "securityLevel:'loose'});</script></body></html>"
    )
    ctx.log(f"{mode} diagram, {len(code.splitlines())} line(s)")
    return {"html": html, "mermaid": code}
