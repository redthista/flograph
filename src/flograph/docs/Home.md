# flograph

A visual node-based Python environment: dataflow on an infinite,
Blueprint-style canvas where every node is real, editable Python — and the
same graph also gives you interactive dashboards and printable reports. One
file, three surfaces, no export step between them.

This handbook is the everyday reference. It opens from **Help ▸
Documentation** or **F1**.

## Pages

- **[[Getting Started]]** — install, launch, open an example, build and run
  your first flow.
- **[[The Canvas]]** — nodes, wires, ports, frames, panning, the shortcuts
  that matter.
- **[[Nodes and the Library]]** — finding nodes, the standard library,
  optional-extra packages.
- **[[Writing a Node]]** — the full node contract: `NODE`, params, the `run`
  context, cards, where node files live.
- **[[Dashboards and Reports]]** — turning a flow into a dashboard for
  someone else, or a report that prints to PDF.
- **[[Flow Variables]]** — `${name}` settings, the Variables node, and
  secrets that stay out of the project file.
- **[[Running Headless]]** — run a `.flograph` from a terminal, a scheduler,
  or another Python program.
- **[[Keyboard Shortcuts]]** — the full default binding list.

## The shape of it

- **Nodes are Python scripts.** Every node — the shipped library included —
  is one small module with a `NODE` dict, an optional `PARAMS` list, and a
  `run(ctx, **inputs)` function. There is no privileged built-in tier: the
  Group By node is a file you can open and change.
- **Dataflow semantics.** Data flows through typed ports; a run is a
  topological walk of the *dirty* subgraph on background threads, so a re-run
  only recomputes what changed. Independent branches run at the same time.
- **A project is one file** (`.flograph`). By default it bundles the graph
  and its node output caches together, so reopening — or handing the file to
  someone else — restores every result without a re-run. Turn off
  *Settings ▸ General ▸ Saving ▸ Include cached results in the project file*
  and it is written as plain JSON instead — the graph alone, diffable and
  small, re-run on open.
