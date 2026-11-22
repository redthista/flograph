"""Regenerate src/flograph/docs/Themes.md: the hand-written guide below plus
a key table built from `themes/reference.py` and the reference theme, so the
handbook can never disagree with the code.

    python scripts/gen_theme_docs.py
"""
from pathlib import Path

from flograph.ui import themes
from flograph.ui.themes import reference

INTRO = """\
# Themes

A theme is a small text file of colours and a few drawing choices. flograph
ships **Dark**, **Light** and **Light Steel**; you can make your own, either
by hand or with the **Theme Customiser**, and switch between them from
**View ▸ Theme** or **Settings ▸ General ▸ Appearance**.

## The Theme Customiser

**Tools ▸ Theme Customiser…** edits every setting with the app following live:

- **Colours** — every setting with a swatch, a hex box and a ↺ button that puts
  the starting theme's value back. Select a setting to read what it does.
- **Text** — the whole theme as text in the code editor, each colour on a
  swatch of itself; double-click a colour to pick another. A wrong line is
  marked, and the app keeps the last good version until it is fixed.
- **Preview** — labelled examples: buttons, inputs and choices in their normal,
  default, focused, disabled and error states, a list, tabs, and a small canvas
  with nodes (normal, selected, broken, bypassed), every port colour, the
  three wire states and frames on a light and a dark colour.
- **⌖ Select element** — click any part of the app and the list jumps to the
  settings that style it.
- **Checks** — warnings, as you edit, for text, the keyboard-focus ring, wires,
  selection and code colours that are hard to see (WCAG contrast: 4.5:1 for
  text, 3:1 for things you must spot, 2:1 where a hairline only has to be
  visible). They are advice about a design choice: a theme with warnings still
  loads and works. Click one to go to the settings it is about.

Nothing is written until **Save theme**, which writes
`<your flograph folder>/themes/<name>.toml` listing only what differs from the
theme you started from. Closing without saving puts your saved theme back.

## A theme file

```toml
[meta]
label = "Light, warmer"
based_on = "light"        # inherits everything it does not set

[canvas]
CANVAS_BG = "#ece8e1"

[style]
node_corner_radius = 0    # square nodes
```

A key a theme does not set comes from `based_on` (default `dark`, which sets
every key). A file that cannot be read falls back to Dark rather than stopping
the app.

## Which setting wins

""" + reference.PRECEDENCE + """
## Interaction states

What a theme can say about states today, and where it comes from:

- **Selected** (nodes, wires, frames, tiles) — `canvas.SELECTION_OUTLINE`.
  Lists and menus use `ui.highlight`; the code editor `editor.SELECTION_BG`.
- **Keyboard focus** on a text input — `ui.input_focus`, `style.focus_width`
  thick (themes with `flat_controls`). Other controls use the style's own rim.
- **Hover** — the title bar and toolbar use `chrome.hover`/`pressed`; widgets
  with their own stylesheet use `surface.hover`/`pressed`; a wire or node under
  the pointer is drawn heavier in its own colour. Hover colours for nodes,
  ports and wires are not separate settings yet.
- **Disabled** — `ui.disabled_text`, `disabled_base`, `disabled_button`.
- **Bypassed / broken** — `canvas.BYPASS`; `NODE_HEADER_BROKEN` and
  `NODE_BORDER_BROKEN`.
- **Wire being dragged** — `WIRE_PENDING` (no target), `WIRE_VALID` (compatible
  port), `WIRE_INVALID` (incompatible).

## Colour is not the only signal

A broken node also carries a ⚠ in its title; a wire being dragged to an
incompatible port is dashed as well as red; a node's state shows in a light
*and* in its position in the run. Status lights by themselves are still colour
only (red/green): if that matters to you, the Preview and the contrast checks
help you pick a pair that differs in lightness as well as hue.

## Every setting

Defaults are the reference theme's (Dark). "Only when `flat_controls` is on"
means the setting has no effect in a theme that leaves that choice off.

"""

OUTRO = """
## Notes

- `category_colours` uses a fixed set of category colours chosen by flograph
  (io blue, transform violet, viz amber …); a theme turns them on or off but
  does not recolour them. They affect a node's outline and a thin tint, never
  its header.
- `FRAME_*` values are alphas. A frame's own colour is set on the frame
  (right-click ▸ colour), so overlapping frames mix.
- A `pin` in `PIN_STALE` / `PIN_HELD` is a node's **freeze** pin — the amber
  or cyan badge on a frozen node — not a port.
"""


def build() -> str:
    return INTRO + reference.markdown_tables(themes.load("dark")) + OUTRO


if __name__ == "__main__":
    target = (Path(__file__).resolve().parent.parent
              / "src" / "flograph" / "docs" / "Themes.md")
    target.write_text(build(), encoding="utf-8")
    print("wrote", target)
