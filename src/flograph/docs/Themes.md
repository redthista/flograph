# Themes

A theme is a small text file of colours and a few drawing choices. flograph
ships **Dark**, **Light**, **Dark Slate** and **Light Steel**; you can make your own, either
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

When two settings could colour the same thing, the more specific one wins:

* A node's own colour (set on the node) is tinted over canvas.NODE_BODY and canvas.NODE_HEADER; a broken node ignores it.
* style.one_tone_header decides whether the header is NODE_HEADER or NODE_BODY; style.category_colours only changes the outline and a thin tint.
* style.panel_borders makes ui.panel / panel_border / panel_title win over ui.window and ui.dock_title for docks.
* surface.* is read only by widgets that write their own colours; ui.* is read by Qt itself. Where a pair exists (ui.base/surface.base, ui.text/surface.text, ui.highlight/surface.selection, ui.panel/surface.panel) set both if you want them to agree: neither inherits from the other.
* chrome.* applies only to the title bar and toolbar, and ignores ui.
* canvas.SELECTION_OUTLINE is the canvas's selection; ui.highlight is a list's; editor.SELECTION_BG is the code editor's.

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

## The redesign's palette

**Light** and **Dark Slate** follow the palette of the 2026 UI redesign
(`docs/design/ui-ux-redesign-2026/`). **Dark** is the original dark theme,
unchanged, and remains the default. The redesign names its colours by role;
this is where each role lives in a theme file:

| Redesign colour | Theme keys | Light | Dark Slate |
| --- | --- | --- | --- |
| App background | `ui.window`, `ui.dock_title`, `chrome.bar_bg` | `#f4f6fa` | `#202a39` / `#141922` |
| Canvas | `canvas.CANVAS_BG` | `#e3e8ef` | `#111821` |
| Panel | `ui.panel`, `ui.base`, `surface.base` | `#ffffff` | `#202a39` / `#1a2230` |
| Node / card | `canvas.NODE_BODY`, `canvas.NODE_HEADER` | `#ffffff` | `#273344` |
| Border | `ui.line`, `ui.panel_border`, `surface.border` | `#d8e0ea` | `#364559` |
| Primary text | `ui.text`, `ui.window_text`, `canvas.NODE_TEXT` | `#1d2939` | `#e6edf7` |
| Secondary text | `ui.mid`, `canvas.NODE_SUBTEXT`, `surface.text_dim` | `#5b6b7d` | `#a7b7cb` |
| Accent | `ui.accent`, `ui.highlight`, `canvas.SELECTION_OUTLINE` | `#2869e8` | `#7aa9ff` |
| Default wires | `wires.dataframe`, `wires.series` | `#4f8696` | `#60899a` |

Light's canvas is a shade darker than the redesign's `#eef2f7`, which was too
close to white for a white node to stand off it.

## Every setting

Defaults are the reference theme's (Dark). "Only when `flat_controls` is on"
means the setting has no effect in a theme that leaves that choice off.

### `[ui]`

The window palette, handed to Qt. Everything that does not write its own colours follows it.

