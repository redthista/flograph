"""Trace Precedents / Trace Dependents — Excel's formula auditing arrows.

**Trace Precedents** on a formula cell draws an arrow into it from every
cell it reads, and a box round every range it reads (with an arrow from
the box). Press it again and it goes a level further back: the formulas
among those cells get their own arrows. **Trace Dependents** goes the
other way — arrows out to every formula that reads the cell, then to
what reads those. **Remove Arrows** clears them.

This module is the bookkeeping, Qt-free: which arrows and boxes are
drawn, and which cells have been traced already, so the next press knows
where to carry on from. The grid paints what it holds.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

Cell = tuple[int, int]
Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class Arrow:
    source: Cell            # the cell read (a range's top-left for a box)
    target: Cell            # the formula reading it
    box: Optional[Box] = None   # the range read, when it was a range


@dataclass
class Trace:
    arrows: set = field(default_factory=set)
    boxes: set = field(default_factory=set)
    _back: set = field(default_factory=set)     # traced for precedents
    _forward: set = field(default_factory=set)  # traced for dependents

    def __bool__(self) -> bool:
        return bool(self.arrows or self.boxes)

    def clear(self) -> None:
        self.arrows.clear()
        self.boxes.clear()
        self._back.clear()
        self._forward.clear()

    # ------------------------------------------------------- precedents

    def precedents(self, evaluator, start: Cell) -> int:
        """One more level of precedent arrows from `start`; the number of
        arrows added (0: nothing further to trace)."""
        start = tuple(start)
        if start not in self._back:
            frontier = {start}
        else:
            # the next level: formulas among what is already drawn
            # reading into the traced cells, not yet traced themselves
            frontier = set()
            for arrow in self.arrows:
                if arrow.target in self._back:
                    if arrow.box is None:
                        frontier.add(arrow.source)
                    else:
                        frontier |= _formulas_in(evaluator, arrow.box)
            frontier = {c for c in frontier if c not in self._back
                        and evaluator.is_formula(c)}
        added = 0
        for cell in frontier:
            self._back.add(cell)
            cells, ranges = evaluator.precedents(cell)
            for ref in cells:
                added += self._add(Arrow(ref, cell))
            for box in ranges:
                self.boxes.add(box)
                added += self._add(Arrow((box[0], box[1]), cell, box))
        return added

    # ------------------------------------------------------- dependents

    def dependents(self, evaluator, start: Cell) -> int:
        """One more level of dependent arrows from `start`."""
        start = tuple(start)
        if start not in self._forward:
            frontier = {start}
        else:
            frontier = {a.target for a in self.arrows
                        if a.source in self._forward
                        or (a.box is not None
                            and any(_inside(c, a.box)
                                    for c in self._forward))}
            frontier -= self._forward
        added = 0
        for cell in frontier:
            self._forward.add(cell)
            for reader in evaluator.dependents(cell):
                added += self._add(Arrow(cell, reader))
        return added

    def _add(self, arrow: Arrow) -> int:
        if arrow in self.arrows:
            return 0
        self.arrows.add(arrow)
        return 1


def _inside(cell: Cell, box: Box) -> bool:
    r1, c1, r2, c2 = box
    return r1 <= cell[0] <= r2 and c1 <= cell[1] <= c2


def _formulas_in(evaluator, box: Box) -> set:
    r1, c1, r2, c2 = box
    return {(r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)
            if evaluator.is_formula((r, c))}
