# Node Packs

A **node pack** adds a whole set of nodes to the library at once — a pack
of connectors for one company system, the nodes a team shares, or a
capability flograph does not ship with, such as image generation. Packs
are distributed on their own, not with flograph. Each pack gets its own
section in the library, titled with the pack's name.

## Adding a pack

Open **Tools ▸ Node Packs…**.

- **Install from .zip…** copies a pack into flograph's own folder. If you
  already have that pack, flograph asks before replacing it — which is
  also how you update one.
- **Link Folder…** uses a pack where it is, without copying it — for a
  pack you are writing, or one kept in a shared folder or a git checkout.
  A linked folder can hold several packs; every one of them is picked up.

A pack that needs Python packages it doesn't have says so in the **Status**
column. **Install Requirements…** opens **Manage Packages** with them
already filled in.

**Disable** keeps a pack but hides its nodes; **Remove** deletes an
installed pack (a linked one is only unlinked — its folder is never
touched). **More ▸ Open Example** opens any example flows the pack ships.

From a terminal, `flograph pack list`, `flograph pack install pack.zip`,
`flograph pack link FOLDER` and friends do the same — see
`flograph pack --help`.

## Flows that use a pack

A flow saves only which node it used, not the pack's code — the pack is
installed once, not copied into every project. The flow does record which
packs it used, so opening it where a pack is missing shows those nodes as
broken placeholders that say **which pack to install**. Their wiring and
settings are kept; install the pack and open the flow again.

Editing a pack node's code turns that one node into a fork, exactly like
editing a built-in node, and **Reset** brings it back.

## Making a pack

A pack is a folder with a `pack.toml` beside its nodes:

```
my_pack/
    pack.toml
    nodes/            node scripts — exactly like any other node
        fetch.py
        tidy/clean.py     (one level of subfolder is allowed)
    lib/              optional: Python code the nodes share
        client.py
    examples/         optional: .flograph files shown under Open Example
    README.md
```

```toml
[pack]
id = "my_pack"               # lower_snake_case, unique
name = "My Pack"             # the library section's title
version = "0.1.0"
author = "you"
description = "One line about what it adds."
requires = ["requests>=2.31"]   # Python packages the nodes import
```

Each node script follows the usual rules (see [[Writing a Node]]); its type
id becomes `pack.my_pack.fetch`. Its `NODE["category"]` groups it inside
the pack's section.

**`lib/` is what makes a pack more than a folder of nodes.** A node script
is run afresh every time — anything it builds is thrown away. Code in
`lib/` is an ordinary Python package, importable from a node as
`flograph_packs.my_pack`:

```python
def run(ctx, table):
    from flograph_packs.my_pack import client   # imported once per session
    return {"rows": client.fetch(table)}
```

It is imported once and stays imported, so it is the place for a
connection pool, a cache, or a model that takes seconds to load. Nothing in
`lib/` runs until a node first imports it, so a pack with heavy
requirements costs nothing when the library loads — but keep any import a
script makes at its *top level* light, because that runs when the library
is built.

### Settings

A pack that needs something set once per computer — where its files
live, the address of the server it talks to — declares it in `pack.toml`, and **Node Packs ▸
Settings…** shows a form for it:

```toml
[[settings]]
name = "server"
type = "string"            # folder, file, string, bool, int, float, choice
label = "Server address"
placeholder = "https://crm.example.com"
help = "One line under the box saying what it is for."
```

The pack's own code reads them back by its id:

```python
from flograph.core import packs
server = packs.settings("my_pack")["server"]   # "" until it is set
```

They are read fresh on every call, so a change applies to the next run.
Settings belong to the computer, not to a flow — they are never saved in a
.flograph, and removing and reinstalling a pack keeps them. Saving the form
reloads the packs, so a dropdown a setting fills (a list of model files) is
rebuilt; nodes already on the canvas keep the list they had until the flow
is opened again.

To share a pack, select it in **Node Packs** and use **More ▸ Export as
.zip…**.
