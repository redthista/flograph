# Input Controls

The **Input** category holds the nodes you *set* rather than compute. Each
one is a card on the canvas and a tile on a [[Dashboards and Reports|
dashboard]], and both are the same control: move it in either place and the
other follows.

| Control | What it gives the flow |
|---|---|
| **Slider** | a number, dragged along a track |
| **Between** | a `low` and a `high` number — a window on one track |
| **Number** | a number, typed |
| **Text** | text |
| **Date** | a date, `YYYY-MM-DD` |
| **Date Range** | a `start` and an `end` date — last 30 days, this month, year to date, or two picked dates |
| **Time** | a time of day, `HH:MM` |
| **Date & Time** | a moment, `YYYY-MM-DDTHH:MM` |
| **Toggle** | True or False, as a tick box or a switch |
| **Choice** | one of a set, as a dropdown, buttons or radio buttons |
| **Multi Choice** | a list of any number of a set, as chips |
| **Checklist** | a list of any number of a set, as a scrolling tick list with search |
| **Colour** | a colour, `#rrggbb`, with optional preset swatches |
| **File** | the path of a file or folder the person chooses |
| **Input Panel** | several of the above in one card, filtering a table — see below |

Options and bounds can come from the control's own input ports: wire a
column into a Choice's or Multi Choice's `options` and the picks are that
column's values; wire a date column into a Date Range's `minimum` and
`maximum` and it is pinned to the period the data covers.

Every control carries the same **Behaviour** settings in its Properties,
folded under their own heading, whatever its shape — including a control
you wrote yourself from the **Control Template**:

| Setting | What it does |
|---|---|
| **Apply changes** | When a change reaches the flow — see below. |
| **Show reset button** | A small ↺ on the control while it is away from its default. |
| **Variable name** | Publishes the value as `${name}` — see below. |
| **Required** | A red `*` on the caption; left empty, the box is outlined red and the nodes after it stop with "*Caption* is required". (Numbers, sliders, tick boxes and dropdowns always hold a value, so it has no effect on them.) |
| **Help text** | An ⓘ beside the caption; hovering it shows the text. Write what the person using the dashboard needs to know. |
| **Accent colour** | The control's own colour for its track, ticks, focus ring and buttons. **Theme** keeps the usual blue. |

## Each control's own options

- **Text** — an ✕ in the box empties it. **Search as you type** follows the
  typing (once it pauses) instead of waiting for Enter. **Pattern** is a
  regular expression the text must match, with **Pattern message** saying
  what is wrong; a mismatch is outlined red and stops the flow. **Hide what
  is typed** shows dots — but the text is still saved in the project, so keep
  real passwords in a secret (`${env:NAME}`).
- **Choice** — **Style** shows the options as a dropdown, a row of
  **buttons**, or **radio** buttons. In a dropdown, type while it is open to
  narrow a long list. **Offer (All)** adds an "(All)" entry that emits an
  empty value — "don't filter". **Emits number** sends 2024, not "2024".
- **Toggle** — **Style** draws a tick box or an on/off switch.
- **Date** — **Starts on** gives an untouched picker a moving date: today,
  yesterday, the start of this week, month or year, or a number of days ago.
  A date picked by hand stays picked until it is reset. **Allow no date**
  lets it be left empty ("No date", emitted as "").
- **Number** — **Thousands separator** shows 1,250,000; the flow still gets
  the bare number.
- **Between** — in Properties the range is two boxes, low and high; both
  empty is the whole range.

## Applying a change

**Apply changes** decides when a change reaches the flow:

| Setting | What happens when you move the control |
|---|---|
| **instantly** | Everything downstream re-runs straight away. The default, and how controls have always behaved. |
| **with ✓ on the control** | The control carries its own **✓ Apply** button. A new value waits (an amber dot, and Apply lit amber) until you press it; pressing Apply re-runs the control and everything after it, change or no change. |
| **with an Apply button** | The new value waits, with only the amber dot. An **Action Button** set to **Apply inputs** sends it on, together with every other waiting control it reaches. |

A waiting change is shown on the control but not used by the flow: a run
started in the meantime uses the value as last applied, and the status bar
says so. It is saved with the project, and it undoes like any edit. Right-
click a control on the canvas for **Apply Change** and **Discard Change**.

### A form with one Apply button

Put four filters on a dashboard page with **Apply changes** set to *with an
Apply button*, then add an **Action Button** with **On click** set to
**Apply inputs**. Picking a region, a price range and two dates now costs one
run — when Apply is pressed — instead of four.

The button's **Inputs** setting says which controls it applies:

- **on this page** — the controls with a tile on the same page as the
  button (on every page the button is on). A button on no page reaches every
  control.
- **named inputs** — the controls whose names you list, one per line.
- **every input** — every control in the flow.

