"""Table conditional formatting — the rule model and its evaluation.

Qt-free on purpose. The **Table Style** node turns its parameters (a
structured quick-rule plus a free-text rule box) into a list of :class:`Rule`
dicts and emits them on its ``style`` port; :class:`~flograph.ui.inspector.
pandas_model.PandasModel` and the cell delegate turn the evaluated
:class:`CellStyle` into ``QColor`` / ``QFont`` / a painted bar / an icon
glyph.

Nothing here imports pandas at module load — the evaluators take a Series /
DataFrame and import pandas locally, matching the node-script rule.

The text DSL, one rule per line (blank lines skipped, ``#`` starts a
comment — a whole line, or trailing after a rule)::

    revenue              scale green                # 2- or 3-colour gradient
    margin               scale red-yellow-green
    units                bar blue                   # in-cell data bar
    score   >= 90        => bg green, bold          # highlight a cell
    status  contains fail => bg red
    status  = closed     => row grey                # highlight the whole row
    health               icons traffic              # 3-tier icon set
    amount               format $,.0f               # per-column number format

A ``scale`` / ``bar`` / ``icons`` rule can take its deciding value **from
another column** with a trailing ``by`` (or ``from``) clause, and a
highlight can **test another column** with an ``if`` (or ``when``) clause —
the style still lands in the column(s) named on the left::

    product   scale green by revenue               # shade Product by revenue
    product   bar blue    by units
    product   icons traffic by score
    product   if revenue < 0 => bg red             # flag Product when revenue < 0
    product   if status = closed => row grey        # whole row, tested on status

A highlight can place **one icon** as well as a colour, which is how a flag
column gets a tick; and ``iconmap`` / ``colormap`` map a value to an icon or
a fill. Both maps may leave the **source column out** — write nothing before
the colon — and then each column reads its own value, which is the only
thing that means anything under a pattern::

    20*       = 1 => icon ✓ green                  # a tick in every year column
    20*       iconmap: 1=✓ green, 0=✗ red          # the same, as a lookup
    status    colormap: breach=red, watch=amber, ok=green
    product   colormap severity: high=red          # decided by another column

An icon belongs to a cell, so it cannot be combined with ``row``. A
``colormap`` ink is worked out from its fill unless a second colour is
given (``ok=green white``).

Any of ``scale`` / ``bar`` / ``icons`` / ``iconmap`` can draw its format
**instead of** the value — Power BI's "bar only" / "icon only" — with a
standalone ``only`` at either end of the argument. The value is still
there: it sorts, copies and exports as it always did, it is just not
displayed::

    sla       iconmap only status: breach=🔥, ok=✅   # the icon is the column
    units     bar blue only                          # a bar chart in a column
    revenue   scale green only by margin             # a plain heatmap block

A cell holds **as many decorations as the rules give it**, not one. Two
rules that both match both land, which is how a cell gets an "OT" mark
*and* a green tick — before, the second could only fail to replace the
first. Each one says where it goes: ``left`` (the default, and where the
single icon always went), ``right``, ``above``, ``below``, or ``in``,
which draws it where the value would have been and takes the value away.
``above`` and ``below`` take a line of their own and so make that row
taller — per cell, unlike ``wrap``, because only the rows a rule matches
pay for it::

    ready   = 1  => icon ✓ green right      # a tick after the value
    late    = 1  => icon ! amber above      # its own line, on that row only
    sla     iconmap right: breach=✗, ok=✓
    grade   icons traffic in                # the icon *is* the cell

``over``/``top`` and ``under``/``bottom`` are accepted for ``above`` and
``below``, and ``instead``/``inplace`` for ``in``.

A **pill** is a coloured lozenge. What it wraps is decided by whether
anything is written in it — with a label it is a mark of its own standing
beside the value, without one it wraps the value already there::

    status  = breach => pill red            # the value, in a red lozenge
    status  = breach => pill red "OT"       # an OT badge beside the value
    status  colormap pill: breach=red, ok=green    # a column of them
    grade   icons check pill                # the tier colour as the ground

``pill`` also re-reads the colour an ``iconmap`` gives: with no lozenge it
is the glyph's ink, with one it is the ground behind it, since the map has
only the one colour to spend. On paper a lozenge prints square-cornered —
Qt's rich text drops ``border-radius`` — so the colour survives and the
shape does not.

``autocolour`` needs nothing named at all: point it at a column and
every distinct value takes its own colour from a palette. That is the one
thing a ``colormap`` cannot do, because a map has to be written out, and a
column of statuses nobody has seen yet cannot be::

    status    autocolour                 # a lozenge each, from the default palette
    owner     autocolour vivid           # a named palette
    region    autocolour earth fill      # flood the cell instead
    product   autocolour cool text       # colour the text and nothing else
    product   autocolour by severity     # categories read from another column

The colours land in **sorted** order of the distinct values, not the order
they appear in. First-appearance order would repaint the whole column the
moment a row arrived at the top, and a colour that moves means less than a
colour nobody picked. More values than the palette has colours and it
wraps, so a column of hundreds is still drawn — just not usefully.

The default shape is a **pill**, because that is what a category wants: a
lozenge round each value rather than a flooded column of eight saturated
chart colours. ``fill`` and ``text`` ask for the other two.

The same list shapes the table as well as painting it. ``width`` / ``align``
/ ``label`` are properties of a *column*, read once rather than per cell,
and ``wrap`` is the one rule that names no columns — a row is as tall as
its tallest cell, so wrapping is a fact about the table::

    region    width 90
    region    align centre
    revenue   label "Revenue (£)"                 # the header only
    wrap                                          # rows grow to fit
    height    40                                  # every row 40px tall
    revenue   sort desc                           # the order it opens in

A row can be made taller for the rows a test picks, too — ``height`` is a
style word after ``=>``, on a cell rule or a ``row`` rule alike, because a
row is one height across the table either way::

    status = late => row #3a1e1e, height 40
    score >= 90   => height 48

A mark on a line of its own (``above`` / ``below``) or a ``tall`` spark
still gets its room, so a row is never cut shorter than what it carries;
a spark standing in a cell grows to fill the height it is given.

``sort`` is table-wide for the same reason: there is one row order, so it
takes one column and a later `sort` line replaces an earlier one rather
than being a tie-break. It decides the order the table is *first shown*
in — on the card, in a dashboard tile and on a printed report, which is
where it matters most, since a page has no header to click. Clicking a
header still wins from then on.

``tooltip`` (``tip`` for short) puts another column's value on a cell as
a hover note — a sentence about a number that would make the table worse
as a column of its own. Each row reads its own note and a blank one shows
nothing::

    revenue   tooltip note
    revenue   tooltip by note        # the `by` clause, for the habit

The note column keeps showing until a ``hide`` line says otherwise, which
is deliberate: a rule that quietly removed a column it never named is a
kindness that has to be undone by somebody who cannot see why it happened.

``spark`` (``sparkline``) draws a row's numbers as a chart the size of a
word. The numbers come **across the row**, from the columns after ``from``
— named, a pattern, or a ``first..last`` range in table order — and the
column on the left is where it is drawn::

    trend     spark from jan..dec                  # a column of its own
    trend     spark bars green from q1, q2, q3, q4
    region    spark area teal last high low from 2024-*   # beside the name
    trend     spark from jan..dec replace          # where the months were
    trend     spark winloss from m_* hide          # the months hidden

A column the table **does not have** becomes one — display only, holding
the row's latest number so it still sorts and copies — and the spark
stands in it on its own. A column the table *does* have keeps its value
and the spark sits beside it like an icon, ``left`` unless a place is
named (``right`` / ``above`` / ``below`` / ``in``). ``hide`` puts the
source columns out of view; ``replace`` does that and puts the new column
where they were.

Kinds: ``line`` (the default), ``area``, ``step``, ``bars``, ``winloss``
and ``dots``. Marks: ``first``, ``last``, ``high``, ``low``, ``ends`` and
``points``, each optionally followed by its colour. ``negative <colour>``
colours a bar below zero, ``ref mean`` / ``ref median`` / ``ref 100``
draws a dashed reference line, ``shared`` puts every row on one scale (each
row is scaled to itself otherwise, which shows its shape best), and
``smooth``, ``thick``, ``tall`` and a width such as ``90px`` shape the
drawing. A blank is a gap in the line, never a zero, and a row with fewer
than two numbers draws nothing. A pattern never reads the column the spark
is drawn in; a range reads everything between its two ends.

``hide`` and ``show`` are the two ways to say which columns the table
has, and they are not mirror images. ``hide`` subtracts — name the helper
columns a rule reads and the reader shouldn't see. ``show`` is the
keep-list, and it also fixes the **order**: the columns come out in the
order they were named, which is the only way to reorder a table without a
Select Columns node in front of it::

    hide sla                                      # keep a helper out of view
    show region, revenue, product                 # these three, in that order
    show 20*                                      # every year column, no others

Both are a *view*: the frame carries on out of the ``table`` port whole,
in its own order, because the card is a way of looking at a table rather
than a way of changing one. Naming both applies ``show`` first and then
subtracts ``hide`` from what is left. Every ``show`` adds to the keep-list
rather than replacing it, the same way every ``hide`` adds to the drop-list.

A column name is matched exactly, unless it contains a glob metacharacter
(``*``, ``?``, ``[``) — then it selects every matching column, so
``20* scale green`` heatmaps every year column and ``*_qty bar blue`` every
quantity column. (Case-sensitive; quote a pattern that contains a space.)

Later lines win where two rules touch the same cell; a ``row``-scope style
sits under a ``cell``-scope one.
"""
from __future__ import annotations

import dataclasses
import fnmatch
import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from . import images as _images
from . import sparkline as _spark
from .visual_style import PALETTES

# --------------------------------------------------------------- presets

# Solid dark-theme fills — chosen to read against the grid (#2a2c33) without
# a translucent-alpha composite the delegate would have to special-case.
_FILL_PRESETS = {
    "red": "#5c2b2b", "amber": "#5c4a24", "orange": "#5c4a24",
    "green": "#2e4d33", "blue": "#26415c", "grey": "#3a3d44",
    "gray": "#3a3d44", "purple": "#3f2e57",
}

# (low, mid, high); mid None ⇒ a 2-colour gradient.
_SCALE_PRESETS = {
    "green": ("#23252b", None, "#2e7d46"),
    "blue": ("#23252b", None, "#2f6f9f"),
    "red": ("#23252b", None, "#a4373a"),
    "white-red": ("#23252b", None, "#a4373a"),
    "red-green": ("#a4373a", None, "#2e7d46"),
    "red-yellow-green": ("#a4373a", "#b0902f", "#2e7d46"),
    "green-yellow-red": ("#2e7d46", "#b0902f", "#a4373a"),
    "diverging": ("#2f6f9f", "#3a3d44", "#a4373a"),
}

_BAR_PRESETS = {
    "blue": "#3b6299", "green": "#2e7d46", "orange": "#b9722e",
    "purple": "#7d5aa8", "red": "#a4373a", "grey": "#5b5f68",
}
_BAR_NEGATIVE = "#a4373a"

# (glyph, colour) low -> high. Plain Unicode, not emoji — a colour-emoji
# font is not a given, but ● ▲ ▼ ✓ ✗ are in every default sans.
_ICON_SETS = {
    "traffic": [("●", "#d9534f"), ("●", "#e0a83d"),
                ("●", "#5cb85c")],                        # ● ● ●
    "arrows": [("▼", "#d9534f"), ("▬", "#9aa0a6"),
               ("▲", "#5cb85c")],                         # ▼ ▬ ▲
    "check": [("✗", "#d9534f"), ("–", "#9aa0a6"),
              ("✓", "#5cb85c")],                          # ✗ – ✓
}
_ICON_LABELS = {
    "traffic lights": "traffic", "traffic": "traffic", "arrows": "arrows",
    "check / cross": "check", "check": "check", "cross": "check",
}

_MODES = {"color_scale", "data_bar", "highlight", "icons", "icon_map",
          "number_format", "column_width", "align", "header_label", "wrap",
          "sort", "color_map", "auto_color", "tooltip", "sparkline",
          "row_height", "image"}

#: The rules that shape the *table* rather than paint a cell. They are read
#: once into a `ColumnLayout` and never evaluated per row, so they cost
#: nothing on a big frame and are not what makes a style "active".
LAYOUT_MODES = {"column_width", "align", "header_label", "wrap", "sort",
                "row_height"}

_ALIGNMENTS = {"left": "left", "right": "right", "center": "center",
               "centre": "center", "middle": "center"}

#: How a sort direction may be spelled. "up"/"down" are here because that
#: is what people say about a *ranking* ("biggest at the top"), and getting
#: it wrong is invisible until you read the numbers.
_SORT_WORDS = {"asc": "asc", "ascending": "asc", "up": "asc", "a-z": "asc",
               "desc": "desc", "descending": "desc", "down": "desc",
               "z-a": "desc"}

#: Sanity bounds on a typed width, in pixels. Wide enough for a paragraph
#: of prose, narrow enough that a fat-fingered `width 5000` cannot push
#: every other column off the card.
MIN_RULE_WIDTH, MAX_RULE_WIDTH = 16, 1200

#: Sanity bounds on a typed row height, in pixels. Low enough for a
#: compact table of short numbers; high enough for a row that is mostly a
#: sparkline, and no more than a screenful.
MIN_ROW_HEIGHT, MAX_ROW_HEIGHT = 12, 600


def scale_token(low, mid, high) -> str:
    """The DSL name for a (low, mid, high) triple, or its raw ``low..high``
    when it matches no preset."""
    for name, triple in _SCALE_PRESETS.items():
        if triple == (low, mid, high):
            return name
    return "green"


def preset_name(colour, presets) -> str:
    for name, value in presets.items():
        if value == colour:
            return name
    return colour or ""


def bar_token(colour) -> str:
    return preset_name(colour, _BAR_PRESETS)


def fill_token(colour) -> str:
    return preset_name(colour, _FILL_PRESETS)
_OPS = {">", ">=", "<", "<=", "=", "!=", "between",
        "contains", "starts", "ends", "matches", "empty", "notempty"}


# --------------------------------------------------------------- shapes