| Key | Default | What it does |
| --- | --- | --- |
| `window` | `#24262b` | Window background and the default fill behind everything that has no colour of its own — dialogs, the gutter between docks. Text on it is window_text. |
| `window_text` | `#e5e7eb` | Default text on window: labels, dock contents, dialogs. |
| `base` | `#1e2024` | Fill of text inputs, lists, tables and trees — the working areas. Text on it is text. |
| `alt_base` | `#202226` | Every second row of a striped list or table. |
| `text` | `#e5e7eb` | Text typed into or listed in base areas (inputs, lists, tables). |
| `button` | `#24262b` | Push button face. Label colour is button_text. |
| `button_text` | `#e5e7eb` | Push button label. |
| `bright_text` | `#f87171` | Text that must stand out on a coloured fill (Qt BrightText) — error-ish. |
| `light` | `#3a3d47` | Qt bevel role: the lit edge of raised controls. Only visible where a control draws a 3D edge. |
| `midlight` | `#2f323b` | Qt bevel role between light and the face; also lightly shades hovered controls. |
| `dark` | `#141517` | Qt bevel role: the shadowed edge of raised controls; also the sunken groove of sliders and progress bars. |
| `mid` | `#8b929e` | Qt bevel role that flograph also uses as its DIM TEXT colour (palette(mid)): unselected tab labels, secondary labels. Keep it readable on window. |
| `shadow` | `#0c0d0f` | Qt bevel role: the darkest edge and drop shadows of native-style controls. |
| `placeholder` | `#7f8694` | Hint text in an empty input. |
| `tooltip_bg` | `#1e2024` | Tooltip background. |
| `tooltip_text` | `#e5e7eb` | Tooltip text. |
| `tooltip_border` | `#3a3d46` | Tooltip outline. |
| `highlight` | `#3b82f6` | Selected row/item in lists, tables, trees and menus, and selected text in inputs. NOT the canvas selection (canvas.SELECTION_OUTLINE) or the code editor's (editor.SELECTION_BG). |
| `highlighted_text` | `#ffffff` | Text drawn on highlight. |
| `link` | `#60a5fa` | Hyperlinks in the handbook, dialogs and reports. |
| `link_visited` | `#a78bfa` | Visited hyperlinks. |
| `accent` | `#60a5fa` | The app's one accent colour, handed to Qt as its Accent role (ticks, sliders, default-button emphasis on Qt 6.6+). Used for selection and focus when the theme does not set its own. |
| `disabled_text` | `#6b7280` | Text of disabled controls (any text role in the Disabled state). |
| `disabled_base` | `#1b1d21` | Fill of disabled inputs. |
| `disabled_button` | `#24262b` | Fill of disabled buttons, and the selection colour of disabled lists. |
| `dock_title` | `#2a2c33` | Dock title strip (Properties, Log, Library …). With panel_borders on, panel_title wins instead. |
| `tab` | `#24262b` | Unselected tab background (page tabs, dock tab groups). |
| `tab_selected` | `#33363e` | Selected tab background. |
| `tab_bar` | `#2a2c33` | The strip a panel's tabs sit on (Properties \| Code \| Log, the Inspector's port tabs), so the tab row reads apart from the panel beneath it. |
| `statusbar` | `#202226` | Status bar at the bottom of the window. |
| `line` | `#24262b` | Hairline rules — dock title underline, status bar top rule, menu separators, dock gaps. Only drawn when style.flat_controls is on. |
| `accent_line` | `#60a5fa` | Underline under the selected tab. Only when style.flat_controls is on. |
| `menu` | `#24262b` | Background of menus and context menus. Only when style.flat_controls is on (otherwise menus use window). |
| `menu_border` | `#3a3d47` | Outline of menus. Only when style.flat_controls is on. |
| `input_border` | `#3a3d47` | Outline of text inputs, combo boxes and spin boxes. Only when style.flat_controls is on. |
| `input_focus` | `#60a5fa` | Outline of the input that has keyboard focus, style.focus_width thick. Only when style.flat_controls is on. Keep it visible on base and window. |
| `scrollbar` | `#4b4e58` | Scroll bar handle. Only when style.flat_controls is on. |
| `scrollbar_hover` | `#5b5f68` | Scroll bar handle under the pointer. |
| `panel` | `#24262b` | Body of a dock. Only when style.panel_borders is on. Docks have no border of their own; they meet at a single ui.divider line. |
| `panel_border` | `#3a3d47` | The 1px line under a dock's title strip. Only when style.panel_borders is on. The lines BETWEEN panels are ui.divider. |
| `panel_title` | `#2a2c33` | Title strip of a dock. Only when style.panel_borders is on; wins over dock_title. |
| `divider` | `#3a3d47` | The line round the panels that you drag to resize or fold them away; style.divider_width thick. |

### `[chrome]`

Only the custom title bar and toolbar. They are always drawn from this section, whatever ui says.

