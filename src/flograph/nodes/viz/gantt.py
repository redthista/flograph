"""Gantt Chart

A project plan on a time axis: one bar per task, hover for detail, drag to
pan and scroll to zoom the dates. Needs the 'plotly' package — install it
from Tools > Manage Packages if missing.

**It works the dates out for you.** Give it a Duration column and a Depends
on column and it schedules the plan itself, so a task that slips pushes
everything downstream of it. A Start date on a row pins that row; tasks with
neither a pinned start nor a predecessor begin at Project start.

**Depends on** holds task ids, comma separated for several — the ids come
from the Task id column, or from the task names when there isn't one. Links
are finish-to-start: a task begins when the last of its predecessors ends.

**Zero duration draws as a milestone diamond**, which is how you put "signed
off" or "go live" on the chart.

The second output is the schedule it computed — the same tasks with real
start and finish dates — so the dates can flow on to a table, a filter or a
spreadsheet like any other data.

**Emit HTML** fills the third output with the whole chart as a standalone
web page, ready to save as an .html file and send to someone who has no
flograph. plotly.js travels inside it rather than being linked, so it opens
offline — which is why it is off by default: the page is around 4.5 MB, and
a chart you are only reading on the canvas should not pay for one.
"""
NODE = {
    "label": "Gantt Chart",
    "category": "Viz",
    # "webview" is what gives this node the embedded browser, so the chart's
    # own pan and zoom work on the card. The figure goes out on an "object"
    # port, not a "figure" one: "figure" means a matplotlib Figure.
    "card": "webview",
    "inputs": [("table", "dataframe")],
    "outputs": [("figure", "object"), ("schedule", "dataframe"),
                ("html", "string")],
}
PARAMS = [
    {"name": "task", "type": "columns", "label": "Task", "multi": False,
     "default": "", "placeholder": "the name on each bar"},
    {"name": "task_id", "type": "columns", "label": "Task id", "multi": False,
     "default": "", "placeholder": "optional; defaults to the task name"},
    {"name": "duration", "type": "columns", "label": "Duration",
     "multi": False, "default": "", "placeholder": "how long each task runs"},
    {"name": "duration_unit", "type": "choice", "label": "Duration unit",
     "options": ["days", "hours", "weeks"], "default": "days"},
    {"name": "depends_on", "type": "columns", "label": "Depends on",
     "multi": False, "default": "",
     "placeholder": "task ids, comma separated"},
    {"name": "start", "type": "columns", "label": "Start", "multi": False,
     "default": "", "placeholder": "optional; pins a task to a date"},
    {"name": "finish", "type": "columns", "label": "Finish", "multi": False,
     "default": "", "placeholder": "optional; used when there is no duration"},
    {"name": "project_start", "type": "date", "label": "Project start",
     "default": ""},
    # Working days is whole days by definition, so it cannot honour an
    # hours duration — the node says so rather than quietly rounding.
    {"name": "calendar", "type": "choice", "label": "Calendar",
     "options": ["calendar days", "working days (Mon-Fri)"],
     "default": "calendar days"},
    {"name": "group", "type": "columns", "label": "Group by", "multi": False,
     "default": "", "placeholder": "optional; draws phases as bands"},
    {"name": "color", "type": "columns", "label": "Color by", "multi": False,
     "default": "", "placeholder": "optional; defaults to the group column"},
    {"name": "progress", "type": "columns", "label": "Progress",
     "multi": False, "default": "", "placeholder": "0-1 or 0-100"},
    {"name": "show_baseline", "type": "bool", "label": "Show baseline",
     "default": False},
    {"name": "baseline_start", "type": "columns", "label": "Baseline start",
     "multi": False, "default": "",
     "visible_when": {"show_baseline": ["True"]}},
    {"name": "baseline_finish", "type": "columns", "label": "Baseline finish",
     "multi": False, "default": "",
     "visible_when": {"show_baseline": ["True"]}},
    {"name": "sort", "type": "choice", "label": "Sort",
     "options": ["input order", "start date"], "default": "input order"},
    {"name": "show_dependencies", "type": "bool", "label": "Show dependencies",
     "default": True},
    {"name": "show_today", "type": "bool", "label": "Show today",
     "default": True},
    # Off by default because it is not free: the page carries plotly.js
    # inline so it opens anywhere, which is ~4.5 MB held in the run cache
    # and written into the project's side-car cache on save. Nobody should
    # pay that for a chart they are only looking at on the canvas.
    {"name": "emit_html", "type": "bool", "label": "Emit HTML",
     "default": False},
    {"name": "title", "type": "string", "label": "Title", "default": ""},
    {"name": "width", "type": "int", "label": "Width",
     "default": 560, "min": 260, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 360, "min": 200, "max": 2000},
    # Cosmetic: run() never reads it — the zoom is the embedded browser's
    # own, applied to the figure this node already produced. Dirtying on it
    # would re-run the plot, and everything downstream, for the same figure.
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400, "cosmetic": True},
]

