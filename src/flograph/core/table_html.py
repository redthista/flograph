"""A DataFrame as a report table — with the formatting its card is showing.

A Show Table card is not a plain grid: it heatmaps a column, draws in-cell
bars, highlights rows that fail a test, sets icons, formats numbers and
hides helper columns (see table_format). None of that used to survive being
put on a report, because a frame reached the page as a *markdown* table —
a grid of text and nothing else. This module is the other half: the same
rules, evaluated the same way, written as HTML the report's document
understands.

Two decisions worth knowing:

**A table stays text.** It would have been less code to photograph the card
the way a web view is now photographed, but a picture of a table cannot be
selected, searched, or split across a page break — a forty-row table would
arrive as one image that either shrinks to nothing or runs off the paper.
So the styles are written as cell attributes and the text stays text.

**The colours are re-grounded for paper.** The card's palette is built for
a dark grid; the same fills on white would print "low" as a near-black
block and put light auto-text on a white page. `table_format.for_paper`
maps each style onto the page — same hue, same gradient direction, white
underneath (pass ``paper=False`` for a ground that is already dark).

Qt-free, and pandas is imported inside the functions, as everywhere in
core.
"""
from __future__ import annotations

from flograph.core.report import format_scalar
from flograph.core.table_format import (CellStyle, column_matches,
                                        column_stats, evaluate_column,
                                        evaluate_rows, for_paper,
                                        split_rules)

#: Rows shown before a table is cut with a note. The same default
#: frame_to_markdown uses — a report that quietly showed the first 30 of
#: 4000 rows would be a lie either way.
MAX_ROWS = 30

#: How wide the bar's track is, in points — fixed, not a percentage of the
#: cell. A percentage makes the *cell* greedy: Qt hands the column whatever
#: the nested table asks for, then squeezes the value beside it until "412"
#: wraps to "41 / 2". A fixed track leaves the value cell content-sized, so
#: the number always fits, and every bar in the column is still drawn
#: against the same length. Narrower tables get a shorter track (see
#: _track_width) — at half a page the bars are the greedy part, and a bar
#: is worth less than the column it would squeeze.
BAR_TRACK = 54
MIN_BAR_TRACK = 22

#: The track a bar is drawn in. Light enough to sit under a table's rules
#: without being mistaken for a filled cell.
BAR_TRACK_COLOR = "#eceef1"


def frame_to_html(frame, rules=(), hidden=(), max_rows: int = MAX_ROWS,
                  width: "int | None" = None, paper: bool = True) -> str:
    """`frame` as an HTML table carrying `rules` as cell styling.

    `hidden` is the card's hidden-column list (patterns allowed); `width`
    is how wide the table should sit, in points, so an embed's `width=`
    reaches a table as well as a chart. Rows past `max_rows` are cut with
    a note, exactly as the markdown form cuts them.
    """
    frame = _as_frame(frame)
    if frame is None:
        return "> *(not a table)*"
    columns = [c for c in frame.columns
               if not (hidden and column_matches(list(hidden), str(c)))]
    if not columns:
        return "> *(no columns)*"

    total = len(frame)
    shown = frame.head(max_rows) if total > max_rows else frame
    styles = _cell_styles(frame, shown, columns, rules, paper)
    numeric = {c: _is_numeric(frame[c]) for c in columns}
    track = _track_width(width)

    size = f' width="{int(width)}"' if width else ""
    out = [f'<table{size} class="flograph-table"><thead><tr>']
    for column in columns:
        align = ' align="right"' if numeric[column] else ""
        out.append(f"<th{align}>{_escape(str(column))}</th>")
    out.append("</tr></thead><tbody>")
    for row in range(len(shown)):
        out.append("<tr>")
        for column in columns:
            out.append(_cell(shown[column].iloc[row],
                             styles.get((row, column)),
                             numeric[column], track))
        out.append("</tr>")
    out.append("</tbody></table>")
    if total > max_rows:
        out.append(f"<p><i>Showing {max_rows:,} of {total:,} rows.</i></p>")
    return "".join(out)


