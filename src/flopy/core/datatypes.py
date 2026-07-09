"""Port type system: a small closed set of types with a table-driven
compatibility rule and per-type wire colors (hex strings — QColor lives in
ui.theme, not here).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class PortType(str, Enum):
    ANY = "any"
    DATAFRAME = "dataframe"
    SERIES = "series"
    NUMBER = "number"
    STRING = "string"
    BOOL = "bool"
    OBJECT = "object"
    FIGURE = "figure"


# Concrete types that may flow one-way into an OBJECT input.
_WIDENS_TO_OBJECT = frozenset({
    PortType.DATAFRAME,
    PortType.SERIES,
    PortType.NUMBER,
    PortType.STRING,
    PortType.BOOL,
    PortType.FIGURE,
})

WIRE_COLORS: dict[PortType, str] = {
    PortType.ANY: "#e8e8e8",
    PortType.DATAFRAME: "#2dd4bf",
    PortType.SERIES: "#7dd3c8",
    PortType.NUMBER: "#4ade80",
    PortType.STRING: "#fbbf24",
    PortType.BOOL: "#f87171",
    PortType.OBJECT: "#9ca3af",
    PortType.FIGURE: "#c084fc",
}


def can_connect(out_type: PortType, in_type: PortType) -> bool:
    """May a wire run from an output of `out_type` to an input of `in_type`?"""
    if out_type == in_type:
        return True
    if PortType.ANY in (out_type, in_type):
        return True
    if in_type == PortType.OBJECT and out_type in _WIDENS_TO_OBJECT:
        return True
    return False


def validate_value(value: Any, port_type: PortType) -> Optional[str]:
    """Check a runtime value against a declared port type.

    Returns an error message, or None if the value is acceptable. Imports of
    pandas/matplotlib happen lazily so flopy.core stays import-light.
    """
    if port_type in (PortType.ANY, PortType.OBJECT):
        return None
    if value is None:
        return f"got None for a port of type '{port_type.value}'"
    if port_type == PortType.NUMBER:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return _type_error(value, port_type)
        return None
    if port_type == PortType.STRING:
        return None if isinstance(value, str) else _type_error(value, port_type)
    if port_type == PortType.BOOL:
        return None if isinstance(value, bool) else _type_error(value, port_type)
    if port_type == PortType.DATAFRAME:
        import pandas as pd
        return None if isinstance(value, pd.DataFrame) else _type_error(value, port_type)
    if port_type == PortType.SERIES:
        import pandas as pd
        return None if isinstance(value, pd.Series) else _type_error(value, port_type)
    if port_type == PortType.FIGURE:
        from matplotlib.figure import Figure
        return None if isinstance(value, Figure) else _type_error(value, port_type)
    return None


def _type_error(value: Any, port_type: PortType) -> str:
    return (
        f"got {type(value).__name__!r} for a port of type '{port_type.value}'"
    )