# Bar geometry, in row units. The baseline sits just below its task so the
# pair reads as planned-against-actual rather than as two separate tasks.
_BAR = 0.52
_PROGRESS_BAR = 0.24
_BASELINE_BAR = 0.14
_BASELINE_OFFSET = 0.30

_PALETTE = ["#3b82f6", "#f59e0b", "#10b981", "#8b5cf6", "#ef4444",
            "#14b8a6", "#ec4899", "#84cc16", "#6366f1", "#f97316"]
_PLAIN = "#64748b"
_MILESTONE = "#334155"
_PROGRESS_FILL = "rgba(0, 0, 0, 0.38)"
_BASELINE_FILL = "rgba(100, 116, 139, 0.55)"
_TODAY = "#ef4444"
_BAND = "rgba(100, 116, 139, 0.08)"


def run(ctx, table):
    try:
        import plotly.graph_objects as go
    except ImportError:
        raise ImportError(
            "plotly is not installed — add it via Tools > Manage Packages"
        ) from None
    import pandas as pd

    from flograph.core.gantt import schedule

    params = ctx.params
    baseline = bool(params.get("show_baseline"))
    plan = schedule(
        table,
        task=params["task"],
        id=params["task_id"],
        start=params["start"],
        finish=params["finish"],
        duration=params["duration"],
        depends_on=params["depends_on"],
        progress=params["progress"],
        group=params["group"],
        baseline_start=params["baseline_start"] if baseline else "",
        baseline_finish=params["baseline_finish"] if baseline else "",
        unit=params["duration_unit"],
        calendar=params["calendar"],
        project_start=params["project_start"],
    )
    if plan.empty:
        raise ValueError("there are no tasks to chart")

    # The colour key rides along as a column so it survives the sort. It is
    # read off the *input* table, which has columns the schedule does not.
    plan["_color"] = _color_key(table, plan, params)
    plan = _ordered(plan, params["sort"])
    rows = _rows(plan)
    figure = _figure(go, pd, plan, rows, params)
    first, last = plan["start"].min(), plan["finish"].max()
    ctx.log(f"{len(plan)} task(s), {first:%d %b %Y} to {last:%d %b %Y}")
    html = ""
    if params.get("emit_html"):
        # The same helper the card and Open in Browser use, so the file on
        # disk is the page you were looking at rather than something that
        # merely resembles it. plotly.js rides along inside it — no CDN, so
        # it opens on a machine with no internet.
        from flograph.core.html import to_html

        html = to_html(figure) or ""
        ctx.log(f"HTML page: {len(html) / 1048576:.1f} MB, self-contained")
    return {"figure": figure, "schedule": plan.drop(columns=["_color"]),
            "html": html}


def _color_key(table, plan, params):
    """What decides each bar's colour: the Color by column when there is
    one, the grouping column otherwise, and nothing at all when neither is
    set — one colour for every bar is the right answer for a plain plan."""
    column = (params["color"] or "").strip()
    if not column:
        return [str(v) for v in plan["group"]]
    if column == (params["group"] or "").strip():
        return [str(v) for v in plan["group"]]
    if column not in table.columns:
        raise ValueError(f"Color by column {column!r} is not in the table")
    return [_label(v) for v in table[column]]


def _label(value):
    return "" if _missing(value) else str(value).strip()


