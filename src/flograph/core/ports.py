from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .datatypes import PortType


class PortDirection(str, Enum):
    INPUT = "input"
    OUTPUT = "output"


@dataclass(frozen=True)
class PortSpec:
    name: str
    type: PortType
    direction: PortDirection
    optional: bool = False  # inputs only: node may run with this port unconnected
    # inputs only: the trailing "one more slot" of a node that takes an open
    # ended stack of tables (Concatenate was the first). A wire landing on a
    # spare promotes it — the connection is rewritten to a fresh permanent
    # name and a new spare appears below — so there is always exactly one
    # visible invitation and never a dialog asking how many ports you want.
    # See Graph._grow_input, which owns the mechanics.
    spare: bool = False


# --------------------------------------------------------------- flow port

#: The reserved name of the flow port. Every node has one of each direction,
#: whatever its script says, and no script may declare a port by this name.
FLOW_PORT = "flow"

#: The implicit pair. Every node carries them, so they are two shared frozen
#: instances rather than a pair built per node.
#:
#: A wire between two of these — an *order edge* — hands over no value. It
#: says "that node first", which is the whole feature: the engine's ordering,
#: dirtying, cycle rejection and cache invalidation all follow edges without
#: caring what travels along them, so an edge that carries nothing still
#: schedules a node after its predecessor and re-runs it when that
#: predecessor changes. KNIME's flow-variable connection, minus the
#: variables (flograph has `${name}` for those — see core.varlinks).
#:
#: Deliberately *not* in `NodeSpec.inputs`/`outputs`: those lists are the
#: node's data contract, walked by the panel, the dashboard, the run
#: blocking check and the canvas's pin geometry, none of which should grow a
#: port that moves nothing. `NodeSpec.input`/`output` resolve this name
#: instead, which is what lets a flow wire be an ordinary Connection.
FLOW_INPUT = PortSpec(FLOW_PORT, PortType.FLOW, PortDirection.INPUT,
                      optional=True)
FLOW_OUTPUT = PortSpec(FLOW_PORT, PortType.FLOW, PortDirection.OUTPUT)


def is_flow(port_name: str) -> bool:
    return port_name == FLOW_PORT
