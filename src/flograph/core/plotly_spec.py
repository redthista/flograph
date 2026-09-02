"""The lock every Plotly-figure-building node shares.

Building a figure is not thread-safe, and node bodies share the process
(see the concurrency note in AGENTS.md): `px` resolves an unset palette by
reading the trace defaults off the shared template singleton
(`apply_default_cascade` in plotly.express._core), and stamping a template
onto a figure re-parents that same shared object. Two nodes doing both at
once corrupt its parent links, and plotly then fails deep inside itself
with a bare `ValueError: Invalid value` from `BaseFigure._index_is` — on
whichever node happened to lose the race.

Measured on the chart-gallery example, eight plotly nodes ready at once:
two runs in five failed at the default worker count, none in three at one
worker. This lock closes it.

A lock rather than `NODE["exclusive"] = True` (which is how the matplotlib
nodes handle their own thread-unsafety) because the unsafe region here is a
few milliseconds of figure construction, not the whole node body —
`exclusive` would drain every other node in flight to draw a bar chart.

## Every plotly node is otherwise self-contained

Show Plotly, Chart per Value (Plotly), Plotly Table, Plotly Style and Gantt
Chart each carry their own copy of whatever chart-building logic they need
directly in their node script, rather than sharing it from here — a node
script is meant to be readable start to finish without a trip to `core/`,
and each is droppable into a user-nodes folder on its own. This lock is the
one thing that still has to be the *same object* across all of them, so it
stays here as the one piece of shared state: a node prefers importing it
from this module (so it queues behind the built-in chart nodes rather than
beside them) and falls back to one parked in `sys.modules` when this module
isn't there to import from — see `_figure_lock()` in `plotly_table.py` or
`plotly_style.py` for the fallback itself.
"""
import threading

FIGURE_LOCK = threading.Lock()