@dataclass
class Rule:
    mode: str
    columns: list[str] = field(default_factory=list)
    scope: str = "cell"                       # cell | row
    # color_scale
    low: Optional[str] = None
    mid: Optional[str] = None
    high: Optional[str] = None
    low_value: Optional[float] = None
    high_value: Optional[float] = None
    # data_bar
    color: Optional[str] = None
    negative_color: Optional[str] = None
    origin: Optional[float] = None
    # highlight
    op: Optional[str] = None
    value: Any = None                         # scalar, or [a, b] for between
    bg: Optional[str] = None
    fg: Optional[str] = None
    bold: bool = False
    # icons
    icon_set: Optional[str] = None
    thresholds: Optional[list] = None
    reverse: bool = False
    # icon_map, and any rule that reads a different column than the one it
    # draws in: `scale`/`bar`/`icons` with a `by <col>` clause, and a
    # `highlight` with an `if <col> …` clause (the tested column).
    source: Optional[str] = None              # column whose value decides it
    mapping: Optional[dict] = None            # exact value -> [glyph, colour]
    # number_format
    number_spec: Optional[str] = None
    #: draw the format *instead of* the value — Power BI's "icon only" /
    #: "bar only". The cell keeps its value for copy, export and sort; only
    #: the display of it goes.
    hide_value: bool = False
    # layout (column_width / align / header_label)
    width: Optional[int] = None               # pixels; None = fit to content
    align: Optional[str] = None               # left | right | center
    label: Optional[str] = None               # header text shown instead
    #: highlight: a literal icon to place in the cell the test passed in.
    #: Distinct from `icons` (a graded set) and `icon_map` (a lookup) —
    #: this is one glyph, chosen by a condition.
    glyph: Optional[str] = None
    glyph_color: Optional[str] = None
    #: sort: "asc" | "desc". A string rather than an `ascending` bool
    #: because `to_dict` drops False as absence — a descending sort would
    #: have crossed the style port and come back ascending.
    direction: Optional[str] = None
    #: Where this rule's decoration sits — one of :data:`DECOR_PLACES`.
    #: None means "left", which is the only place there was before.
    glyph_where: Optional[str] = None
    #: Draw this rule's colour as a **lozenge** rather than as a fill behind
    #: the whole cell. What it wraps is decided by whether the rule also
    #: names something to write in it: with a glyph it is a pill of its own
    #: (`pill green "OT"`), without one it wraps the cell's own value
    #: (`pill green`). Safe as a bool where `direction` was not, because
    #: here False *is* absence, which is exactly what `to_dict` drops.
    as_pill: bool = False
    #: auto_color: which palette to spend, by name from
    #: :data:`flograph.core.visual_style.PALETTES`. None = the default one.
    palette: Optional[str] = None
    #: auto_color: colour the *text* rather than the ground behind it.
    #: A bool for the same reason `as_pill` is one — False is absence.
    ink_only: bool = False
    #: Columns measured *together* for a scale, bar or icon set, instead of
    #: the one column being drawn. Never typed: a matrix (core/matrix.py)
    #: sets it so a heatmap reads across every cell a value built, the way
    #: a matrix is read, rather than month by month.
    pool: list = field(default_factory=list)
    #: sparkline: the columns whose numbers make the line, as typed —
    #: names, patterns and ``first..last`` ranges. `spark_projection`
    #: resolves them against the table before anything is drawn.
    series: list = field(default_factory=list)
    #: sparkline: one of `sparkline.KINDS`' values. `color` is its colour
    #: and `negative_color` a bar's below zero, shared with `data_bar`.
    spark_kind: Optional[str] = None
    #: sparkline: [[mark, colour | None], …] — first/last/high/low/points
    marks: list = field(default_factory=list)
    #: sparkline: a reference line — a number, "mean" or "median"
    ref: Any = None
    #: sparkline: one scale down the whole column instead of one per row
    shared: bool = False
    tall: bool = False
    smooth: bool = False
    thick: bool = False
    spark_width: Optional[int] = None
    #: sparkline: what becomes of the columns it reads — None (left alone),
    #: "hide", or "replace" (hidden, with the new column where they were)
    take_sources: Optional[str] = None
    #: row_height: how tall every row is. highlight: how tall the rows it
    #: matches are — `status = late => height 40`. Pixels on the card.
    row_height: Optional[int] = None
    #: image, and an `icon` / `iconmap` whose mark is a pasted picture: how
    #: tall the picture is drawn, in pixels on the card. None = as tall as
    #: the line it sits on — which a `height` makes taller.
    picture_size: Optional[int] = None
    #: …and the shape it is cut to — "square", "rounded" or "circle" — and
    #: the colour of the tile behind it. A picture with a plain ground reads
    #: as an icon on a tile; a photo cut to a circle, as an avatar.
    picture_shape: Optional[str] = None
    picture_tile: Optional[str] = None

    def to_dict(self) -> dict:
        out = {}
        for f in dataclasses.fields(self):
            v = getattr(self, f.name)
            # keep 0 / 0.0 (a real threshold or origin); drop only genuine
            # absence — None, False, an empty list
            if v is None or v is False or (isinstance(v, list) and not v):
                continue
            out[f.name] = v
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


#: Where a decoration sits relative to the cell's value. ``left`` and
#: ``right`` cost nothing — the row is as tall as it was. ``above`` and
#: ``below`` give the decoration a line of its own, so the row grows; and
#: because a rule fires on the rows that match it and not the rest, the row
#: that grows is the row that asked. That is the one place this differs
#: from ``wrap``, which is table-wide precisely because it would otherwise
#: spend every row's height on one cell's second line.
#:
#: ``in`` is the fifth: *instead of* the value, in the place the value
#: would have been. One cell can carry all five at once — a mark above, a
#: tick on the right, a pill where the number was — because a cell holds a
#: list and every entry names its own place. ``in`` is the only one that
#: takes the value away, and it is the same thing the older ``only`` says
#: about a bar or a scale, which is why both end up setting `hide_value`.
DECOR_PLACES = ("left", "right", "above", "below", "in")

#: The places that stack vertically, and so decide a row's height.
DECOR_LINES = ("above", "below")

#: How much of a pill's fill survives on the card. A lozenge is a solid
#: shape behind a few characters, so unlike a cell fill it can afford its
#: colour outright.
_PILL_INK = "#ffffff"


@dataclass
class Decoration:
    """One thing drawn in a cell beside — or instead of — its value.

    A cell used to hold exactly one ``icon`` / ``icon_color`` pair, and
    :meth:`CellStyle.over` merged two rules with ``icon=self.icon or
    base.icon``. That is why a second icon rule could never *add* one: it
    could only fail to replace what was already there, and no amount of
    delegate work gets round a model that has one slot. This is that slot
    made a list.

    ``text`` is whatever the rule typed — usually a glyph, but a pill with
    a label in it is the same shape and gets the same field. ``pill`` is
    the fill of the lozenge drawn behind it, or None for a bare glyph.
    """
    text: str = ""
    color: Optional[str] = None               # ink
    pill: Optional[str] = None                # lozenge fill; None = bare
    where: str = "left"
    #: A sparkline drawn in the decoration's place instead of text. It is a
    #: decoration rather than a field of its own because it *is* one: it
    #: sits left, right, above, below or in place of the value exactly as
    #: an icon does, and a cell may carry it beside a tick.
    spark: Optional["_spark.Spark"] = None
    #: A picture drawn in the decoration's place instead of text — an image
    #: `data:` address, pasted into a rule or read from a column. `size` is
    #: its height in card pixels; None fits it to the line it sits on.
    image: Optional[str] = None
    size: Optional[int] = None
    #: The colour of a tile behind the picture, and the shape both are cut
    #: to: "square", "rounded" or "circle". None and None draw it as it is.
    tile: Optional[str] = None
    shape: Optional[str] = None

    def to_dict(self) -> dict:
        out = {"text": self.text}
        if self.color:
            out["color"] = self.color
        if self.pill:
            out["pill"] = self.pill
        if self.where != "left":
            out["where"] = self.where
        if self.spark is not None:
            out["spark"] = self.spark.to_dict()
        if self.image:
            out["image"] = self.image
        if self.size:
            out["size"] = self.size
        if self.tile:
            out["tile"] = self.tile
        if self.shape:
            out["shape"] = self.shape
        return out

    @classmethod
    def from_dict(cls, d: Any) -> "Decoration":
        if isinstance(d, (list, tuple)):        # the old (glyph, colour) pair
            glyph = d[0] if d else ""
            return cls(text=str(glyph or ""),
                       color=d[1] if len(d) > 1 else None)
        d = d or {}
        spark = d.get("spark")
        return cls(text=str(d.get("text") or ""), color=d.get("color"),
                   pill=d.get("pill"),
                   where=d.get("where") or "left",
                   spark=(_spark.Spark.from_dict(spark)
                          if isinstance(spark, dict) else None),
                   image=d.get("image") or None,
                   size=d.get("size") or None,
                   tile=d.get("tile") or None,
                   shape=d.get("shape") or None)


@dataclass
class CellStyle:
    bg: Optional[str] = None
    fg: Optional[str] = None
    bold: bool = False
    bar: Optional[float] = None               # signed, -1..1
    bar_color: Optional[str] = None
    bar_mode: str = "left"                    # left | center (column has < 0)
    #: Every glyph, label and pill this cell draws, in the order the rules
    #: that asked for them were read. Position within the cell is each
    #: decoration's own `where`.
    decorations: list = field(default_factory=list)
    #: A lozenge drawn around the cell's *own* value — `status pill`, as
    #: against `status pill "OT"`, which is a decoration of its own.
    pill: Optional[str] = None
    pill_fg: Optional[str] = None
    text: Optional[str] = None                # DisplayRole override
    hide_value: bool = False                  # show the format, not the value
    #: What this cell says when you rest on it — a `tooltip` rule's note,
    #: read from another column. Not drawn, so it costs the cell nothing
    #: until somebody points at it.
    tooltip: Optional[str] = None
    #: How tall this cell's row should be, from a highlight's `height`. A
    #: row is as tall as the tallest any of its cells asks for.
    row_height: Optional[int] = None

    def over(self, base: Optional["CellStyle"]) -> "CellStyle":
        """`self` laid on top of `base` — self's set fields win."""
        if base is None:
            return self
        return CellStyle(
            bg=self.bg or base.bg,
            fg=self.fg or base.fg,
            bold=self.bold or base.bold,
            bar=base.bar if self.bar is None else self.bar,
            bar_color=self.bar_color or base.bar_color,
            bar_mode=self.bar_mode if self.bar is not None else base.bar_mode,
            # decorations *add*. Every other field here is last-one-wins,
            # because there is one background and one weight; there is no
            # such limit on how many things a cell can show, and the ask
            # this list exists for — an OT mark and then a green tick — is
            # exactly two rules both firing. Base first, so the earlier
            # rule keeps the position it had and the later one arrives
            # beside it in reading order.
            decorations=list(base.decorations) + list(self.decorations),
            pill=self.pill or base.pill,
            pill_fg=self.pill_fg or base.pill_fg,
            text=self.text or base.text,
            hide_value=self.hide_value or base.hide_value,
            # last one wins, like every other single-valued field: there is
            # one tooltip, and two rules naming a note column is a
            # replacement rather than something to concatenate
            tooltip=self.tooltip or base.tooltip,
            row_height=self.row_height or base.row_height,
        )

    def at(self, where: str) -> list:
        """The decorations sitting at one of :data:`DECOR_PLACES`."""
        return [d for d in self.decorations if d.where == where]

    @property
    def icon(self) -> Optional[str]:
        """The first decoration's glyph, or None.

        Read-only, and a view rather than a second home for the data:
        `decorations` is the truth. It stays because "is there a mark in
        this cell, and what is it" is a real question with a single
        answer — it is what a column sizing itself asks, and it is the
        whole of what a cell could hold before this was a list.
        """
        return self.decorations[0].text if self.decorations else None

    @property
    def icon_color(self) -> Optional[str]:
        return self.decorations[0].color if self.decorations else None

    def is_empty(self) -> bool:
        return (self.bg is None and self.fg is None and not self.bold
                and self.bar is None and not self.decorations
                and self.pill is None and self.tooltip is None
                and self.text is None and not self.hide_value
                and self.row_height is None)


@dataclass
class ColumnLayout:
    """How one column is *shaped*, as opposed to painted.

    Every field is None for "leave it alone", which is what an untouched
    column gets — so a table with no layout rules behaves exactly as it did
    before there were any.
    """
    width: Optional[int] = None       # pixels; None = fit to the content
    align: Optional[str] = None       # left | right | center
    label: Optional[str] = None       # header text shown instead of the name

    def is_empty(self) -> bool:
        return self.width is None and self.align is None and self.label is None


@dataclass
class ColumnStats:
    min: Optional[float] = None
    max: Optional[float] = None
    mean: Optional[float] = None
    tertiles: Optional[tuple] = None          # (t1, t2)


# --------------------------------------------------------------- colour maths

