"""Drawing a chart with nothing but arithmetic and a string of SVG.

The visuals built on a web library (Sankey, Circle Pack, the calendar
heatmap) hand a page some JSON and let JavaScript work out where things go.
That is the right trade when the layout is genuinely hard — nobody should
re-derive a force simulation — but it costs a library install, a canvas that
will not print, and a page whose own size it cannot measure inside a report.

These charts take the other road. Python works out every coordinate and
emits finished `<svg>` markup, so the page has nothing left to compute: no
library, no canvas, nothing animating, nothing to measure. It draws the same
on the card, in a dashboard tile, printed into a report, and opened in
somebody else's browser with the app nowhere in sight.

What lives here is the part worth testing on its own — colour arithmetic,
splitting a hundred squares between six categories so they still come to a
hundred, ranking a series within each period, running a smooth line through
a set of points. Qt-free and pandas-free, like the rest of `core`.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional, Sequence

#: Coordinates are rounded to this many decimals on the way into markup.
#: Nothing in a drawing means anything past a hundredth of a unit, and full
#: float repr triples the size of a page in exchange for that nothing.
PRECISION = 2

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def num(value: float) -> str:
    """A number as SVG writes it: rounded, and never `1.0` where `1` will do."""
    rounded = round(float(value) + 0.0, PRECISION)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:g}"


def rgb(colour: str) -> tuple[int, int, int]:
    """`#rgb` or `#rrggbb` to three 0-255 channels."""
    text = str(colour or "").strip()
    if not _HEX.match(text):
        raise ValueError(f"not a hex colour: {colour!r}")
    body = text[1:]
    if len(body) == 3:
        body = "".join(c * 2 for c in body)
    return (int(body[0:2], 16), int(body[2:4], 16), int(body[4:6], 16))


def hexed(channels: Iterable[float]) -> str:
    """Three channels back to `#rrggbb`, clamped."""
    return "#" + "".join(f"{max(0, min(255, int(round(c)))):02x}"
                         for c in channels)


def mix(start: str, end: str, position: float) -> str:
    """A colour `position` of the way from `start` to `end` (0-1)."""
    t = max(0.0, min(1.0, float(position)))
    a, b = rgb(start), rgb(end)
    return hexed(a[i] + (b[i] - a[i]) * t for i in range(3))


def ramp(stops: Sequence[str], position: float) -> str:
    """A colour off a multi-stop ramp. One stop is that colour, flat."""
    colours = [c for c in stops if c]
    if not colours:
        raise ValueError("a colour ramp needs at least one colour")
    if len(colours) == 1:
        return colours[0]
    t = max(0.0, min(1.0, float(position)))
    span = t * (len(colours) - 1)
    lower = min(int(span), len(colours) - 2)
    return mix(colours[lower], colours[lower + 1], span - lower)


def luminance(colour: str) -> float:
    """Perceived brightness, 0 (black) to 1 (white)."""
    r, g, b = (channel / 255.0 for channel in rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def readable_on(colour: str, dark: str = "#0b1220",
                light: str = "#ffffff") -> str:
    """Which of two inks to write on a given fill.

    The threshold sits high on purpose: a mid-tone reads better with dark
    text than light, and a label that is merely legible is not good enough
    when it is sitting on top of the number it describes.
    """
    return dark if luminance(colour) > 0.55 else light


def fade(colour: str, amount: float, towards: str = "#000000") -> str:
    """Pull a colour part of the way towards another — how a tile that was
    not the one clicked steps back without disappearing."""
    return mix(colour, towards, amount)


def cycle(palette: Sequence[str], index: int) -> str:
    """The palette colour for the nth series, wrapping round."""
    colours = [c for c in palette if c]
    if not colours:
        raise ValueError("empty palette")
    return colours[index % len(colours)]


#: How far a colour is shifted each time the palette has been used up.
#: Alternating lighter, darker, lighter keeps neighbouring laps apart.
_LAP_SHIFT = ((0.0, "#ffffff"), (0.42, "#ffffff"), (0.34, "#000000"),
              (0.62, "#ffffff"), (0.52, "#000000"))


def series_colours(names: Sequence[str],
                   palette: Sequence[str]) -> dict[str, str]:
    """One colour per distinct name, in first-seen order.

    First-seen rather than sorted, so a series keeps the colour it had when
    a filter upstream removes some *other* series and everything below it
    would otherwise shuffle up a shade.

    Past the end of the palette the colours are **shaded** rather than
    simply repeated. Twelve regions against eight colours would otherwise
    give London and Scotland the same indigo, and a chart where two things
    share a colour is not a chart — you cannot tell which squares are
    whose, and the legend cannot help you.
    """
    colours = [c for c in palette if c]
    if not colours:
        raise ValueError("empty palette")
    out: dict[str, str] = {}
    for name in names:
        if name in out:
            continue
        index = len(out)
        lap, step = divmod(index, len(colours))
        amount, towards = _LAP_SHIFT[min(lap, len(_LAP_SHIFT) - 1)]
        base = colours[step]
        out[name] = mix(base, towards, amount) if amount else base
    return out


def allocate(values: Sequence[float], cells: int) -> list[int]:
    """Split `cells` between `values` in proportion, losing none of them.

    Rounding each share on its own leaves a waffle of 97 or 103 squares,
    which is the one thing a waffle may not do — being countable is the
    whole point of it. So this rounds every share down and hands the
    remainder out largest-fraction-first.

    A category with any value at all also gets at least one square, even
    where its share rounds to nothing: "too small to see" and "not there"
    have to look different.
    """
    total_cells = max(0, int(cells))
    numbers = [max(0.0, float(v or 0)) for v in values]
    total = sum(numbers)
    if total <= 0 or total_cells == 0:
        return [0] * len(numbers)

    exact = [n / total * total_cells for n in numbers]
    counts = [int(share) for share in exact]

    # Largest remaining fraction gets the next spare square, which is the
    # standard apportionment and the only split that stays stable when one
    # value moves a little.
    order = sorted(range(len(numbers)),
                   key=lambda i: (-(exact[i] - int(exact[i])), i))
    handed_out = 0
    while sum(counts) < total_cells and order:
        counts[order[handed_out % len(order)]] += 1
        handed_out += 1

    # Then the minimum-one guarantee, paid for out of the largest holding
    # rather than out of the total — one square off a category that has
    # ninety-nine is invisible, and a category shown as nothing is not.
    starved = [i for i, n in enumerate(numbers) if n > 0 and counts[i] == 0]
    for index in starved:
        donor = max(range(len(counts)), key=lambda i: (counts[i], -i))
        if counts[donor] <= 1:
            break                    # more categories than squares: give up
        counts[donor] -= 1
        counts[index] = 1
    return counts


def to_number(value: Any) -> Optional[float]:
    """A float if the value is one, else None. Blanks and text are None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number          # NaN