def _track_width(width: "int | None") -> int:
    """How long a data bar may be, given the room the table has.

    A tenth of the table per bar: enough to compare lengths at a glance,
    little enough that a table placed at `width=50%` spends its width on
    the figures rather than on the decoration beside them.
    """
    if not width:
        return BAR_TRACK
    return max(MIN_BAR_TRACK, min(BAR_TRACK, int(width) // 10))


def _as_frame(frame):
    """A DataFrame from a DataFrame or a Series, or None."""
    if frame is None:
        return None
    if hasattr(frame, "to_frame") and not hasattr(frame, "columns"):
        return frame.to_frame()
    return frame if hasattr(frame, "columns") else None


def _is_numeric(series) -> bool:
    try:
        from pandas.api.types import is_numeric_dtype
        return bool(is_numeric_dtype(series))
    except Exception:
        return False


def _cell_styles(frame, shown, columns, rules, paper: bool) -> dict:
    """(row, column) -> the CellStyle to draw, already grounded for paper.

    The composition is the card's, rule for rule: every rule that touches a
    cell is applied in the order it was written, so a later line wins over
    an earlier one and a whole-row highlight sits under a cell one (see
    ui/inspector/pandas_model._cell_style). The *stats* come from the whole
    column and the *styles* from the rows on show, so a heatmap of the
    first 30 of 4000 rows is still shaded against the real range.
    """
    rules = [r for r in (rules or []) if r.mode != "hide"]
    if not rules or shown is None or not len(shown):
        return {}
    column_rules, row_rules = split_rules(rules)
    order = {id(rule): index for index, rule in enumerate(rules)}

    parts: dict = {}         # (row, column) -> [(rule order, CellStyle)]

    def add(row: int, column, index: int, style) -> None:
        if style is not None:
            parts.setdefault((row, column), []).append((index, style))

    for column in columns:
        name = str(column)
        stats = None
        for rule in column_rules:
            if rule.columns and not column_matches(rule.columns, name):
                continue
            if stats is None:
                stats = column_stats(frame[column])
            evaluated = evaluate_column(shown[column], [rule], stats,
                                        frame=shown)
            for row, style in enumerate(evaluated):
                add(row, column, order[id(rule)], style)
    for rule in row_rules:
        for row, style in enumerate(evaluate_rows(shown, [rule])):
            for column in columns:
                add(row, column, order[id(rule)], style)

    final: dict = {}
    for key, found in parts.items():
        found.sort(key=lambda pair: pair[0])
        style = None
        for _index, part in found:
            style = part.over(style)
        final[key] = for_paper(style) if paper else style
    return final


def _cell(value, style: "CellStyle | None", numeric: bool,
          track: int = BAR_TRACK) -> str:
    """One `<td>`: the value, plus whatever the rules said about it."""
    text = _escape(_text(value, style))
    if style is not None and style.icon:
        colour = (f' style="color:{style.icon_color}"'
                  if style.icon_color else "")
        text = f"<span{colour}>{_escape(style.icon)}</span> {text}"
    if style is not None and style.bar is not None:
        text = _bar(text, style, numeric, track)
        numeric = False       # the bar table fills the cell; don't re-align
    css = []
    if style is not None:
        if style.bg:
            css.append(f"background-color:{style.bg}")
        if style.fg:
            css.append(f"color:{style.fg}")
        if style.bold:
            css.append("font-weight:bold")
    attrs = f' style="{";".join(css)}"' if css else ""
    align = ' align="right"' if numeric else ""
    return f"<td{align}{attrs}>{text}</td>"


def _bar(text: str, style: CellStyle, numeric: bool,
         track_width: int = BAR_TRACK) -> str:
    """A data bar beside its value, as a nested one-row table.

    Beside, not behind: the card paints the bar under the text, and Qt's
    rich text has no way to say that. A percentage-width cell is the one
    proportional shape it *does* understand, so the value keeps its own
    column and the bar gets the rest — the length still says what the card's
    says.
    """
    fraction = max(-1.0, min(1.0, float(style.bar)))
    colour = style.bar_color or "#3b6299"
    align = ' align="right"' if numeric else ""
    track = (_centred_track(fraction, colour) if style.bar_mode == "center"
             else _left_track(fraction, colour))
    # No width on the outer table, and one only on the track: the value
    # cell is then sized by its own text, which is what stops Qt stacking
    # "412" as "4 / 1 / 2". Giving the value a stated width instead makes
    # it *fixed*, and anything the estimate was short by wraps — worse than
    # the problem it was meant to fix.
    return (f'<table cellspacing="0" cellpadding="0"><tr>'
            f'<td{align} style="border:none;padding:0 6px 0 0">{text}</td>'
            f'<td width="{track_width}" style="border:none;padding:0">'
            f"{track}</td></tr></table>")


def _left_track(fraction: float, colour: str) -> str:
    filled = max(0, min(100, round(abs(fraction) * 100)))
    return _track([(filled, colour), (100 - filled, None)])


def _centred_track(fraction: float, colour: str) -> str:
    """A column holding negatives grows from the middle, as the card's
    does, so the sign is visible without reading the number."""
    half = max(0, min(50, round(abs(fraction) * 50)))
    if fraction < 0:
        return _track([(50 - half, None), (half, colour), (50, None)])
    return _track([(50, None), (half, colour), (50 - half, None)])


def _track(cells) -> str:
    """The bar itself: cells of the given widths, coloured or empty.

    A zero-width cell is dropped rather than written — Qt gives an empty
    cell its padding whatever its stated width, so a run of them would
    stretch the track wider than the column it sits in.
    """
    out = ['<table width="100%" cellspacing="0" cellpadding="0"'
           f' bgcolor="{BAR_TRACK_COLOR}"><tr>']
    for width, colour in cells:
        if width <= 0:
            continue
        fill = f' bgcolor="{colour}"' if colour else ""
        out.append(f'<td width="{width}%"{fill} '
                   'style="border:none;padding:0">&nbsp;</td>')
    out.append("</tr></table>")
    return "".join(out)


def _text(value, style: "CellStyle | None") -> str:
    """The cell's text: a `format` rule's version if there is one, else the
    report's ordinary scalar formatting. Missing values stay blank."""
    if style is not None and style.text is not None:
        return str(style.text)
    try:
        if value is None or value != value:      # NaN/NaT; pd.NA raises
            return ""
    except Exception:
        return ""
    return format_scalar(value).replace("\n", " ")


def _escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
