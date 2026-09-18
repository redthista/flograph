# Chart Rules

**Show Plotly**, **Chart per Value (Plotly)** and **Plotly Style** each have a
**Chart rules** box: a plain-text list of rules that adds series to a chart and
styles it, in the same spirit as a table's [[Conditional Formatting]].

Nothing changes until you write a rule. Rules run **after** the settings above
them, top to bottom, so a rule wins over a setting and a later rule wins over
an earlier one. A line nobody can read is **reported in the node's log and
skipped** — the chart still draws.

Write into the box, or press **Chart Rules…** for a builder that reads and
writes the same text. The bundled **Open Example ▸ Chart Rules** flow shows a
total line, last year's total from a second table, a second Y axis, a shared
house style and one chart per region.

## The shape of a rule

One rule per line, starting with a verb. A blank line is skipped; `#` starts a
comment — a whole line, or trailing after a rule. A `#hex` colour is not a
comment.

```
title "Units by month" center
axis y title "Units" format ,.0f grid off
axis x hide title
legend bottom horizontal
series total line thick blue as "Total"
series total from compare dashed grey as "Last year"
line at 100 dashed red label "Target"
note "Draft" bottom right
```

Text with a space in it goes in `"quotes"`. A colour is a name (`red`, `amber`,
`green`, `orange`, `yellow`, `blue`, `purple`, `pink`, `brown`, `grey`,
`black`, `white`), any CSS colour name, `#hex` or `rgb()`.

## `series` — another line on the chart

Each `series` rule adds one trace, with its own legend entry. This is how a bar
chart gets a total line over it, or last year's figures beside this year's.

```
series margin right dotted amber as "Margin %"
series total line thick blue as "Total"
series total of units, returns dashed as "Both"
series total from compare dashed grey as "Last year"
```

| part | what it does |
| --- | --- |
| what to plot | a **column** of the table, or `total`, `average`, `min`, `max`, `count`, `median` worked out across the columns the chart plots. `total of units, returns` totals the columns you name. |
| `from compare` | read the node's **compare** input — a second table — instead of the chart's own. It is matched on the chart's X column, so a category missing there leaves a gap rather than a zero. |
| how to draw it | `line` (the default), `dashed`, `dotted`, `step`, `area`, `bars`, `markers`, `points`, `both`. `thick`, or `width 4`. |
| where | `right` puts it on a second Y axis (`axis y2 …` labels that axis); the same axis otherwise. |
| colour | a colour word or code. |
| `as "…"` | the legend entry. The column's own name otherwise. |

A series is drawn from the same rows as the chart, so with **Group and total**
set to sum, the bars and the total line agree. A column that the summarising
took away is read from the raw rows and grouped the same way.

On **Chart per Value**, every panel gets the rules. A compare table holding the
**Split by** column is cut to each panel; one without it is used whole, so a
single historic total can sit on every panel.

`series` only works on the chart nodes — **Plotly Style** never sees the data,
only a finished figure, and says so in the log.

## `axis` — one axis at a time

`axis x|y|y2` then any number of settings on the same line:

| setting | example |
| --- | --- |
| `title "…"` | `axis y title "Units"` |
| `hide title` / `hide ticks` / `hide` | `axis x hide ticks` — `hide` on its own takes the line, ticks, labels and gridlines |
| `format` | `axis y format ,.0f` (d3 formats: `.1%`, `$,.2f`, `%b %Y`) |
| `range` | `axis y range 0 100` |
| `log` | `axis y log` |
| `grid on` / `grid off` | `axis x grid off` |
| `angle` | `axis x angle -45` |
| `order` | `axis x order total descending` |
| `slider` | `axis x slider` — a range slider under the chart |

`axis y2` is the right-hand axis a `series … right` draws on; naming it before
or after the series both work.

## `legend`

```
legend bottom horizontal
legend inside top right size 11 background #ffffff border #cccccc 1
legend hide
legend hide title
legend clicks isolate
```

Positions: `top`, `bottom`, `left`, `right`, `inside top left`, `inside top
right`, `inside bottom left`, `inside bottom right`. Also `title "…"`,
`order reversed`, `clicks off|toggle|isolate`.

## The rest

| verb | example |
| --- | --- |
| `title` / `subtitle` | `title "Sales" center` |
| `note` | `note "Draft" bottom right` |
| `line` | `line at 100 on y dashed red label "Target"` |
| `font` | `font Georgia 12 #333333` |
| `background` | `background plot #ffffff`, `background paper transparent` |
| `margin` | `margin 40 20 30 50` (left, right, top, bottom) |
| `hover` | `hover unified`, `hover off` |
| `bars` | `bars stack gap 0.2` |
| `colorbar` | `colorbar hide`, `colorbar title "Score"` |

## The escape hatches

Three verbs hand a JSON object straight to plotly, so anything plotly can do is
reachable even where the language has no word for it:

```
layout {"bargap": 0.4, "shapes": []}
traces {"marker_line_width": 1}
config {"scrollZoom": true, "displayModeBar": false}
```

They run in their place in the list like any other rule, so a `layout` line at
the end wins over everything above it.

## Sharing rules between charts

Put the rules on a **Plotly Style** node instead of the chart, and wire its
**figure** output into as many charts as you like — or chain styles: a Style
node's **style** input takes another's output and **appends** to it, so a house
style can sit at the head of a chain with a per-chart style after it. See
**Plotly Style**'s own help (F1 from the node) for the chain.