def text_of(value: Any) -> str:
    """A cell as a label: trimmed, and empty when there is nothing there.

    `str(value)` is not good enough. A blank in a text column arrives from
    pandas as a float `nan`, and `str(nan)` is `"nan"` — which draws as a
    category, a series or a place called "nan", sitting on the chart
    looking like data.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value != value:          # NaN
        return ""
    return str(value).strip()


def rank_within(rows: Sequence[dict], *, group: str, value: str,
                highest_first: bool = True) -> dict[int, int]:
    """Rank each row against the others in its group; 1 is the top.

    Keyed by the row's position in `rows`, so the caller keeps whatever else
    it had on the row. Ties share a rank. A row with no number is left out
    altogether rather than ranked last — a series that did not report this
    month has no rank, and drawing it at the bottom would be a lie.
    """
    ranks: dict[int, int] = {}
    groups: dict[Any, list[int]] = {}
    for index, row in enumerate(rows):
        if to_number(row.get(value)) is None:
            continue
        groups.setdefault(row.get(group), []).append(index)

    for members in groups.values():
        members.sort(key=lambda i: to_number(rows[i][value]),
                     reverse=highest_first)
        place = 0
        previous = None
        for position, index in enumerate(members, 1):
            number = to_number(rows[index][value])
            if number != previous:
                place = position
                previous = number
            ranks[index] = place
    return ranks


def extent(values: Iterable[Any]) -> tuple[float, float]:
    """The low and high of whatever numbers are in there; (0, 0) if none."""
    numbers = [n for n in (to_number(v) for v in values) if n is not None]
    if not numbers:
        return (0.0, 0.0)
    return (min(numbers), max(numbers))


def position(value: float, low: float, high: float) -> float:
    """Where a value sits between two bounds, 0-1.

    A flat range is 0.5, not 0: every value the same means every tile the
    same shade, not every tile at the empty end of the ramp.
    """
    if high == low:
        return 0.5
    return max(0.0, min(1.0, (float(value) - low) / (high - low)))


def smooth_path(points: Sequence[tuple[float, float]],
                tension: float = 0.5) -> str:
    """A path through every point, curved rather than kinked.

    Cubic segments with control points along the neighbours' direction — the
    usual Catmull-Rom-to-Bezier conversion. `tension` 0 gives straight
    lines; past about 0.8 it starts to overshoot, which on a bump chart
    reads as a series briefly holding a place it never held.
    """
    pts = [(float(x), float(y)) for x, y in points]
    if not pts:
        return ""
    if len(pts) == 1:
        return f"M {num(pts[0][0])} {num(pts[0][1])}"
    if tension <= 0:
        return "M " + " L ".join(f"{num(x)} {num(y)}" for x, y in pts)

    k = max(0.0, min(1.0, float(tension))) / 3.0
    out = [f"M {num(pts[0][0])} {num(pts[0][1])}"]
    for i in range(len(pts) - 1):
        before = pts[i - 1] if i else pts[0]
        start, end = pts[i], pts[i + 1]
        after = pts[i + 2] if i + 2 < len(pts) else end
        c1 = (start[0] + (end[0] - before[0]) * k,
              start[1] + (end[1] - before[1]) * k)
        c2 = (end[0] - (after[0] - start[0]) * k,
              end[1] - (after[1] - start[1]) * k)
        out.append(f"C {num(c1[0])} {num(c1[1])}, {num(c2[0])} {num(c2[1])}, "
                   f"{num(end[0])} {num(end[1])}")
    return " ".join(out)


def spread(targets: Sequence[float], gap: float, low: float,
           high: float) -> list[float]:
    """Nudge labels apart until none overlaps, keeping their order.

    Returned in the same order as `targets`. Each label wants to sit at its
    own value; where two want the same place, the pair is separated by at
    least `gap` and the whole run is kept inside `low`-`high`.

    This is the difference between a slope graph and an unreadable smear:
    the two things that changed least are exactly the two whose labels
    collide, and they are usually the ones being pointed at.
    """
    if not targets:
        return []
    span = high - low
    order = sorted(range(len(targets)), key=lambda i: (targets[i], i))
    needed = gap * (len(targets) - 1)
    if needed > span > 0:
        # More labels than room: share the space out evenly and accept that
        # they touch. Better than a stack that runs off the bottom.
        gap = span / (len(targets) - 1)

    placed: list[float] = []
    for position, index in enumerate(order):
        want = min(max(float(targets[index]), low), high)
        placed.append(want if not placed else max(want, placed[-1] + gap))

    overflow = placed[-1] - high
    if overflow > 0:
        placed = [y - overflow for y in placed]
        # Pushing the run up can drive the top out of the box, so walk back
        # down enforcing the gap from the top edge this time.
        for position in range(len(placed)):
            floor = low if position == 0 else placed[position - 1] + gap
            placed[position] = max(placed[position], floor)

    out = [0.0] * len(targets)
    for position, index in enumerate(order):
        out[index] = placed[position]
    return out


def shorten(text: str, room: int) -> str:
    """A label cut to fit, with an ellipsis to admit that it was cut."""
    body = str(text)
    if room <= 0:
        return ""
    if len(body) <= room:
        return body
    return body[:max(1, room - 1)].rstrip() + "…"


#: An average glyph's width as a fraction of the font size. Rough by
#: nature — the page picks its own font and this cannot measure it — but a
#: rough number beats the alternative, which is a fixed gutter that fits
#: "Wales" and cuts "Yorkshire and The Humber" in half.
GLYPH = 0.53


def text_width(text: Any, size: float) -> float:
    """Roughly how wide a label will draw, in the drawing's own units."""
    return len(str(text)) * float(size) * GLYPH