| Key | Default | What it does |
| --- | --- | --- |
| `bar_bg` | `#17181c` | Custom title bar and toolbar background. |
| `bar_border` | `#14151a` | Line under the title bar / toolbar. |
| `fg` | `#c8cbd2` | Title bar and toolbar text and icons. |
| `fg_strong` | `#f3f4f6` | Emphasised title bar text: the project name, button labels under the pointer. |
| `fg_dim` | `#8b8f99` | Secondary title bar text: folder path, counts. |
| `fg_disabled` | `#5f636d` | Disabled title bar / toolbar buttons. |
| `hover` | `#34363f` | A title bar / toolbar button under the pointer. |
| `pressed` | `#3d404a` | A title bar / toolbar button while pressed. |
| `outline` | `#3c3f49` | Outline of buttons and fields on the bar. |
| `sep` | `#2c2d34` | Separator lines between toolbar groups. |
| `panel` | `#2b2d36` | Popup cards opened from the title bar (recent projects, flow meter). |
| `panel_line` | `#3a3d47` | Borders and hover fill inside those cards. |
| `star_off` | `#7f838d` | The "favourite" star when off. |
| `track` | `#1c1d23` | Empty groove of the bar's meters and progress rings. |
| `unselected` | `#4b5563` | Unselected state of the bar's toggle glyphs. |
| `frozen` | `#5b8def` | Marker for frozen state on the bar. |
| `run` | `#22c55e` | Run buttons' glyph colour. |
| `stop` | `#ef4444` | Stop button's glyph colour. |
| `reset` | `#eab308` | Reset-caches button's glyph colour. |
| `close_hover` | `#e5484d` | Window close button under the pointer. |

### `[canvas]`

The node graph and the things drawn like it (dashboard tiles, minimap, monitors).

| Key | Default | What it does |
| --- | --- | --- |
| `CANVAS_BG` | `#1b1c20` | Canvas background. Also the base for the minimap and node search backdrops. |
| `GRID_FINE` | `#232429` | Fine grid lines. |
| `GRID_COARSE` | `#2c2d34` | Coarse (every Nth) grid lines; also borders of the minimap and monitors. |
| `NODE_BODY` | `#2a2c33` | Node body fill. Also dashboard tile and Table card surfaces. A node with its own colour is tinted over this. |
| `NODE_HEADER` | `#363943` | Node header strip. Wins over NODE_BODY unless style.one_tone_header is on; a node's own colour is tinted over it instead. |
| `NODE_HEADER_BROKEN` | `#4c2626` | Header of a node whose script failed to load. Wins over every other header colour. |
| `NODE_BORDER` | `#17181c` | Node outline (idle). With style.category_colours on, a node's category colour replaces it. |
| `NODE_BORDER_BROKEN` | `#7f1d1d` | Outline of a broken node. |
| `NODE_TEXT` | `#e5e7eb` | Node titles and card text. |
| `NODE_SUBTEXT` | `#9ca3af` | Secondary node text: port names, counts, the compact node's caption. |
| `SELECTION_OUTLINE` | `#60a5fa` | Selected node, frame, wire, tile and minimap viewport; the canvas's selection and hover emphasis colour (distinct from ui.highlight). |
| `PIN_STALE` | `#eab308` | A node's FREEZE pin when its upstream has changed since it was frozen (amber: worth a look). Also the amber of the "heavy node" badge. Not a port pin. |
| `PIN_HELD` | `#22d3ee` | A node's FREEZE pin when the frozen result is still current (cyan). Not a port pin. |
| `BYPASS` | `#e879f9` | Bypassed node's overlay and its marker in the minimap. |
| `MEM_CACHE` | `#60a5fa` | Memory bar: the part held by cached results. |
| `MEM_APP` | `#3b6299` | Memory bar: the rest of flograph's process. |
| `MEM_OTHER` | `#4b4e58` | Memory bar: other programs' memory. |
| `FRAME_TITLE` | `#d1d5db` | Text of a frame's title. |
| `BUTTON_ACCENT` | `#7c6cf6` | Fill of in-canvas buttons (Button node, Run buttons on cards, page links). |
| `WIRE_VALID` | `#4ade80` | A wire being dragged onto a compatible port. |
| `WIRE_INVALID` | `#ef4444` | A wire being dragged onto an incompatible port; a rejected connection. |
| `WIRE_PENDING` | `#93c5fd` | A wire being dragged with no target yet. |

### `[status]`

The status lights on nodes and in the minimap.

| Key | Default | What it does |
| --- | --- | --- |
| `idle` | `#6b7280` | Status light: not run. |
| `queued` | `#eab308` | Status light: waiting for its turn. |
| `running` | `#3b82f6` | Status light: running. |
| `done` | `#22c55e` | Status light: finished. soft_done paler-greens it in the minimap. |
| `error` | `#ef4444` | Status light: failed. Also error text throughout. |

### `[wires]`

One colour per data type, for wires and ports.

