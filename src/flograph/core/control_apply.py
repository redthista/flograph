"""When an input control's change reaches the flow — at once, or held
until someone presses Apply. Qt-free: the rules only; the undo-stack half
lives in `ui/control_binding.py`.

Live (the default, and how every control before this worked): moving a
slider writes its `value` param, which dirties the node and everything after
it, and the window re-runs them straight away.

Held: the new value goes into the control's `draft` param instead. `draft`
is cosmetic, so writing it marks nothing out of date and starts no run — the
flow keeps using the value as last applied, however many times the knob is
turned. Apply moves the draft into `value` as one undo step and asks for one
run. This is the Table's Submit (`ui/spreadsheet/binding.py`) for a single
value, and for the same reasons the draft is a param and not widget state:
it undoes, it saves, and the canvas card and a dashboard tile of the same
node always show the same pending value, because both draw from the node.

There are two held modes, differing only in *who* applies. BUTTON puts a
✓ on the control itself; WAIT leaves that off, because the control is one
field of a form whose page has an Action Button set to Apply inputs — four
fields, one press, one run.

These params are given to every control node by `parse_spec` (see
`COMMON_PARAMS`), so a control somebody writes for themselves gets Apply,
Reset and the rest without declaring any of it.
"""
from __future__ import annotations

import json
from typing import Any

# Stored as written and shown as written — a choice param has no separate
# display labels — so they are phrases, not codes.
LIVE = "instantly"                      # every change reaches the flow
BUTTON = "with ✓ on the control"        # held; the control's ✓ applies it
WAIT = "with an Apply button"           # held; Action Button ▸ Apply inputs
MODES = (LIVE, BUTTON, WAIT)

# Params every control node gets, in this order, unless its script declares
# one of the same name itself (which wins). A section of their own, folded,
# so a fresh Slider's properties look the way they always did.
_SECTION = "Behaviour"
COMMON_PARAMS: list[dict] = [
    {"name": "apply", "type": "choice", "label": "Apply changes",
     "options": list(MODES), "default": LIVE, "cosmetic": True,
     "section": _SECTION, "folded": True},
    {"name": "draft", "type": "text", "label": "Change not yet applied",
     "hidden": True, "default": "", "cosmetic": True},
    {"name": "show_reset", "type": "bool", "label": "Show reset button",
     "default": False, "cosmetic": True, "section": _SECTION},
    # Not cosmetic: naming a variable changes which nodes read this one,
    # and the graph re-derives those edges itself (core.varlinks).
    {"name": "variable", "type": "string", "label": "Variable name",
     "default": "", "section": _SECTION,
     "placeholder": "e.g. threshold — then write ${threshold} in any box"},
]


def apply_mode(node) -> str:
    mode = node.params.get("apply") if node is not None else None
    return mode if mode in MODES else LIVE


def is_held(node) -> bool:
    return apply_mode(node) != LIVE


def draft_text(params: dict) -> str:
    return str((params or {}).get("draft") or "")


def has_draft(node) -> bool:
    return node is not None and bool(draft_text(node.params))


def encode(value: Any) -> str:
    """A value as a draft. JSON, so a held "" (an emptied text box) is
    still a draft — `'""'` — and only a truly blank draft means none."""
    return json.dumps(value)


def decode(text: Any):
    """`(True, value)` for a readable draft, `(False, None)` otherwise. A
    draft that does not parse is treated as no draft: a hand-edited file
    should leave the control on its applied value, not break it."""
    text = str(text or "")
    if not text:
        return False, None
    try:
        return True, json.loads(text)
    except ValueError:
        return False, None


def shown_params(params: dict) -> dict:
    """The params a control should *draw*: its own, with a pending draft in
    place of the applied value. run() reads the applied one; the card shows
    what the user has set, and the pending marker says the two differ."""
    shown = dict(params or {})
    ok, value = decode(draft_text(shown))
    if ok:
        shown["value"] = value
    return shown


def default_value(node) -> Any:
    """What Reset puts back: the script's own default for `value`."""
    spec = node.spec.param("value") if node is not None else None
    return spec.default if spec is not None else None


def shown_value(node) -> Any:
    return shown_params(node.params).get("value")


def differs_from_default(node) -> bool:
    return shown_value(node) != default_value(node)


def held_controls(graph, ids=None) -> list[str]:
    """Ids of the controls with a change waiting to be applied — all of
    them, or only those among `ids`."""
    pool = graph.nodes if ids is None else [i for i in ids if i in graph.nodes]
    return [i for i in pool
            if graph.nodes[i].spec.card == "control"
            and has_draft(graph.nodes[i])]


def describe_pending(node) -> str:
    if not has_draft(node):
        return ""
    return "Changed — not applied yet"
