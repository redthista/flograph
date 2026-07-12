"""Declarative node parameters.

A node script declares PARAMS as a list of dicts; each becomes a ParamSpec
and maps to exactly one widget in the properties panel. Values are plain
JSON-serializable scalars kept on the NodeInstance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

PARAM_TYPES = {
    "string",     # QLineEdit
    "text",       # multiline QPlainTextEdit
    "int",        # QSpinBox
    "float",      # QDoubleSpinBox
    "bool",       # QCheckBox
    "choice",     # QComboBox (requires options)
    "file_open",  # line edit + browse (existing file)
    "file_save",  # line edit + browse (save path)
    "columns",    # free string in v1; column picker later
}

_TYPE_DEFAULTS: dict[str, Any] = {
    "string": "", "text": "", "int": 0, "float": 0.0, "bool": False,
    "choice": None, "file_open": "", "file_save": "", "columns": "",
}


@dataclass
class ParamSpec:
    name: str
    type: str
    label: str = ""
    default: Any = None
    options: list[str] = field(default_factory=list)  # choice only
    placeholder: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    multi: bool = True  # columns only: comma list (True) or single column

    @classmethod
    def from_dict(cls, d: dict[str, Any], where: str = "PARAMS") -> "ParamSpec":
        if not isinstance(d, dict):
            raise ValueError(f"{where}: each param must be a dict, got {type(d).__name__}")
        name = d.get("name")
        if not name or not isinstance(name, str) or not name.isidentifier():
            raise ValueError(f"{where}: param needs a 'name' that is a valid identifier, got {name!r}")
        ptype = d.get("type")
        if ptype not in PARAM_TYPES:
            valid = ", ".join(sorted(PARAM_TYPES))
            raise ValueError(f"{where}: param {name!r} has unknown type {ptype!r} (valid: {valid})")
        options = list(d.get("options", []))
        if ptype == "choice" and not options:
            raise ValueError(f"{where}: choice param {name!r} requires non-empty 'options'")
        default = d.get("default", _TYPE_DEFAULTS[ptype])
        if ptype == "choice" and default is None:
            default = options[0]
        return cls(
            name=name,
            type=ptype,
            label=d.get("label", name.replace("_", " ").capitalize()),
            default=default,
            options=options,
            placeholder=d.get("placeholder", ""),
            minimum=d.get("min"),
            maximum=d.get("max"),
            multi=bool(d.get("multi", True)),
        )
