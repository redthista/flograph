"""What every theme key does, in words — the single source for the customiser's
tooltips, its checks, and the handbook's Themes page.

Each line is ``section.key: what it paints. Where it shows.`` and every key in
``dark.toml`` must have one (``tests/test_themes.py`` fails if one is missing
or left over). Qt-free.
"""
from __future__ import annotations

_TEXT = """
ui.window: Window background and the default fill behind everything that has no colour of its own — dialogs, the gutter between docks. Text on it is window_text.
ui.window_text: Default text on window: labels, dock contents, dialogs.
ui.base: Fill of text inputs, lists, tables and trees — the working areas. Text on it is text.
ui.alt_base: Every second row of a striped list or table.
ui.text: Text typed into or listed in base areas (inputs, lists, tables).
ui.button: Push button face. Label colour is button_text.
ui.button_text: Push button label.
ui.bright_text: Text that must stand out on a coloured fill (Qt BrightText) — error-ish.
ui.light: Qt bevel role: the lit edge of raised controls. Only visible where a control draws a 3D edge.
ui.midlight: Qt bevel role between light and the face; also lightly shades hovered controls.
ui.dark: Qt bevel role: the shadowed edge of raised controls; also the sunken groove of sliders and progress bars.
ui.mid: Qt bevel role that flograph also uses as its DIM TEXT colour (palette(mid)): unselected tab labels, secondary labels. Keep it readable on window.
ui.shadow: Qt bevel role: the darkest edge and drop shadows of native-style controls.
ui.placeholder: Hint text in an empty input.
ui.tooltip_bg: Tooltip background.
ui.tooltip_text: Tooltip text.
ui.tooltip_border: Tooltip outline.
ui.highlight: Selected row/item in lists, tables, trees and menus, and selected text in inputs. NOT the canvas selection (canvas.SELECTION_OUTLINE) or the code editor's (editor.SELECTION_BG).
ui.highlighted_text: Text drawn on highlight.
ui.link: Hyperlinks in the handbook, dialogs and reports.
ui.link_visited: Visited hyperlinks.
ui.accent: The app's one accent colour, handed to Qt as its Accent role (ticks, sliders, default-button emphasis on Qt 6.6+). Used for selection and focus when the theme does not set its own.
ui.disabled_text: Text of disabled controls (any text role in the Disabled state).
ui.disabled_base: Fill of disabled inputs.
ui.disabled_button: Fill of disabled buttons, and the selection colour of disabled lists.
ui.dock_title: Dock title strip (Properties, Log, Library …). With panel_borders on, panel_title wins instead.
ui.tab: Unselected tab background (page tabs, dock tab groups).
ui.tab_selected: Selected tab background.
ui.tab_bar: The strip a panel's tabs sit on (Properties | Code | Log, the Inspector's port tabs), so the tab row reads apart from the panel beneath it.
ui.statusbar: Status bar at the bottom of the window.
ui.line: Hairline rules — dock title underline, status bar top rule, menu separators, dock gaps. Only drawn when style.flat_controls is on.
ui.accent_line: Underline under the selected tab. Only when style.flat_controls is on.
ui.menu: Background of menus and context menus. Only when style.flat_controls is on (otherwise menus use window).
ui.menu_border: Outline of menus. Only when style.flat_controls is on.
ui.input_border: Outline of text inputs, combo boxes and spin boxes. Only when style.flat_controls is on.
ui.input_focus: Outline of the input that has keyboard focus, style.focus_width thick. Only when style.flat_controls is on. Keep it visible on base and window.
ui.scrollbar: Scroll bar handle. Only when style.flat_controls is on.
ui.scrollbar_hover: Scroll bar handle under the pointer.
ui.panel: Body of a dock. Only when style.panel_borders is on. Docks have no border of their own; they meet at a single ui.divider line.
ui.panel_border: The 1px line under a dock's title strip. Only when style.panel_borders is on. The lines BETWEEN panels are ui.divider.
ui.panel_title: Title strip of a dock. Only when style.panel_borders is on; wins over dock_title.
ui.divider: The line round the panels that you drag to resize or fold them away; style.divider_width thick.
chrome.bar_bg: Custom title bar and toolbar background.
chrome.bar_border: Line under the title bar / toolbar.
chrome.fg: Title bar and toolbar text and icons.
chrome.fg_strong: Emphasised title bar text: the project name, button labels under the pointer.
chrome.fg_dim: Secondary title bar text: folder path, counts.
chrome.fg_disabled: Disabled title bar / toolbar buttons.
chrome.hover: A title bar / toolbar button under the pointer.
chrome.pressed: A title bar / toolbar button while pressed.
chrome.outline: Outline of buttons and fields on the bar.
chrome.sep: Separator lines between toolbar groups.
chrome.panel: Popup cards opened from the title bar (recent projects, flow meter).
chrome.panel_line: Borders and hover fill inside those cards.
chrome.star_off: The "favourite" star when off.
chrome.track: Empty groove of the bar's meters and progress rings.
chrome.unselected: Unselected state of the bar's toggle glyphs.
chrome.frozen: Marker for frozen state on the bar.
chrome.run: Run buttons' glyph colour.
chrome.stop: Stop button's glyph colour.
chrome.reset: Reset-caches button's glyph colour.
chrome.close_hover: Window close button under the pointer.
canvas.CANVAS_BG: Canvas background. Also the base for the minimap and node search backdrops.
canvas.GRID_FINE: Fine grid lines.
canvas.GRID_COARSE: Coarse (every Nth) grid lines; also borders of the minimap and monitors.
canvas.NODE_BODY: Node body fill. Also dashboard tile and Table card surfaces. A node with its own colour is tinted over this.
canvas.NODE_HEADER: Node header strip. Wins over NODE_BODY unless style.one_tone_header is on; a node's own colour is tinted over it instead.
canvas.NODE_HEADER_BROKEN: Header of a node whose script failed to load. Wins over every other header colour.
canvas.NODE_BORDER: Node outline (idle). With style.category_colours on, a node's category colour replaces it.
canvas.NODE_BORDER_BROKEN: Outline of a broken node.
canvas.NODE_TEXT: Node titles and card text.
canvas.NODE_SUBTEXT: Secondary node text: port names, counts, the compact node's caption.
canvas.SELECTION_OUTLINE: Selected node, frame, wire, tile and minimap viewport; the canvas's selection and hover emphasis colour (distinct from ui.highlight).
canvas.PIN_STALE: A node's FREEZE pin when its upstream has changed since it was frozen (amber: worth a look). Also the amber of the "heavy node" badge. Not a port pin.
canvas.PIN_HELD: A node's FREEZE pin when the frozen result is still current (cyan). Not a port pin.
canvas.BYPASS: Bypassed node's overlay and its marker in the minimap.
canvas.MEM_CACHE: Memory bar: the part held by cached results.
canvas.MEM_APP: Memory bar: the rest of flograph's process.
canvas.MEM_OTHER: Memory bar: other programs' memory.
canvas.FRAME_TITLE: Text of a frame's title.
canvas.BUTTON_ACCENT: Fill of in-canvas buttons (Button node, Run buttons on cards, page links).
canvas.WIRE_VALID: A wire being dragged onto a compatible port.
canvas.WIRE_INVALID: A wire being dragged onto an incompatible port; a rejected connection.
canvas.WIRE_PENDING: A wire being dragged with no target yet.
status.idle: Status light: not run.
status.queued: Status light: waiting for its turn.
status.running: Status light: running.
status.done: Status light: finished. soft_done paler-greens it in the minimap.
status.error: Status light: failed. Also error text throughout.
wires.any: Wire and port colour for the "any" type.
wires.dataframe: Wire and port colour for tables.
wires.series: Wire and port colour for columns.
wires.number: Wire and port colour for numbers.
wires.string: Wire and port colour for text.
wires.bool: Wire and port colour for true/false.
wires.object: Wire and port colour for objects.
wires.figure: Wire and port colour for charts.
wires.flow: Wire and port colour for order edges (the dashed arcs).
frame.FRAME_FILL: How much of a frame's own colour fills its body — an ALPHA (0 = transparent, 1 = solid) laid over whatever is behind, so overlapping frames mix.
frame.FRAME_TITLE_BAR: Alpha of the frame's colour on its title bar.
frame.FRAME_FOLDED: Alpha of the colour on a collapsed frame.
frame.FRAME_CHIP: Alpha of the colour on a frame's small label chip.
frame.FRAME_CHIP_HOVER: Alpha of the chip under the pointer.
surface.base: Widget-stylesheet role: the face of lists, inputs and cards in dialogs and docks that write their own colours. Follows ui.base's job.
surface.base_alt: Widget-stylesheet role: alternate rows.
surface.panel: Widget-stylesheet role: cards, groups and tool panels. Same job as ui.panel, for widgets that carry their own stylesheet.
surface.raised: Widget-stylesheet role: raised strips such as headers and ribbons.
surface.hover: Widget-stylesheet role: an item under the pointer.
surface.pressed: Widget-stylesheet role: an item being pressed.
surface.line: Widget-stylesheet role: hairlines inside widgets.
surface.border: Widget-stylesheet role: normal widget outlines.
surface.border_strong: Widget-stylesheet role: emphasised outlines and splitters.
surface.deep: Widget-stylesheet role: the sunken background behind cards.
surface.shadow: Widget-stylesheet role: darkest backgrounds and shadows.
surface.text_strong: Widget-stylesheet role: headings and emphasised text.
surface.text: Widget-stylesheet role: normal text. Same job as ui.text for widgets that carry their own stylesheet.
surface.text_soft: Widget-stylesheet role: secondary text.
surface.text_dim: Widget-stylesheet role: hints and captions.
surface.text_disabled: Widget-stylesheet role: disabled text.
surface.selection: Widget-stylesheet role: selected rows and items. Same job as ui.highlight for widgets that carry their own stylesheet.
surface.selection_soft: Widget-stylesheet role: a quieter selection (inactive, or a hover-selection).
surface.error_bg: Widget-stylesheet role: background of an error message or cell.
surface.ok_bg: Widget-stylesheet role: background of a success message.
surface.warn_bg: Widget-stylesheet role: background of a warning.
surface.accent_text: Widget-stylesheet role: links and accent-coloured text.
surface.error_text: Widget-stylesheet role: error text.
surface.warn_text: Widget-stylesheet role: warning text.
surface.ok_text: Widget-stylesheet role: success text.
editor.GUTTER_BG: Code editor line-number column.
editor.GUTTER_FG: Line numbers.
editor.GUTTER_FG_CURRENT: The current line's number.
editor.CURRENT_LINE_BG: Band behind the line the caret is on (swatches in the theme editor are drawn over it).
editor.EDITOR_BG: Code editor background; also the background of node text boxes that pop out to an editor.
editor.EDITOR_FG: Code editor text that has no syntax colour.
editor.SELECTION_BG: Selected text in the code editor.
editor.ERROR_LINE_BG: Background of a line with an error.
editor.MATCH_BG: Find matches.
editor.CURRENT_MATCH_BG: The find match you are on.
editor.ERROR_DOT: Error marker in the gutter and its wavy underline.
syntax.keyword: Python keywords (def, if, return …); also keywords in rule/expression boxes and section names in theme text.
syntax.builtin: Python builtins (len, print …); also names of settings in theme text.
syntax.self: self and cls in Python code.
syntax.def_name: The name after def or class in Python code.
syntax.decorator: @decorators in Python code.
syntax.string: Quoted strings. Python code, rule boxes and theme text. Anything the highlighter has no token for uses editor.EDITOR_FG.
syntax.number: Numbers in Python code, rule boxes and theme text.
syntax.comment: Comments in Python code, rule boxes and theme text.
style.node_shadow: true = a soft drop shadow lifts each node off the canvas.
style.category_colours: true = a node's outline (and a thin tint) takes its category's colour; the categories' colours are fixed by flograph. Does not change the header: see one_tone_header and canvas.NODE_HEADER.
style.one_tone_header: true = a node's header is the same colour as its body (NODE_BODY) instead of NODE_HEADER. A node with its own colour, and a broken node, ignore this.
style.card_shadow: How a dashboard tile's shadow is drawn, when its Format turns one on: "dark" (a heavy shadow, for dark themes) or "soft" (a pale one). No tile has a shadow by default.
style.soft_done: true = the minimap draws finished nodes in a paler green.
style.flat_controls: true = inputs, menus and scroll bars are drawn flat with hairline borders from ui (line, menu, menu_border, input_border, input_focus, scrollbar); false = Qt's own bevelled look.
style.panel_borders: true = each dock is a bordered card (ui.panel, panel_border, panel_title) with a gutter of window colour between docks.
style.divider_width: Pixels: the thickness of the line round the panels. 0 to 12.
style.focus_width: Pixels: the thickness of the keyboard-focus outline on inputs (ui.input_focus). 1 to 4. Only when flat_controls is on.
style.node_corner_radius: Pixels: node corner roundness. 0 = square. Up to 40.
style.node_width: Pixels: width of an ordinary (wide) node. 100 to 400.
style.node_header_height: Pixels: the title strip of a wide node. 16 to 60.
style.node_row_height: Pixels: one row of ports on a wide node. 14 to 48.
style.node_compact_size: Pixels: the side of a compact (square) node. 40 to 120.
"""

