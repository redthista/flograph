# Conditional Formatting

A **Show Table** card paints itself from a plain-text list of rules — heatmaps,
data bars, traffic-light icons, highlighted cells and rows, per-column number
formats. Nothing is styled until you add a rule, and older projects open
exactly as they were.

Open **Show Table**'s Properties and write into the **Conditional formatting**
box, or press **Rules…** for a guided builder that reads and writes the same
text. The bundled **Open Example ▸ Conditional Formatting** flow shows every
rule type against one small table.

## The rule language

One rule per line. A blank line is skipped; `#` starts a comment — a whole
line, or trailing after a rule (`revenue scale green   # the money column`).
A rule is `columns  verb  argument`:

| verb | example | what it does |
| --- | --- | --- |
| `scale` | `revenue scale green` | 2- or 3-colour heatmap across the column's range |
| `bar` | `units bar blue` | in-cell data bar; a column with negatives splits from the centre |
| `icons` | `score icons traffic` | a 3-tier icon set (`traffic`, `arrows`, `check`), split at the column's thirds — add `reverse` to flip it |
| `iconmap` | `sla iconmap sla: ok=✓ green, breach=✗ red` | an icon per exact value; the glyph is any character or emoji |
| `… => bg / fg / bold` | `score >= 90 => bg green, bold` | highlight the cell when the test passes |
| `… => row <colour>` | `status = fail => row red` | highlight the whole row |
| `format` | `amount format $,.0f` | a Python / d3 number format for the column |
| `hide` | `hide helper_col` | keep a column in the data (a rule can still read it) but out of the view |
| `only` | `units bar blue only` | draw the format **instead of** the value — Power BI's "bar only" / "icon only" |

Tests for a highlight: `> < >= <= = !=`, `between 10 20`, `contains`,
`starts with`, `ends with`, `matches` (regex), `is empty`, `is not empty`.

Colours are a preset — `green` `red` `amber` `blue` `grey` `purple` — or a
`#hex`. Scale presets: `green` `blue` `red` `red-green` `red-yellow-green`
`green-yellow-red` `diverging`. In the **Rules…** builder every colour box is
a swatch menu with a **Custom…** entry that opens the system colour picker.

A column name with a space just works (`unit price scale green`). Wrap it in
`"quotes"` if it contains a comma or reads like a keyword.

An `iconmap` glyph can be an emoji — `sla iconmap sla: breach=🔥, ok=✅` — and
the app hunts down a font that can draw it, so the same rules look the same on
Windows, macOS and Linux. If one still shows as a blank space, the machine has
no emoji font at all: install one (Noto Color Emoji, or Twemoji) and reopen the
project.

## Showing the format instead of the value

Add **`only`** to a `scale`, `bar`, `icons` or `iconmap` rule and the cell
draws the format on its own — no number, no text:

```
status  iconmap only sla: breach=🔥, ok=✅   # the icon is the column
units   bar blue only                       # a bar chart down a column
score   scale green only                    # a plain heatmap block
```

The value is only hidden, never lost: the column still **sorts** on it,
**Ctrl+C** still copies it, and an export still writes it. It works at
either end of the rule (`bar only blue`, `bar blue only`), a `by` clause and
all — and a highlight takes it as a style word, so `score < 0 => bg red,
only` blanks the failing cells and leaves the rest alone.

## Order of application

Rules compose **top to bottom, and a later line wins** any attribute it sets —
including a single-cell highlight beating an earlier whole-row one. So a
`=> bg green` line placed below a `=> row red` line turns that one cell green
on an otherwise-red row. Several rules can target the same column (a data bar
*and* an icon, say).

## Deciding on another column

A `scale`, `bar` or `icons` rule can take its deciding value from a **different
column** with a trailing `by` (or `from`) clause. The style still lands in the
columns on the left; the named column's own min / max / thirds drive it:

```
product   scale green by revenue      # shade the Product label by its revenue
product   bar blue    by units        # bar length reads units, drawn in Product
product   icons traffic by score
```

A highlight tests another column with an `if` (or `when`) clause:

```
product   if revenue < 0   => bg red         # flag the Product cell
product   if status = closed => row grey      # whole row, tested on status
```

Name the helper column in a `hide` line to keep it out of the view.

## Column patterns

A column entry containing `*` or `?` is a glob that selects **every matching
column** (case-sensitive):

```
FY*        scale green        # every fiscal-year column, one rule
*_qty      bar blue
hide _tmp_*                   # every scratch column
```

A pattern that matches nothing is reported on the Show Table, next to the data.

## Sharing one look across tables

The rules a Show Table applies come out on its **style** output, and a Show
Table also *accepts* a **style** input — so one table's formatting wires
straight into another. The **Table Style** node (Viz) is a bare rules holder
with no data input, for a look shared across several tables. An incoming style
is the base; the receiving card's own rule box layers on top.

Errors — a bad line, a column the table lacks, a pattern that matches nothing —
are always reported on the **Show Table** that *applies* the style, never where
it was typed.

## Where it works

Conditional formatting applies to the **Show Table** card and to table tiles on
a [[Dashboards and Reports|dashboard]]. It is skipped above 200,000 rows (the
per-cell pass is Python-level and nobody heatmaps a million rows). The **Table**
grid and **Plotly Table** have their own, separate styling.
