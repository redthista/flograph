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

import math
import re
from html import unescape

from flograph.core.report import format_scalar
from flograph.core.table_format import (CellStyle, column_layout,
                                        column_matches, column_stats,
                                        evaluate_column, evaluate_rows,
                                        for_paper, sort_order,
                                        spark_projection, split_rules,
                                        visible_columns)
from flograph.core import sparkline

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

#: Below this table width, in points, the bar goes *under* its value
#: instead of beside it. Side by side reads better and is what a full-width
#: table gets; but the two share one line's width, and on a narrow table Qt
#: pays for that by wrapping the number itself — "412" comes out as three
#: stacked digits, which costs more than the row of height the stacked form
#: costs. See _bar.
STACK_BELOW = 380

#: The track a bar is drawn in. Light enough to sit under a table's rules
#: without being mistaken for a filled cell.
BAR_TRACK_COLOR = "#eceef1"

#: Added to a bar column's measured value width: a width exactly the widest
#: text's leaves nothing for a bold rule, or for a font that sets a hair
#: wider on the page than it measured.
VALUE_SLACK = 4

#: The value cell's own right padding, which Qt counts inside a stated
#: width — so the width written is the text's plus this.
VALUE_PADDING = 6


def frame_to_html(frame, rules=(), hidden=(), shown=(),
                  max_rows: int = MAX_ROWS,
                  width: "int | None" = None, paper: bool = True,
                  font_pt: "float | None" = None, marker: str = "",
                  text_width=None) -> str:
    """`frame` as an HTML table carrying `rules` as cell styling.

    `hidden` and `shown` are the card's column projection — what to drop
    and what to keep, in the order to keep it (patterns allowed in both);
    `width`
    is how wide the table should sit, in points, so an embed's `width=`
    reaches a table as well as a chart. Rows past `max_rows` are cut with
    a note, exactly as the markdown form cuts them.

    `font_pt` sets the whole table's text size — an embed's `scale=`, and
    the knob `fit` turns to get a table into the room left on a page.
    `marker` is an invisible string tucked into the first header cell so
    the renderer can find *this* table in the laid-out document and
    measure it; it prints as nothing.

    `text_width(text, font_pt)` says how wide plain text sets, for the
    renderer to pass in — core has no fonts to ask. With it, every data bar
    in a column gives its value the same width, the widest one's, so the
    tracks start level and the bars read by length (U2). Without it, or when
    it returns None, each value cell is sized by its own text as it always
    was: a guessed width has nothing to catch a short guess, and the markup
    that does catch one crashed Qt in a process with no GUI application.
    """
    frame = _as_frame(frame)
    if frame is None:
        return "> *(not a table)*"
    # a spark may add a column and put away the ones it reads — the same
    # function the card calls, before the projection that has to see both
    frame, rules, spark_hidden = spark_projection(frame, rules)
    if spark_hidden:
        hidden = list(hidden) + spark_hidden
    # the same projection the card applies, from the same function: a
    # printed table showing different columns from the dashboard it came
    # off is the exact failure this whole module exists to avoid
    columns = visible_columns(frame.columns, shown, hidden)
    if not columns:
        return "> *(no columns)*"

    # Before the row cut, not after: `rows=`/`fit` keep the *top* of the
    # table, so sorting afterwards would print an arbitrary thirty rows
    # neatly ordered among themselves — which looks right and is wrong.
    order = sort_order(rules)
    if order:
        from flograph.core.table_sort import sorted_frame
        frame = sorted_frame(frame, order[0], order[1])

    total = len(frame)
    shown = frame.head(max_rows) if total > max_rows else frame
    styles = _cell_styles(frame, shown, columns, rules, paper)
    numeric = {c: _is_numeric(frame[c]) for c in columns}
    track = _track_width(width)
    stacked = bool(width) and int(width) < STACK_BELOW
    # Beside its value, every bar in a column starts where the widest value
    # ends. Under its value (stacked), they already start level.
    value_widths = ({} if stacked else
                    _value_widths(shown, columns, styles, font_pt, text_width))

    # `width` / `align` / `label` rules shape the printed table the same
    # way they shape the card — a report that reads differently from the
    # dashboard it came off is what this whole path exists to avoid
    layout = column_layout(rules, columns)

    size = f' width="{int(width)}"' if width else ""
    text_size = f' style="font-size:{font_pt:g}pt"' if font_pt else ""
    out = [f'<table{size}{text_size} class="flograph-table"><thead><tr>']
    for index, column in enumerate(columns):
        entry = layout.get(str(column))
        align = _align_attr(entry, numeric[column])
        # Qt's rich text takes a column's width off the first row that
        # states one, and the header is that row
        fixed = f' width="{entry.width}"' if entry and entry.width else ""
        label = entry.label if entry and entry.label else str(column)
        # the marker rides in the first header cell rather than in a
        # paragraph of its own, which would print as a blank line
        head = (marker if index == 0 else "") + _escape(label)
        out.append(f"<th{align}{fixed}>{head}</th>")
    out.append("</tr></thead><tbody>")
    for row in range(len(shown)):
        out.append("<tr>")
        for column in columns:
            entry = layout.get(str(column))
            out.append(_cell(shown[column].iloc[row],
                             styles.get((row, column)),
                             numeric[column], track, stacked,
                             align=entry.align if entry else None,
                             value_width=value_widths.get(column)))
        out.append("</tr>")
    out.append("</tbody></table>")
    if total > max_rows:
        # the marker rides in the note as well as the header: a table that
        # is rebuilt shorter has to take its own "showing N of M" with it,
        # or the page ends up carrying both counts
        out.append(f"<p><i>{marker}Showing {max_rows:,} of "
                   f"{total:,} rows.</i></p>")
    return "".join(out)