REFERENCE: dict[str, str] = {}
for _line in _TEXT.strip().splitlines():
    _key, _, _what = _line.partition(": ")
    REFERENCE[_key.strip()] = _what.strip()

SECTION_NOTES = {
    "ui": "The window palette, handed to Qt. Everything that does not write "
          "its own colours follows it.",
    "chrome": "Only the custom title bar and toolbar. They are always drawn "
              "from this section, whatever ui says.",
    "canvas": "The node graph and the things drawn like it (dashboard tiles, "
              "minimap, monitors).",
    "status": "The status lights on nodes and in the minimap.",
    "wires": "One colour per data type, for wires and ports.",
    "frame": "Alphas (0 to 1) that say how much of a frame's own colour "
             "shows. They do not choose the colour: the frame's colour is "
             "set per frame.",
    "surface": "Widgets written for the dark theme carry hard-coded dark "
               "colours in their own stylesheets; each such colour plays a "
               "role, and this section says what that role becomes. Prefer "
               "ui where a widget follows the palette.",
    "editor": "The code editor's own surfaces (it does not use the window "
              "palette).",
    "syntax": "Highlighting in the code editor and the small-language boxes.",
    "style": "On/off and size choices about how things are drawn.",
}

PRECEDENCE = """\
When two settings could colour the same thing, the more specific one wins:

* A node's own colour (set on the node) is tinted over canvas.NODE_BODY and \
canvas.NODE_HEADER; a broken node ignores it.
* style.one_tone_header decides whether the header is NODE_HEADER or \
NODE_BODY; style.category_colours only changes the outline and a thin tint.
* style.panel_borders makes ui.panel / panel_border / panel_title win over \
ui.window and ui.dock_title for docks.
* surface.* is read only by widgets that write their own colours; ui.* is \
read by Qt itself. Where a pair exists (ui.base/surface.base, \
ui.text/surface.text, ui.highlight/surface.selection, ui.panel/surface.panel) \
set both if you want them to agree: neither inherits from the other.
* chrome.* applies only to the title bar and toolbar, and ignores ui.
* canvas.SELECTION_OUTLINE is the canvas's selection; ui.highlight is a list's; \
editor.SELECTION_BG is the code editor's.
"""


def describe(section: str, key: str) -> str:
    return REFERENCE.get(f"{section}.{key}", "")


def markdown_tables(theme) -> str:
    """The Themes handbook page's key tables, from the live reference theme."""
    from . import SECTIONS
    out = []
    for section in SECTIONS:
        items = theme.values.get(section)
        if not items:
            continue
        out += [f"### `[{section}]`", "", SECTION_NOTES.get(section, ""), "",
                "| Key | Default | What it does |", "| --- | --- | --- |"]
        for key, value in items.items():
            text = REFERENCE.get(f"{section}.{key}", "").replace("|", "\\|")
            out.append(f"| `{key}` | `{value}` | {text} |")
        out.append("")
    return "\n".join(out)
