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
    "password",   # QLineEdit with masked echo + reveal toggle
    "node_ref",   # QComboBox of other nodes in the graph; stores a node id
    "date",       # QDateEdit with a calendar popup; stores an ISO "YYYY-MM-DD"
}

_TYPE_DEFAULTS: dict[str, Any] = {
    "string": "", "text": "", "int": 0, "float": 0.0, "bool": False,
    "choice": None, "file_open": "", "file_save": "", "columns": "",
    "password": "", "node_ref": "", "date": "",
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
    hidden: bool = False  # not shown in the properties panel (edited elsewhere)
    ref_kind: str = ""  # node_ref only: card kind the referenced node must have
    # Show this row only while other params hold certain values:
    # {"format": ["auto", "csv"]} means "visible when format is auto or csv".
    # Several keys are ANDed. A node that reads five file types would
    # otherwise show all five sets of options at once; this lets it show the
    # ones that apply. Purely presentational — run() still receives every
    # param, visible or not, so a hidden value is never silently dropped.
    visible_when: dict[str, list[str]] = field(default_factory=dict)
    # Presentation-only: changing it cannot change what run() produces, so
    # the node is NOT marked dirty and its cached output survives. For
    # things like how a list of charts is arranged — re-running a heavy
    # node because someone asked for two columns would be absurd.
    cosmetic: bool = False

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
        cosmetic = bool(d.get("cosmetic", False))
        options = list(d.get("options", []))
        raw_when = d.get("visible_when") or {}
        if not isinstance(raw_when, dict):
            raise ValueError(
                f"{where}: param {name!r} has a 'visible_when' that is not a "
                f"dict of param -> allowed values, got {type(raw_when).__name__}")
        visible_when: dict[str, list[str]] = {}
        for controller, allowed in raw_when.items():
            if not isinstance(controller, str) or not controller.isidentifier():
                raise ValueError(
                    f"{where}: param {name!r} has a 'visible_when' key that is "
                    f"not a param name, got {controller!r}")
            if controller == name:
                raise ValueError(
                    f"{where}: param {name!r} cannot depend on its own value")
            # A bare string is the obvious way to write a single value, and
            # rejecting it would only teach people to type a one-item list.
            values = [allowed] if isinstance(allowed, str) else list(allowed)
            if not values:
                raise ValueError(
                    f"{where}: param {name!r} has an empty 'visible_when' for "
                    f"{controller!r} — it could never be shown")
            visible_when[controller] = [str(v) for v in values]
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
            hidden=bool(d.get("hidden", False)),
            ref_kind=str(d.get("ref_kind", "")),
            cosmetic=cosmetic,
            visible_when=visible_when,
        )

    def visible_for(self, values: dict[str, Any]) -> bool:
        """Should this param have a row, given the node's current params?

        Unknown controllers show the param rather than hide it: a typo in a
        script's `visible_when` should leave an option findable, not make it
        vanish with no way to get it back.
        """
        if self.hidden:
            return False
        for controller, allowed in self.visible_when.items():
            if controller not in values:
                continue
            if str(values[controller]) not in allowed:
                return False
        return True


def controllers(specs: list["ParamSpec"]) -> set[str]:
    """Names whose value decides whether some other param is shown."""
    return {name for spec in specs for name in spec.visible_when}
