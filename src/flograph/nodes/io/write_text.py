"""Write Text

Write text to a file — an HTML page from a Gantt Chart or Show Web View, a
Report's markdown, a string a script built. Passes the text through so the
pipeline can continue.

The input is deliberately `any` rather than `string`, because the nodes
whose output *is* text do not all declare it that way: Show Web View emits
its HTML on an `object` port, and `object` will not flow into a `string`
one. Whatever arrives has to be text by the time it gets here, though —
a table is Write CSV's job, and this node says so rather than writing the
repr of a DataFrame to disk.

**Create folders** makes any missing parent directories rather than
failing, which is what you want when the path has a dated folder in it.
"""
NODE = {
    "label": "Write Text",
    "category": "IO",
    "version": "1.0",
    "inputs": [("text", "any")],
    "outputs": [("text", "string")],
}
PARAMS = [
    {"name": "path", "type": "file_save", "label": "Output file",
     "default": "", "placeholder": "e.g. plan.html"},
    {"name": "mode", "type": "choice", "label": "If file exists",
     "options": ["overwrite", "append"], "default": "overwrite"},
    {"name": "encoding", "type": "string", "label": "Encoding", "default": "",
     "placeholder": "auto (utf-8)"},
    {"name": "newline_at_end", "type": "bool", "label": "End with a newline",
     "default": False},
    {"name": "create_dirs", "type": "bool", "label": "Create folders",
     "default": False},
]


def run(ctx, text):
    import os

    p = ctx.params
    path = p["path"]
    if not path:
        raise ValueError(
            "no output file set — choose one in the node's properties")
    if text is None:
        raise ValueError("nothing to write — the text input is empty")
    if not isinstance(text, str):
        kind = type(text).__name__
        hint = (" — for a table use Write CSV, Write Excel or Write JSON"
                if kind == "DataFrame" else "")
        raise ValueError(f"Write Text takes text, but got a {kind}{hint}")

    body = text if not p.get("newline_at_end") else text.rstrip("\n") + "\n"
    if p.get("create_dirs"):
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
    appending = (p.get("mode", "overwrite") == "append"
                 and os.path.exists(path) and os.path.getsize(path) > 0)
    encoding = (p.get("encoding") or "").strip() or "utf-8"
    with open(path, "a" if appending else "w", encoding=encoding,
              newline="") as handle:
        handle.write(body)

    verb = "appended" if appending else "wrote"
    size = len(body.encode(encoding, errors="replace"))
    if size >= 1048576:
        measure = f"{size / 1048576:.1f} MB"
    elif size >= 1024:
        measure = f"{size / 1024:.0f} KB"
    else:
        measure = f"{size} bytes"
    ctx.log(f"{verb} {measure} to {path}")
    return body
