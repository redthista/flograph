"""Column headings — columns gathered under a heading you can fold away.

Qt-free, and pandas is imported inside the functions that need it, as
everywhere in core. The card (`ui/inspector/pandas_model`), the dashboard
tile (the same model) and the printed page (`core/table_html`) all ask this
module the same two questions — which columns sit under which heading, and
which of them show while a heading is folded — so a report cannot come to
disagree with the dashboard it came off.

It is the column-wise twin of a grouped table's rows (core/table_totals.py)
and is spelled the same way, as rules::

    jan, feb, mar   heading "Q1"            # three columns under one heading
    apr, may, jun   heading "Q2" folded     # …starting folded
    jul, aug, sep   heading "2024 › Q3"     # › nests: 2024 above Q3
    heading "2024" folded sum               # set how a heading folds

**What a folded heading shows** is one column, always — the only question
is which:

* nothing more said: a narrow **stub**, the heading's name over a blank
  column, there only to be clicked open again;
* an aggregation (`sum`, `average`, … the fourteen totals know): a
  **summary** column worked out across each row of the columns it folds,
  named after the heading so a rule can colour it (`Q1 scale green`);
* ``keep <column>``: a column the table **already has** — a `q1_total` the
  data came with — shown alone. It may be a hidden one, which is how a
  matrix hands over true coarser totals (core/matrix.py).

``headings folded`` / ``headings sum`` set the starting state and the fold
for every heading at once; a heading's own line beats them.

Headings are a *view*: the table leaving the node is the one that arrived.
A summary or stub column is added to the frame the model holds (so it
sorts, totals and takes rules like any column) but never to the output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

#: The rule mode a heading line parses to.
MODE = "heading"

#: What a heading is folded into when nothing says otherwise.
STUB = "stub"
KEEP = "keep"

#: `2024 › Q1` and `2024 > Q1` both nest; `>` only with spaces round it, so
#: a heading may still say `>90 days`.
_NEST = re.compile(r"\s*›\s*|\s+>\s+")

#: What a stub column's header reads — the heading above it names it.
STUB_HEADER = "⋯"

_START_WORDS = {"folded": "closed", "closed": "closed",
                "collapsed": "closed", "fold": "closed",
                "open": "open", "expanded": "open", "unfolded": "open"}


def heading_path(text: Any) -> tuple:
    """A heading's written name as its path, outermost first."""
    parts = [p.strip() for p in _NEST.split(str(text or "").strip())]
    return tuple(p for p in parts if p)


def path_text(path) -> str:
    return " › ".join(str(p) for p in path)


def start_word(word: Any) -> Optional[str]:
    return _START_WORDS.get(str(word or "").strip().lower())


# ------------------------------------------------------------------ plan

@dataclass
class HeadingSpec:
    """What the rules said about one heading."""
    path: tuple
    fold: Optional[str] = None          # an aggregation, KEEP, STUB, None
    keep: Optional[str] = None
    start: Optional[str] = None         # "open" | "closed" | None


@dataclass
class BandPlan:
    specs: dict = field(default_factory=dict)       # path -> HeadingSpec
    #: (path, patterns) in rule order — the last one naming a column wins
    assignments: list = field(default_factory=list)
    default_start: str = "open"
    default_fold: Optional[str] = None

    @property
    def active(self) -> bool:
        return bool(self.assignments) or any(
            s.keep for s in self.specs.values())


def plan_from_rules(rules) -> BandPlan:
    plan = BandPlan()
    for rule in rules or ():
        if getattr(rule, "mode", None) != MODE:
            continue
        path = heading_path(rule.label) if rule.label else ()
        fold = rule.total_agg or (KEEP if rule.source else None)
        if not path:
            # `headings folded sum` — every heading
            if rule.total_place:
                plan.default_start = rule.total_place
            if fold and fold != KEEP:
                plan.default_fold = fold
            continue
        for depth in range(1, len(path) + 1):
            plan.specs.setdefault(path[:depth], HeadingSpec(path[:depth]))
        spec = plan.specs[path]
        if fold:
            spec.fold = fold
            spec.keep = rule.source if fold == KEEP else None
        if rule.total_place:
            spec.start = rule.total_place
        if rule.columns:
            plan.assignments.append((path, list(rule.columns)))
    return plan


# ------------------------------------------------------------------ tree