def fit(text: Any, room: float, size: float) -> str:
    """A label shortened to what will actually fit in `room` units."""
    return shorten(str(text), int(room / (float(size) * GLYPH)))


def gutter(labels: Sequence[Any], size: float, *, pad: float = 28.0,
           low: float = 120.0, high: float = 300.0) -> float:
    """How much edge room a set of labels wants, within reason.

    Short names give the drawing back the space they do not need; long ones
    are allowed up to `high` and then ellipsised, so one unusually long name
    cannot squeeze the chart itself down to a sliver.
    """
    if not labels:
        return low
    wanted = max(text_width(label, size) for label in labels) + pad
    return min(high, max(low, wanted))


def svg_open(width: float, height: float, *, extra: str = "") -> str:
    """The opening tag: a viewBox and no fixed size, so CSS decides how big
    the drawing is and it scales to whatever box it lands in."""
    return (f"<svg xmlns='http://www.w3.org/2000/svg' "
            f"viewBox='0 0 {num(width)} {num(height)}' "
            f"preserveAspectRatio='xMidYMid meet' role='img'"
            + (" " + extra if extra else "") + ">")


# --- the page these charts are served in ---------------------------------
#
# One shell for all four, so a waffle and a bump chart dropped on the same
# dashboard are recognisably the same family: same heading, same legend,
# same behaviour under a click. Each node supplies only its drawing.

