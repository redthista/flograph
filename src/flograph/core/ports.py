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