def _hex_rgb(value: str) -> Optional[tuple]:
    s = str(value or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def _rgb_hex(rgb: tuple) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def _lerp(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def readable_fg(bg_hex: str) -> str:
    """A legible text colour for a given cell background."""
    rgb = _hex_rgb(bg_hex)
    if rgb is None:
        return "#e5e7eb"
    r, g, b = (c / 255 for c in rgb)
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#1b1c20" if luminance > 0.55 else "#e5e7eb"


#: The grid a table cell is painted on.
CARD_GROUND = "#2a2c33"

#: The contrast an automatically-chosen ink has to reach against it —
#: WCAG AA for body text, which is what a table cell is.
INK_CONTRAST = 4.5


def _relative_luminance(rgb: tuple) -> float:
    """WCAG relative luminance — gamma-corrected, unlike the quick
    weighted average :func:`readable_fg` uses to pick between two fixed
    inks. Choosing *between* two colours tolerates a rough number;
    deciding whether one is readable at all does not."""
    def channel(c: float) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    """The WCAG contrast between two colours, 1.0 (identical) to 21.0."""
    ra, rb = _hex_rgb(a), _hex_rgb(b)
    if ra is None or rb is None:
        return 21.0
    hi, lo = sorted((_relative_luminance(ra), _relative_luminance(rb)),
                    reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def on_dark(colour: str, ground: str = CARD_GROUND,
            target: float = INK_CONTRAST) -> str:
    """`colour` made legible as *ink on the card*. The mirror of
    :func:`on_white`, which darkens ink that would vanish on paper.

    Only used where the colour was chosen **for** somebody rather than by
    them. A `fg red` rule gets red, because that is what it asked for; an
    ``autocolour … text`` rule is spending a *chart* palette, and those
    colours are built to be grounds with text laid on top. Several are
    darker than the grid they would then have to be read against —
    ``#1e293b`` on ``#2a2c33`` is 1.05:1, which is not dim, it is
    invisible.

    Lifted toward white in small steps and stopped at the **first** one
    that clears `target`, so a colour keeps as much of itself as it can
    afford. A colour already clear enough is returned untouched, which is
    most of the brighter half of every palette.
    """
    rgb = _hex_rgb(colour)
    if rgb is None or _hex_rgb(ground) is None:
        return colour
    if contrast_ratio(colour, ground) >= target:
        return colour
    for step in range(1, _INK_LIFT_STEPS + 1):
        lifted = _rgb_hex(_lerp(rgb, (255, 255, 255),
                                step / _INK_LIFT_STEPS))
        if contrast_ratio(lifted, ground) >= target:
            return lifted
    return "#e5e7eb"


#: How finely the lift is searched. Twenty is 5% a step — fine enough that
#: nothing is lightened much past what it needed.
_INK_LIFT_STEPS = 20


# ------------------------------------------------------------------ paper

# The presets above are built for the card: solid fills that read against a
# dark grid (#2a2c33). A report page is white, so printed unchanged they
# would put a near-black block where the card shows "low", and light
# auto-text on a white ground where it shows a highlight. These turn a card
# style into the same style *for paper* — the meaning kept (the gradient
# still runs the same way, the highlight is still that colour), the ground
# swapped underneath it.

#: How much of the card's colour survives against white. Low enough that a
#: whole heatmapped column stays readable text on tinted paper rather than
#: a wall of ink; high enough that the gradient is still legible.
PAPER_TINT = 0.24

#: A bar is one solid shape rather than a ground for text, so it keeps more
#: of its colour than a fill does.
PAPER_BAR_TINT = 0.55

#: The two values readable_fg produces. A style carrying one of these has an
#: *automatic* text colour — chosen for the card's ground, so on paper it has
#: to be chosen again. Anything else was asked for by name and is kept, only
#: darkened if it would be invisible on white.
_AUTO_FG = {"#1b1c20", "#e5e7eb"}


def paper_tint(colour: str, amount: float = PAPER_TINT) -> str:
    """`colour` mixed into white — the same hue, on a page."""
    rgb = _hex_rgb(colour)
    if rgb is None:
        return colour
    return _rgb_hex(_lerp((255, 255, 255), rgb, amount))


def on_white(colour: str) -> str:
    """`colour` made legible as *ink*: darkened if it would disappear."""
    rgb = _hex_rgb(colour)
    if rgb is None:
        return colour
    r, g, b = (c / 255 for c in rgb)
    if 0.2126 * r + 0.7152 * g + 0.0722 * b <= 0.55:
        return colour
    return _rgb_hex(_lerp(rgb, (0, 0, 0), 0.45))


def for_paper(style: Optional["CellStyle"]) -> Optional["CellStyle"]:
    """A cell's card style as it should print on a white page."""
    if style is None:
        return None
    bg = paper_tint(style.bg) if style.bg else None
    fg = style.fg
    if fg is None or fg.lower() in _AUTO_FG:
        fg = readable_fg(bg) if bg else None
    else:
        fg = on_white(fg)
    pill = paper_tint(style.pill, PAPER_BAR_TINT) if style.pill else None
    return dataclasses.replace(
        style, bg=bg, fg=fg,
        bar_color=(paper_tint(style.bar_color, PAPER_BAR_TINT)
                   if style.bar_color else None),
        decorations=[_decor_for_paper(d) for d in style.decorations],
        pill=pill,
        pill_fg=_pill_ink_for_paper(style.pill_fg, pill))


def _pill_ink_for_paper(ink: Optional[str], tinted: Optional[str]) -> Optional[str]:
    """A lozenge's ink, re-chosen for the tint it now sits on.

    On the card a pill is a solid colour carrying white text. Tinted for
    paper it is pale, and that white would vanish — so an ink that was
    *chosen* (white, or either of `readable_fg`'s two) is chosen again,
    while one asked for by name is only darkened if it would disappear.
    """
    if tinted is None:
        return on_white(ink) if ink else None
    if ink is None or ink.lower() in _AUTO_FG or ink.lower() == _PILL_INK:
        return readable_fg(tinted)
    return on_white(ink)


def _decor_for_paper(d: "Decoration") -> "Decoration":
    pill = paper_tint(d.pill, PAPER_BAR_TINT) if d.pill else None
    return dataclasses.replace(
        d, pill=pill, color=_pill_ink_for_paper(d.color, pill),
        spark=_spark_for_paper(d.spark) if d.spark is not None else None)


def _spark_for_paper(spark: "_spark.Spark") -> "_spark.Spark":
    """A spark's colours made legible as ink on white.

    A line is ink, not a ground, so it is darkened where it would vanish
    (amber, yellow, white) rather than tinted the way a fill is. The
    defaults are resolved first — a colour nobody named still has to
    survive the page.
    """
    line = on_white(spark.color or _spark.DEFAULT_COLOR)
    marks = []
    for entry in spark.marks:
        name = entry[0]
        chosen = entry[1] if len(entry) > 1 else None
        marks.append([name, on_white(chosen or _spark.MARK_COLORS.get(name)
                                     or line)])
    return dataclasses.replace(
        spark, color=line, marks=marks,
        negative_color=on_white(spark.negative_color
                                or _spark.NEGATIVE_COLOR))


def _scale_color(frac: float, low: str, mid: Optional[str], high: str) -> Optional[str]:
    lo, hi = _hex_rgb(low), _hex_rgb(high)
    if lo is None or hi is None:
        return None
    frac = 0.0 if frac < 0 else 1.0 if frac > 1 else frac
    md = _hex_rgb(mid) if mid else None
    if md is None:
        return _rgb_hex(_lerp(lo, hi, frac))
    if frac <= 0.5:
        return _rgb_hex(_lerp(lo, md, frac / 0.5))
    return _rgb_hex(_lerp(md, hi, (frac - 0.5) / 0.5))


# --------------------------------------------------------------- parsing

def _coerce(text: str) -> Any:
    t = str(text).strip()
    low = t.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        return t


def _unquote(name: str) -> str:
    name = str(name).strip()
    if len(name) >= 2 and name[0] == name[-1] and name[0] in "\"'":
        return name[1:-1]
    return name


#: A whitespace split that keeps a "quoted phrase" in one piece — what a
#: `pill` argument needs, where the label is quoted precisely so it cannot
#: be mistaken for a colour.
_TOKEN_RE = re.compile(r'"[^"]*"|\'[^\']*\'|\S+')


def _quoted_tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(str(text).strip())


def _split_top_commas(text: str) -> list[str]:
    """Split on commas that are not inside "quotes"; the quote chars are
    dropped."""
    parts: list[str] = []
    buf: list[str] = []
    quote = None
    for ch in str(text):
        if quote:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
        elif ch in "\"'":
            quote = ch
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _column_list(value: Any) -> list[str]:
    """A comma-separated column list, honouring "quotes" so a name may
    itself contain a comma or read like a keyword."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [_unquote(v) for v in value if str(v).strip()]
    return _split_top_commas(str(value))


def _is_glob(pattern: str) -> bool:
    return any(ch in str(pattern) for ch in "*?[")


def column_matches(patterns, name) -> bool:
    """True if `name` is selected by `patterns` — a plain entry matches by
    exact name, an entry with ``*`` / ``?`` / ``[`` is a case-sensitive
    glob. An empty `patterns` matches nothing (callers treat that as
    "every column" themselves)."""
    name = str(name)
    for p in patterns or ():
        p = str(p)
        if p == name or (_is_glob(p) and fnmatch.fnmatchcase(name, p)):
            return True
    return False


def expand_columns(patterns, columns) -> list[str]:
    """The concrete column names `patterns` selects, de-duplicated.

    In **pattern** order, not frame order — each pattern contributes in
    turn, and a glob contributes the names it matches in frame order. A
    subtractive caller (`hide`) does not care; `show` is ordered by what it
    returns, so this is load-bearing there.

    A plain name is kept even when absent, so a caller can still flag it
    missing."""
    cols = [str(c) for c in columns]
    out: list[str] = []
    for p in patterns or ():
        p = str(p)
        if _is_glob(p):
            out.extend(c for c in cols if fnmatch.fnmatchcase(c, p))
        else:
            out.append(p)
    return _dedup(out)


def visible_columns(columns, shown=(), hidden=()) -> list[str]:
    """The columns a table shows, in the order it shows them.

    `shown` is the keep-list — name what you want and everything else goes,
    in the order you named it. Empty (the usual case) means every column in
    the frame's own order. `hidden` then subtracts from whatever is left,
    so naming a column in both is not a contradiction to resolve: it was
    kept, then dropped.

    A name in `shown` that the table does not have is dropped rather than
    left as a hole — `style_report` is what tells the reader it was named.

    One function, called by both the card and the printed page, because
    two implementations of the same projection is exactly how a report
    starts quietly differing from the dashboard it came off.
    """
    cols = [str(c) for c in columns]
    if shown:
        known = set(cols)
        keep = [c for c in expand_columns(shown, cols) if c in known]
    else:
        keep = list(cols)
    if hidden:
        keep = [c for c in keep if not column_matches(list(hidden), c)]
    return keep


def quote_column(name: str) -> str:
    """Wrap a column name in quotes for the DSL when it would otherwise be
    ambiguous — a space, a comma, or a bare keyword."""
    name = str(name)
    if (any(ch in name for ch in ', "\'')
            or name.lower() in _KEYWORDS
            or name.lower() in _LEADING_KEYWORDS
            or name.lower() in _HEIGHT_WORDS):
        return '"' + name.replace('"', "") + '"'
    return name


def parse_op_value(text: str) -> tuple:
    """`"> 90"` / `"contains fail"` / `"between 10 20"` → (op, value).

    Value is ``None`` for empty/notempty, a 2-list for between, else a
    coerced scalar. Raises ``ValueError`` on an unrecognised expression.
    """
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty condition")
    low = raw.lower()
    if low in ("is empty", "empty"):
        return ("empty", None)
    if low in ("is not empty", "not empty", "notempty"):
        return ("notempty", None)
    for token, canon in (("contains", "contains"), ("starts with", "starts"),
                         ("ends with", "ends"), ("starts", "starts"),
                         ("ends", "ends"), ("matches", "matches"),
                         ("between", "between")):
        if low.startswith(token + " "):
            rest = raw[len(token):].strip()
            if canon == "between":
                parts = rest.replace("..", " ").split()
                if len(parts) != 2:
                    raise ValueError(f"'between' needs two values, got {rest!r}")
                return ("between", [_coerce(parts[0]), _coerce(parts[1])])
            return (canon, rest)
    for op in ("!=", ">=", "<=", "=", ">", "<"):
        if raw.startswith(op):
            return (op, _coerce(raw[len(op):]))
    # a bare value means equals
    return ("=", _coerce(raw))


#: How "auto colour" may be spelled. Both spellings of the colour, and
#: the hyphen, because all four get typed and `str.split()` keeps a hyphen
#: inside the one token. Not a bare ``auto`` — the rightmost-keyword scan
#: would then read ``region width auto`` as a rule about a column called
#: "region width".
_AUTO_KEYWORDS = ("autocolour", "autocolor", "auto-colour", "auto-color")

#: The shapes an auto colour can take, and the words for them. The default
#: is a pill: a category wants a lozenge round its value, not a column
#: flooded with one of eight saturated chart colours.
_AUTO_SHAPES = {"pill": "pill", "pills": "pill", "fill": "fill",
                "block": "fill", "text": "text", "ink": "text"}

#: The two that lead a line rather than following a column list. They are
#: taken before the right-to-left keyword scan and never join `_KEYWORDS`,
#: which is what keeps them from colliding with a word some other rule
#: takes as an argument — and is why a column actually called "show" has to
#: be quoted, exactly as one called "hide" always has.
_LEADING_KEYWORDS = ("hide", "show")

#: `tip` is the short spelling of `tooltip`. It is also a perfectly
#: ordinary column name (seaborn's own tips dataset has one), which is
#: what `quote_column` is for — it already quotes anything that reads as
#: a keyword, so the cost falls on that one table and is handled.
_TIP_KEYWORDS = ("tooltip", "tip")

#: `spark` is what people say; `sparkline` is what Excel calls it.
_SPARK_KEYWORDS = ("spark", "sparkline")

#: How a row height is spelled — on a line of its own for every row, or
#: after `=>` for the rows a test picks. Not in `_KEYWORDS`: it never follows
#: a column list, so the right-to-left scan has no business finding it.
_HEIGHT_WORDS = ("height", "row-height", "rowheight")


def _row_height(lineno: int, token: Any) -> int:
    """`"40"` / `"40px"` as a row height in pixels, or a ValueError."""
    text = str(token or "").strip().lower().removesuffix("px")
    value = _spark.number(text)
    if value is None:
        raise ValueError(f"line {lineno}: 'height' wants a number of pixels, "
                         f"got {token!r}")
    height = int(round(value))
    if not MIN_ROW_HEIGHT <= height <= MAX_ROW_HEIGHT:
        raise ValueError(f"line {lineno}: a row {height}px tall is outside "
                         f"{MIN_ROW_HEIGHT}–{MAX_ROW_HEIGHT} pixels")
    return height


#: A column of pictures — `logo image`, or `name image from logo`.
_PICTURE_KEYWORDS = ("image", "picture")

#: How tall a picture may be drawn, in pixels on the card.
MIN_PICTURE_SIZE, MAX_PICTURE_SIZE = 8, 400

_PICTURE_HELP = ("left|right|above|below|in · a height like 32px · "
                 "square|rounded|circle · on <colour> · only · "
                 "from <column> · hide")

#: The shape a picture is cut to, and the words for each.
_SHAPE_WORDS = {"square": "square", "squared": "square",
                "rounded": "rounded", "round": "rounded",
                "circle": "circle", "circular": "circle", "circled": "circle"}


def _tile_colour(token: "str | None") -> "str | None":
    """`token` as the colour of the tile behind a picture — a vivid preset,
    white, black or a hex — or None."""
    if not token:
        return None
    low = token.lower()
    if low in ("white", "black"):
        return "#ffffff" if low == "white" else "#000000"
    if low in _GLYPH_COLOURS:
        return _GLYPH_COLOURS[low]
    if re.fullmatch(r"#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?", token):
        return token
    return None


def _picture_size(lineno: int, token: Any) -> int:
    """`"32px"` as a picture's height in pixels, or a ValueError."""
    value = _spark.number(str(token or "").strip().lower().removesuffix("px"))
    if value is None:
        raise ValueError(f"line {lineno}: a picture's size is a height in "
                         f"pixels — '32px', got {token!r}")
    size = int(round(value))
    if not MIN_PICTURE_SIZE <= size <= MAX_PICTURE_SIZE:
        raise ValueError(f"line {lineno}: a picture {size}px tall is outside "
                         f"{MIN_PICTURE_SIZE}–{MAX_PICTURE_SIZE} pixels")
    return size


def _split_size(lineno: int, arg: str) -> tuple:
    """Pull a `32px` off either end of a keyword argument — how tall the
    pictures an `iconmap` pastes are drawn."""
    text = arg.strip()
    lead = re.match(r"(\d+px)(?=[\s:]|$)", text, re.IGNORECASE)
    if lead:
        rest = text[lead.end():]
        # the colon opening a map with no source belongs to the body
        return (rest if rest.startswith(":") else rest.strip(),
                _picture_size(lineno, lead.group(1)))
    trail = re.search(r"\s(\d+px)$", text, re.IGNORECASE)
    if trail:
        return text[:trail.start()].strip(), _picture_size(lineno,
                                                           trail.group(1))
    return text, None


def _parse_picture(lineno: int, columns: list, arg: str) -> Rule:
    """`"right 32px from logo hide"` → an image rule.

    With no `from`, the column's *own* values are the pictures and each one
    stands in place of the text it was written as — a wall of base64 is not
    a value anyone wants to read. With one, the picture comes from that
    column and sits beside the value like an icon, `left` unless a place is
    named; `hide` puts the picture column away.
    """
    if not columns:
        raise ValueError(
            f"line {lineno}: 'image' needs a column to draw in — "
            f"'logo image', or 'name image from logo'")
    spans = list(_TOKEN_RE.finditer(arg))
    cut = next((k for k, m in enumerate(spans)
                if m.group().lower() in ("from", "by")), None)
    options = [m.group() for m in (spans if cut is None else spans[:cut])]
    source = fate = None
    if cut is not None:
        tail = arg[spans[cut].end():].strip()
        # The picture column comes after `from`, and people carry on
        # writing after it — `from logo hide circle`. Words this rule knows
        # come back off the end while a column name is left in front of
        # them; a name that really ends in one is quoted.
        trailing: list = []
        while True:
            words = list(_TOKEN_RE.finditer(tail))
            if len(words) < 2:
                break
            last = words[-1].group()
            if (len(words) > 2 and words[-2].group().lower()
                    in ("on", "bg", "tile") and _tile_colour(last)):
                trailing[:0] = [words[-2].group(), last]
                tail = tail[:words[-2].start()].rstrip()
            elif (last.lower() in _PLACE_WORDS or last.lower() in _SHAPE_WORDS
                    or last.lower() in ("hide", "keep", "only")
                    or re.fullmatch(r"\d+px", last.lower())):
                trailing[:0] = [last]
                tail = tail[:words[-1].start()].rstrip()
            else:
                break
        for word in trailing:
            if word.lower() == "keep":
                continue
            options.append(word)
        source = _unquote(tail) or None
        if source is None:
            raise ValueError(
                f"line {lineno}: 'image … from' needs the column holding "
                f"the pictures — 'name image from logo'")
    place = size = shape = tile = None
    only = False
    i = 0
    while i < len(options):
        token = options[i]
        low = token.lower()
        if low in _PLACE_WORDS:
            place = _PLACE_WORDS[low]
        elif re.fullmatch(r"\d+px", low):
            size = _picture_size(lineno, token)
        elif low in _SHAPE_WORDS:
            shape = _SHAPE_WORDS[low]
        elif low in ("on", "bg", "tile"):
            following = options[i + 1] if i + 1 < len(options) else None
            tile = _tile_colour(following)
            if tile is None:
                raise ValueError(
                    f"line {lineno}: '{low}' needs a colour for the tile "
                    f"behind the picture — 'on white', 'on #1e1e1e'")
            i += 1
        elif low == "only":
            only = True
        elif low == "hide":
            fate = "hide"
        else:
            raise ValueError(f"line {lineno}: don't understand {token!r} in "
                             f"an image rule ({_PICTURE_HELP})")
        i += 1
    if fate and not source:
        raise ValueError(
            f"line {lineno}: 'hide' puts away the column the pictures come "
            f"from, so name it — 'name image from logo hide'")
    return Rule("image", columns, source=source, glyph_where=place,
                picture_size=size, hide_value=only, take_sources=fate,
                picture_shape=shape, picture_tile=tile)


_KEYWORDS = ("scale", "bar", "icons", "icon", "iconmap", "colormap",
             "colourmap", "format", "width", "align", "label", "sort"
             ) + (_AUTO_KEYWORDS + _TIP_KEYWORDS + _SPARK_KEYWORDS
                  + _PICTURE_KEYWORDS)

#: The keywords whose argument is a `source: value=…` map. They are the
#: only ones that may be written with the colon stuck to them — `iconmap:`
#: with no source is how a rule says "read the column you are drawing in".
_MAP_KEYWORDS = ("iconmap", "colormap", "colourmap")


def _keyword_of(token: str) -> "str | None":
    """The rule keyword `token` is, or None.

    A map keyword is allowed to carry the colon that opens its body,
    because leaving the source out is a real spelling and `"iconmap:"` is
    one token to `str.split()`.
    """
    low = token.lower()
    if low in _TIP_KEYWORDS:
        return "tooltip"                  # `tip` is the short spelling
    if low in _KEYWORDS:
        return low
    if low.endswith(":") and low[:-1] in _MAP_KEYWORDS:
        return low[:-1]
    return None


def _split_by_clause(arg: str) -> tuple:
    """Pull a trailing ``by <column>`` / ``from <column>`` off a keyword
    argument. Returns ``(remaining arg, source column | None)``.

    ``x scale green by revenue`` → ``("green", "revenue")``;
    ``x icons by score`` (no preset) → ``("", "score")``.
    """
    low = arg.lower()
    for sep in (" by ", " from "):
        idx = low.rfind(sep)
        if idx != -1:
            return arg[:idx].strip(), (_unquote(arg[idx + len(sep):].strip())
                                       or None)
    for sep in ("by ", "from "):
        if low.startswith(sep):
            return "", (_unquote(arg[len(sep):].strip()) or None)
    return arg, None


#: The words that name a place in a cell, and what each one means. The
#: synonyms are here because this is typed by hand in a text box and
#: "over"/"under" are what people reach for as often as "above"/"below".
#: ``centre`` is deliberately *not* one of them — it already means
#: something else on an `align` line, and a word that means two things in
#: one DSL is worse than a word that means nothing.
_PLACE_WORDS = {
    "left": "left", "right": "right",
    "above": "above", "over": "above", "top": "above",
    "below": "below", "under": "below", "bottom": "below",
    "in": "in", "inplace": "in", "instead": "in",
}


def _split_flag(arg: str, words: dict) -> tuple:
    """Pull a standalone modifier off either end of a keyword argument.

    Returns the argument without it, and what it meant (or None). Both
    ends are accepted because both read naturally depending on the rule —
    ``units bar blue only`` and ``growth iconmap only sla: breach=🔥`` —
    and a trailing one has to come off before an `iconmap` body is split
    on commas, where it would otherwise be read as a colour name.
    """
    text = arg.strip()
    low = text.lower()
    if low in words:
        return "", words[low]
    for word, meaning in words.items():
        if low.startswith(word + " "):
            return text[len(word):].strip(), meaning
        if low.startswith(word + ":"):
            # `status colormap only: fail=red` — the modifier written hard
            # against the colon that opens a map with no source. The colon
            # belongs to the body, so it goes back on.
            return ":" + text[len(word) + 1:], meaning
        if low.endswith(" " + word):
            return text[:-(len(word) + 1)].strip(), meaning
    return text, None


def _split_only(arg: str) -> tuple:
    """Pull a standalone ``only`` off either end — Power BI's "Bar only" /
    "Icon only": draw the format *instead of* the value."""
    text, hit = _split_flag(arg, {"only": True})
    return text, bool(hit)


def _split_place(arg: str) -> tuple:
    """Pull a standalone position word off either end of an argument.

    A column genuinely named "left" survives, the same way one named
    "only" does: the search runs on the keyword's argument, never on the
    column names, which were taken off the line before this sees it.
    """
    return _split_flag(arg, _PLACE_WORDS)


def _split_pill(arg: str) -> tuple:
    """Pull a standalone ``pill`` off either end — draw this rule's colour
    as a lozenge round the value rather than as a fill behind the cell."""
    text, hit = _split_flag(arg, {"pill": True, "pills": True})
    return text, bool(hit)


def _split_modifiers(arg: str) -> tuple:
    """`"green only by revenue"` → `("green", "revenue", True)`.

    `only` is looked for on both sides of the `by` clause, because both
    orders are things people write and neither is wrong. A column actually
    named "only" survives — the search runs on the argument, never on the
    name the clause hands back.
    """
    arg, only = _split_only(arg)
    arg, source = _split_by_clause(arg)
    arg, trailing = _split_only(arg)
    return arg, source, only or trailing


def _parse_value_map(lineno: int, arg: str, keyword: str) -> tuple:
    """`"severity: high=▲ #d9534f, med=■ amber, low=▼ green"`
    → (source column, {value: [first token, colour]}).

    Shared by `iconmap` and `colormap`, which differ only in what the
    right-hand side of each pair means and in which colours it resolves
    against.

    **The source column may be left out** — `20* iconmap: 1=✓ green` reads
    each column it draws in. That is the only spelling that works with a
    pattern: naming one source paints one column's answer into all of
    them, which is what "the 20* rule doesn't work" turned out to be.
    """
    arg = arg.strip()
    if arg[:1] in "\"'":
        end = arg.find(arg[0], 1)
        after = arg[end + 1:].lstrip() if end != -1 else ""
        source = arg[1:end] if end != -1 else ""
        body = after[1:] if after.startswith(":") else ""
        sep = ":" if after.startswith(":") else ""
    else:
        source, sep, body = arg.partition(":")
        source = source.strip()
    what = "icon" if keyword == "iconmap" else "colour"
    if not sep:
        raise ValueError(
            f"line {lineno}: {keyword!r} needs "
            f"'source-column: value={what}, …' — or ': value={what}, …' "
            f"to read the column it draws in")
    mapping: dict = {}
    for chunk in body.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, eq, spec = chunk.partition("=")
        if not eq or not key.strip() or not spec.strip():
            raise ValueError(
                f"line {lineno}: don't understand {what} mapping {chunk!r} "
                f"(use 'value={what}')")
        parts = spec.split()
        if keyword == "iconmap":
            # glyph, then an optional colour for it
            mapping[key.strip()] = [parts[0],
                                    _resolve_glyph_color(parts[1])
                                    if len(parts) > 1 else None]
        else:
            # a fill, then an optional ink to put on it. Left out, the ink
            # is computed from the fill — the same readable_fg every other
            # colour rule uses, so a dark preset does not get dark text.
            fill = _resolve_color(parts[0])
            # the ink resolves against the *vivid* presets, not the fill
            # ones: `ok=green white` is text on a block, and the fill
            # presets are dark backgrounds that would vanish on one
            mapping[key.strip()] = [fill,
                                    _resolve_glyph_color(parts[1])
                                    if len(parts) > 1 else readable_fg(fill)]
    if not mapping:
        raise ValueError(
            f"line {lineno}: {keyword!r} has no value={what} pairs")
    return source, mapping


#: The word that separates a spark's own settings from the columns it
#: reads. `by` is accepted because every other rule that reads another
#: column takes it, and `across` because that is what a spark does.
_SPARK_FROM = ("from", "by", "across")

#: What becomes of the columns a spark reads. `keep` is the default, and
#: is here so it can be said out loud over an earlier habit.
_SPARK_FATES = {"hide": "hide", "replace": "replace", "keep": None}

#: A spark's width, in pixels on the card.
MIN_SPARK_WIDTH, MAX_SPARK_WIDTH = 16, 400

_SPARK_HELP = ("kinds: line, area, step, bars, winloss, dots · marks: "
               "first, last, high, low, ends, points (each may take a "
               "colour) · a colour · negative <colour> · ref mean|median|"
               "<number> · shared · smooth · thick · tall · 90px · "
               "left|right|above|below|in · only · hide|replace")


def _spark_colour(token: "str | None") -> "str | None":
    """`token` as a spark colour — a vivid preset name or a hex — or None."""
    if not token:
        return None
    low = token.lower()
    if low in _spark.COLORS:
        return _spark.COLORS[low]
    if re.fullmatch(r"#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?", token):
        return token
    return None


def _parse_spark(lineno: int, columns: list, arg: str) -> Rule:
    """`"bars green last from jan..dec hide"` → a sparkline rule.

    The column list comes last, after `from`, because it is the one part of
    the line that can be anything — a name with a space, a pattern, a
    range. Everything before it is a word this parser knows, in any order,
    so an unknown word is an error that lists what it could have been
    rather than a column name nobody meant.
    """
    if not columns:
        raise ValueError(
            f"line {lineno}: 'spark' needs a column to draw in — "
            f"'trend spark from jan..dec'")
    spans = list(_TOKEN_RE.finditer(arg))
    cut = next((k for k, m in enumerate(spans)
                if m.group().lower() in _SPARK_FROM), None)
    if cut is None:
        raise ValueError(
            f"line {lineno}: 'spark' needs the columns to read — "
            f"'… spark from jan..dec', 'from q1, q2, q3' or 'from sales_*'")
    options = [m.group() for m in spans[:cut]]
    tail = arg[spans[cut].end():].strip()

    fate = None
    # a trailing `hide` / `replace` after the column list — only when a
    # space, not a comma, sets it off, so a column called "hide" in the
    # list itself survives
    words = list(_TOKEN_RE.finditer(tail))
    if len(words) > 1 and words[-1].group().lower() in _SPARK_FATES:
        before = tail[:words[-1].start()]
        if before[-1:].isspace() and not before.rstrip().endswith(","):
            fate = _SPARK_FATES[words[-1].group().lower()]
            tail = before.rstrip()
    series = _column_list(tail)
    if not series:
        raise ValueError(
            f"line {lineno}: 'spark … from' needs at least one column")

    kind = colour = negative = width = place = ref = None
    marks: list = []
    shared = tall = smooth = thick = only = False
    i = 0
    while i < len(options):
        token = options[i]
        low = token.lower()
        following = options[i + 1] if i + 1 < len(options) else None
        if low in _spark.KINDS:
            kind = _spark.KINDS[low]
        elif low in _spark.MARKS:
            chosen = _spark_colour(following)
            for name in _spark.MARKS[low]:
                marks.append([name, chosen])
            i += 1 if chosen else 0
        elif low in ("negative", "negatives", "neg"):
            chosen = _spark_colour(following)
            if chosen is None:
                raise ValueError(f"line {lineno}: 'negative' needs a colour "
                                 f"— 'negative red'")
            negative = chosen
            i += 1
        elif low in ("ref", "reference", "target", "baseline"):
            spec = (_spark.REFS.get(following.lower())
                    if following else None)
            if spec is None:
                spec = _spark.number(following)
            if spec is None:
                raise ValueError(
                    f"line {lineno}: 'ref' needs mean, median or a number "
                    f"— 'ref mean', 'ref 100'")
            ref = spec
            i += 1
        elif low in ("shared", "same-scale", "together"):
            shared = True
        elif low == "tall":
            tall = True
        elif low in ("smooth", "curved", "curve"):
            smooth = True
        elif low in ("thick", "bold"):
            thick = True
        elif re.fullmatch(r"\d+px", low):
            width = int(low[:-2])
            if not MIN_SPARK_WIDTH <= width <= MAX_SPARK_WIDTH:
                raise ValueError(
                    f"line {lineno}: a spark {width}px wide is outside "
                    f"{MIN_SPARK_WIDTH}–{MAX_SPARK_WIDTH} pixels")
        elif low in _PLACE_WORDS:
            place = _PLACE_WORDS[low]
        elif low == "only":
            only = True
        elif low in _SPARK_FATES:
            fate = _SPARK_FATES[low]
        elif _spark_colour(token) and colour is None:
            colour = _spark_colour(token)
        else:
            raise ValueError(
                f"line {lineno}: don't understand {token!r} in a spark "
                f"({_SPARK_HELP})")
        i += 1
    return Rule("sparkline", columns, series=series,
                spark_kind=kind or "line", color=colour,
                negative_color=negative, marks=marks, ref=ref,
                shared=shared, tall=tall, smooth=smooth, thick=thick,
                spark_width=width, glyph_where=place, hide_value=only,
                take_sources=fate)


def _parse_token_line(lineno: int, line: str) -> Rule:
    tokens = line.split()

    spark_at = next((i for i, t in enumerate(tokens)
                     if t.lower() in _SPARK_KEYWORDS), None)
    if spark_at and not any(_keyword_of(t) for t in tokens[:spark_at]):
        # Taken before the right-to-left keyword scan, because a spark's
        # column list comes *after* its keyword and may hold a name that
        # reads as one (`from label, sort`). The scan would pick the last
        # of those and parse a different rule entirely.
        return _parse_spark(lineno, _column_list(" ".join(tokens[:spark_at])),
                            " ".join(tokens[spark_at + 1:]))

    picture_at = next((i for i, t in enumerate(tokens)
                       if t.lower() in _PICTURE_KEYWORDS), None)
    if (picture_at and tokens[0].lower() not in _LEADING_KEYWORDS
            and not any(_keyword_of(t) for t in tokens[:picture_at])):
        # Before the scan for the same reason a spark is: the column after
        # `from` is anything at all, `from bar` included.
        return _parse_picture(
            lineno, _column_list(" ".join(tokens[:picture_at])),
            " ".join(tokens[picture_at + 1:]))

    if tokens and tokens[0].lower() in _LEADING_KEYWORDS:
        # `hide`/`show` lead their line instead of following a column list,
        # so they are taken before the right-to-left keyword scan rather
        # than being added to it — which is also why neither can collide
        # with a word that appears as some other rule's argument.
        word = tokens[0].lower()
        cols = _column_list(" ".join(tokens[1:]))
        if not cols:
            raise ValueError(f"line {lineno}: {word!r} needs a column name")
        return Rule(word, cols)

    if len(tokens) == 2 and tokens[0].lower() in _HEIGHT_WORDS:
        # `height 40` — how tall every row is. Two tokens exactly, so a
        # column genuinely called "height" (`height scale green`) is still a
        # column.
        return Rule("row_height", row_height=_row_height(lineno, tokens[1]))
    if (len(tokens) >= 3 and tokens[-2].lower() in _HEIGHT_WORDS
            and _spark.number(tokens[-1].lower().removesuffix("px"))
            is not None
            and not any(_keyword_of(t) for t in tokens[:-2])):
        # `revenue height 40` reads as a column's and cannot be one: a row
        # is one height across the whole table. Said, rather than applied
        # to everything the way the line did not say.
        raise ValueError(
            f"line {lineno}: 'height' is how tall a *row* is, and a row is "
            f"one height across the table — put 'height "
            f"{tokens[-1]}' on a line of its own, or after '=>' for the rows "
            f"that pass a test ('status = late => height {tokens[-1]}')")

    if any(t.lower() == "wrap" for t in tokens):
        # Deliberately not a per-column rule. A row is as tall as its
        # tallest cell, so "let this text wrap" is a fact about the table
        # however it is spelled — and a rule that reads as one column's
        # while acting on all of them is worse than no rule at all.
        if len(tokens) > 1:
            raise ValueError(
                f"line {lineno}: 'wrap' takes no columns — a row grows to "
                f"fit its tallest cell, so it applies to the whole table. "
                f"Put it on a line of its own.")
        return Rule("wrap")

    kw_idx = next((i for i in range(len(tokens) - 1, -1, -1)
                   if _keyword_of(tokens[i])), None)
    if kw_idx is None or kw_idx == 0:
        raise ValueError(
            f"line {lineno}: expected 'column scale|bar|icons|iconmap|"
            f"colormap|format …', 'hide column', 'show column, column', "
            f"or 'condition => style', "
            f"got {line!r}")
    columns = _column_list(" ".join(tokens[:kw_idx]))
    keyword = _keyword_of(tokens[kw_idx])
    arg = " ".join(tokens[kw_idx + 1:]).strip()
    if tokens[kw_idx].endswith(":"):
        # give the map parser back the colon the split took off it, so an
        # absent source still reads as absent rather than as missing
        arg = ":" + arg

    if keyword in _SPARK_KEYWORDS:
        return _parse_spark(lineno, columns, arg)
    if keyword in _PICTURE_KEYWORDS:
        return _parse_picture(lineno, columns, arg)

    if keyword in ("iconmap", "colormap", "colourmap"):
        # here the `only` comes off the whole argument: the mapping body is
        # split on commas, and a trailing one left in place would be read
        # as the last pair's colour
        arg, only = _split_only(arg)
        arg, place = _split_place(arg)
        arg, pill = _split_pill(arg)
        arg, size = _split_size(lineno, arg)
        arg, shape = _split_flag(arg, _SHAPE_WORDS)
        keyword = "iconmap" if keyword == "iconmap" else "colormap"
        source, mapping = _parse_value_map(lineno, arg, keyword)
        mode = "icon_map" if keyword == "iconmap" else "color_map"
        return Rule(mode, columns, source=source, mapping=mapping,
                    hide_value=only, glyph_where=place, as_pill=pill,
                    picture_size=size, picture_shape=shape)
    if keyword == "tooltip":
        # `revenue tooltip note` and `revenue tooltip by note` mean the
        # same thing: the whole argument *is* the source column, and the
        # `by` clause every other rule uses is accepted so nobody has to
        # remember which rules take it.
        rest, source, _only = _split_modifiers(arg)
        name = _unquote((source or rest).strip())
        if not name:
            raise ValueError(
                f"line {lineno}: 'tooltip' needs the column to read the "
                f"note from — 'revenue tooltip note'")
        if source and rest.strip():
            raise ValueError(
                f"line {lineno}: 'tooltip' takes one column, got "
                f"{rest.strip()!r} and {source!r}")
        return Rule("tooltip", columns, source=name)

    if keyword in _AUTO_KEYWORDS:
        arg, source, only = _split_modifiers(arg)
        arg, shape = _split_flag(arg, _AUTO_SHAPES)
        name = arg.strip().lower()
        if name and name not in PALETTES:
            raise ValueError(f"line {lineno}: unknown palette {arg!r} "
                             f"(try {', '.join(sorted(PALETTES))})")
        return Rule("auto_color", columns, palette=name or None,
                    source=source, hide_value=only,
                    as_pill=shape in (None, "pill"),
                    ink_only=shape == "text")
    if keyword == "scale":
        arg, source, only = _split_modifiers(arg)
        preset = _SCALE_PRESETS.get(arg.lower().replace(" ", "-")
                                    or "red-yellow-green")
        if preset is None:
            raise ValueError(f"line {lineno}: unknown scale {arg!r} "
                             f"(try {', '.join(sorted(_SCALE_PRESETS))})")
        return Rule("color_scale", columns, low=preset[0], mid=preset[1],
                    high=preset[2], source=source, hide_value=only)
    if keyword == "bar":
        arg, source, only = _split_modifiers(arg)
        return Rule("data_bar", columns,
                    color=_BAR_PRESETS.get(arg.lower(), arg or _BAR_PRESETS["blue"]),
                    negative_color=_BAR_NEGATIVE, source=source,
                    hide_value=only)
    if keyword in ("icons", "icon"):
        arg, source, only = _split_modifiers(arg)
        arg, place = _split_place(arg)
        arg, pill = _split_pill(arg)
        reverse = False
        low = arg.lower()
        if low.endswith(" reverse") or low == "reverse":
            reverse = True
            arg = arg[:len(arg) - len("reverse")].strip()
        key = _ICON_LABELS.get(arg.lower(), arg.lower() or "traffic")
        if key not in _ICON_SETS:
            raise ValueError(f"line {lineno}: unknown icon set {arg!r} "
                             f"(traffic, arrows, check)")
        return Rule("icons", columns, icon_set=key, reverse=reverse,
                    source=source, hide_value=only, glyph_where=place,
                    as_pill=pill)
    if keyword == "width":
        if arg.lower() in ("auto", "fit", ""):
            # an explicit "back to normal", for undoing a wider pattern rule
            return Rule("column_width", columns, width=None)
        try:
            width = int(round(float(arg)))
        except ValueError:
            raise ValueError(
                f"line {lineno}: 'width' wants a number of pixels or 'auto', "
                f"got {arg!r}") from None
        if not MIN_RULE_WIDTH <= width <= MAX_RULE_WIDTH:
            raise ValueError(
                f"line {lineno}: width {width} is outside "
                f"{MIN_RULE_WIDTH}–{MAX_RULE_WIDTH} pixels")
        return Rule("column_width", columns, width=width)
    if keyword == "align":
        align = _ALIGNMENTS.get(arg.lower())
        if align is None:
            raise ValueError(f"line {lineno}: unknown alignment {arg!r} "
                             f"(left, right, centre)")
        return Rule("align", columns, align=align)
    if keyword == "label":
        text = _unquote(arg)
        if not text:
            raise ValueError(
                f"line {lineno}: 'label' needs the header text to show")
        return Rule("header_label", columns, label=text)
    if keyword == "sort":
        direction = _SORT_WORDS.get(arg.lower().strip() or "asc")
        if direction is None:
            raise ValueError(
                f"line {lineno}: don't understand sort {arg!r} "
                f"(asc / ascending / up, or desc / descending / down)")
        if len(columns) != 1:
            # One column, because there is one row order. Naming two would
            # read as a tie-break and isn't one.
            raise ValueError(
                f"line {lineno}: 'sort' takes one column, got "
                f"{len(columns)} — a table has one row order")
        return Rule("sort", columns, direction=direction)
    # format
    if not arg:
        raise ValueError(f"line {lineno}: 'format' needs a spec like ',.0f'")
    return Rule("number_format", columns, number_spec=arg)


def _resolve_color(token: str) -> str:
    token = token.strip()
    return _FILL_PRESETS.get(token.lower(), token)


# vivid foreground colours for an icon glyph — the fill presets are dark
# backgrounds and would be invisible drawn as a glyph on the grid
_GLYPH_COLOURS = {
    "green": "#5cb85c", "amber": "#e0a83d", "orange": "#e0a83d",
    "red": "#d9534f", "blue": "#4a90d9", "grey": "#9aa0a6", "gray": "#9aa0a6",
}


def _resolve_glyph_color(token: str) -> str:
    token = token.strip()
    return _GLYPH_COLOURS.get(token.lower(), token)


def _parse_style_tokens(lineno: int, rhs: str) -> dict:
    out: dict = {"scope": "cell"}
    for chunk in rhs.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(None, 1)
        head = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""
        if head == "bold":
            out["bold"] = True
        elif head == "bg" and rest:
            out["bg"] = _resolve_color(rest)
        elif head == "fg" and rest:
            out["fg"] = _resolve_color(rest)
        elif head == "row":
            out["scope"] = "row"
            if rest:
                out["bg"] = _resolve_color(rest)
        elif head == "only":
            # the same modifier the format keywords take: show the styling,
            # not the value. On its own it blanks the cell where the test
            # passes, which is the honest reading of it.
            out["hide_value"] = True
        elif head in _HEIGHT_WORDS:
            # the rows the test picks are this tall — on a cell rule the
            # cell's row, on a `row` rule the same row; a row is one height
            out["row_height"] = _row_height(lineno, rest)
        elif head == "icon" and rest:
            # One glyph placed by a condition — distinct from `icons` (a
            # graded set) and `iconmap` (a lookup). Without this there was
            # no way at all to say "a tick where the cell is 1", which is
            # the commonest thing anyone wants of a flag column.
            parts = rest.split()
            out["glyph"] = parts[0]
            for token in parts[1:]:
                place = _PLACE_WORDS.get(token.lower())
                if place:
                    out["glyph_where"] = place
                elif re.fullmatch(r"\d+px", token.lower()):
                    # how tall a pasted picture is drawn
                    out["picture_size"] = _picture_size(lineno, token)
                elif token.lower() in _SHAPE_WORDS:
                    # …and the shape it is cut to; its colour is the tile
                    out["picture_shape"] = _SHAPE_WORDS[token.lower()]
                else:
                    out["glyph_color"] = _resolve_glyph_color(token)
        elif head == "pill":
            # A lozenge. What it wraps is decided by whether anything is
            # written in it: `pill green` puts it round the cell's own
            # value, `pill green "OT"` makes it a mark of its own standing
            # beside the value. The label is quoted for the same reason
            # `label` quotes its text — an unquoted word here is a colour,
            # and guessing between the two would be silently wrong.
            out["as_pill"] = True
            for token in _quoted_tokens(rest):
                place = _PLACE_WORDS.get(token.lower())
                if place:
                    out["glyph_where"] = place
                elif token[:1] in "\"'":
                    out["glyph"] = _unquote(token)
                else:
                    out["bg"] = _resolve_color(token)
        else:
            raise ValueError(
                f"line {lineno}: don't understand style {chunk!r} "
                f"(use 'bg <colour>', 'fg <colour>', 'bold', 'row <colour>', "
                f"'icon <glyph> [colour] [left|right|above|below|in]', "
                f"'pill <colour> [\"text\"]', 'only', 'height <pixels>')")
    if ("bg" not in out and "fg" not in out and "glyph" not in out
            and not out.get("bold") and not out.get("hide_value")
            and not out.get("as_pill") and not out.get("row_height")):
        raise ValueError(f"line {lineno}: no style after '=>'")
    if (out.get("glyph") or out.get("as_pill")) and out["scope"] == "row":
        # a row highlight paints every cell; a mark in every cell of the
        # row is not what anyone means by it
        what = "a 'pill'" if out.get("as_pill") else "an 'icon'"
        raise ValueError(
            f"line {lineno}: {what} goes in a cell, so it cannot be "
            f"combined with 'row' — name the column on the left instead")
    return out


def _parse_condition_line(lineno: int, line: str) -> Rule:
    cond, _, rhs = line.partition("=>")
    cond, rhs = cond.strip(), rhs.strip()
    style = _parse_style_tokens(lineno, rhs)
    # `paint-columns if <other column> op value` — style the columns on the
    # left, but test the column named after `if` / `when`.
    low = cond.lower()
    for sep in (" if ", " when "):
        idx = low.find(sep)
        if idx > 0:
            left, right = cond[:idx].strip(), cond[idx + len(sep):].strip()
            try:
                op, value, tested = _split_condition(right)
            except ValueError:
                continue
            if not left or not tested:
                break
            return Rule("highlight", _column_list(left), scope=style["scope"],
                        op=op, value=value, source=tested, bg=style.get("bg"),
                        fg=style.get("fg"), bold=bool(style.get("bold")),
                        glyph=style.get("glyph"),
                        glyph_color=style.get("glyph_color"),
                        glyph_where=style.get("glyph_where"),
                        as_pill=bool(style.get("as_pill")),
                        hide_value=bool(style.get("hide_value")),
                        row_height=style.get("row_height"),
                picture_size=style.get("picture_size"),
                picture_shape=style.get("picture_shape"))
    # split "column op value": the column is everything up to the operator
    op, value, column = _split_condition(cond)
    if not column:
        raise ValueError(f"line {lineno}: no column in condition {cond!r}")
    return Rule("highlight", _column_list(column), scope=style["scope"],
                op=op, value=value, bg=style.get("bg"), fg=style.get("fg"),
                bold=bool(style.get("bold")), glyph=style.get("glyph"),
                glyph_color=style.get("glyph_color"),
                glyph_where=style.get("glyph_where"),
                as_pill=bool(style.get("as_pill")),
                hide_value=bool(style.get("hide_value")),
                row_height=style.get("row_height"),
                picture_size=style.get("picture_size"),
                picture_shape=style.get("picture_shape"))


def _split_condition(cond: str) -> tuple:
    """`"score >= 90"` → (op, value, column)."""
    cond = cond.strip()
    # a "quoted column" takes everything up to its closing quote, then the
    # rest is a bare condition parse_op_value already understands
    if cond[:1] in "\"'":
        end = cond.find(cond[0], 1)
        if end != -1:
            op, value = parse_op_value(cond[end + 1:])
            return (op, value, cond[1:end])
    low = cond.lower()
    for token, canon in (("is not empty", "notempty"), ("is empty", "empty")):
        if low.endswith(" " + token) or low == token:
            return (canon, None, cond[:len(cond) - len(token)].strip())
    for token, canon in ((" contains ", "contains"), (" starts with ", "starts"),
                         (" ends with ", "ends"), (" matches ", "matches"),
                         (" between ", "between")):
        idx = low.find(token)
        if idx != -1:
            column = cond[:idx].strip()
            rest = cond[idx + len(token):].strip()
            if canon == "between":
                parts = rest.replace("..", " ").split()
                return ("between", [_coerce(parts[0]), _coerce(parts[1])]
                        if len(parts) == 2 else rest, column)
            return (canon, rest, column)
    for op in ("!=", ">=", "<=", "=", ">", "<"):
        idx = cond.find(op)
        if idx > 0:
            return (op, _coerce(cond[idx + len(op):]), cond[:idx].strip())
    raise ValueError(f"no operator in condition {cond!r}")


def _strip_inline_comment(line: str) -> str:
    """Drop a trailing ``# comment`` from a rule line. A ``#`` only starts a
    comment when it is outside "quotes" and followed by whitespace or the end
    of the line — so ``=> bg #2e7d46`` and ``ok=✓ #d9534f`` keep their hex."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i + 1 == len(line) or line[i + 1].isspace()):
            return line[:i].rstrip()
    return line


def _parse_one_line(lineno: int, line: str) -> Rule:
    # A pasted picture's `data:image/png;base64,` prefix holds a comma, and
    # a rules line is split on commas — so the prefix comes off before
    # anything else reads the line. The bytes say what type it was.
    line = _images.DATA_PREFIX.sub("", line)
    line = _strip_inline_comment(line)
    if not line:
        raise ValueError(f"line {lineno}: nothing but a comment")
    return (_parse_condition_line(lineno, line) if "=>" in line
            else _parse_token_line(lineno, line))


def parse_rules(text: str) -> list[Rule]:
    """Parse the rule text, raising ``ValueError`` on the first bad line."""
    rules: list[Rule] = []
    for lineno, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.strip()
        if line and not line.startswith("#"):
            rules.append(_parse_one_line(lineno, line))
    return rules


def parse_rule_lines(text: str) -> list[tuple]:
    """Every line of the rules box as ``(raw line, Rule | None, error | None)``
    — comments and blanks come back as ``(raw, None, None)``. For the rule
    manager, which edits the box one line at a time and must not disturb the
    others."""
    out: list[tuple] = []
    for lineno, raw in enumerate(str(text or "").splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            out.append((raw, None, None))
            continue
        try:
            out.append((raw, _parse_one_line(lineno, stripped), None))
        except ValueError as exc:
            out.append((raw, None, str(exc)))
    return out


def _op_phrase(op: str, value: Any) -> str:
    words = {">": "> ", ">=": "≥ ", "<": "< ", "<=": "≤ ", "=": "= ",
             "!=": "≠ ", "contains": "contains ", "starts": "starts with ",
             "ends": "ends with ", "matches": "matches "}
    if op == "empty":
        return "is empty"
    if op == "notempty":
        return "is not empty"
    if op == "between" and isinstance(value, (list, tuple)):
        return f"between {value[0]}–{value[1]}"
    return words.get(op, f"{op} ") + str(value)


#: How a decoration's place reads in the rules manager. "left" is absent
#: rather than spelled out, because it is where a mark went before there
#: was anywhere else to put one.
_PLACE_PHRASE = {"right": "on the right", "above": "above the value",
                 "below": "below the value", "in": "in place of the value"}


#: A run long enough to be a pasted picture, with or without its prefix.
_LONG_BASE64 = re.compile(
    r"(?:data:image/[\w.+-]+;base64,)?[A-Za-z0-9+/_-]{64,}={0,2}")


def abbreviate_pictures(text: Any) -> str:
    """`text` with each pasted picture in it shortened to ``‹picture · 3 KB›``.

    For *showing* a rule line — a preview, a list, an error — never for
    keeping one: a 20 KB logo is one unbreakable word, and a label asked to
    wrap it grows as wide as the logo is long.
    """
    def short(match) -> str:
        if _images.picture_uri(match.group(0)) is None:
            return match.group(0)
        kb = max(1, round(len(match.group(0)) * 3 / 4 / 1024))
        return f"‹picture · {kb} KB›"
    return _LONG_BASE64.sub(short, str(text or ""))


def rule_summary(rule: Rule) -> str:
    """A one-line human description of a rule, for the manager's list."""
    cols = ", ".join(rule.columns) or "every column"
    by = f" (by {rule.source})" if rule.source else ""
    only = ", value hidden" if rule.hide_value else ""
    place = ("" if not rule.glyph_where or rule.glyph_where == "left"
             else ", " + _PLACE_PHRASE.get(rule.glyph_where, rule.glyph_where))
    potted = " in a pill" if rule.as_pill else ""
    if rule.mode == "color_scale":
        return f"{cols}  ·  colour scale{by}{only}"
    if rule.mode == "data_bar":
        return f"{cols}  ·  data bar{by}{only}"
    if rule.mode == "highlight":
        where = "row" if rule.scope == "row" else "cell"
        tall = f", {rule.row_height}px tall" if rule.row_height else ""
        if rule.glyph:
            test = f"{rule.source} " if rule.source else ""
            glyph = ("a picture" if _images.picture_uri(rule.glyph)
                     else rule.glyph)
            return (f"{cols}  ·  {glyph} when {test}"
                    f"{_op_phrase(rule.op, rule.value)}" if rule.source else
                    f"{cols} {_op_phrase(rule.op, rule.value)}  ·  "
                    f"{glyph}{potted}{place}") + tall
        test = f"{rule.source} " if rule.source else ""
        return (f"{cols}  ·  highlight the {where} when {test}"
                f"{_op_phrase(rule.op, rule.value)}" if rule.source else
                f"{cols} {_op_phrase(rule.op, rule.value)}  ·  "
                f"highlight the {where}") + tall
    if rule.mode == "icons":
        rev = ", reversed" if rule.reverse else ""
        return (f"{cols}  ·  icons ({rule.icon_set or 'traffic'}{rev})"
                f"{potted}{by}{place}{only}")
    if rule.mode == "icon_map":
        whence = f"“{rule.source}”" if rule.source else "its own value"
        return f"{cols}  ·  icon from {whence}{potted}{place}{only}"
    if rule.mode == "color_map":
        whence = f"“{rule.source}”" if rule.source else "its own value"
        return f"{cols}  ·  colour from {whence}{potted}{only}"
    if rule.mode == "auto_color":
        whence = f" from “{rule.source}”" if rule.source else ""
        shape = ("text" if rule.ink_only else
                 "a pill each" if rule.as_pill else "a fill each")
        return (f"{cols}  ·  auto colour{whence} "
                f"({rule.palette or DEFAULT_PALETTE}, {shape}){only}")
    if rule.mode == "number_format":
        return f"{cols}  ·  number format “{rule.number_spec}”"
    if rule.mode == "tooltip":
        return f"{cols}  ·  tooltip from “{rule.source}”"
    if rule.mode == "sparkline":
        fate = {"hide": ", sources hidden",
                "replace": ", in place of its sources"}.get(
                    rule.take_sources, "")
        return (f"{cols}  ·  {rule.spark_kind or 'line'} sparkline from "
                f"{', '.join(str(s) for s in rule.series)}{place}{fate}"
                f"{only}")
    if rule.mode == "image":
        size = f", {rule.picture_size}px tall" if rule.picture_size else ""
        size += f", {rule.picture_shape}" if rule.picture_shape else ""
        size += f" on {rule.picture_tile}" if rule.picture_tile else ""
        if not rule.source:
            return f"{cols}  ·  its values drawn as pictures{place}{size}"
        fate = ", that column hidden" if rule.take_sources == "hide" else ""
        return (f"{cols}  ·  picture from “{rule.source}”{place}{size}"
                f"{fate}{only}")
    if rule.mode == "hide":
        return f"hide  {cols}"
    if rule.mode == "show":
        return f"show only  {cols}"
    if rule.mode == "column_width":
        return (f"{cols}  ·  width {rule.width}px" if rule.width
                else f"{cols}  ·  width fits the content")
    if rule.mode == "align":
        return f"{cols}  ·  aligned {rule.align}"
    if rule.mode == "header_label":
        return f"{cols}  ·  headed “{rule.label}”"
    if rule.mode == "wrap":
        return "wrap text  ·  rows grow to fit"
    if rule.mode == "row_height":
        return f"every row  ·  {rule.row_height}px tall"
    if rule.mode == "sort":
        way = "Z–A" if rule.direction == "desc" else "A–Z"
        return f"{cols}  ·  sorted {way} to start with"
    return rule.mode


def parse_rules_lenient(text: str) -> tuple[list[Rule], list[str]]:
    """Parse the rule text, skipping bad lines and collecting their
    messages — for the node paths where one typo must not lose the rest."""
    rules: list[Rule] = []
    errors: list[str] = []
    for lineno, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rules.append(_parse_one_line(lineno, line))
        except ValueError as exc:
            errors.append(str(exc))
    return rules, errors


def _dedup(seq) -> list:
    seen, out = set(), []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def style_payload(params: dict) -> dict:
    """Turn a node's params — a ``format_rules`` text box and the ``show``
    / ``hide`` column lists — into the payload carried on a ``style`` port.

    Never raises: a bad rule line is dropped and its message collected, to
    be reported wherever the style is *applied* (Show Table), not typed.
    """
    rules, errors = parse_rules_lenient(params.get("format_rules", ""))
    hide = [c for r in rules if r.mode == "hide" for c in r.columns]
    hide += _column_list(params.get("hide"))
    # A `show` list is ordered, so it is concatenated rather than unioned
    # into a set: the order the columns were named is the order they sit
    # in, and the box's lines come before the picker's for the same reason
    # a rule earlier in the box is drawn first.
    show = [c for r in rules if r.mode == "show" for c in r.columns]
    show += _column_list(params.get("show"))
    keep = [r for r in rules if r.mode not in _LEADING_KEYWORDS]
    # The Sort By / direction pair is the same rule spelled as a control.
    # Appended, so it wins over a `sort` line in the box the way a later
    # line wins over an earlier one — the box is the advanced way in, the
    # dropdown the obvious one, and the obvious one should not lose.
    sort_col = str(params.get("sort") or "").strip()
    if sort_col:
        keep.append(Rule("sort", [_unquote(sort_col)],
                         direction=("desc" if str(
                             params.get("sort_dir") or "").lower().startswith(
                                 "desc") else "asc")))
    payload = {"rules": [r.to_dict() for r in keep], "show": _dedup(show),
               "hide": _dedup(hide), "errors": errors}
    # Written only when the index is put away, so a style that says nothing
    # about it is the payload it always was (AA6).
    if not params.get("row_index", True):
        payload["index"] = False
    return payload


def _style_parts(style_obj: Any) -> tuple:
    """(rules, show, hide, errors) out of a payload of any shape."""
    if isinstance(style_obj, dict):
        return (list(style_obj.get("rules") or []),
                list(style_obj.get("show") or []),
                list(style_obj.get("hide") or []),
                list(style_obj.get("errors") or []))
    if isinstance(style_obj, (list, tuple)):
        return (list(style_obj), [], [], [])
    return ([], [], [], [])


def merge_styles(base: Any, extra: Any) -> dict:
    """`extra` laid on top of `base`: rules concatenated (so a later rule
    wins), show and hide lists appended, errors kept from both. Either side
    may be a payload dict, a bare rule list, or ``None``.

    `show` appends rather than replacing, which is the same bargain `hide`
    has always struck: a card can add to an incoming style but not argue
    with it. Replacing would let a card silently drop a column the style it
    was handed was built around, and there is no way to tell from here
    which of the two was meant.
    """
    b_rules, b_show, b_hide, b_err = _style_parts(base)
    e_rules, e_show, e_hide, e_err = _style_parts(extra)
    merged = {"rules": b_rules + e_rules, "show": _dedup(b_show + e_show),
              "hide": _dedup(b_hide + e_hide), "errors": b_err + e_err}
    # the index goes the way a hidden column does: either side can put it
    # away, and neither can bring it back
    if not (index_shown(base) and index_shown(extra)):
        merged["index"] = False
    return merged


def shown_columns(style_obj: Any) -> list[str]:
    """The keep-list the style asks Show Table for, in order. Empty — the
    usual case — means every column, which is not the same as none."""
    if isinstance(style_obj, dict):
        return [str(c) for c in (style_obj.get("show") or [])]
    return []


def hidden_columns(style_obj: Any) -> list[str]:
    """Columns the style asks Show Table to keep out of view — helper
    columns a rule reads but the reader shouldn't see."""
    if isinstance(style_obj, dict):
        return [str(c) for c in (style_obj.get("hide") or [])]
    return []


def index_shown(style_obj: Any) -> bool:
    """Does the style leave the row index on show? It does unless it says
    otherwise — the index is the table's own, not something a rule adds."""
    return not (isinstance(style_obj, dict) and style_obj.get("index") is False)


def rules_from_style(style_obj: Any) -> list[Rule]:
    """Rehydrate the ``style`` port payload — a ``{"rules": [...]}`` dict or
    a bare list. Tolerant of anything: a bad payload yields no rules rather
    than an exception, because this runs in the render path where a raise
    would blank the card."""
    if isinstance(style_obj, dict):
        style_obj = style_obj.get("rules")
    if not isinstance(style_obj, (list, tuple)):
        return []
    out: list[Rule] = []
    for item in style_obj:
        try:
            if isinstance(item, Rule):
                out.append(item)
            elif isinstance(item, dict) and item.get("mode") in _MODES:
                out.append(Rule.from_dict(item))
        except (TypeError, ValueError):
            continue
    return out


def style_report(style_obj: Any, df=None) -> list[str]:
    """Everything wrong with a style, for Show Table to log: the parse
    errors the Table Style node carried, plus any column its rules name that
    this table does not have."""
    messages: list[str] = []
    if isinstance(style_obj, dict):
        messages.extend(str(m) for m in (style_obj.get("errors") or []))
    columns = getattr(df, "columns", None)
    if columns is not None:
        known = {str(c) for c in columns}
        named: set = set()
        patterns: set = set()
        rules = rules_from_style(style_obj)
        # A spark drawn in a column the table lacks is *making* that column,
        # so it is not a missing one — not on the spark's own line, and not
        # on a `width`, `label` or `show` line that goes on to use it. The
        # same resolution the card applies, so the two agree on what exists.
        known |= set(spark_projection(df, rules)[0].columns.map(str)) - known
        entries = [c for rule in rules for c in rule.columns
                   if rule.mode != "sparkline" or _is_glob(c)]
        entries += [r.source for r in rules if r.source]
        entries += hidden_columns(style_obj) + shown_columns(style_obj)
        for rule in rules:
            if rule.mode != "sparkline":
                continue
            for entry in rule.series:
                entry = str(entry)
                if entry not in known and ".." in entry:
                    first, _dots, last = entry.partition("..")
                    entries += [_unquote(first.strip()),
                                _unquote(last.strip())]
                else:
                    entries.append(entry)
            if not series_columns(rule.series, df):
                messages.append(
                    f"“{rule_summary(rule)}” has no numeric column to read")
        for c in entries:
            (patterns if _is_glob(c) else named).add(str(c))
        missing = sorted(c for c in named if c not in known)
        if missing:
            messages.append("column(s) not in the table: " + ", ".join(missing))
        empty = sorted(p for p in patterns
                       if not any(fnmatch.fnmatchcase(k, p) for k in known))
        if empty:
            messages.append("pattern(s) matched no column: " + ", ".join(empty))
    return messages


# --------------------------------------------------------------- evaluation

#: The palette an ``autocolour`` rule spends when it is not told one.
#: "mixed" is the app's own default series palette, so a table auto-coloured
#: beside a chart of the same categories reads as one picture.
DEFAULT_PALETTE = "mixed"


def auto_colors(values, palette: "str | None" = None) -> dict:
    """A colour for every distinct value in `values`, naming none of them.

    Returns ``{stringified value: colour}``. Blanks and missing values are
    left out — an empty cell is not a category, and giving it one paints a
    block over the hole rather than showing it.

    **Sorted, deliberately.** Ordering by first appearance would repaint
    the whole column the moment a row arrived at the top, which is the one
    thing that makes an automatic colour worse than a named one: you can no
    longer learn it. Values that compare are sorted natively, so 2 comes
    before 10; a column that mixes types falls back to sorting by text
    rather than raising, because a table is not the place to be strict
    about that.

    More distinct values than the palette has colours and it wraps. That is
    honest rather than good — a column of two hundred categories cannot be
    told apart by colour whatever we do — and it beats leaving the tail
    uncoloured, which reads as "these rows are special".
    """
    wheel = list(PALETTES.get(str(palette or DEFAULT_PALETTE).strip().lower())
                 or PALETTES[DEFAULT_PALETTE])
    seen: list = []
    keys: set = set()
    for v in values:
        if _is_missing(v):
            continue
        key = str(v).strip()
        if not key or key in keys:
            continue
        keys.add(key)
        seen.append(v)
    try:
        ordered = sorted(seen)
    except TypeError:
        ordered = sorted(seen, key=str)
    return {str(v).strip(): wheel[i % len(wheel)]
            for i, v in enumerate(ordered)}


def column_stats(series) -> ColumnStats:
    import pandas as pd

    num = pd.to_numeric(series, errors="coerce")
    num = num[num.notna()]
    if num.empty:
        return ColumnStats()
    lo, hi = float(num.min()), float(num.max())
    try:
        tertiles = (float(num.quantile(1 / 3)), float(num.quantile(2 / 3)))
    except Exception:
        tertiles = None
    return ColumnStats(lo, hi, float(num.mean()), tertiles)


def _is_missing(value: Any) -> bool:
    try:
        return value is None or (isinstance(value, float) and math.isnan(value))
    except Exception:
        return False


def _condition_mask(series, op: str, value: Any):
    import pandas as pd

    if op == "empty":
        return series.isna() | (series.astype("string").str.strip() == "")
    if op == "notempty":
        return ~(series.isna() | (series.astype("string").str.strip() == ""))
    if op in ("contains", "starts", "ends", "matches"):
        text = series.astype("string")
        if op == "contains":
            return text.str.contains(str(value), regex=False, na=False)
        if op == "starts":
            return text.str.startswith(str(value), na=False)
        if op == "ends":
            return text.str.endswith(str(value), na=False)
        return text.str.match(str(value), na=False)

    if op == "between" and isinstance(value, (list, tuple)) and len(value) == 2:
        num = pd.to_numeric(series, errors="coerce")
        lo, hi = sorted(float(v) for v in value)
        return num.between(lo, hi)

    target = value
    if isinstance(target, (int, float)) and not isinstance(target, bool):
        s = pd.to_numeric(series, errors="coerce")
    else:
        s = series.astype("string")
        target = str(value)
    return {
        "=": s == target, "!=": s != target,
        "<": s < target, "<=": s <= target,
        ">": s > target, ">=": s >= target,
    }.get(op, pd.Series(False, index=series.index))


def _format_value(value: Any, spec: str) -> Optional[str]:
    """Apply a Python format spec, with a leading currency symbol (`$`, `€`,
    `£`, `¥`) pulled off as a prefix so a d3-style `$,.0f` also works."""
    if _is_missing(value):
        return None
    spec = str(spec or "").strip()
    prefix = ""
    if spec[:1] in "$€£¥":
        prefix, spec = spec[0], spec[1:]
    number = value if not isinstance(value, str) else _coerce(value)
    try:
        return prefix + format(float(number), spec)
    except (ValueError, TypeError):
        return None


def _place(rule) -> str:
    """Where `rule` puts what it draws. Absent means left, which is where
    the one icon a cell used to hold always went."""
    where = rule.glyph_where or "left"
    return where if where in DECOR_PLACES else "left"


def _mark(text, *, color=None, pill=None, where="left", size=None,
          shape=None) -> "Decoration":
    """The decoration a rule's mark makes: a picture when what was typed as
    the mark is one — base64 pasted where a glyph goes — else the text.

    A picture brings its own colours, so the colour the rule gave the mark
    (a lozenge's, or else the ink's) becomes the tile behind it, cut to a
    rounded square unless a shape was named.
    """
    uri = _images.picture_uri(text)
    if uri is not None:
        tile = pill or color
        return Decoration(image=uri, where=where, size=size, tile=tile,
                          shape=shape or ("rounded" if tile else None))
    return Decoration(text=text, color=color, pill=pill, where=where)


def _picture_place(rule) -> str:
    """Where an `image` rule's pictures go: where it said, else in place of
    the value when the pictures *are* the value (or `only` was said), else
    left of it, like an icon."""
    if rule.glyph_where in DECOR_PLACES:
        return rule.glyph_where
    return "in" if (not rule.source or rule.hide_value) else "left"


def _highlight_style(rule) -> "CellStyle":
    """The style a matched `highlight` lays on a cell.

    Three shapes come out of the same rule, and which one is decided by
    what the rule named rather than by a separate keyword:

    * a plain fill (no ``pill``) — the cell's background, as it always was;
    * ``pill green`` — the colour becomes a lozenge around the cell's own
      value, so the *cell* is not filled and the value carries the ink;
    * ``pill green "OT"`` — the same lozenge, but around a label of its
      own, which makes it a decoration that sits beside the value instead
      of wrapping it.
    """
    place = _place(rule)
    if not rule.as_pill:
        deco = ([_mark(rule.glyph, color=rule.glyph_color, where=place,
                       size=rule.picture_size, shape=rule.picture_shape)]
                if rule.glyph else [])
        return CellStyle(
            bg=rule.bg,
            fg=rule.fg or (readable_fg(rule.bg) if rule.bg else None),
            bold=rule.bold, decorations=deco)

    fill = rule.bg or _FILL_PRESETS["blue"]
    ink = rule.fg or readable_fg(fill)
    if rule.glyph:
        # a pill with something written in it stands beside the value
        return CellStyle(bold=rule.bold, decorations=[_mark(
            rule.glyph, color=rule.glyph_color or ink, pill=fill,
            where=place, size=rule.picture_size, shape=rule.picture_shape)])
    # a pill with nothing written in it wraps what is already there
    return CellStyle(bold=rule.bold, pill=fill, pill_fg=ink)


def _pooled_stats(rule, frame) -> Optional[ColumnStats]:
    """Stats over every column in `rule.pool` at once, or None when the rule
    pools nothing (or `frame` has none of them)."""
    names = getattr(rule, "pool", None)
    if not names or frame is None:
        return None
    import pandas as pd
    present = [c for c in names if c in getattr(frame, "columns", [])]
    if not present:
        return None
    return column_stats(pd.concat([frame[c] for c in present],
                                  ignore_index=True))


def evaluate_column(series, rules, stats: ColumnStats, frame=None,
                    pool_frame=None) -> list:
    """One ``CellStyle | None`` per row of `series`, in its current order.

    `frame` is the whole (current-order) DataFrame — needed only by a rule
    that reads a *different* column than the one it draws in: ``iconmap``,
    and any ``scale`` / ``bar`` / ``icons`` / ``highlight`` rule carrying a
    ``by`` / ``if`` clause (its deciding column is ``rule.source``).

    `pool_frame` is where a pooled rule (``Rule.pool``) is measured, when
    that is more than `frame` holds — a printed table cut to its first rows
    is still shaded against the whole matrix, as `stats` is.
    """
    import pandas as pd

    n = len(series)
    acc: list = [None] * n
    values = list(series)

    def _decide(rule) -> tuple:
        """The series whose values drive `rule`, and stats for it — the
        drawn column, unless a ``by`` / ``if`` clause named another one;
        measured over `rule.pool` together when it names columns."""
        pooled = _pooled_stats(
            rule, pool_frame if pool_frame is not None else frame)
        if (rule.source and frame is not None
                and rule.source in getattr(frame, "columns", [])):
            other = frame[rule.source]
            return other, pooled or column_stats(other)
        return series, pooled or stats

    for rule in rules:
        contrib: list = [None] * n

        if rule.mode == "color_scale":
            decide, dstats = _decide(rule)
            lo = dstats.min if rule.low_value is None else rule.low_value
            hi = dstats.max if rule.high_value is None else rule.high_value
            if lo is None or hi is None or hi == lo:
                span = None
            else:
                span = hi - lo
            num = pd.to_numeric(decide, errors="coerce")
            for i, v in enumerate(num):
                if span is None or _is_missing(v):
                    continue
                color = _scale_color((float(v) - lo) / span,
                                     rule.low or "#23252b", rule.mid,
                                     rule.high or "#2e7d46")
                if color:
                    contrib[i] = CellStyle(bg=color, fg=readable_fg(color))

        elif rule.mode == "data_bar":
            # Excel-style: the axis sits at zero (or an explicit origin). A
            # column with negatives splits from the centre; an all-positive
            # column fills from the left.
            decide, dstats = _decide(rule)
            origin = 0.0 if rule.origin is None else rule.origin
            top = max(abs((dstats.max or 0) - origin),
                      abs((dstats.min or 0) - origin)) or 1.0
            mode = "center" if (dstats.min is not None
                                and dstats.min < origin) else "left"
            num = pd.to_numeric(decide, errors="coerce")
            for i, v in enumerate(num):
                if _is_missing(v):
                    continue
                frac = (float(v) - origin) / top
                negative = frac < 0
                contrib[i] = CellStyle(
                    bar=max(-1.0, min(1.0, frac)), bar_mode=mode,
                    bar_color=(rule.negative_color or _BAR_NEGATIVE) if negative
                    else (rule.color or _BAR_PRESETS["blue"]))

        elif rule.mode == "highlight" and rule.scope == "cell":
            decide, _ = _decide(rule)
            try:
                mask = _condition_mask(decide, rule.op, rule.value)
            except Exception:
                mask = pd.Series(False, index=decide.index)
            style = _highlight_style(rule)
            if rule.row_height:
                style.row_height = rule.row_height
            for i, hit in enumerate(mask.tolist()):
                if hit:
                    contrib[i] = style

        elif rule.mode == "icons":
            decide, dstats = _decide(rule)
            glyphs = _ICON_SETS.get(rule.icon_set or "traffic",
                                    _ICON_SETS["traffic"])
            if rule.reverse:
                glyphs = list(reversed(glyphs))
            t1, t2 = (rule.thresholds if rule.thresholds
                      else (dstats.tertiles or (None, None)))
            num = pd.to_numeric(decide, errors="coerce")
            for i, v in enumerate(num):
                if _is_missing(v) or t1 is None:
                    continue
                tier = 0 if v < t1 else (1 if v < t2 else 2)
                glyph, color = glyphs[tier]
                # in a lozenge the tier colour is the ground, not the ink
                deco = (Decoration(text=glyph, pill=color,
                                   color=readable_fg(color),
                                   where=_place(rule))
                        if rule.as_pill else
                        Decoration(text=glyph, color=color,
                                   where=_place(rule)))
                contrib[i] = CellStyle(decorations=[deco])

        elif rule.mode in ("icon_map", "color_map"):
            if not rule.source:
                # no source named = this column decides its own; the only
                # spelling that means anything under a pattern
                src = values
            elif (frame is not None
                    and rule.source in getattr(frame, "columns", [])):
                src = list(frame[rule.source])
            else:
                src = None
            mapping = rule.mapping or {}
            if src is not None:
                for i, v in enumerate(src):
                    if _is_missing(v):
                        continue
                    pair = mapping.get(str(v).strip())
                    if not pair or not pair[0]:
                        continue
                    first = pair[0]
                    second = pair[1] if len(pair) > 1 else None
                    if rule.mode == "icon_map":
                        # `pill` re-reads the mapped colour: it is the ink
                        # on a bare glyph, and the fill once the glyph is
                        # in a lozenge — there is no third colour in the
                        # map to be both.
                        if rule.as_pill and second:
                            deco = _mark(first, pill=second,
                                         color=readable_fg(second),
                                         where=_place(rule),
                                         size=rule.picture_size,
                                         shape=rule.picture_shape)
                        else:
                            deco = _mark(first, color=second,
                                         where=_place(rule),
                                         size=rule.picture_size,
                                         shape=rule.picture_shape)
                        contrib[i] = CellStyle(decorations=[deco])
                    elif rule.as_pill:
                        # a category pill: the mapped colour wraps the
                        # value rather than flooding the cell, which is
                        # what a status column wants and what T4 will
                        # write into once it can pick the colours itself
                        contrib[i] = CellStyle(
                            pill=first, pill_fg=second or readable_fg(first))
                    else:
                        contrib[i] = CellStyle(bg=first, fg=second)

        elif rule.mode == "image":
            # a column of pictures: this one's own values, or another
            # column's drawn beside this one's like an icon
            if not rule.source:
                pictures = values
            elif (frame is not None
                    and rule.source in getattr(frame, "columns", [])):
                pictures = list(frame[rule.source])
            else:
                pictures = None
            where = _picture_place(rule)
            for i, v in enumerate(pictures or ()):
                uri = _images.picture_uri(v)
                if uri is None:
                    continue      # not a picture: the cell shows what it has
                contrib[i] = CellStyle(
                    decorations=[Decoration(
                        image=uri, where=where, size=rule.picture_size,
                        tile=rule.picture_tile,
                        shape=(rule.picture_shape
                               or ("rounded" if rule.picture_tile
                                   else None)))],
                    # in place of the value, the base64 it was written as
                    # goes from the display — and from the width a column
                    # measures itself by
                    hide_value=where == "in")

        elif rule.mode == "tooltip":
            # the note is a whole other column's value, so there is nothing
            # to compute per cell — read it across and hand it over
            notes = (list(frame[rule.source])
                     if (frame is not None and rule.source
                         and rule.source in getattr(frame, "columns", []))
                     else None)
            if notes is not None:
                for i, note in enumerate(notes):
                    if _is_missing(note) or not str(note).strip():
                        continue        # a blank note is no note, not ""
                    contrib[i] = CellStyle(tooltip=str(note))

        elif rule.mode == "sparkline" and frame is not None:
            # A pattern never reads the column the spark is drawn in —
            # `sales_total spark from sales_*` means the months, not the
            # total beside them. `spark_projection` has usually resolved
            # the names already; this is for a caller that did not.
            own = getattr(series, "name", None)
            cols = series_columns(rule.series, frame,
                                  exclude=() if own is None else (str(own),))
            block = _numeric_block(frame, cols)
            if block is not None:
                low = high = None
                if rule.shared:
                    whole = _numeric_block(
                        pool_frame if pool_frame is not None else frame,
                        cols)
                    low, high = _extent(whole if whole is not None
                                        else block)
                alone = rule.hide_value or _place(rule) == "in"
                for i, row in enumerate(block.itertuples(index=False,
                                                         name=None)):
                    # number() is None for NaN, pd.NA and anything else that
                    # is not a finite number — a blank, drawn as a gap
                    numbers = [_spark.number(v) for v in row]
                    if sum(v is not None for v in numbers) < _spark.MIN_POINTS:
                        continue      # one point is not a trend
                    drawing = _spark.Spark(
                        values=numbers, kind=rule.spark_kind or "line",
                        color=rule.color, negative_color=rule.negative_color,
                        marks=[list(m) for m in rule.marks],
                        low=low, high=high,
                        ref=_spark.reference(rule.ref, numbers),
                        width=rule.spark_width, tall=rule.tall,
                        smooth=rule.smooth, thick=rule.thick)
                    contrib[i] = CellStyle(
                        decorations=[Decoration(where=_place(rule),
                                                spark=drawing)],
                        # a spark standing on its own has no number beside
                        # it, so resting on it says what it drew; one beside
                        # a value leaves that cell's tooltip to its own rules
                        tooltip=(_spark.summary(numbers, cols)
                                 if alone else None))

        elif rule.mode == "auto_color":
            # the same three spellings as a map: no source means this
            # column decides its own, which is the only one that means
            # anything under a pattern
            if not rule.source:
                src = values
            elif (frame is not None
                    and rule.source in getattr(frame, "columns", [])):
                src = list(frame[rule.source])
            else:
                src = None
            if src is not None:
                wheel = auto_colors(src, rule.palette)
                for i, v in enumerate(src):
                    color = wheel.get(str(v).strip()) if not _is_missing(v) else None
                    if not color:
                        continue
                    if rule.ink_only:
                        # a palette colour is built to be a ground, so as
                        # ink it has to clear the grid first
                        contrib[i] = CellStyle(fg=on_dark(color))
                    elif rule.as_pill:
                        contrib[i] = CellStyle(pill=color,
                                               pill_fg=readable_fg(color))
                    else:
                        contrib[i] = CellStyle(bg=color, fg=readable_fg(color))

        elif rule.mode == "number_format":
            for i, v in enumerate(values):
                text = _format_value(v, rule.number_spec or "")
                if text is not None:
                    contrib[i] = CellStyle(text=text)

        # `only` and a decoration placed `in` overlap but are not the same
        # thing: both take the value away, and only the second says where
        # the format goes instead. So `only` on its own moves the mark to
        # the middle — with nothing beside it, a left margin would read as
        # a stray mark — but `only right` is a rule that named its place
        # and keeps it.
        takes_the_place = rule.hide_value or _place(rule) == "in"
        placed = bool(rule.glyph_where)
        for i in range(n):
            if contrib[i] is not None:
                if takes_the_place:
                    contrib[i].hide_value = True
                    if not placed:
                        for d in contrib[i].decorations:
                            d.where = "in"
                acc[i] = contrib[i].over(acc[i])

    return acc


def _is_numeric_column(frame, position: int) -> bool:
    from pandas.api.types import is_bool_dtype, is_numeric_dtype
    column = frame.iloc[:, position]
    return is_numeric_dtype(column) and not is_bool_dtype(column)


def series_columns(entries, frame, exclude=()) -> list[str]:
    """The columns a spark reads, in the order it reads them.

    * a **name** is taken as it is, numeric or not — it was asked for;
    * a **pattern** takes the *numeric* columns it matches, in table order,
      leaving out anything in `exclude` (the column the spark is drawn in);
    * a ``first..last`` **range** takes the numeric columns between its two
      ends, both included, in table order — reversed when the first is to
      the right of the last, so ``dec..jan`` reads the way it is written.

    `frame` may be a plain list of names, when there are no dtypes to ask;
    then nothing is ruled out for not being a number.
    """
    columns = getattr(frame, "columns", None)
    names = [str(c) for c in (columns if columns is not None else frame or ())]
    first_at: dict = {}
    for i, name in enumerate(names):
        first_at.setdefault(name, i)
    skip = {str(e) for e in exclude}

    def numeric(name: str) -> bool:
        return columns is None or _is_numeric_column(frame, first_at[name])

    out: list[str] = []
    for entry in entries or ():
        entry = str(entry)
        if entry in first_at:
            out.append(entry)
        elif ".." in entry:
            start, _dots, end = entry.partition("..")
            start, end = _unquote(start.strip()), _unquote(end.strip())
            if start in first_at and end in first_at:
                a, b = first_at[start], first_at[end]
                span = names[a:b + 1] if a <= b else names[b:a + 1][::-1]
                out.extend(c for c in span if numeric(c))
        elif _is_glob(entry):
            out.extend(c for c in names if fnmatch.fnmatchcase(c, entry)
                       and c not in skip and numeric(c))
    return _dedup(out)


def _numeric_block(frame, names):
    """The named columns as floats, one row per table row — or None."""
    if frame is None or not names:
        return None
    import pandas as pd
    first_at: dict = {}
    for i, name in enumerate(str(c) for c in frame.columns):
        first_at.setdefault(name, i)
    positions = [first_at[n] for n in names if n in first_at]
    if not positions:
        return None
    import numpy as np
    # Plain float64 with NaN for a blank, whatever the column was. The Table
    # node types numbers `Float64` / `Int64`, whose blank is `pd.NA` — and
    # `float(pd.NA)` raises, which inside a card's data() crashed the app.
    arrays = [pd.to_numeric(frame.iloc[:, p], errors="coerce")
              .to_numpy(dtype="float64", na_value=np.nan) for p in positions]
    block = pd.DataFrame(np.column_stack(arrays), index=frame.index)
    block.columns = [str(frame.columns[p]) for p in positions]
    return block


def _extent(block) -> tuple:
    """(lowest, highest) number anywhere in `block`, or (None, None)."""
    stacked = block.stack() if len(block.columns) else block
    try:
        stacked = stacked.dropna()
    except Exception:
        pass
    if not len(stacked):
        return None, None
    return float(stacked.min()), float(stacked.max())


def spark_projection(frame, rules) -> tuple:
    """``(frame, rules, hidden)`` once every spark has been given its place.

    Three things a `spark` rule can do to a table that no other rule does,
    all worked out here, once, by both the card and the printed page:

    * **make a column.** A spark drawn in a column the table lacks gets
      one — display only, holding the row's latest number, so the column
      still sorts and copies as something. Its spark stands in it on its
      own (``in``) unless the rule named another place, in which case that
      latest number shows beside it.
    * **resolve what it reads.** Patterns and ranges become names, against
      the table as it arrived — so one spark's new column is never read by
      another's ``from *``.
    * **put its sources away.** ``hide`` hides them; ``replace`` hides them
      and puts the new column where the first of them stood.

    The frame that comes back is a shallow copy with the new columns on it
    (and the original when no spark adds one), which is a view like every
    other projection here: the table leaving the node's port is untouched.
    """
    rules = list(rules or [])
    # `name image from logo hide` puts its picture column away the same way
    # a spark puts its months away — read, drawn beside another, not shown
    picture_hidden = [str(r.source) for r in rules
                      if getattr(r, "mode", None) == "image"
                      and r.take_sources == "hide" and r.source]
    if (frame is None or not hasattr(frame, "columns")
            or not any(getattr(r, "mode", None) == "sparkline"
                       for r in rules)):
        return frame, rules, _dedup(picture_hidden)
    names = [str(c) for c in frame.columns]
    present = set(names)
    added: dict = {}             # new column -> (latest numbers, anchor)
    hidden: list[str] = list(picture_hidden)
    out: list = []
    for rule in rules:
        if rule.mode != "sparkline":
            out.append(rule)
            continue
        drawn = [str(c) for c in rule.columns]
        sources = series_columns(rule.series, frame, exclude=drawn)
        # a spark with nothing to read makes no column: an empty column
        # would look like a spark that failed to draw, where `style_report`
        # can say what is actually wrong
        fresh = [c for c in drawn if not _is_glob(c) and c not in present
                 and sources]
        existing = [c for c in drawn if c in present or _is_glob(c)]
        if rule.take_sources in ("hide", "replace"):
            hidden.extend(c for c in sources if c not in drawn)
        for name in fresh:
            if name in added:
                continue
            block = _numeric_block(frame, sources)
            latest = (block.ffill(axis=1).iloc[:, -1] if block is not None
                      else None)
            anchor = (sources[0] if rule.take_sources == "replace"
                      and sources else None)
            added[name] = (latest, anchor)
        if existing:
            out.append(dataclasses.replace(rule, columns=existing,
                                           series=list(sources)))
        if fresh:
            place = rule.glyph_where
            if place is None and not rule.hide_value:
                place = "in"
            out.append(dataclasses.replace(rule, columns=fresh,
                                           series=list(sources),
                                           glyph_where=place))
    if not added:
        return frame, out, _dedup(hidden)

    import pandas as pd
    shown = frame.copy(deep=False)
    order = list(range(len(names)))
    first_at: dict = {}
    for i, name in enumerate(names):
        first_at.setdefault(name, i)
    for name, (latest, anchor) in added.items():
        shown[name] = (latest.to_numpy() if latest is not None
                       else pd.Series([None] * len(frame), dtype="float64",
                                      index=frame.index).to_numpy())
        position = len(shown.columns) - 1
        if anchor is not None and first_at.get(anchor) in order:
            order.insert(order.index(first_at[anchor]), position)
        else:
            order.append(position)
    if order != list(range(len(shown.columns))):
        shown = shown.iloc[:, order]
    return shown, out, _dedup(hidden)


def evaluate_rows(df, row_rules) -> list:
    """One ``CellStyle | None`` per row position of `df`."""
    import pandas as pd

    n = len(df)
    acc: list = [None] * n
    names = list(df.columns)
    for rule in row_rules:
        # an `if <column>` clause names the tested column in `source`;
        # otherwise the condition is tested on the rule's own column(s),
        # which may be a glob.
        if rule.source:
            col = rule.source if rule.source in df.columns else None
        else:
            patterns = rule.columns or names
            col = next((c for c in names if column_matches(patterns, c)), None)
        if col is None:
            continue
        try:
            mask = _condition_mask(df[col], rule.op, rule.value)
        except Exception:
            continue
        style = CellStyle(bg=rule.bg,
                          fg=rule.fg or (readable_fg(rule.bg) if rule.bg else None),
                          bold=rule.bold, hide_value=rule.hide_value,
                          row_height=rule.row_height)
        for i, hit in enumerate(mask.tolist()):
            if hit:
                acc[i] = style.over(acc[i])
    return acc


def split_rules(rules) -> tuple:
    """(column rules, whole-row rules) — ``hide``/``show`` and the layout
    rules are neither: they shape the table rather than paint a cell."""
    row, col = [], []
    for r in rules:
        if r.mode in _LEADING_KEYWORDS or r.mode in LAYOUT_MODES:
            continue
        (row if r.mode == "highlight" and r.scope == "row" else col).append(r)
    return col, row


def wraps_text(rules) -> bool:
    """Does any rule ask for wrapped text? Table-wide by nature — see the
    `wrap` branch in the parser."""
    return any(getattr(r, "mode", None) == "wrap" for r in rules or [])


def row_height_of(rules) -> "int | None":
    """How tall a `height` line asks every row to be, in pixels, or None.
    Last one wins, like `sort`: there is one default row height."""
    found = None
    for rule in rules or []:
        if getattr(rule, "mode", None) == "row_height" and rule.row_height:
            found = int(rule.row_height)
    return found


def sort_order(rules) -> "tuple[str, bool] | None":
    """``(column name, ascending)`` the rules ask the table to open in, or
    None for "leave the rows as they arrived".

    Table-wide like `wrap`, and last-one-wins like everything else here: a
    table has one row order, so a second `sort` line replaces the first
    rather than being a tie-break.
    """
    found = None
    for rule in rules or []:
        if getattr(rule, "mode", None) == "sort" and rule.columns:
            found = (str(rule.columns[0]), rule.direction != "desc")
    return found


def column_layout(rules, columns) -> dict:
    """``{column name: ColumnLayout}`` for the columns any layout rule
    names — patterns expanded, later lines winning, and columns nobody
    mentioned left out entirely.

    Read once per table rather than per cell: width, alignment and the
    header label are properties of the column, and asking a rule about them
    a hundred thousand times would be a hundred thousand answers the same.
    """
    out: dict = {}
    for rule in rules or []:
        # `wrap` and `sort` are layout rules about the *table*, not about a
        # column, so they have no ColumnLayout entry to fill in
        if rule.mode not in LAYOUT_MODES or rule.mode in ("wrap", "sort",
                                                          "row_height"):
            continue
        for name in expand_columns(rule.columns, columns):
            entry = out.setdefault(name, ColumnLayout())
            if rule.mode == "column_width":
                entry.width = rule.width
            elif rule.mode == "align":
                entry.align = rule.align
            else:
                entry.label = rule.label
    return {name: entry for name, entry in out.items() if not entry.is_empty()}