#: Every rule the shell needs.
#:
#: The height chain starts at `100vh` and that choice is load-bearing.
#: A report takes its picture through print-to-PDF in a view that is never
#: shown, and inside that page **`%` heights collapse to nothing** — there
#: is no viewport for them to resolve against, which is the same hole that
#: makes JavaScript measurement impossible there. Measured 2026-09-06:
#: `height:25%` renders as content-height, while `height:25vh` renders as
#: exactly a quarter of the page box, and `50vw` as half its width. So
#: viewport *units* do work where viewport *measurement* does not, because
#: in print media the initial containing block is the page itself.
#:
#: One `vh` anchor therefore gives `.chart` a definite height on a card, in
#: a dashboard tile and on paper alike — and every percentage below it
#: resolves against that. Without it the drawing is an unbreakable block
#: taller than the page, and Chromium moves the whole thing to page two,
#: which a report renders as a heading with nothing under it.
#:
#: `display:block` on the SVG is not a nicety either — an inline SVG keeps
#: text-baseline descender space beneath it, which overflows the card and
#: leaves a permanent scrollbar stealing ~15px of width.
CHART_CSS = """
.chart{display:flex;flex-direction:column;gap:calc(var(--gap) * 0.6);
  box-sizing:border-box;height:calc(100vh - var(--pad) * 2)}
.chart-head{display:flex;flex-direction:column;gap:2px;flex:0 0 auto}
.chart-body{flex:1 1 auto;min-height:0;display:flex;
  align-items:center;justify-content:center}
.chart-body > svg{display:block;width:100%;height:auto;max-height:100%}
.legend{display:flex;flex-wrap:wrap;gap:4px calc(var(--gap) * 0.9);
  flex:0 0 auto;align-items:center;font-size:calc(var(--size) * 0.86)}
.key{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.key i{width:11px;height:11px;border-radius:3px;flex:0 0 auto;
  display:inline-block}
.key.off{opacity:0.45}
.ramp{width:120px;height:11px;border-radius:3px;display:inline-block}
.key .n{color:var(--muted);font-variant-numeric:tabular-nums}
.hit{cursor:pointer}
.note{color:var(--muted);font-size:calc(var(--size) * 0.86)}
"""

#: Clicking. Identical in spirit to HTML Template's, and guarded the same
#: way: the page is meant to survive being saved out and opened somewhere
#: with no flograph behind it, where a click does nothing rather than
#: throwing into an empty console.
CLICK_JS = """
<script>
var PICKED = /*PICKED*/;
var MODE = /*MODE*/;
function pick(name) {
  if (MODE === "nothing") { return; }
  if (MODE === "select many") {
    var at = PICKED.indexOf(name);
    if (at === -1) { PICKED.push(name); } else { PICKED.splice(at, 1); }
  } else {
    PICKED = (PICKED.length === 1 && PICKED[0] === name) ? [] : [name];
  }
  if (window.flograph && flograph.select) { flograph.select(PICKED); }
}
</script>
"""