def _ordered(plan, sort):
    """Rows in drawing order. A group column always blocks its tasks
    together — the sort decides the order inside each block."""
    plan = plan.copy(deep=False)
    grouped = _grouped(plan)
    keys = []
    if grouped:
        # First appearance, not alphabetical: a plan's phases are already
        # written in the order they happen.
        seen = list(dict.fromkeys(plan["group"]))
        plan["_block"] = plan["group"].map(seen.index)
        keys.append("_block")
    if sort == "start date":
        keys.append("start")
    if keys:
        plan = plan.sort_values(keys, kind="stable")
    plan = plan.drop(columns=["_block"], errors="ignore")
    return plan.reset_index(drop=True)


def _grouped(plan):
    return any(str(v).strip() for v in plan["group"])


def _rows(plan):
    """One entry per chart row, top to bottom: a group header carries no
    task, every other row points at a row of the plan."""
    grouped = _grouped(plan)
    rows = []
    current = None
    for i in range(len(plan)):
        group = str(plan["group"].iloc[i])
        if grouped and group != current:
            rows.append({"index": None, "label": f"<b>{group}</b>",
                         "group": group})
            current = group
        label = str(plan["task"].iloc[i])
        rows.append({"index": i, "group": group,
                     "label": f"&nbsp;&nbsp;{label}" if grouped else label})
    return rows


def _figure(go, pd, plan, rows, params):
    y_of = {row["index"]: i for i, row in enumerate(rows)
            if row["index"] is not None}
    series = _series(plan)
    unit = params["duration_unit"]
    figure = go.Figure()

    _add_bars(go, figure, plan, y_of, series, unit)
    _add_progress(go, figure, plan, y_of)
    if "baseline_start" in plan:
        _add_baseline(go, figure, plan, y_of)
    _add_milestones(go, figure, plan, y_of, unit)
    if params.get("show_dependencies"):
        _add_dependencies(go, plan, figure, y_of)
    _add_bands(figure, rows)
    if params.get("show_today"):
        _add_today(figure, pd, plan)

    legend = len(series) > 1 or "baseline_start" in plan
    figure.update_layout(
        barmode="overlay",
        bargap=0,
        title=params["title"] or None,
        showlegend=legend,
        # Dates run along the top, as a Gantt's do, which leaves the bottom
        # for the legend — with the title above the axis, all three would
        # otherwise be fighting for the same band.
        legend={"orientation": "h", "yanchor": "top", "y": -0.04,
                "xanchor": "left", "x": 0},
        hovermode="closest",
        plot_bgcolor="white",
        # The card sizes the figure; a figure insisting on its own pixel
        # height would overflow the card it was given.
        autosize=True,
        margin={"t": 74 if params["title"] else 46,
                "b": 54 if legend else 24, "l": 10, "r": 20},
    )
    figure.update_xaxes(type="date", showgrid=True, gridcolor="#e2e8f0",
                        side="top")
    # The range is written out rather than left to autorange="reversed" so
    # the half-row of padding above the first bar and below the last is the
    # same, whatever the group bands and headers add.
    figure.update_yaxes(
        showgrid=False, zeroline=False, tickmode="array", automargin=True,
        tickvals=list(range(len(rows))),
        ticktext=[row["label"] for row in rows],
        range=[len(rows) - 0.5, -0.5],
    )
    return figure


def _series(plan):
    """Bars grouped into colour series, in first-appearance order — one
    entry of (legend name, colour, row indices)."""
    values = []
    for value in plan["_color"]:
        if value not in values:
            values.append(value)
    return [(value, _PLAIN if not value else _PALETTE[n % len(_PALETTE)],
             [i for i in range(len(plan)) if plan["_color"].iloc[i] == value])
            for n, value in enumerate(values)]


def _hover(plan, i, unit):
    row = plan.iloc[i]
    lines = [f"<b>{row['task']}</b>"]
    if row["group"]:
        lines.append(str(row["group"]))
    if row["is_milestone"]:
        lines.append(f"{row['start']:%a %d %b %Y}")
    else:
        lines.append(f"{row['start']:%a %d %b %Y} &#8594; "
                     f"{row['finish']:%a %d %b %Y}")
        lines.append(f"{row['duration']:g} {unit}")
    if not _missing(row["progress"]):
        lines.append(f"{row['progress'] * 100:.0f}% complete")
    if row["depends_on"]:
        lines.append(f"after {row['depends_on']}")
    return "<br>".join(lines)