| Key | Default | What it does |
| --- | --- | --- |
| `any` | `#e8e8e8` | Wire and port colour for the "any" type. |
| `dataframe` | `#2dd4bf` | Wire and port colour for tables. |
| `series` | `#7dd3c8` | Wire and port colour for columns. |
| `number` | `#4ade80` | Wire and port colour for numbers. |
| `string` | `#fbbf24` | Wire and port colour for text. |
| `bool` | `#f87171` | Wire and port colour for true/false. |
| `object` | `#9ca3af` | Wire and port colour for objects. |
| `figure` | `#c084fc` | Wire and port colour for charts. |
| `flow` | `#94a3b8` | Wire and port colour for order edges (the dashed arcs). |

### `[frame]`

Alphas (0 to 1) that say how much of a frame's own colour shows. They do not choose the colour: the frame's colour is set per frame.

| Key | Default | What it does |
| --- | --- | --- |
| `FRAME_FILL` | `0.18` | How much of a frame's own colour fills its body — an ALPHA (0 = transparent, 1 = solid) laid over whatever is behind, so overlapping frames mix. |
| `FRAME_TITLE_BAR` | `0.45` | Alpha of the frame's colour on its title bar. |
| `FRAME_FOLDED` | `0.45` | Alpha of the colour on a collapsed frame. |
| `FRAME_CHIP` | `0.4` | Alpha of the colour on a frame's small label chip. |
| `FRAME_CHIP_HOVER` | `0.65` | Alpha of the chip under the pointer. |

### `[surface]`

Widgets written for the dark theme carry hard-coded dark colours in their own stylesheets; each such colour plays a role, and this section says what that role becomes. Prefer ui where a widget follows the palette.

| Key | Default | What it does |
| --- | --- | --- |
| `base` | `#1e2024` | Widget-stylesheet role: the face of lists, inputs and cards in dialogs and docks that write their own colours. Follows ui.base's job. |
| `base_alt` | `#202226` | Widget-stylesheet role: alternate rows. |
| `panel` | `#24262c` | Widget-stylesheet role: cards, groups and tool panels. Same job as ui.panel, for widgets that carry their own stylesheet. |
| `raised` | `#2f323b` | Widget-stylesheet role: raised strips such as headers and ribbons. |
| `hover` | `#34363f` | Widget-stylesheet role: an item under the pointer. |
| `pressed` | `#3d404a` | Widget-stylesheet role: an item being pressed. |
| `line` | `#3a3d47` | Widget-stylesheet role: hairlines inside widgets. |
| `border` | `#3c3f49` | Widget-stylesheet role: normal widget outlines. |
| `border_strong` | `#4b5563` | Widget-stylesheet role: emphasised outlines and splitters. |
| `deep` | `#14151a` | Widget-stylesheet role: the sunken background behind cards. |
| `shadow` | `#0c0d0f` | Widget-stylesheet role: darkest backgrounds and shadows. |
| `text_strong` | `#f3f4f6` | Widget-stylesheet role: headings and emphasised text. |
| `text` | `#d6d8de` | Widget-stylesheet role: normal text. Same job as ui.text for widgets that carry their own stylesheet. |
| `text_soft` | `#aeb2bc` | Widget-stylesheet role: secondary text. |
| `text_dim` | `#8b909c` | Widget-stylesheet role: hints and captions. |
| `text_disabled` | `#5f636d` | Widget-stylesheet role: disabled text. |
| `selection` | `#264f78` | Widget-stylesheet role: selected rows and items. Same job as ui.highlight for widgets that carry their own stylesheet. |
| `selection_soft` | `#2b3550` | Widget-stylesheet role: a quieter selection (inactive, or a hover-selection). |
| `error_bg` | `#4b1d24` | Widget-stylesheet role: background of an error message or cell. |
| `ok_bg` | `#3b4a2a` | Widget-stylesheet role: background of a success message. |
| `warn_bg` | `#6b5a1a` | Widget-stylesheet role: background of a warning. |
| `accent_text` | `#93c5fd` | Widget-stylesheet role: links and accent-coloured text. |
| `error_text` | `#f87171` | Widget-stylesheet role: error text. |
| `warn_text` | `#fbbf24` | Widget-stylesheet role: warning text. |
| `ok_text` | `#86efac` | Widget-stylesheet role: success text. |

### `[editor]`

The code editor's own surfaces (it does not use the window palette).

