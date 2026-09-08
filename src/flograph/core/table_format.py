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
    revenue   sort desc                           # the order it opens in

``sort`` is table-wide for the same reason: there is one row order, so it
takes one column and a later `sort` line replaces an earlier one rather
than being a tie-break. It decides the order the table is *first shown*
in — on the card, in a dashboard tile and on a printed report, which is
where it matters most, since a page has no header to click. Clicking a
header still wins from then on.

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
          "sort", "color_map", "auto_color"}

#: The rules that shape the *table* rather than paint a cell. They are read
#: once into a `ColumnLayout` and never evaluated per row, so they cost
#: nothing on a big frame and are not what makes a style "active".
LAYOUT_MODES = {"column_width", "align", "header_label", "wrap", "sort"}

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

    def to_dict(self) -> dict:
        out = {"text": self.text}
        if self.color:
            out["color"] = self.color
        if self.pill:
            out["pill"] = self.pill
        if self.where != "left":
            out["where"] = self.where
        return out

    @classmethod
    def from_dict(cls, d: Any) -> "Decoration":
        if isinstance(d, (list, tuple)):        # the old (glyph, colour) pair
            glyph = d[0] if d else ""
            return cls(text=str(glyph or ""),
                       color=d[1] if len(d) > 1 else None)
        d = d or {}
        return cls(text=str(d.get("text") or ""), color=d.get("color"),
                   pill=d.get("pill"),
                   where=d.get("where") or "left")


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
                and self.pill is None
                and self.text is None and not self.hide_value)


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
        d, pill=pill, color=_pill_ink_for_paper(d.color, pill))


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
    """The concrete column names `patterns` selects, in `columns` order and
    de-duplicated. A plain name is kept even when absent (so a caller can
    still flag it missing); a glob contributes only the names it matches."""
    cols = [str(c) for c in columns]
    out: list[str] = []
    for p in patterns or ():
        p = str(p)
        if _is_glob(p):
            out.extend(c for c in cols if fnmatch.fnmatchcase(c, p))
        else:
            out.append(p)
    return _dedup(out)


def quote_column(name: str) -> str:
    """Wrap a column name in quotes for the DSL when it would otherwise be
    ambiguous — a space, a comma, or a bare keyword."""
    name = str(name)
    if (any(ch in name for ch in ', "\'')
            or name.lower() in _KEYWORDS or name.lower() == "hide"):
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

_KEYWORDS = ("scale", "bar", "icons", "icon", "iconmap", "colormap",
             "colourmap", "format", "width", "align", "label", "sort"
             ) + _AUTO_KEYWORDS

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


def _parse_token_line(lineno: int, line: str) -> Rule:
    tokens = line.split()

    if tokens and tokens[0].lower() == "hide":
        cols = _column_list(" ".join(tokens[1:]))
        if not cols:
            raise ValueError(f"line {lineno}: 'hide' needs a column name")
        return Rule("hide", cols)

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
            f"colormap|format …', 'hide column', or 'condition => style', "
            f"got {line!r}")
    columns = _column_list(" ".join(tokens[:kw_idx]))
    keyword = _keyword_of(tokens[kw_idx])
    arg = " ".join(tokens[kw_idx + 1:]).strip()
    if tokens[kw_idx].endswith(":"):
        # give the map parser back the colon the split took off it, so an
        # absent source still reads as absent rather than as missing
        arg = ":" + arg

    if keyword in ("iconmap", "colormap", "colourmap"):
        # here the `only` comes off the whole argument: the mapping body is
        # split on commas, and a trailing one left in place would be read
        # as the last pair's colour
        arg, only = _split_only(arg)
        arg, place = _split_place(arg)
        arg, pill = _split_pill(arg)
        keyword = "iconmap" if keyword == "iconmap" else "colormap"
        source, mapping = _parse_value_map(lineno, arg, keyword)
        mode = "icon_map" if keyword == "iconmap" else "color_map"
        return Rule(mode, columns, source=source, mapping=mapping,
                    hide_value=only, glyph_where=place, as_pill=pill)
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
                f"'pill <colour> [\"text\"]', 'only')")
    if ("bg" not in out and "fg" not in out and "glyph" not in out
            and not out.get("bold") and not out.get("hide_value")
            and not out.get("as_pill")):
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
                        hide_value=bool(style.get("hide_value")))
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
                hide_value=bool(style.get("hide_value")))


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
        if rule.glyph:
            test = f"{rule.source} " if rule.source else ""
            return (f"{cols}  ·  {rule.glyph} when {test}"
                    f"{_op_phrase(rule.op, rule.value)}" if rule.source else
                    f"{cols} {_op_phrase(rule.op, rule.value)}  ·  "
                    f"{rule.glyph}{potted}{place}")
        test = f"{rule.source} " if rule.source else ""
        return (f"{cols}  ·  highlight the {where} when {test}"
                f"{_op_phrase(rule.op, rule.value)}" if rule.source else
                f"{cols} {_op_phrase(rule.op, rule.value)}  ·  "
                f"highlight the {where}")
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
    if rule.mode == "hide":
        return f"hide  {cols}"
    if rule.mode == "column_width":
        return (f"{cols}  ·  width {rule.width}px" if rule.width
                else f"{cols}  ·  width fits the content")
    if rule.mode == "align":
        return f"{cols}  ·  aligned {rule.align}"
    if rule.mode == "header_label":
        return f"{cols}  ·  headed “{rule.label}”"
    if rule.mode == "wrap":
        return "wrap text  ·  rows grow to fit"
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
    """Turn a node's params — a ``format_rules`` text box and an optional
    ``hide`` column list — into the payload carried on a ``style`` port.

    Never raises: a bad rule line is dropped and its message collected, to
    be reported wherever the style is *applied* (Show Table), not typed.
    """
    rules, errors = parse_rules_lenient(params.get("format_rules", ""))
    hide = [c for r in rules if r.mode == "hide" for c in r.columns]
    hide += _column_list(params.get("hide"))
    keep = [r for r in rules if r.mode != "hide"]
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
    return {"rules": [r.to_dict() for r in keep], "hide": _dedup(hide),
            "errors": errors}


