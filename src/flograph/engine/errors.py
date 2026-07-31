"""Node execution errors, with tracebacks mapped back to node script lines.

Node code is exec'd under a virtual filename "<node:{id}>", so the standard
traceback machinery can't show source text for those frames — we splice the
node's source lines back in ourselves.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Optional

from flograph.core.script import missing_module_hint, node_filename


@dataclass
class NodeError:
    node_id: str
    message: str
    exc_type: str
    formatted_tb: str
    script_line: Optional[int] = None

    @property
    def cancelled(self) -> bool:
        return self.exc_type == "NodeCancelled"


def readonly_input_hint(exc: BaseException) -> Optional[str]:
    """The "you're writing to an input" line for the error numpy raises when
    a node writes through the read-only view it was handed, or None.

    numpy has no copy-on-write, so an array input is guarded by refusing the
    write rather than by duplicating the array (scheduler._read_only_view).
    Refusing is correct but its own message never mentions why the array is
    read-only, which makes it look like a bug in the app rather than the
    thing it is actually reporting.
    """
    if not isinstance(exc, ValueError) or "read-only" not in str(exc):
        return None
    return ("Node inputs are read-only — an array input is shared with the "
            "node upstream, and writing to it would rewrite that node's "
            "cached output and any other branch reading from it. Take a copy "
            "first: arr = arr.copy().")


def build_node_error(node_id: str, source: str, exc: BaseException) -> NodeError:
    """Extract the node-script line and a readable traceback from an exception
    raised inside a node's run()."""
    virtual = node_filename(node_id)
    source_lines = source.splitlines()
    frames = traceback.extract_tb(exc.__traceback__)

    script_line: Optional[int] = None
    parts = ["Traceback (most recent call last):"]
    for frame in frames:
        parts.append(f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}')
        if frame.filename == virtual:
            script_line = frame.lineno
            if frame.lineno and 0 < frame.lineno <= len(source_lines):
                parts.append(f"    {source_lines[frame.lineno - 1].strip()}")
        elif frame.line:
            parts.append(f"    {frame.line.strip()}")
    parts.append(f"{type(exc).__name__}: {exc}")

    # "No module named 'plotly'" is accurate and useless on its own — say
    # where to get it, since the app can install packages itself
    message = f"{type(exc).__name__}: {exc}"
    hint = missing_module_hint(exc) or readonly_input_hint(exc)
    if hint:
        message = f"{message} — {hint}"
        parts.append("")
        parts.append(hint)

    return NodeError(
        node_id=node_id,
        message=message,
        exc_type=type(exc).__name__,
        formatted_tb="\n".join(parts),
        script_line=script_line,
    )
