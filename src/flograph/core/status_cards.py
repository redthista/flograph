"""The small status cards a dashboard is read by: a number and how it is
doing, a lamp, a headline, a tray of alerts, an as-of line.

Qt-free on purpose. Each card's node works out its numbers and hands this
module the parts; this module writes the whole page — self-contained HTML
with inline SVG, no script fetched and no font linked — so a card looks the
same on the canvas, in a dashboard tile, printed into a report and opened in
a browser with the app closed. Colours, type and corners come from the
Visual Style tokens (`visual_style.tokens`), so a page of these re-themes
with the charts beside it.

**Good, bad, watch.** A status card speaks in three tones and nothing else.
They are fixed colours rather than palette entries, because a palette is
for telling series apart and these must mean the same thing on every card
of every page: green is fine, amber is look at it, red is act.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

TONES = {"good": "#10b981", "watch": "#f59e0b", "bad": "#ef4444",
         "neutral": ""}

#: What a card adds to the Visual Style sheet. Sizes scale with the card
#: (`vmin`), so a tile dragged bigger gets a bigger number, not more air.
CARD_CSS = """
html, body { height: 100%; margin: 0; padding: 0 !important; }
body { display: flex; }
.card { flex: 1; display: flex; flex-direction: column; justify-content: center;
  gap: .35em; padding: var(--pad); box-sizing: border-box;
  min-width: 0; overflow: hidden; }
.label { color: var(--muted); font-size: max(11px, 5.5vmin);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.big { font-size: max(20px, 17vmin); font-weight: 700; line-height: 1.05;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sub { font-size: max(11px, 6vmin); white-space: nowrap; }
.muted { color: var(--muted); }
.spark { width: 100%; height: 26%; min-height: 24px; }
.spark svg { width: 100%; height: 100%; display: block; overflow: visible; }
.track { height: max(6px, 4.5vmin); flex: none; }
"""


def tone_colour(tone: str, tok: dict) -> str:
    """The ink for a tone; *neutral* is the theme's own text colour."""
    return TONES.get(tone) or tok.get("fg", "#e2e8f0")


def judge(change: Optional[float], higher_is_better: bool = True,
          flat_band: float = 0.0) -> str:
    """`good` / `bad` / `neutral` for a change, read in the direction that
    counts as better. A change inside ±`flat_band` is neutral."""
    if change is None or change != change:
        return "neutral"
    if abs(change) <= flat_band:
        return "neutral"
    up = change > 0
    return "good" if up == bool(higher_is_better) else "bad"


def lamp_tone(value: Optional[float], amber: Optional[float],
              red: Optional[float], higher_is_worse: bool = True) -> str:
    """Green / amber / red for `value` against two breakpoints. With
    `higher_is_worse` (debt, days overdue) at or past `red` is red; the
    other way round (cash runway, uptime) at or below `red` is."""
    if value is None or value != value:
        return "neutral"
    if higher_is_worse:
        if red is not None and value >= red:
            return "bad"
        if amber is not None and value >= amber:
            return "watch"
    else:
        if red is not None and value <= red:
            return "bad"
        if amber is not None and value <= amber:
            return "watch"
    return "good"


def to_float(value: Any) -> Optional[float]:
    """A number out of whatever arrived — a scalar, a one-cell table, a
    one-value Series, numeric text — or None."""
    from flograph.core.svgplot import to_number

    try:
        import pandas as pd
    except ImportError:            # pragma: no cover - pandas ships with us
        pd = None
    if pd is not None:
        if isinstance(value, pd.DataFrame):
            if value.size != 1:
                raise ValueError(
                    f"expected a single number, got a table of "
                    f"{value.shape[0]} × {value.shape[1]} — reduce it first "
                    "(a Card's value, or Group By)")
            value = value.iat[0, 0]
        elif isinstance(value, pd.Series):
            if len(value) != 1:
                raise ValueError(
                    f"expected a single number, got {len(value)} values — "
                    "reduce them first")
            value = value.iat[0]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (ValueError, TypeError):
            pass
    number = to_number(value)
    # 85 stays 85 on the card, not "85.0", when no format is set
    if number is not None and number == number and float(number).is_integer() \
            and abs(number) < 2 ** 53:
        return int(number)
    return number


def arrow(tone_or_change) -> str:
    if isinstance(tone_or_change, (int, float)):
        if tone_or_change > 0:
            return "▲"
        if tone_or_change < 0:
            return "▼"
    return "▬"


def spark_svg(values: Sequence[float], colour: str, *, area: bool = True,
              mark_last: bool = True) -> str:
    """A sparkline drawn to fill its box (`preserveAspectRatio=none`), so
    the card decides its size; the stroke keeps its width when stretched."""
    from flograph.core.svgplot import escape, num

    points = [float(v) for v in values if v is not None and v == v]
    if len(points) < 2:
        return ""
    lo, hi = min(points), max(points)
    span = (hi - lo) or 1.0
    w, h = 100.0, 30.0
    step = w / (len(points) - 1)
    xy = [(i * step, h - (v - lo) / span * (h - 4) - 2)
          for i, v in enumerate(points)]
    line = " ".join(f"{'M' if i == 0 else 'L'}{num(x)} {num(y)}"
                    for i, (x, y) in enumerate(xy))
    out = [f"<svg viewBox='0 0 {num(w)} {num(h)}' "
           f"preserveAspectRatio='none' role='img' "
           f"aria-label='{escape(f'trend of {len(points)} values')}'>"]
    if area:
        out.append(f"<path d='{line} L{num(w)} {num(h)} L0 {num(h)} Z' "
                   f"fill='{colour}' fill-opacity='0.16' stroke='none'/>")
    out.append(f"<path d='{line}' fill='none' stroke='{colour}' "
               f"stroke-width='2' vector-effect='non-scaling-stroke' "
               f"stroke-linejoin='round' stroke-linecap='round'/>")
    if mark_last:
        x, y = xy[-1]
        out.append(f"<circle cx='{num(x)}' cy='{num(y)}' r='2.4' "
                   f"fill='{colour}'/>")
    out.append("</svg>")
    return "".join(out)


def page(body: str, style: Any = None, *, title: str = "",
         extra_css: str = "") -> tuple[str, dict]:
    """(whole page, the resolved style payload) for a card's markup."""
    from flograph.core import visual_style

    merged = visual_style.merge_styles(
        style if visual_style.is_style(style) else None, None)
    tok = visual_style.tokens(merged)
    html = visual_style.page(body, tok, title=title,
                             extra_css=CARD_CSS + "\n" + extra_css)
    return html, merged


def tokens(style: Any = None) -> dict:
    from flograph.core import visual_style

    merged = visual_style.merge_styles(
        style if visual_style.is_style(style) else None, None)
    return visual_style.tokens(merged)