def _align_attr(entry, numeric: bool) -> str:
    """The `align=` for a header: what a rule asked for, else the dtype's
    own habit (numbers right, everything else left)."""
    if entry is not None and entry.align:
        return f' align="{entry.align}"'
    return ' align="right"' if numeric else ""


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
                                        frame=shown, pool_frame=frame)
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


def _cell_text(value, style: "CellStyle | None") -> str:
    """A cell's text as HTML: formatted, escaped and decorated."""
    text = _escape(_text(value, style))
    if style is not None:
        text = _decorate(text, style)
    return text


def _value_widths(shown, columns, styles, font_pt, text_width) -> dict:
    """column -> the width every data bar in it gives its value.

    Each bar is a little table of its own, value then track, and a value
    cell sized by its own text started `1`'s track further left than
    `412`'s — so a column of bars could not be read by length, which is the
    one thing a bar is for (U2). One width per column, the widest value's,
    puts every track at the same place.
    """
    out = {}
    for column in columns:
        widest = 0.0
        for row in range(len(shown)):
            style = styles.get((row, column))
            if style is None or style.bar is None:
                continue
            width = _set_width(_cell_text(shown[column].iloc[row], style),
                               font_pt, text_width)
            if not width:
                # one value that could not be measured and the column cannot
                # promise a width to any of them
                widest = 0.0
                break
            widest = max(widest, width)
        if widest > 0:
            out[column] = int(math.ceil(widest)) + VALUE_SLACK
    return out


def _set_width(html: str, font_pt, text_width) -> float:
    """How wide a cell's HTML sets as text, as the caller measured it — 0
    when there is nothing to measure with (see frame_to_html)."""
    plain = unescape(re.sub(r"<[^>]+>", "", html))
    if not plain or text_width is None:
        return 0.0
    measured = text_width(plain, font_pt)
    return float(measured) if measured is not None else 0.0


def _cell(value, style: "CellStyle | None", numeric: bool,
          track: int = BAR_TRACK, stacked: bool = False,
          align: "str | None" = None,
          value_width: "int | None" = None) -> str:
    """One `<td>`: the value, plus whatever the rules said about it."""
    text = _cell_text(value, style)
    if style is not None and style.bar is not None:
        text = _bar(text, style, numeric, track, stacked, value_width)
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
    if style is not None and style.tooltip:
        # `title` is what a browser shows on hover, so a note survives Open
        # in Browser and the exported HTML. On paper it prints as nothing,
        # which is the honest answer: paper has no hover.
        attrs += f' title="{_escape(style.tooltip)}"'
    if align:
        placement = f' align="{align}"'          # an `align` rule was explicit
    elif style is not None and style.hide_value and style.decorations:
        # an icon standing in for the value centres, as the grid centres it
        placement = ' align="center"'
    else:
        placement = ' align="right"' if numeric else ""
    return f"<td{placement}{attrs}>{text}</td>"


