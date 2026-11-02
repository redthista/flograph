"""Sparkline Card

A KPI card with a little line under the big number — one glance answers
"how much?" *and* "which way is it going?".

The big number is **Value** reduced by **Aggregation**, as on a Card. The
line under it is **Trend column** in row order (blank = the Value column) —
sort the table first, or set **Order by** to a date column, so it reads left
to right through time. The arrow and percentage compare the line's last
point with its first, coloured by whether that's good: tick off **Higher is
better** for a cost or a wait time, where going down is the good news.

**value** is the big number and **trend** the change as a ratio
(0.12 = up 12%), for a Status Light or a Plain-English Summary to pick up.

Colours, type and corners follow a **Visual Style** on the `style` input.
"""
NODE = {
    "label": "Sparkline Card",
    "category": "Viz",
    "version": "1.0",
    "card": "webview",
    "inputs": [("table", "dataframe"),
               ("style", "object",
                {"optional": True, "suggest": ["flograph.viz.visual_style"]})],
    "outputs": [("html", "string"), ("value", "any"), ("trend", "number")],
}
PARAMS = [
    {"name": "column", "type": "columns", "label": "Value",
     "default": "", "multi": False},
    {"name": "aggregation", "type": "choice", "label": "Aggregation",
     "options": ["Sum", "Average", "Median", "Min", "Max", "Count",
                 "Distinct count", "First", "Last"], "default": "Sum"},
    {"name": "trend_column", "type": "columns", "label": "Trend column",
     "default": "", "multi": False, "placeholder": "(the Value column)"},
    {"name": "order_by", "type": "columns", "label": "Order by",
     "default": "", "multi": False, "placeholder": "(row order)"},
    {"name": "label", "type": "string", "label": "Label", "default": "",
     "placeholder": "Caption over the value"},
    {"name": "format", "type": "string", "label": "Format", "default": "",
     "placeholder": "Python format spec, e.g. $,.0f"},
    {"name": "higher_is_better", "type": "bool", "label": "Higher is better",
     "default": True},
    {"name": "width", "type": "int", "label": "Width",
     "default": 240, "min": 140, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 150, "min": 90, "max": 1000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

_AGG = {"Sum": "sum", "Average": "mean", "Median": "median", "Min": "min",
        "Max": "max"}


def _check(table, name, what):
    if name and name not in table.columns:
        raise ValueError(f"{what} column {name!r} not in table (has: "
                         + ", ".join(map(str, table.columns)) + ")")


def run(ctx, table, style=None):
    import pandas as pd

    from flograph.core import status_cards as sc
    from flograph.core.infographic import format_value
    from flograph.core.svgplot import escape

    p = ctx.params
    column = str(p["column"]).strip()
    if not column:
        raise ValueError("no column selected — set 'Value'")
    _check(table, column, "value")
    trend_col = str(p["trend_column"]).strip() or column
    _check(table, trend_col, "trend")
    order = str(p["order_by"]).strip()
    _check(table, order, "order-by")
    rows = table.sort_values(order, kind="stable") if order else table

    col = table[column]
    agg = p["aggregation"]
    if agg == "Count":
        value = int(col.count())
    elif agg == "Distinct count":
        value = int(col.nunique())
    elif agg in ("First", "Last"):
        if not len(rows):
            raise ValueError("table has no rows — nothing to show")
        value = rows[column].iloc[0 if agg == "First" else -1]
    else:
        value = getattr(pd.to_numeric(col, errors="coerce"), _AGG[agg])()
    if hasattr(value, "item"):
        value = value.item()

    points = pd.to_numeric(rows[trend_col], errors="coerce").dropna().tolist()
    trend = float("nan")
    if len(points) >= 2 and points[0]:
        trend = (points[-1] - points[0]) / abs(points[0])
    tone = sc.judge(trend if trend == trend else None,
                    bool(p["higher_is_better"]))
    tok = sc.tokens(style)
    ink = sc.tone_colour(tone, tok)
    line_colour = tok["palette"][0] if tone == "neutral" else ink

    label = str(p["label"]) or f"{agg} of {column}"
    sub = ""
    if trend == trend:
        sub = (f"<div class='sub' style='color:{ink}'>{sc.arrow(trend)} "
               f"{abs(trend):.1%}</div>")
    body = (f"<div class='card'><div class='label'>{escape(label)}</div>"
            f"<div class='big'>{escape(format_value(value, p['format']))}"
            f"</div>{sub}<div class='spark'>"
            f"{sc.spark_svg(points, line_colour)}</div></div>")
    html, _ = sc.page(body, style, title=label)
    ctx.log(f"{agg}({column}) = {value!r}; trend over {len(points)} "
            f"point(s)" + (f" {trend:+.1%}" if trend == trend else ""))
    return {"html": html, "value": value, "trend": trend}
