from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Optional

from .params import ParamSpec
from .ports import FLOW_INPUT, FLOW_OUTPUT, PortSpec, is_flow


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
    # rich-card kind declared by NODE["card"] (e.g. "webview", "figure"); drives
    # canvas/dashboard rendering. Lives in `source`, so it survives fork/save —
    # unlike the old type_id-based dispatch. None = an ordinary node.
    card: Optional[str] = None
    # which widget a card == "control" node draws (NODE["control"]): "slider",
    # "toggle", ... None for every other card kind. Like `card`, it lives in
    # `source`, so forking or saving the node keeps it.
    control: Optional[str] = None
    # declared by NODE["exclusive"]: this node cannot run beside another, so
    # the engine drains the in-flight set and gives it the process to itself.
    # For matplotlib, which is not thread-safe from a worker, and for anything
    # reaching a resource that tolerates one user at a time. Like `card`, it
    # lives in `source`, so forking or saving the node keeps it.
    exclusive: bool = False
    # placeholder standing in for a type_id serialization couldn't resolve
    broken: bool = False
    # library sub-section for user-saved nodes; None/"" = ungrouped, top-level
    group: Optional[str] = None

    def input(self, name: str) -> Optional[PortSpec]:
        if is_flow(name):
            return FLOW_INPUT   # implicit on every node; see core.ports
        return next((p for p in self.inputs if p.name == name), None)

    def output(self, name: str) -> Optional[PortSpec]:
        if is_flow(name):
            return FLOW_OUTPUT
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
    also the serialization signal). `status`/`status_message`/`progress` are
    runtime-only and never serialized; every node loads dirty.
    """
    id: str
    spec: NodeSpec
    code_override: Optional[str] = None
    params: dict[str, Any] = field(default_factory=dict)
    pos: tuple[float, float] = (0.0, 0.0)
    label_override: Optional[str] = None
    description: str = ""
    # Skipped by every run, along with everything downstream of it. The node
    # keeps its params, its wires and whatever it last produced; it simply
    # does not execute. For trying a graph without one branch, or parking a
    # step that is slow or broken without unwiring it.
    active: bool = True
    # Pinned output: the node serves whatever it last produced and is not
    # re-run, however many times Run All is pressed. For the expensive step
    # at the top of a flow — a slow read from a remote source — that is
    # already set up and working. Unfreeze to pull it again.
    frozen: bool = False
    # Runs only in a run that names it: Run All walks past, and so does the
    # reactive re-run a slider or a typed cell sets off. For the step nobody
    # wants fired by accident — the write that costs money, the mail that
    # goes out, the read that takes four minutes.
    #
    # Not a third spelling of `active`. A deactivated node takes its whole
    # branch out of every run; a manual one holds its place, and whatever it
    # last produced stays available to the nodes below it exactly as a
    # frozen node's value does. Only when it has produced nothing yet is the
    # branch below skipped too — there is no input for it to run on, and
    # skipping it says so more clearly than letting each node fail.
    manual: bool = False
    # What this node's params and inputs hashed to at the moment it was
    # frozen. Compared after a run to tell a pin that still reflects the
    # graph from one that has been quietly overtaken by an edit upstream;
    # None on a node that was never frozen. See engine.cache_persistence.
    frozen_fingerprint: Optional[str] = None
    # Run this node on its own, with nothing else in flight — or explicitly
    # alongside others, overriding a script that asks to be exclusive. None,
    # which is every node until somebody says otherwise, means "follow the
    # script's NODE['exclusive']". Tri-state for the same reason port_labels
    # is: an instance that had silently baked in the spec's answer would keep
    # the old one after the code was edited to say something else.
    exclusive_override: Optional[bool] = None
    # Read-only guard: params, code and position are frozen so a working node
    # cannot be nudged by accident. Purely a UI protection — a locked node
    # runs exactly as it always did, and can still be deleted, that being an
    # aimed and undoable act rather than the stray drag this is here to stop.
    locked: bool = False
    # canvas-UI-only: hides this node's embedded preview widget (figure/
    # webview/table/slicer) on the model canvas to save render cost; the
    # node still renders fully on Dashboard pages regardless of this flag.
    canvas_preview_enabled: bool = True
    # canvas-UI-only: float this node's port names beside its pins.
    # None — every node until somebody right-clicks one — means "follow the
    # canvas-wide preference"; True/False is an explicit override for this
    # node. Tri-state rather than a plain bool so the global toggle keeps
    # working on nodes nobody has singled out.
    port_labels: Optional[bool] = None
    # canvas-UI-only: show this node's two flow pins (see core.ports). Hidden
    # on every node until asked for, because the ordering they exist to
    # express is the exception rather than the rule and two more pins on
    # every node is a real cost to a canvas that never uses them. A pin with
    # an order edge on it is drawn regardless — a wire has to end somewhere.
    # Tri-state for the same reason port_labels is: None follows the
    # canvas-wide preference, so the global toggle keeps working on nodes
    # nobody has singled out.
    flow_pins: Optional[bool] = None
    # canvas-UI-only: gather this node's pins back into the header instead of
    # running them down its edge. For a node with many ports, whose pins
    # otherwise extend past the bottom of the card by design. Expanded by
    # default — a collapsed node hides which input is which, which is only
    # worth paying once a graph is complex enough to want the quiet.
    ports_collapsed: bool = False
    # canvas-UI-only: draw this plain node as the compact square (True) or
    # the wide labelled box (False). None — every node until somebody
    # right-clicks one — means "follow the canvas-wide preference".
    # Tri-state rather than a plain bool for the same reason port_labels is:
    # the global toggle has to keep working on nodes nobody has singled out.
    # Ignored by every card kind, which has only ever had the one size.
    compact_view: Optional[bool] = None
    # custom header colour (hex string); None = default theme colour
    color: Optional[str] = None
    # canvas-UI-only: what a compact node draws inside its square. Empty
    # means the mark its category maps to (see ui.canvas.marks); a name from
    # marks.MARK_NAMES picks a different drawn mark instead.
    mark: str = ""
    # canvas-UI-only: a few characters drawn in place of a mark. Wins over
    # `mark` when set. Two fields rather than one because a single one would
    # have to guess whether "funnel" meant the drawn funnel or the literal
    # word — a guess that changes meaning the day a mark is named after
    # something somebody typed.
    mark_text: str = ""
    # canvas-UI-only: a picture drawn in the square instead of a mark, held
    # as a data: URI so it travels inside the .flograph file rather than as a
    # path into a folder the next person won't have. Downscaled on import —
    # see ui.canvas.marks.encode_mark_image. Wins over both fields above.
    mark_image: str = ""
    # Index in the canvas's back-to-front stacking order (see core.layers).
    # None means "not placed yet" — Graph.add_node puts it on top, which is
    # both what a freshly dropped node wants and what a file written before
    # layering existed gets, reproducing its old insertion-order stacking.
    z: Optional[int] = None
    # Inputs this instance grew past its script (Graph._grow_input: wires
    # landing on a spare port). The list is the source of truth — `spec` is
    # replaced wholesale by forks, loads and library resets, so every one of
    # those paths re-applies these through adopt_extra_inputs() to keep both
    # the grown ports and their wires alive. Serialized with the node.
    extra_inputs: list[PortSpec] = field(default_factory=list)
    status: NodeStatus = NodeStatus.IDLE
    status_message: str = ""
    # How far through its own work the running node says it is, 0..1, from
    # ctx.progress(). Runtime-only like status, and only meaningful while
    # RUNNING: Graph.set_status zeroes it on the way to any other status, so
    # a finished or cancelled node can never leave a stale fraction behind.
    # 0.0 means "no fraction reported" — the node shows an indeterminate
    # pulse rather than an empty ring.
    progress: float = 0.0
    dirty: bool = True
    _temp_edit: bool = False  # transient — unsaved edits in editor panel

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

    def adopt_extra_inputs(self, extras: list[PortSpec]) -> None:
        """Grow (or regrow) this instance's inputs by `extras`.

        The trailing spare of the script's own declaration stays last — the
        empty slot is an invitation, and it belongs at the bottom whatever
        has been added above it. Replaces `spec` rather than mutating it:
        the spec object may be the registry's shared one.

        Regrowing has to start from the script's own ports, not from
        whatever the last call left behind: the second growth is handed
        [in3, in4] while `spec` already carries the in3 from the first, and
        splicing onto that spec listed in3 twice. A duplicate name is worse
        than untidy — the canvas keys its pins by name, so the two entries
        collapse into one and the loser is stranded at the node's origin as
        a pin nothing owns and no rebuild can reach.
        """
        grown = {p.name for p in self.extra_inputs}
        self.extra_inputs = list(extras)
        fixed = [p for p in self.spec.inputs if p.name not in grown]
        spare_tail = []
        if fixed and fixed[-1].spare:
            fixed, spare_tail = fixed[:-1], fixed[-1:]
        self.spec = replace(
            self.spec,
            inputs=[*fixed, *self.extra_inputs, *spare_tail])
