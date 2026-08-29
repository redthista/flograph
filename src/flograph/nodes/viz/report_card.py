"""Report

A block of markdown that renders on the canvas and on a dashboard page,
with your charts and tables dropped into it by name.

Write the text in the "Report text" box in Properties (or double-click the
card). To place something, wire it into one of this node's inputs and refer
to that **input's name**:

    ![[a]]      whatever is wired into input "a"
    ![[b]]      ...and into "b"

Four inputs are provided. Need more, or better names? Fork the node (Edit
Code) and change the `inputs` list — `("summary", "any", {"optional": True})`
gives you `![[summary]]`. Rename them to whatever the report is about; the
embed follows the port name.

You can also name **any node on the canvas by its label**:

    ![[Sales Chart]]    that node's output, wherever it is

If a name is both one of this node's inputs and a node's label, the **input
wins** — so unplugging a wire reports that, rather than quietly swapping the
paragraph to some other node that happens to share the name.

Prefer wires where it matters. An input is a dependency the scheduler can
see: it orders this card after its source, re-runs when that source changes,
and shows on the canvas what the report is built from. A label is none of
those — handy for pulling in a number from across a big graph, but a partial
run (Run To This Node) can leave it with nothing to show, and nothing on the
canvas says where the value came from.

What each embed becomes depends on what arrives: a chart is placed as a
picture, a table as a table, a number inline in your sentence, and a plain
string as markdown — so prose composed in a Python Script node drops
straight in. A **list** of charts renders as a stack, which is how one
embed becomes one chart per region.
"""
NODE = {
    "label": "Report",
    "category": "Viz",
    "version": "1.0",
    "card": "report",
    "inputs": [("a", "any", {"optional": True}),
               ("b", "any", {"optional": True}),
               ("c", "any", {"optional": True}),
               ("d", "any", {"optional": True})],
    "outputs": [("text", "string")],
}
PARAMS = [
    {"name": "text", "type": "text", "label": "Report text",
     "default": ("## Summary\n\nWire a chart into input **a**, then place "
                 "it with `![[a]]`.\n\n![[a]]\n"),
     "placeholder": "Markdown, with ![[a]] to place a wired input"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 460, "min": 240, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 340, "min": 140, "max": 2000},
]


def run(ctx, a=None, b=None, c=None, d=None):
    # The card renders itself from the params and its wired inputs, so run()
    # has nothing to compute — but it still has to *exist* and be scheduled,
    # or nothing would establish that this node depends on what feeds it.
    # The text output makes the source available downstream (to a writer
    # node, say); the rendering is the card's job, not this function's.
    return {"text": str(ctx.params.get("text", "") or "")}
