# The Canvas

The **model canvas** is where the pipeline is built. It is an infinite
Blueprint-style surface.

## Getting around

| Action | Binding |
| --- | --- |
| Pan | middle-drag, or hold **Space** and drag |
| Zoom | mouse wheel |
| Frame the whole graph in view | **F** |
| Nudge the selection | arrow keys |

A **minimap** (toggle in Settings ▸ Canvas) and a status-bar resource
monitor keep the scale of a large graph legible.

## Adding and connecting nodes

| Action | How |
| --- | --- |
| Add a node | **Tab** or right-click — both open the search palette — or drag from the [[Nodes and the Library]] dock |
| Connect | drag from an output port; drop on empty canvas to pick a compatible node |
| Splice into a wire | drop a library node onto the wire — it lights green while it will take; hold **Alt** to drop without connecting |
| Replace a node | drop a library node onto it — wires that fit the new node's ports come across |
| Reroute dot | double-click a wire; double-click the dot again to name it |
| Comment frame | **Ctrl+G** around the selection |

Hold **Q** over the canvas to float every port's name for as long as you
hold it.

## Nodes

A node that is only a step in the pipeline draws as a fixed **60×60 square** —
a mark inside, its name floating above, its status light below — so a graph
of them reads as a pipeline, not a row of mismatched boxes. Nodes that show
data ([[Dashboards and Reports|cards]]) keep their own size.

- **Double-click** a node for its properties, its code, or a rename — your
  choice in Settings. **Ctrl+double-click** opens both in a window of its own
  you can leave open beside another node.
- **Right-click ▸ Appearance…** is one live dialog for everything about how a
  node looks: shape, colour, port names, and its mark (the category default,
  a drawn mark, a few characters of text, or a picture carried inside the
  project file).
- Select several nodes and right-click one: the menu acts on the whole
  **selection** — run, freeze, lock, deactivate, *Run only when asked*,
  appearance, add to a page — one undo step each.

## Frames

**Ctrl+G** wraps the selection in a comment frame. Drag a frame by its
**title bar** and its contents come with it. Frames can also gate execution
(*run only when asked*, *run on its own*) from their right-click menu.

## Wires without wires

**Goto / From** nodes carry a value across the canvas without a line: name it
at the Goto, pick it up at any number of Froms. A **Variables** node does the
same for settings — see [[Flow Variables]].

## Order edges

Sometimes order matters but no data passes — write a file, *then* read it
back. Every node has a small **flow pin** off each upper corner; drag one to
another node's and you have said "that one first". The dashed arc carries
nothing but is a real dependency: the dependent re-runs when its prerequisite
changes, and is held back if the prerequisite fails or is switched off.

The pins stay hidden until something is wired to them. Bring them up by
holding **Q**, via **Settings ▸ Canvas ▸ Show flow pins**, or per node from
its Appearance dialog. Right-click a dashed arc for **What is this?**

## Running

| Action | Binding |
| --- | --- |
| Run all | **F5** |
| Run selected | **F6** |
| Cancel | **Esc** |
| Run to this node | right-click a node |

Execution is a topological walk of the *dirty* subgraph on background
threads. Independent branches run at the same time, up to a worker limit
(**Settings ▸ General ▸ Nodes to run at once**, Auto by default). A node that
cannot share the process declares `NODE["exclusive"] = True` and runs alone.
Cancellation is cooperative and stops every node in flight.

**Ctrl+Z** undoes anything — every graph mutation is on the undo stack.

See [[Keyboard Shortcuts]] for the complete list.
