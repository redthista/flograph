# Flow Variables

A **Variables** node names settings once so the rest of the flow can refer to
them. It is the settings counterpart of a [[The Canvas|Goto/From]] pair.

## Declaring and using

Add a **Variables** node (Util category) and write assignments, one per line:

```
data_dir = C:/data
region   = North
min_rows = 20
```

Then write `${data_dir}` into any text box in the **Properties** panel — a
file path, a filter expression, a title — or read `ctx.vars` in a Python
Script node:

```python
def run(ctx, table):
    return table[table["region"] == ctx.vars["region"]]
```

Change a value in the Variables node and **everything that reads it re-runs**.
A `${name}` reference is a real edge in the graph — it participates in run
ordering and cache invalidation exactly as a wire does. This is why a `--var`
override on a [[Running Headless|headless run]] is identical to opening the
project and typing the value in.

## Input controls as variables

Any [[Input Controls|input control]] can publish its value as a variable:
open its **Behaviour** settings and type a **Variable name** — `threshold`,
say. Now `${threshold}` works anywhere a Variables node's names do, with no
wire, and moving the slider re-runs everything that reads it.

```
price > ${threshold}            a Filter's query
${data_dir}/${region}.csv       a Read CSV path, two variables at once
```

The value is written in as text, so quote a string where the box expects
one: `region == "${region}"`. A list (from a control that picks several)
is written as a list: `region in ${regions}`.

**Between** publishes three names: `price_low`, `price_high`, and `price`
as the pair `[low, high]`.

A control that holds its change until **Apply** keeps its variable on the
value as last applied, like everything else downstream.

## Variables in number, tick-box, dropdown and date settings

A number box cannot hold `${threshold}` inside other text, but it can be
**bound** to a variable outright. Right-click the setting's row in
Properties ▸ **Use Variable** ▸ pick the name. The row then shows what it is
bound to and its current value; **✕** (or right-click ▸ **Stop Using
Variable**) puts it back to its default.

At each run the variable's value is converted to the setting's type: `"40"`
becomes 40 (kept inside the setting's own minimum and maximum), `yes`/`no`
and `true`/`false` become a tick, a date becomes `YYYY-MM-DD`, and a dropdown
must be given one of its own options. A value that cannot be converted stops
the node with a message saying which setting and what it got.

## Secrets

Secrets stay **out of the project file**. Write `${env:NAME}` in any text box
and it reads from a `.env` file you manage under **Tools ▸ Secrets…**. The
project stores only the path to that file, never the value.

```
${env:DB_PASSWORD}
${env:API_TOKEN}
```

The `.env` file lives in your flograph user directory by default. It is per
machine and never travels with the project.

## Overriding without opening the app

`flograph run project.flograph --var region=South` rewrites the Variables
node's declaration for that run only. A name published by an input control
sets that control's value instead, as moving it would. A name the flow does not declare is
**refused, not ignored** — a typo that silently ran the default would be
worse than a stop. See [[Running Headless]].
