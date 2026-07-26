"""Stacking order: who draws on top of whom.

Nodes, frames and dashboard tiles each carry a ``z`` — their index in a
back-to-front ordering of their own kind. Only the *order* means anything;
the numbers are normalized to 0..n-1 on every change so save files stay
stable and no arithmetic can drift.

This module is the whole of the reordering rule, kept pure so it can be
tested without a canvas: give it an ordering and which ids are moving, get
the new ordering back. Both canvases and every undo command share it, so
"bring forward" cannot come to mean two different things.
"""
from __future__ import annotations

# All four take the *selection* as a unit: a group keeps its own internal
# order and steps past whatever is outside it, which is what makes repeated
# presses walk a stack predictably.
ACTIONS = ("front", "forward", "backward", "back")


def restack(order: list[str], moving, action: str) -> list[str]:
    """The new back-to-front ordering after `action` on the `moving` ids.

    `order` is back-to-front: index 0 is drawn first, so the last entry is
    the one on top. Ids in `moving` that aren't in `order` are ignored, and
    an action that can't move anything (already at the front, say) returns
    an equal ordering — callers use that to skip pushing a no-op undo step.
    """
    if action not in ACTIONS:
        raise ValueError(f"unknown restack action {action!r} "
                         f"(valid: {', '.join(ACTIONS)})")
    moving = {i for i in moving if i in order}
    if not moving or len(moving) == len(order):
        return list(order)   # nothing to move past

    if action == "front":
        return ([i for i in order if i not in moving]
                + [i for i in order if i in moving])
    if action == "back":
        return ([i for i in order if i in moving]
                + [i for i in order if i not in moving])

    result = list(order)
    if action == "forward":
        # top-down, so a block of selected items travels together instead of
        # the topmost one being swapped past the one below it
        for i in range(len(result) - 2, -1, -1):
            if result[i] in moving and result[i + 1] not in moving:
                result[i], result[i + 1] = result[i + 1], result[i]
    else:   # backward — the mirror image, bottom-up
        for i in range(1, len(result)):
            if result[i] in moving and result[i - 1] not in moving:
                result[i], result[i - 1] = result[i - 1], result[i]
    return result


def order_of(items) -> list[str]:
    """The back-to-front ordering of things carrying ``id`` and ``z``.

    Ties (a node restored by undo can land on a z another node has since
    taken) fall back to iteration order, so the result is always a total
    order and never loses an item.
    """
    indexed = list(enumerate(items))
    indexed.sort(key=lambda pair: (pair[1].z if pair[1].z is not None else 0,
                                   pair[0]))
    return [item.id for _, item in indexed]


def next_z(items) -> int:
    """The z that puts a newly placed item on top of `items`."""
    used = [i.z for i in items if i.z is not None]
    return max(used) + 1 if used else 0
