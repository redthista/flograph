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
node's declaration for that run only. A name the flow does not declare is
**refused, not ignored** — a typo that silently ran the default would be
worse than a stop. See [[Running Headless]].
