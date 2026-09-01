"""SVG Template

Draw an SVG once — in Inkscape, Figma, a text editor — leave `{{tokens}}`
where the numbers go, and this node fills them from your data and renders it
live on the canvas. A hand-built gauge, a floor plan that lights up, a
branded KPI strip, a stadium map: anything an SVG can be, driven by a flow.

    <text x="20" y="40">{{revenue:$,.0f}}</text>
    <circle cx="200" cy="30" r="8" fill="{{status_color}}"/>

A token is `{{name}}` or `{{name:format}}` (a Python format spec). Names
resolve against **Bindings** first (`token = column`, or `token = a literal`,
one per line), then against column **Row** of the incoming table. `${name}`
flow variables work in Bindings too.

Two outputs: **html** (a full page, for a dashboard tile or Open in Browser)
and **svg** (the raw markup — wire it into Write Text to save a `.svg`, or
into Image).
"""
NODE = {
    "label": "SVG Template",
    "category": "Viz",
    "version": "1.0",
    "card": "webview",
    "inputs": [("data", "dataframe", {"optional": True})],
    "outputs": [("html", "string"), ("svg", "string")],
}
PARAMS = [
    {"name": "svg_file", "type": "file_open", "label": "SVG file",
     "default": "", "placeholder": "leave blank to use the box below"},
    {"name": "row", "type": "int", "label": "Row", "default": 0, "min": 0,
     "max": 1_000_000},
    {"name": "missing", "type": "choice", "label": "Missing token",
     "options": ["leave as-is", "blank", "error"], "default": "leave as-is"},
    {"name": "bindings", "type": "text", "label": "Bindings",
     "default": "", "placeholder": "status_color = #22c55e\nrevenue = total_sales"},
    {"name": "svg_source", "type": "text", "label": "SVG markup",
     "default": "",
     "placeholder": "<svg xmlns='http://www.w3.org/2000/svg' ...>...</svg>"},
    {"name": "width", "type": "int", "label": "Width", "default": 420,
     "min": 200, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height", "default": 320,
     "min": 120, "max": 2000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

def _bindings(raw):
    out = {}
    for lineno, line in enumerate((raw or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, val = line.partition("=")
        name, val = name.strip(), val.strip()
        if not sep or not name:
            raise ValueError(f"bindings line {lineno}: expected 'name = value'")
        out[name] = val
    return out


_CURRENCY = ("$", "£", "€", "¥", "₹")


def _format(value, spec):
    if value is None:
        return ""
    if not spec:
        return str(value)
    prefix = ""
    if spec[0] in _CURRENCY:          # {{x:$,.0f}} -> "$" + format(x, ",.0f")
        prefix, spec = spec[0], spec[1:]
    for candidate in (value, _to_number(value)):
        if candidate is None:
            continue
        try:
            return prefix + format(candidate, spec)
        except (ValueError, TypeError):
            continue
    return prefix + str(value)


def _to_number(value):
    try:
        f = float(value)
        return int(f) if f.is_integer() else f
    except (ValueError, TypeError):
        return None


def run(ctx, data=None):
    import re

    p = ctx.params
    svg = ""
    path = (p.get("svg_file") or "").strip()
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            svg = fh.read()
    else:
        svg = p.get("svg_source") or ""
    if not svg.strip():
        raise ValueError("no SVG — pick an 'SVG file' or paste markup into "
                         "'SVG markup'")

    values = {}
    if data is not None and len(data):
        idx = max(0, min(int(p.get("row", 0) or 0), len(data) - 1))
        rowvals = data.iloc[idx].to_dict()
        values.update(rowvals)

    binds = _bindings(p.get("bindings"))
    for name, expr in binds.items():
        # a binding naming a column takes that column's value; otherwise it's
        # a literal (already ${var}-substituted by the engine)
        values[name] = values[expr] if expr in values else expr

    missing_mode = p.get("missing", "leave as-is")
    unresolved = []

    def replace(match):
        name = match.group("name")
        spec = match.group("spec") or ""
        if name in values:
            return _format(values[name], spec)
        unresolved.append(name)
        if missing_mode == "blank":
            return ""
        if missing_mode == "error":
            return match.group(0)
        return match.group(0)

    token = re.compile(r"\{\{\s*(?P<name>[\w.\-]+)\s*(?::(?P<spec>[^}]+))?\}\}")
    rendered = token.sub(replace, svg)

    if unresolved and missing_mode == "error":
        raise ValueError(f"unresolved token(s): {sorted(set(unresolved))}")
    if unresolved:
        ctx.log(f"left {len(set(unresolved))} token(s) unresolved: "
                f"{sorted(set(unresolved))}")

    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>html,body{margin:0;height:100%;background:transparent}"
        "body{display:flex;align-items:center;justify-content:center}"
        "svg{max-width:100%;max-height:100%;height:auto}</style></head>"
        f"<body>{rendered}</body></html>"
    )
    ctx.log(f"rendered SVG ({len(rendered)} chars)")
    return {"html": html, "svg": rendered}