def click_script(picked: Sequence[str], mode: str) -> str:
    """The click handler, with this run's selection baked in."""
    import json

    return (CLICK_JS.replace("/*PICKED*/", json.dumps(list(picked)))
            .replace("/*MODE*/", json.dumps(str(mode))))


def click_attr(name: str, mode: str) -> str:
    """The `onclick` for one shape, or nothing at all when clicking is off.

    The `hit` class is *not* in here: most of these shapes already carry a
    class, and two `class` attributes on one tag means the browser keeps the
    first and silently drops the second. Ask for it with `hit_class`.
    """
    import json

    if mode == "nothing":
        return ""
    return f' onclick="pick({escape(json.dumps(str(name)))})"'


def hit_class(mode: str) -> str:
    """`" hit"` when a click does something, to append to a class list."""
    return "" if mode == "nothing" else " hit"


def escape(text: Any) -> str:
    """Escape a value on its way into markup. Same rules as everywhere else
    — imported from `visual_style` so there is one of these, not two."""
    from flograph.core.visual_style import escape as _escape

    return _escape(text)


def legend(entries: Sequence[tuple[str, str, str]], mode: str = "nothing",
           picked: Sequence[str] = ()) -> str:
    """A row of keys: `(name, colour, note)` each.

    Clickable when clicking is on, because a legend is where people expect
    to be able to switch a series off, and the picked ones stay lit while
    the rest dim — the same language the tiles themselves speak.
    """
    if not entries:
        return ""
    chosen = set(picked or ())
    keys = []
    for name, colour, note in entries:
        dim = " off" if chosen and name not in chosen else ""
        tail = f" <span class='n'>{escape(note)}</span>" if note else ""
        keys.append(f"<span class='key{dim}{hit_class(mode)}'"
                    f"{click_attr(name, mode)}>"
                    f"<i style='background:{escape(colour)}'></i>"
                    f"{escape(name)}{tail}</span>")
    return "<div class='legend'>" + "".join(keys) + "</div>"


def ramp_legend(stops: Sequence[str], low: str, high: str,
                middle: str = "") -> str:
    """A key for a continuous scale: a gradient bar with its ends labelled.

    Built from the same stops the tiles are coloured from, so the bar can
    never drift out of step with the drawing it explains.
    """
    colours = [c for c in stops if c]
    if not colours:
        return ""
    if len(colours) == 1:
        colours = colours * 2
    band = ", ".join(colours)
    label = f"<span class='n'>{escape(middle)}</span>" if middle else ""
    return ("<div class='legend'><span class='key'>"
            f"<span class='n'>{escape(low)}</span>"
            f"<span class='ramp' style='background:linear-gradient("
            f"to right, {band})'></span>"
            f"<span class='n'>{escape(high)}</span>{label}</span></div>")


def chart_page(drawing: str, tok: dict, *, title: str = "", subtitle: str = "",
               legend_html: str = "", note: str = "", mode: str = "nothing",
               picked: Sequence[str] = (), extra_css: str = "") -> str:
    """Wrap a drawing in the shared shell and return a whole page."""
    from flograph.core.visual_style import page

    head = ""
    if title:
        head += f"<div class='title'>{escape(title)}</div>"
    if subtitle:
        head += f"<div class='subtitle'>{escape(subtitle)}</div>"
    if head:
        head = f"<div class='chart-head'>{head}</div>"

    body = (f"<div class='chart'>{head}"
            f"<div class='chart-body'>{drawing}</div>"
            f"{legend_html}"
            + (f"<div class='note'>{escape(note)}</div>" if note else "")
            + "</div>")
    if mode != "nothing":
        body += click_script(picked, mode)
    return page(body, tok, title=title,
                extra_css=CHART_CSS + (("\n" + extra_css) if extra_css else ""))
