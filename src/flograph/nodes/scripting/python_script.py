"""Python Script

A free-form Python node. Edit NODE to change the ports, add PARAMS for
configuration widgets, and write run() to compute the outputs.

Inputs arrive as keyword arguments (unconnected optional inputs are None).
Treat inputs as read-only — outputs are cached and shared by reference. A
pandas input arrives as a copy-on-write shallow copy and a list or dict is
rebuilt one level deep, so writing to those is safe and free; a numpy input
arrives read-only, so copy it before writing. Reaching through an input to
change what is inside it still reaches the node upstream.
Return a dict keyed by output port name (or a bare value if there is exactly
one output).
"""
NODE = {
    "label": "Python Script",
    "category": "Scripting",
    "inputs": [("in1", "any", {"optional": True})],
    "outputs": [("out1", "any")],
}
PARAMS = []


def run(ctx, in1):
    ctx.log(f"received: {in1!r}")
    return {"out1": in1}
