from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .params import ParamSpec
from .ports import PortSpec


class NodeStatus(str, Enum):
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class NodeSpec:
    """A node *definition*: shared by every instance of a node type.

    Produced by script.parse_spec() from a node script's text. `source` is the
    full script; for builtin nodes it's the shipped file's text.
    """
    type_id: str
    label: str
    category: str
    inputs: list[PortSpec]
    outputs: list[PortSpec]
    params: list[ParamSpec]
    source: str
    builtin: bool = False
    doc: str = ""
    # placeholder standing in for a type_id serialization couldn't resolve
    broken: bool = False
    # library sub-section for user-saved nodes; None/"" = ungrouped, top-level
    group: Optional[str] = None

    def input(self, name: str) -> Optional[PortSpec]:
        return next((p for p in self.inputs if p.name == name), None)

    def output(self, name: str) -> Optional[PortSpec]:
        return next((p for p in self.outputs if p.name == name), None)

    def param(self, name: str) -> Optional[ParamSpec]:
        return next((p for p in self.params if p.name == name), None)

    def default_params(self) -> dict[str, Any]:
        return {p.name: p.default for p in self.params}


@dataclass
class NodeInstance:
    """A node placed on the canvas.

    `spec` is the *effective* spec: the registry's shared spec normally, or a
    re-parsed one when the user forked the code (`code_override` set — that is
    also the serialization signal). `status`/`status_message` are runtime-only
    and never serialized; every node loads dirty.
    """
    id: str
    spec: NodeSpec
    code_override: Optional[str] = None
    params: dict[str, Any] = field(default_factory=dict)
    pos: tuple[float, float] = (0.0, 0.0)
    label_override: Optional[str] = None
    status: NodeStatus = NodeStatus.IDLE
    status_message: str = ""
    dirty: bool = True

    @classmethod
    def create(cls, spec: NodeSpec, pos: tuple[float, float] = (0.0, 0.0)) -> "NodeInstance":
        return cls(id=uuid.uuid4().hex, spec=spec, params=spec.default_params(), pos=pos)

    @property
    def type_id(self) -> str:
        return self.spec.type_id

    @property
    def label(self) -> str:
        return self.label_override or self.spec.label

    @property
    def source(self) -> str:
        return self.code_override if self.code_override is not None else self.spec.source

    @property
    def forked(self) -> bool:
        return self.code_override is not None
