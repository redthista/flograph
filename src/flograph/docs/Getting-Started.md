# Getting Started

## Install

flograph is a normal pip package:

```bash
pip install flograph
```

That puts a `flograph` command on your PATH and makes `python -m flograph`
work. Individual nodes need extra packages — install the ones you want now,
or add them later from **Tools ▸ Manage Packages** without restarting:

```bash
pip install "flograph[matplotlib,plotly,excel]"
```

| Extra | For |
| --- | --- |
| `matplotlib` | Show Plot, Chart per Value |
| `plotly` | Show Plotly, Plotly Style, Plotly Table, Gantt Chart |
| `excel` | Read/Write Excel |
| `parquet` | Read/Write Parquet |
| `polars` | the fast polars engine on Read File |
| `geo` | folium / geopandas maps in a web-view node |
| `ai` | the local-LLM node assistant |

No install possible on a locked-down machine? `python scripts/build_onefile.py`
produces one self-contained `.py` that runs anywhere PySide6, pandas, jedi
and psutil already exist.

## Launch

```bash
flograph                          # after install
python -m flograph                # equivalent
```

## Open an example

**File ▸ Open Example** ships around twenty worked projects — filter and
visualise, an aggregate dashboard, a scripted pipeline, join/group-by
comparisons, an interactive slicer dashboard, and walkthroughs of
[[Flow Variables]], order edges and report pages. They are the fastest way
in: open one, click a node to see the data on it, press **F5** to re-run.

## Your first flow

1. **Add a source.** Press **Tab** (or right-click the canvas) to open the
   node search, type `read`, pick **Read File**, and choose a CSV. Or just
   drag a file from your file manager onto the canvas — it arrives as the
   right reader, already configured.
2. **Add a transform.** Drag from the Read File node's output port and drop
   on empty canvas; the search popup offers compatible nodes. Pick **Filter
   Rows**. The wire is made for you.
3. **Configure it.** Select the Filter Rows node and set the condition in the
   **Properties** panel on the right.
4. **See a result.** Add a **Show Table** or **Show Plot** node the same way.
   It becomes a live card on the canvas — the node *is* the view.
5. **Run.** **F5** runs everything; **F6** runs just the selection;
   right-click a node for *Run to this node*. Status lights read at a glance:
   grey idle, yellow queued, pulsing blue running, green done, red error.
6. **Save.** **Ctrl+S** writes a `.flograph` file (plain JSON). Results are
   cached beside it, so reopening restores them without a re-run.

## Where to go next

- [[The Canvas]] for how to move around and edit the graph.
- [[Nodes and the Library]] to see what is available and how to change a
  node's code.
- [[Dashboards and Reports]] once the flow works and you want to hand it to
  someone.