@dataclass
class Heading:
    """One heading as it lands on a table."""
    path: tuple
    columns: list                  # the visible columns under it, in order
    fold: str                      # an aggregation, KEEP or STUB
    face: str                      # the one column shown while it is folded
    start_folded: bool
    #: the columns a summary is worked out from — every real column under
    #: it, nested headings included
    sources: list = field(default_factory=list)

    @property
    def label(self) -> str:
        return str(self.path[-1])

    @property
    def level(self) -> int:
        return len(self.path) - 1

    @property
    def synthetic(self) -> bool:
        """Is `face` a column this module adds, rather than the table's?"""
        return self.fold != KEEP


@dataclass
class Tree:
    headings: dict = field(default_factory=dict)    # path -> Heading
    member_of: dict = field(default_factory=dict)   # column -> leaf path

    def __bool__(self) -> bool:
        return bool(self.headings)

    @property
    def depth(self) -> int:
        return max((len(p) for p in self.headings), default=0)

    def synthetic_names(self) -> list:
        return [h.face for h in self.headings.values() if h.synthetic]

    def is_folded(self, path, toggled=()) -> bool:
        head = self.headings.get(tuple(path))
        if head is None:
            return False
        return head.start_folded != (tuple(path) in (toggled or ()))


def resolve(plan: BandPlan, columns, frame_columns=None) -> Tree:
    """Which of `columns` (the visible ones, in order) sit under which
    heading. `frame_columns` is every column the frame has, hidden ones
    included — a `keep` may name one of those."""
    from .table_format import expand_columns

    tree = Tree()
    if not plan.active:
        return tree
    cols = [str(c) for c in columns]
    known = set(cols)
    everything = set(str(c) for c in (frame_columns or cols)) | known
    member_of: dict = {}
    for path, patterns in plan.assignments:
        for c in expand_columns(patterns, cols):
            if c in known:
                member_of[c] = path
    # a kept column that shows is part of its heading, wherever it stood
    for spec in plan.specs.values():
        if spec.keep and spec.keep in known and spec.keep not in member_of:
            member_of[spec.keep] = spec.path
    tree.member_of = member_of
    # a kept column is a summary the data already carries, so a heading
    # over it sums the columns it summarises, not it on top of them
    kept = {s.keep for s in plan.specs.values() if s.keep}
    taken = set(everything)
    for path, spec in plan.specs.items():
        under = [c for c in cols if c in member_of
                 and member_of[c][:len(path)] == path]
        if not under:
            continue
        fold = spec.fold or plan.default_fold or STUB
        start = spec.start or plan.default_start
        if fold == KEEP and spec.keep in everything:
            face = spec.keep
        else:
            if fold == KEEP:
                fold = STUB             # the column to keep isn't there
            face, n = str(path[-1]), 2
            while face in taken:
                face, n = f"{path[-1]} ({n})", n + 1
            taken.add(face)
        tree.headings[path] = Heading(
            path=path, columns=under, fold=fold, face=face,
            start_folded=start == "closed",
            sources=[c for c in under if c not in kept] or list(under))
    return tree


# --------------------------------------------------------------- summaries

def row_aggregate(part, how: str):
    """`how` across each row of `part` — a summary column's values."""
    import pandas as pd
    from pandas.api.types import is_bool_dtype, is_numeric_dtype

    from .table_totals import _NUMBER_AGGS, canonical_agg

    how = canonical_agg(how) or "sum"
    none = pd.Series([None] * len(part), index=part.index, dtype=object)
    if how == "rows":
        return pd.Series(len(part.columns), index=part.index)
    if how == "count":
        return part.notna().sum(axis=1)
    if how == "distinct":
        return part.nunique(axis=1)
    nums = part.iloc[:, [i for i in range(part.shape[1])
                         if is_numeric_dtype(part.dtypes.iloc[i])]]
    nums = nums.astype({c: int for i, c in enumerate(nums.columns)
                        if is_bool_dtype(nums.dtypes.iloc[i])})
    try:
        if how in _NUMBER_AGGS or how in ("min", "max"):
            if not nums.shape[1]:
                return none
            if how == "sum":
                return nums.sum(axis=1, min_count=1)
            if how == "average":
                return nums.mean(axis=1)
            if how == "median":
                return nums.median(axis=1)
            if how == "std":
                return nums.std(axis=1)
            if how == "variance":
                return nums.var(axis=1)
            if how == "range":
                return nums.max(axis=1) - nums.min(axis=1)
            return getattr(nums, how)(axis=1)
        if how == "first":
            return part.bfill(axis=1).iloc[:, 0]
        if how == "last":
            return part.ffill(axis=1).iloc[:, -1]
        if how == "mode":
            return part.apply(
                lambda r: (r.dropna().value_counts(sort=True).index[0]
                           if r.notna().any() else None), axis=1)
    except Exception:
        pass
    return none