def _width_ms(plan, i):
    delta = plan["finish"].iloc[i] - plan["start"].iloc[i]
    return delta.total_seconds() * 1000.0


def _add_bars(go, figure, plan, y_of, series, unit):
    """One trace per colour, so the legend can switch phases on and off."""
    for name, color, members in series:
        indices = [i for i in members if not plan["is_milestone"].iloc[i]]
        if not indices:
            continue
        figure.add_trace(go.Bar(
            name=name or "task",
            orientation="h",
            y=[y_of[i] for i in indices],
            base=[plan["start"].iloc[i] for i in indices],
            x=[_width_ms(plan, i) for i in indices],
            width=_BAR,
            marker={"color": color, "line": {"width": 0}},
            hovertext=[_hover(plan, i, unit) for i in indices],
            hoverinfo="text",
            showlegend=bool(name),
        ))


def _add_progress(go, figure, plan, y_of):
    indices = [i for i in range(len(plan))
               if not plan["is_milestone"].iloc[i]
               and not _missing(plan["progress"].iloc[i])
               and plan["progress"].iloc[i] > 0]
    if not indices:
        return
    figure.add_trace(go.Bar(
        name="complete",
        orientation="h",
        y=[y_of[i] for i in indices],
        base=[plan["start"].iloc[i] for i in indices],
        x=[_width_ms(plan, i) * float(plan["progress"].iloc[i])
           for i in indices],
        width=_PROGRESS_BAR,
        marker={"color": _PROGRESS_FILL, "line": {"width": 0}},
        # The task bar underneath already answers "what is this?" — a second
        # tooltip on the same pixels would only fight it.
        hoverinfo="skip",
        showlegend=False,
    ))


def _baseline_hover(plan, i):
    return (f"<b>{plan['task'].iloc[i]}</b><br>planned "
            f"{plan['baseline_start'].iloc[i]:%d %b} &#8594; "
            f"{plan['baseline_finish'].iloc[i]:%d %b}<br>{_slip(plan, i)}")


def _add_baseline(go, figure, plan, y_of):
    known = [i for i in range(len(plan))
             if not _missing(plan["baseline_start"].iloc[i])
             and not _missing(plan["baseline_finish"].iloc[i])]
    spans = {i: (plan["baseline_finish"].iloc[i]
                 - plan["baseline_start"].iloc[i]).total_seconds() * 1000.0
             for i in known}
    # A milestone's baseline is a single date, and a bar of zero width draws
    # nothing at all — which loses exactly the comparison that matters most,
    # the day something was promised for against the day it lands.
    points = [i for i in known if spans[i] == 0]
    if points:
        figure.add_trace(go.Scatter(
            name="baseline", mode="markers", legendgroup="baseline",
            x=[plan["baseline_start"].iloc[i] for i in points],
            y=[y_of[i] + _BASELINE_OFFSET for i in points],
            marker={"symbol": "diamond", "size": 8, "color": _BASELINE_FILL},
            hovertext=[_baseline_hover(plan, i) for i in points],
            hoverinfo="text", showlegend=False,
        ))
    indices = [i for i in known if spans[i] > 0]
    if not indices:
        return
    figure.add_trace(go.Bar(
        name="baseline",
        orientation="h",
        legendgroup="baseline",
        y=[y_of[i] + _BASELINE_OFFSET for i in indices],
        base=[plan["baseline_start"].iloc[i] for i in indices],
        x=[spans[i] for i in indices],
        width=_BASELINE_BAR,
        marker={"color": _BASELINE_FILL, "line": {"width": 0}},
        hovertext=[_baseline_hover(plan, i) for i in indices],
        hoverinfo="text",
        showlegend=True,
    ))


def _slip(plan, i):
    days = (plan["finish"].iloc[i]
            - plan["baseline_finish"].iloc[i]).total_seconds() / 86400.0
    if abs(days) < 0.5:
        return "on plan"
    return (f"{abs(days):.0f} days {'late' if days > 0 else 'early'}")


