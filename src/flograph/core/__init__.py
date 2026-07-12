"""flograph.core — the Qt-free graph model.

Nothing in this package may import PySide6 (enforced by
tests/test_no_qt_in_core.py), and module import must not pull in pandas or
matplotlib either — heavy imports happen lazily inside functions.
"""
from .datatypes import PortType, can_connect, validate_value, WIRE_COLORS
from .events import Event, GraphEvents
from .graph import Connection, Frame, Graph, GraphError, Page, Tile
from .node import NodeInstance, NodeSpec, NodeStatus
from .params import ParamSpec
from .ports import PortDirection, PortSpec
from .registry import NodeRegistry, fuzzy_score
from .script import NodeScriptError, compile_run, node_filename, parse_spec
from . import serialization

__all__ = [
    "PortType", "can_connect", "validate_value", "WIRE_COLORS",
    "Event", "GraphEvents",
    "Connection", "Frame", "Graph", "GraphError", "Page", "Tile",
    "NodeInstance", "NodeSpec", "NodeStatus",
    "ParamSpec", "PortDirection", "PortSpec",
    "NodeRegistry", "fuzzy_score",
    "NodeScriptError", "compile_run", "node_filename", "parse_spec",
    "serialization",
]