def _style_parts(style_obj: Any) -> tuple:
    if isinstance(style_obj, dict):
        return (list(style_obj.get("rules") or []),
                list(style_obj.get("hide") or []),
                list(style_obj.get("errors") or []))
    if isinstance(style_obj, (list, tuple)):
        return (list(style_obj), [], [])
    return ([], [], [])


def merge_styles(base: Any, extra: Any) -> dict:
    """`extra` laid on top of `base`: rules concatenated (so a later rule
    wins), hide lists unioned, errors kept from both. Either side may be a
    payload dict, a bare rule list, or ``None``."""
    b_rules, b_hide, b_err = _style_parts(base)
    e_rules, e_hide, e_err = _style_parts(extra)
    return {"rules": b_rules + e_rules, "hide": _dedup(b_hide + e_hide),
            "errors": b_err + e_err}


def hidden_columns(style_obj: Any) -> list[str]:
    """Columns the style asks Show Table to keep out of view — helper
    columns a rule reads but the reader shouldn't see."""
    if isinstance(style_obj, dict):
        return [str(c) for c in (style_obj.get("hide") or [])]
    return []


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
        entries = [c for rule in rules_from_style(style_obj) for c in rule.columns]
        entries += [r.source for r in rules_from_style(style_obj) if r.source]
        entries += hidden_columns(style_obj)
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
        deco = ([Decoration(text=rule.glyph, color=rule.glyph_color,
                            where=place)] if rule.glyph else [])
        return CellStyle(
            bg=rule.bg,
            fg=rule.fg or (readable_fg(rule.bg) if rule.bg else None),
            bold=rule.bold, decorations=deco)

    fill = rule.bg or _FILL_PRESETS["blue"]
    ink = rule.fg or readable_fg(fill)
    if rule.glyph:
        # a pill with something written in it stands beside the value
        return CellStyle(bold=rule.bold, decorations=[Decoration(
            text=rule.glyph, color=rule.glyph_color or ink, pill=fill,
            where=place)])
    # a pill with nothing written in it wraps what is already there
    return CellStyle(bold=rule.bold, pill=fill, pill_fg=ink)


def evaluate_column(series, rules, stats: ColumnStats, frame=None) -> list:
    """One ``CellStyle | None`` per row of `series`, in its current order.

    `frame` is the whole (current-order) DataFrame — needed only by a rule
    that reads a *different* column than the one it draws in: ``iconmap``,
    and any ``scale`` / ``bar`` / ``icons`` / ``highlight`` rule carrying a
    ``by`` / ``if`` clause (its deciding column is ``rule.source``).
    """
    import pandas as pd

    n = len(series)
    acc: list = [None] * n
    values = list(series)

    def _decide(rule) -> tuple:
        """The series whose values drive `rule`, and stats for it — the
        drawn column, unless a ``by`` / ``if`` clause named another one."""
        if (rule.source and frame is not None
                and rule.source in getattr(frame, "columns", [])):
            other = frame[rule.source]
            return other, column_stats(other)
        return series, stats

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
                            deco = Decoration(text=first, pill=second,
                                              color=readable_fg(second),
                                              where=_place(rule))
                        else:
                            deco = Decoration(text=first, color=second,
                                              where=_place(rule))
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
                          bold=rule.bold, hide_value=rule.hide_value)
        for i, hit in enumerate(mask.tolist()):
            if hit:
                acc[i] = style.over(acc[i])
    return acc


def split_rules(rules) -> tuple:
    """(column rules, whole-row rules) — ``hide`` and the layout rules are
    neither: they shape the table rather than paint a cell."""
    row, col = [], []
    for r in rules:
        if r.mode == "hide" or r.mode in LAYOUT_MODES:
            continue
        (row if r.mode == "highlight" and r.scope == "row" else col).append(r)
    return col, row


def wraps_text(rules) -> bool:
    """Does any rule ask for wrapped text? Table-wide by nature — see the
    `wrap` branch in the parser."""
    return any(getattr(r, "mode", None) == "wrap" for r in rules or [])


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
        if rule.mode not in LAYOUT_MODES or rule.mode in ("wrap", "sort"):
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