| Key | Default | What it does |
| --- | --- | --- |
| `GUTTER_BG` | `#202226` | Code editor line-number column. |
| `GUTTER_FG` | `#5c6370` | Line numbers. |
| `GUTTER_FG_CURRENT` | `#9ca3af` | The current line's number. |
| `CURRENT_LINE_BG` | `#24262d` | Band behind the line the caret is on (swatches in the theme editor are drawn over it). |
| `EDITOR_BG` | `#1b1c20` | Code editor background; also the background of node text boxes that pop out to an editor. |
| `EDITOR_FG` | `#d7dae0` | Code editor text that has no syntax colour. |
| `SELECTION_BG` | `#264f78` | Selected text in the code editor. |
| `ERROR_LINE_BG` | `#4b1d24` | Background of a line with an error. |
| `MATCH_BG` | `#3b4a2a` | Find matches. |
| `CURRENT_MATCH_BG` | `#6b5a1a` | The find match you are on. |
| `ERROR_DOT` | `#ef4444` | Error marker in the gutter and its wavy underline. |

### `[syntax]`

Highlighting in the code editor and the small-language boxes.

| Key | Default | What it does |
| --- | --- | --- |
| `keyword` | `#c678dd` | Python keywords (def, if, return …); also keywords in rule/expression boxes and section names in theme text. |
| `builtin` | `#56b6c2` | Python builtins (len, print …); also names of settings in theme text. |
| `self` | `#e06c75` | self and cls in Python code. |
| `def_name` | `#61afef` | The name after def or class in Python code. |
| `decorator` | `#e5c07b` | @decorators in Python code. |
| `string` | `#98c379` | Quoted strings. Python code, rule boxes and theme text. Anything the highlighter has no token for uses editor.EDITOR_FG. |
| `number` | `#d19a66` | Numbers in Python code, rule boxes and theme text. |
| `comment` | `#5c6370` | Comments in Python code, rule boxes and theme text. |

### `[style]`

On/off and size choices about how things are drawn.

| Key | Default | What it does |
| --- | --- | --- |
| `node_shadow` | `False` | true = a soft drop shadow lifts each node off the canvas. |
| `category_colours` | `False` | true = a node's outline (and a thin tint) takes its category's colour; the categories' colours are fixed by flograph. Does not change the header: see one_tone_header and canvas.NODE_HEADER. |
| `one_tone_header` | `False` | true = a node's header is the same colour as its body (NODE_BODY) instead of NODE_HEADER. A node with its own colour, and a broken node, ignore this. |
| `card_shadow` | `dark` | How a dashboard tile's shadow is drawn, when its Format turns one on: "dark" (a heavy shadow, for dark themes) or "soft" (a pale one). No tile has a shadow by default. |
| `soft_done` | `False` | true = the minimap draws finished nodes in a paler green. |
| `flat_controls` | `False` | true = inputs, menus and scroll bars are drawn flat with hairline borders from ui (line, menu, menu_border, input_border, input_focus, scrollbar); false = Qt's own bevelled look. |
| `panel_borders` | `False` | true = each dock is a bordered card (ui.panel, panel_border, panel_title) with a gutter of window colour between docks. |
| `divider_width` | `1` | Pixels: the thickness of the line round the panels. 0 to 12. |
| `focus_width` | `2` | Pixels: the thickness of the keyboard-focus outline on inputs (ui.input_focus). 1 to 4. Only when flat_controls is on. |
| `node_corner_radius` | `7` | Pixels: node corner roundness. 0 = square. Up to 40. |
| `node_width` | `170` | Pixels: width of an ordinary (wide) node. 100 to 400. |
| `node_header_height` | `26` | Pixels: the title strip of a wide node. 16 to 60. |
| `node_row_height` | `20` | Pixels: one row of ports on a wide node. 14 to 48. |
| `node_compact_size` | `60` | Pixels: the side of a compact (square) node. 40 to 120. |

## Notes

- `category_colours` uses a fixed set of category colours chosen by flograph
  (io blue, transform violet, viz amber …); a theme turns them on or off but
  does not recolour them. They affect a node's outline and a thin tint, never
  its header.
- `FRAME_*` values are alphas. A frame's own colour is set on the frame
  (right-click ▸ colour), so overlapping frames mix.
- A `pin` in `PIN_STALE` / `PIN_HELD` is a node's **freeze** pin — the amber
  or cyan badge on a frozen node — not a port.