def with_faces(frame, tree: Tree):
    """`frame` with a column added for each heading's summary or stub."""
    if not tree or not tree.synthetic_names():
        return frame
    import pandas as pd

    names = [str(c) for c in frame.columns]
    added = {}
    for head in tree.headings.values():
        if not head.synthetic:
            continue
        if head.fold == STUB:
            added[head.face] = pd.Series([""] * len(frame),
                                         index=frame.index, dtype=object)
        else:
            idx = [i for i, n in enumerate(names) if n in set(head.sources)]
            added[head.face] = row_aggregate(frame.iloc[:, idx], head.fold)
    extra = pd.DataFrame(added, index=frame.index)
    return pd.concat([frame, extra], axis=1)


def with_carried(frame, grand) -> tuple:
    """(`frame` with the columns a style carries for it, their names).

    A matrix works out each heading's folded value from the rows it was
    built from, which the table leaving Show Table no longer has — so the
    values ride on the style (``grand["faces"]``) rather than in the table,
    where a node downstream summing every number column would count them
    twice. The card and the printed page put them back, hidden, for a
    heading to `keep`."""
    faces = grand.get("faces") if isinstance(grand, dict) else None
    if not faces:
        return frame, []
    names = {str(c) for c in frame.columns}
    add = {str(k): v for k, v in faces.items()
           if str(k) not in names and hasattr(v, "__len__")
           and len(v) == len(frame)}
    if not add:
        return frame, []
    import pandas as pd
    extra = pd.DataFrame(add, index=frame.index)
    return pd.concat([frame, extra], axis=1), list(add)


# ---------------------------------------------------------------- arrange

@dataclass
class Span:
    """A heading as drawn: the displayed columns [start, end) it covers."""
    path: tuple
    start: int
    end: int
    folded: bool

    @property
    def level(self) -> int:
        return len(self.path) - 1

    @property
    def label(self) -> str:
        return str(self.path[-1])


@dataclass
class Arrangement:
    names: list                     # the columns shown, in order
    spans: list                     # Span, outer headings before inner
    depth: int = 0
    #: face column -> its heading, for the folded ones on show
    faces: dict = field(default_factory=dict)

    def span_at(self, column: int, level: int) -> Optional[Span]:
        for span in self.spans:
            if span.level == level and span.start <= column < span.end:
                return span
        return None


def arrange(tree: Tree, columns, toggled=()) -> Arrangement:
    """The columns shown, in order, with the headings over them — each
    heading's columns pulled together where its first one stood, and a
    folded heading reduced to its one face column."""
    cols = [str(c) for c in columns]
    if not tree:
        return Arrangement(cols, [], 0)
    member_of = tree.member_of
    out: list = []
    spans: list = []
    faces: dict = {}
    done: set = set()

    def emit(path):
        head = tree.headings.get(path)
        start = len(out)
        folded = tree.is_folded(path, toggled)
        if folded:
            out.append(head.face)
            faces[head.face] = path
        else:
            for c in head.columns:
                leaf = member_of[c]
                if len(leaf) > len(path):
                    sub = leaf[:len(path) + 1]
                    if sub not in done:
                        done.add(sub)
                        emit(sub)
                else:
                    out.append(c)
        spans.append(Span(path, start, len(out), folded))

    for c in cols:
        leaf = member_of.get(c)
        if leaf is None:
            out.append(c)
            continue
        top = leaf[:1]
        if top not in done:
            done.add(top)
            emit(top)
    spans.sort(key=lambda s: (s.level, s.start))
    # as deep as the headings on show — a folded 2024 hides its quarters,
    # and the rows they stood in go with them
    depth = max((s.level + 1 for s in spans), default=0)
    return Arrangement(out, spans, depth, faces)


def face_header(tree: Tree, arrangement: "Arrangement | None",
                column) -> Optional[str]:
    """What a folded heading's column is headed on screen and on paper, or
    None to use its name: a stub says nothing (the heading above names
    it), and a summary says how it was worked out — `Q1` over `sum` reads
    better than `Q1` over `Q1`. Its *name* stays the heading's, which is
    what a rule calls it by."""
    if arrangement is None:
        return None
    path = arrangement.faces.get(str(column))
    if path is None:
        return None
    head = tree.headings[path]
    if head.fold == STUB:
        return STUB_HEADER
    return head.fold if head.synthetic else None
