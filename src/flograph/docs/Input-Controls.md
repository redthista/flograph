# Input Controls

The **Input** category holds the nodes you *set* rather than compute: a
Slider, a Number box, a Text box, a Date picker, a Toggle, a Choice dropdown
and Between, a two-handled range. Each one is a card on the canvas and a
tile on a [[Dashboards and Reports|dashboard]], and both are the same
control: move it in either place and the other follows.

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
| **with ✓ on the control** | The new value waits. An amber dot and a **✓ Apply** button appear on the control's caption row; press it and the flow re-runs once. |
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

## Resetting

**Reset inputs** on an Action Button puts the same set of controls back to
their defaults. Tick **Show reset button** on a control and a small **↺**
appears on it while its value differs from the default; right-click ▸
**Reset to Default** does the same on the canvas. A control set to wait
holds its reset too, until it is applied.