def _bar(text: str, style: CellStyle, numeric: bool,
         track_width: int = BAR_TRACK, stacked: bool = False,
         value_width: "int | None" = None) -> str:
    """A data bar and its value.

    Beside the value, not behind it: the card paints the bar under the text
    with a delegate, and Qt's rich text has no way to say that. A
    percentage-width cell is the one proportional shape it *does*
    understand, so the value keeps its own column and the bar gets a fixed
    track beside it — the length still says what the card's says.

    `stacked` puts the bar on a line of its own under the value, for a
    table too narrow to give them a line each (see STACK_BELOW). Taller,
    but the alternative is Qt wrapping the number to make room.
    """
    fraction = max(-1.0, min(1.0, float(style.bar)))
    colour = style.bar_color or "#3b6299"
    align = ' align="right"' if numeric else ""
    track = (_centred_track(fraction, colour) if style.bar_mode == "center"
             else _left_track(fraction, colour))
    if stacked:
        where = "right" if numeric else "left"
        return f'<div align="{where}">{text}</div>{track}'
    # No width on the outer table. The value cell states the width its
    # whole column measured (see _value_widths), so every track starts at
    # the same place, and `white-space:nowrap` is what makes stating one
    # safe: a stated width that came up short used to have Qt stack "412"
    # as "4 / 1 / 2", where now it only widens that one row. Given no width,
    # the cell is sized by its own text, as it always was.
    if value_width:
        value_cell = (f'<td{align} width="{value_width + VALUE_PADDING}" '
                      f'style="border:none;padding:0 {VALUE_PADDING}px 0 0;'
                      f'white-space:nowrap">{text}</td>')
    else:
        value_cell = (f'<td{align} style="border:none;padding:0 6px 0 0">'
                      f'{text}</td>')
    return (f'<table cellspacing="0" cellpadding="0"><tr>{value_cell}'
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


#: Padding inside a printed lozenge. The card rounds its ends; this cannot
#: — Qt's rich text drops `border-radius` outright, which a render probe
#: confirms rather than assumes. So a pill prints as a coloured block: the
#: colour and the breathing room carry the meaning, the corners do not
#: survive. Getting real ends on paper needs the column printed as a
#: picture, which is the same escape hatch U2's data bars are waiting on —
#: decide it once, for both.
_PILL_PAD = "1px 6px"


def _spark_img(d) -> str:
    """A sparkline as a picture: an SVG in a `data:` address.

    A picture, where every other format on the page is text, because Qt's
    rich text has nothing that draws a line. A `data:` address because it
    needs no file beside it — it works as it is in a browser and in an
    exported page, and a report swaps it for a token round the markdown
    pass that would otherwise drop it (see ui/report/render.py).
    """
    spark = d.spark
    if spark.width:
        width = spark.width * 0.75           # card pixels, as points
    elif d.where in ("left", "right"):
        width = sparkline.PAPER_BESIDE
    else:
        width = sparkline.PAPER_ALONE
    height = sparkline.PAPER_HEIGHT * (2 if spark.tall else 1)
    uri = sparkline.data_uri(spark, width, height)
    if uri is None:
        return ""
    return (f'<img src="{uri}" width="{width:g}" height="{height:g}" '
            f'style="vertical-align:middle" />')


def _decor_span(d) -> str:
    """One decoration as an inline span."""
    if getattr(d, "spark", None) is not None:
        return _spark_img(d)
    css = []
    if d.color:
        css.append(f"color:{d.color}")
    if d.pill:
        css.append(f"background-color:{d.pill}")
        css.append(f"padding:{_PILL_PAD}")
    attrs = f' style="{";".join(css)}"' if css else ""
    return f"<span{attrs}>{_escape(d.text)}</span>"


def _in_a_pill(text: str, style: "CellStyle") -> str:
    """The value wrapped in its own lozenge, if a rule asked for one."""
    if not style.pill or not text:
        return text
    css = [f"background-color:{style.pill}", f"padding:{_PILL_PAD}"]
    if style.pill_fg:
        css.append(f"color:{style.pill_fg}")
    return f'<span style="{";".join(css)}">{text}</span>'


def _decorate(text: str, style: "CellStyle") -> str:
    """`text` with everything the rules hung on it, arranged as the card
    arranges it: a line above, the value between its side marks, a line
    below. `text` is already escaped; the spans added here are not.

    `above` / `below` are `<br>`-separated lines rather than a nested
    table, because a cell that grows has to grow the row it is in, and a
    line break is the one thing Qt's rich text and a browser agree on.
    """
    if not style.decorations and not style.pill:
        return text
    inside = [_decor_span(d) for d in style.at("in")]
    if inside:
        middle = " ".join(inside)     # `only` / `in` — instead of the value
    else:
        parts = ([_decor_span(d) for d in style.at("left")]
                 + ([_in_a_pill(text, style)] if text or style.pill else [])
                 + [_decor_span(d) for d in style.at("right")])
        middle = " ".join(p for p in parts if p)
    lines = [" ".join(_decor_span(d) for d in style.at("above")),
             middle,
             " ".join(_decor_span(d) for d in style.at("below"))]
    # `<br />`, never a bare `<br>`: Qt's markdown reader, which a report
    # page goes through, throws away the *whole* table a bare `<br>` sits in
    # — no error, the table is simply not on the page. The self-closing
    # spellings survive and break the line all the same (a probe, not a
    # guess: `<br>` 0 tables, `<br/>` and `<br />` 1).
    return "<br />".join(line for line in lines if line)


def _text(value, style: "CellStyle | None") -> str:
    """The cell's text: a `format` rule's version if there is one, else the
    report's ordinary scalar formatting. Missing values stay blank."""
    if style is not None and style.hide_value:
        return ""            # an `only` rule: the format stands in for it
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
