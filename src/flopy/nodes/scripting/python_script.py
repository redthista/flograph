"""Python Script

A free-form Python node. Edit NODE to change the ports, add PARAMS for
configuration widgets, and write run() to compute the outputs.

Inputs arrive as keyword arguments (unconnected optional inputs are None).
Treat inputs as read-only — outputs are cached and shared by reference.
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