All of them go on as one undo step and one run.

## Using a control's value anywhere

Type a **Variable name** in a control's Behaviour settings and its value is
`${name}` everywhere in the flow — a Filter's query, a file path, a chart
title — and, through **Use Variable**, any number, tick-box, dropdown or
date setting. See [[Flow Variables]].

## Input Panel — a page of filters in one card

An **Input Panel** is a whole page of filters in one node — slicers, sliders,
a date window, tick boxes — that all talk to each other, the way the slicers
on a Power BI page do. Wire a table into its **data** input; each field
filters it on a column; the **filtered** output is the rows every field lets
through, ready for cards, charts and tables.

```
Region   = slicer region
Product  = slicer product
Channel  = choice channel style=buttons
Price    = between price step=5
Ordered  = date range order_date
Customer = text customer contains
In stock = toggle in_stock
```

**Setting it up.** Wire a table into **data**, run it, then press **Set Up
Fields…** — on the empty panel's card, under the **Fields** box in
Properties, or right-click the node. The wizard lists a suggested field for
every column worth one (text with a few values becomes buttons, a few dozen
a slicer, numbers a between, dates a date range, true/false a switch); untick
what you don't want, change a shape or a column, reorder the rows, and choose
how the fields filter each other and when changes apply. OK writes the
field lines into **Fields** — the wizard is a way of writing them, so you
can open it again later, or edit the lines by hand.

Each line is `Label = shape [column] [comparison] [option=value …]`:

- **shape** — `slicer` (a tick list with a search box and the number of rows
  behind each value), `choice`, `multi`, `slider`, `number`, `between`,
  `date`, `date range`, `text`, `toggle`, `time`, `datetime` or `colour`.
  Each is drawn with the same widget as the control of that name (a slicer
  is the **Checklist** control).
- **column** — the column of **data** the field filters. Leave it out and
  the field is just a value. Put a name with spaces in quotes:
  `"unit price"`.
- **comparison** — `>=` `<=` `>` `<` `=` for a number or a date (`>=` unless
  you say), `contains` `startswith` `=` for text (`contains`). A choice
  matches exactly, a multi keeps any ticked value, a between or a date range
  keeps the window, and a toggle keeps rows where the column is true while
  it is on.
- **options** — `step=` `decimals=` `min=` `max=` `default=`
  `style=buttons` `all=no` `required=yes` `help="…"` `placeholder="…"`
  `options=a|b|c` (a choice with no column) and `name=` (see below).

A line that can't be read is shown in red on the card and named in the
node's error; the other fields keep working.

**Nothing set filters nothing.** A new panel passes every row — a choice
starts on "(All)", a slider and a date at the end of their column's range, a
between and a date range on the whole range — and each field narrows the
table only once someone uses it.

**Fields filter each other.** The **Fields filter** setting says how:

- **each other** (the default) — every slicer, choice and multi offers the
  values the *other* fields leave, with counts to match. Tick **South** and
  the Product slicer shows only South's products; tick **Sprocket** and the
  Region slicer shows only the regions that sell it. A value you ticked
  that the others have filtered away stays ticked, with a count of 0.
  Sliders and date windows keep their column's whole span, so a value you
  set is never moved under you.
- **top to bottom** — each field sees only the rows the fields above it
  left, ranges included.
- **off** — every field sees the whole table.

**Apply and Reset on the panel.** Set *Behaviour ▸ Apply changes* to **with
✓ on the control** and the panel gets **✓ Apply** and **↺ Reset** buttons
along its bottom: set as many fields as you like, press Apply, and the flow
runs once. Apply is lit amber while something is waiting; Reset clears
every field and applies at once.

**Using the picks elsewhere:**

- **values** is a dict of every field's value, keyed by its name — the label
  made into an identifier (`In stock` is `in_stock`), or `name=` on the
  line.
- **Fields are variables** (on by default) makes each field `${name}`
  anywhere in the flow. A **Variable name** under Behaviour becomes a
  prefix: `f` makes them `${f_region}`, `${f_price}` and so on.
- **filters** describes what the panel filtered. Wire it into **Apply
  Filters** (Transform) with a second table and the same picks filter that
  one too. Where the second table names a column differently, map it in
  **Column names**: `region = sales_region`.

The panel is one control, so **Apply changes** holds every field at once:
set five of them, press Apply, and the flow runs once. The example
**37 Input panel** (File ▸ Open Example) puts all of this on a dashboard.

## Resetting

**Reset inputs** on an Action Button puts the same set of controls back to
their defaults. Tick **Show reset button** on a control and a small **↺**
appears on it while its value differs from the default; right-click ▸
**Reset to Default** does the same on the canvas. A control set to wait
holds its reset too, until it is applied.