def _add_milestones(go, figure, plan, y_of, unit):
    indices = [i for i in range(len(plan)) if plan["is_milestone"].iloc[i]]
    if not indices:
        return
    figure.add_trace(go.Scatter(
        name="milestone",
        mode="markers",
        x=[plan["start"].iloc[i] for i in indices],
        y=[y_of[i] for i in indices],
        marker={"symbol": "diamond", "size": 13, "color": _MILESTONE,
                "line": {"color": "white", "width": 1}},
        hovertext=[_hover(plan, i, unit) for i in indices],
        hoverinfo="text",
        showlegend=False,
    ))


def _add_dependencies(go, plan, figure, y_of):
    """Every link in two traces, not two per link: one poly-line of elbows
    with gaps between them, one set of arrow heads."""
    index_of = {str(plan["id"].iloc[i]): i for i in range(len(plan))}
    span = (plan["finish"].max() - plan["start"].min()).total_seconds()
    gap = _seconds(max(span * 0.012, 3600))

    xs, ys, heads_x, heads_y, symbols = [], [], [], [], []
    for i in range(len(plan)):
        for key in str(plan["depends_on"].iloc[i]).split(","):
            key = key.strip()
            if key not in index_of:
                continue
            j = index_of[key]
            start = plan["start"].iloc[i]
            end = plan["finish"].iloc[j]
            from_y, to_y = y_of[j], y_of[i]
            down = to_y > from_y
            if start <= end + gap:
                # The usual case — the successor starts where its
                # predecessor ended, so the link is the drop between rows,
                # and the head meets the bar's edge rather than its middle.
                head_y = to_y - _BAR / 2 if down else to_y + _BAR / 2
                points = [(end, from_y), (end, head_y), (start, head_y)]
                symbols.append("triangle-down" if down else "triangle-up")
            else:
                elbow = end + gap
                head_y = to_y
                points = [(end, from_y), (elbow, from_y), (elbow, to_y),
                          (start, to_y)]
                symbols.append("triangle-right")
            for x, y in points:
                xs.append(x)
                ys.append(y)
            xs.append(None)
            ys.append(None)
            heads_x.append(start)
            heads_y.append(head_y)
    if not heads_x:
        return
    figure.add_trace(go.Scatter(
        x=xs, y=ys, mode="lines", line={"color": "#94a3b8", "width": 1},
        hoverinfo="skip", showlegend=False, name="depends on"))
    figure.add_trace(go.Scatter(
        x=heads_x, y=heads_y, mode="markers",
        marker={"symbol": symbols, "size": 7, "color": "#94a3b8"},
        hoverinfo="skip", showlegend=False, name="depends on"))


def _add_bands(figure, rows):
    """A tint behind every other group, so a phase reads as one block."""
    blocks, current = [], None
    for i, row in enumerate(rows):
        if row["group"] != current:
            blocks.append([i, i])
            current = row["group"]
        else:
            blocks[-1][1] = i
    if len(blocks) < 2:
        return
    for n, (first, last) in enumerate(blocks):
        if n % 2:
            continue
        figure.add_shape(type="rect", xref="paper", yref="y", layer="below",
                         x0=0, x1=1, y0=first - 0.5, y1=last + 0.5,
                         fillcolor=_BAND, line={"width": 0})


def _add_today(figure, pd, plan):
    today = pd.Timestamp.now().normalize()
    if not (plan["start"].min() <= today <= plan["finish"].max()):
        return
    figure.add_shape(type="line", xref="x", yref="paper",
                     x0=today, x1=today, y0=0, y1=1,
                     line={"color": _TODAY, "width": 1.5, "dash": "dash"})
    # Inside the plot, not above it: the date ticks live along the top edge
    # and a label hanging over them would land on a number.
    figure.add_annotation(x=today, xref="x", y=1, yref="paper",
                          text="today", showarrow=False, yanchor="top",
                          xanchor="left", xshift=4, yshift=-2,
                          font={"color": _TODAY, "size": 10})


def _seconds(seconds):
    import pandas as pd

    return pd.Timedelta(seconds=seconds)


def _missing(value):
    # pandas' isna, not `value != value`: a blank cell of a typed column
    # arrives as pandas' NA, which refuses to be turned into a bool.
    import pandas as pd

    return value is None or bool(pd.isna(value))
