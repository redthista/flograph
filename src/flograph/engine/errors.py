"""Node execution errors, with tracebacks mapped back to node script lines.

Node code is exec'd under a virtual filename "<node:{id}>", so the standard
traceback machinery can't show source text for those frames — we splice the
node's source lines back in ourselves.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Optional

from flograph.core.script import node_filename


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

    return NodeError(
        node_id=node_id,
        message=f"{type(exc).__name__}: {exc}",
        exc_type=type(exc).__name__,
        formatted_tb="\n".join(parts),
        script_line=script_line,
    )
