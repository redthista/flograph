"""The one place colours come from.

Which colours is a *theme*: a TOML file of named colours in
`flograph/ui/themes/` (`dark.toml`, `light.toml`) or in the user's own
`themes/` folder — see `flograph.ui.themes` for the format. This module
turns the active theme into everything Qt needs: the application palette
and stylesheet, the canvas constants, the title-bar colours, and the
translation that makes the dark hex written into older widget stylesheets
follow the theme (`set_qss` / `skin`).

The constants below (`NODE_BODY`, `CANVAS_BG`, ...) are module state that
`apply_theme` rewrites in place, so painting code must read them as
`theme.NODE_BODY` at paint time, never copy them at import.

Adding a theme needs no code: a new `.toml` that sets the colours it
changes, `based_on` the theme it starts from.
"""
from __future__ import annotations

import re
import weakref

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QApplication

from flograph.core import PortType
from flograph.core.node import NodeStatus
from flograph.ui import themes as _themes

# The reference theme: dark, the look every widget was first written in.
# Its colours are what older stylesheets have spelled out in hex.
_REFERENCE = _themes.load(_themes.REFERENCE)
ACTIVE: _themes.Theme = _REFERENCE

# ------------------------------------------------------------------ canvas
#
# Filled from the active theme by `_apply_canvas`; the assignments here are
# only so the names exist (and are dark) before anything is themed.

CANVAS_BG = GRID_FINE = GRID_COARSE = QColor()
NODE_BODY = NODE_HEADER = NODE_HEADER_BROKEN = QColor()
NODE_BORDER = NODE_BORDER_BROKEN = NODE_TEXT = NODE_SUBTEXT = QColor()
SELECTION_OUTLINE = QColor()
# PIN_STALE: frozen, but the inputs have moved since (amber — deliberate but
# no longer true). PIN_HELD: frozen and still true; ice, apart from every
# status colour, since the minimap must tell it from all four at 4px.
# BYPASS: a bypassed node and the line drawn through it.
PIN_STALE = PIN_HELD = BYPASS = QColor()
# Status-bar memory bar, brightest first: the project's cached outputs, the
# rest of flograph, everything else. One hue stepping down in brightness.
MEM_CACHE = MEM_APP = MEM_OTHER = QColor()
FRAME_TITLE = BUTTON_ACCENT = QColor()
WIRE_VALID = WIRE_INVALID = WIRE_PENDING = QColor()

STATUS_COLORS: dict[NodeStatus, QColor] = {}

# How much of a frame's own colour shows, as alpha over the canvas.
FRAME_FILL = FRAME_TITLE_BAR = FRAME_FOLDED = 0.0
FRAME_CHIP = FRAME_CHIP_HOVER = 0.0

# ------------------------------------------------------------------- tinting
#
# User-picked colours are never painted flat. A colour straight from the
# picker is fully saturated and fights the theme; laid over the themed
# surface at low alpha it keeps its hue but takes the theme's value, which is
# why frames have always looked calm. These are the canonical strengths —
# SOFT for large surfaces (a card body, an unselected tab), STRONG for the
# smaller strip that has to stand out from it (a header, the selected tab).
#
# How muted is a matter of taste, so Settings > Canvas can retune both. The
# current values are module state that painting code must read at paint time
# (theme.TINT_SOFT, never a module-level copy taken at import) — otherwise a
# settings change won't reach it until restart.

DEFAULT_TINT_SOFT = 0.30
DEFAULT_TINT_STRONG = 0.55

TINT_SOFT = DEFAULT_TINT_SOFT
TINT_STRONG = DEFAULT_TINT_STRONG


def set_tints(soft: float, strong: float) -> None:
    """Retune the muting. Callers repaint; this only moves the numbers."""
    global TINT_SOFT, TINT_STRONG
    TINT_SOFT = max(0.0, min(1.0, soft))
    TINT_STRONG = max(0.0, min(1.0, strong))


def tint(base: QColor, color, alpha: float) -> QColor:
    """`color` laid over `base` at `alpha`, as an opaque colour.

    Composited here rather than by painting translucently so callers get a
    concrete colour they can hand to a brush, gradient or stylesheet.
    """
    over = QColor(color)
    return QColor(
        round(over.red() * alpha + base.red() * (1 - alpha)),
        round(over.green() * alpha + base.green() * (1 - alpha)),
        round(over.blue() * alpha + base.blue() * (1 - alpha)),
    )


def page_tint(color, alpha: float = None) -> QColor:
    """A page's own colour as it is laid **over** its tab, or None when
    the page has no colour.

    Translucent, unlike `tint` above: the themed tab shows through, so
    whatever the colour picker returned comes out muted rather than
    garish. Read at paint time, so Settings ▸ Canvas reaches it without a
    restart — hence the default resolved here rather than in a signature
    that is bound at import.

    One definition because three places have to agree on it: the tab bar,
    the second row of pages, and the pixmap Qt makes of a tab being
    dragged (`dashboard.page_bar.DraggedTabStyle`).
    """
    if not color:
        return None
    over = QColor(color)
    over.setAlphaF(TINT_STRONG if alpha is None else alpha)
    return over


def wire_color(port_type: PortType) -> QColor:
    return QColor(ACTIVE.get("wires", PortType(port_type).value))


def status_color(status: NodeStatus) -> QColor:
    return STATUS_COLORS[status]


def _apply_canvas() -> None:
    """Point the canvas constants at the active theme, in place."""
    g = globals()
    for name, value in ACTIVE.section("frame").items():
        g[name] = float(value)
    for name, hexcode in ACTIVE.section("canvas").items():
        g[name] = QColor(hexcode)
    for status in NodeStatus:
        STATUS_COLORS[status] = QColor(ACTIVE.get("status", status.value))


# ------------------------------------------------------------ the theme

def current() -> _themes.Theme:
    """The theme in force."""
    return ACTIVE


def color(section: str, key: str) -> QColor:
    """Any colour of the active theme, e.g. `color("editor", "EDITOR_BG")`."""
    return QColor(ACTIVE.get(section, key))


def style(key: str):
    """One of the active theme's on/off style choices (`[style]`)."""
    return ACTIVE.section("style").get(key, _REFERENCE.get("style", key))


def chrome(key: str) -> str:
    """A title-bar / toolbar colour (hex string) for the current theme."""
    return ACTIVE.get("chrome", key)


# ------------------------------------------------------------------ skin
#
# Most of flograph's widgets were drawn in the dark theme first, with their
# colours written into a stylesheet or a QColor as hex. Each such colour
# plays a role — a list's face, a divider, dim text — and `_SKIN_ROLES`
# says which. In any theme but the reference, `skin` swaps the hex for the
# active theme's colour in that role, so a widget keeps writing the dark
# value it always has and still follows the theme. A status or brand
# colour that means the same everywhere (the purple accent, white) has no
# role and is left alone.

_SKIN_ROLES: dict[str, tuple[str, str]] = {}


def _roles(section: str, key: str, *hexes: str) -> None:
    for h in hexes:
        _SKIN_ROLES[h.lower()] = (section, key)


_roles("surface", "deep", "#14151a", "#111318")
_roles("surface", "shadow", "#0c0d0f")
_roles("surface", "base", "#1e2024", "#1f2026", "#1f2024", "#202127")
_roles("surface", "base_alt", "#202226")
_roles("surface", "panel", "#23252c", "#24262c", "#24262d", "#25272e")
_roles("surface", "raised", "#2f323b")
_roles("surface", "hover", "#34363f")
_roles("surface", "pressed", "#3e414c", "#3d404a")
_roles("surface", "line", "#3a3d47")
_roles("surface", "border", "#3c3f49", "#3a3d46", "#3b3d46", "#3a3e47",
       "#4b4e58")
_roles("surface", "border_strong", "#44475a", "#4b4f5c", "#4b5563",
       "#5b5f68")
_roles("surface", "text_disabled", "#5d616c", "#5f636d", "#6b7080")
_roles("surface", "text_strong", "#f3f4f6", "#f4f5f7")
_roles("surface", "text", "#d6d8de", "#c8cbd2", "#c9ccd3", "#d7dae0")
_roles("surface", "text_soft", "#aeb2bc")
_roles("surface", "text_dim", "#8b909c", "#8b8f99", "#9aa0ab", "#9aa0a6",
       "#9da5b4")
_roles("surface", "selection", "#3b4a7a", "#264f78")
_roles("surface", "selection_soft", "#1e3a5f", "#2b3550", "#33415c")
_roles("surface", "error_bg", "#4b1d24")
_roles("surface", "ok_bg", "#3b4a2a")
_roles("surface", "warn_bg", "#6b5a1a")
_roles("surface", "accent_text", "#93c5fd")
_roles("surface", "error_text", "#f87171", "#ef4444")
_roles("surface", "warn_text", "#fde68a", "#fbbf24", "#eab308")
_roles("surface", "ok_text", "#86efac")
# The canvas constants are written *into* stylesheets as `dark_hex(NAME)`,
# so the reference canvas colours are roles too, and win over the above.
for _name in ("CANVAS_BG", "GRID_FINE", "GRID_COARSE", "NODE_BODY",
              "NODE_HEADER", "NODE_BORDER", "NODE_TEXT", "NODE_SUBTEXT",
              "SELECTION_OUTLINE", "FRAME_TITLE"):
    _roles("canvas", _name, _REFERENCE.get("canvas", _name))

#: dark hex -> the active theme's hex; empty while the reference is active.
_SKIN: dict[str, str] = {}


def _build_skin() -> None:
    _SKIN.clear()
    if ACTIVE.name == _REFERENCE.name:
        return
    for dark, (section, key) in _SKIN_ROLES.items():
        _SKIN[dark] = ACTIVE.get(section, key).lower()


def dark_hex(name: str) -> str:
    """The reference (dark) hex of canvas constant `name`, for a stylesheet
    that will go through `set_qss` / `skin`."""
    return _REFERENCE.get("canvas", name)


_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def skin(text: str) -> str:
    """`text` (a stylesheet, or one hex colour) as the active theme wants
    it. The identity under the reference theme."""
    if not _SKIN or "#" not in text:
        return text
    return _HEX.sub(lambda m: _SKIN.get(m.group(0).lower(), m.group(0)), text)


def skin_color(color) -> QColor:
    """A QColor written for the dark theme, as the active theme wants it."""
    c = QColor(color)
    mapped = _SKIN.get(c.name().lower())
    if mapped is None:
        return c
    out = QColor(mapped)
    out.setAlpha(c.alpha())
    return out


# widget -> the dark-theme stylesheet it was given, so a live switch can
# translate it again. Weak: a closed dialog must not be kept alive by this.
_skinned: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def set_qss(widget, qss) -> None:
    """`widget.setStyleSheet(qss)` for a stylesheet written in dark-theme
    colours: translated for the theme now, and again on every theme change.
    `qss` may also be a function returning the stylesheet, called afresh on
    each change — for a sheet that depends on a `[style]` switch, not only
    on colours."""
    try:
        _skinned[widget] = qss
    except TypeError:
        pass                      # not weak-referenceable: no live switch
    widget.setStyleSheet(skin(qss() if callable(qss) else qss))


def _restyle_skinned() -> None:
    for widget, qss in list(_skinned.items()):
        try:
            widget.setStyleSheet(skin(qss() if callable(qss) else qss))
        except RuntimeError:
            pass                  # the C++ half is already gone


def card_look(note: bool = False):
    """The look of a dashboard tile that has not been formatted — the
    theme's card. `core.tile_style.CARD_LOOK` is that card in dark-theme
    hex (core is Qt-free and knows no theme), so the colours that follow
    the theme are filled in here."""
    from dataclasses import replace
    from flograph.core.tile_style import CARD_LOOK, NOTE_LOOK
    if note:
        return NOTE_LOOK          # every colour of it is left to the painter
    if ACTIVE.name == _REFERENCE.name:
        return CARD_LOOK
    return replace(
        CARD_LOOK, frame_color=NODE_BORDER.name(),
        background=NODE_BODY.name(), title_color=NODE_TEXT.name(),
        title_background=NODE_HEADER.name(),
        shadow=CARD_LOOK.shadow or style("card_shadow") == "soft")


# A node's category as a colour: the one splash of identity a card has when
# the theme asks for it (`category_colours`), since a light card's body is
# white whatever it does.
CATEGORY_COLOURS = {
    "io": "#3b82f6", "input": "#14b8a6", "transform": "#8b5cf6",
    "viz": "#f59e0b", "util": "#64748b", "scripting": "#ec4899",
    "ai": "#6366f1", "ml": "#a855f7", "connect": "#0ea5e9",
    "automation": "#f97316",
}


def category_color(category: str) -> QColor | None:
    """The category colour, or None where the theme carries none."""
    if not style("category_colours"):
        return None
    return QColor(CATEGORY_COLOURS.get(
        (category or "").split("/")[0].strip().lower(), "#94a3b8"))


def category_tint(category: str, alpha: float) -> QColor | None:
    """The category colour laid thinly over a card's body, or None. KNIME's
    habit, and the one most people already read: a node's colour says what
    kind of step it is before its name does."""
    base = category_color(category)
    if base is None:
        return None
    return tint(NODE_BODY, base, alpha)


def category_edge(category: str) -> QColor | None:
    """A node's outline in its category's colour, deepened a little so a
    one-pixel line still reads on white — or None."""
    base = category_color(category)
    if base is None:
        return None
    return tint(QColor("#475569"), base, 0.78)


_listeners: list = []


def on_change(callback) -> None:
    """Call `callback()` after every `apply_theme`. Held strongly, so pass
    a bound method of something that lives as long as the app (the main
    window), not a short-lived widget."""
    if callback not in _listeners:
        _listeners.append(callback)


def off_change(callback) -> None:
    if callback in _listeners:
        _listeners.remove(callback)


# ------------------------------------------------------------------- app
#
# The stored preference is "system" or a theme's name. Painting code that
# wants a colour must read it (or a `palette(...)` role in a stylesheet) at
# paint time, never a copy taken at import — a live switch moves this
# module state and re-polishes, it does not restart.

#: The built-in preferences. `theme_prefs()` adds any user themes.
THEME_PREFS = ("system", "light", "dark")

#: The active theme's *kind* — "light" or "dark", never "system". What a
#: drawing decision that depends only on light-vs-dark reads (a shadow's
#: colour, say); a design choice belongs in the theme's `[style]` instead.
APP_MODE = "dark"


def is_dark() -> bool:
    return APP_MODE != "light"


def _user_dir():
    try:
        from flograph.paths import user_data_dir
        return user_data_dir() / "themes"
    except Exception:             # an unreadable home must not stop the app
        return None


def theme_prefs() -> tuple:
    """Every preference that can be stored: "system", then each theme."""
    return ("system",) + tuple(_themes.available(_user_dir()))


def theme_label(pref: str) -> str:
    """How a preference is shown in Settings."""
    if pref == "system":
        return "Follow the system"
    try:
        return _themes.load(pref, _user_dir()).label
    except _themes.ThemeError:
        return pref


# Every visual role, spelled out. An unset QPalette role is resolved from
# the *system* palette, which is how a light desktop leaked pale text into
# flograph's dark theme — some colours flograph's, some the OS's. Nothing
# below is left unset, and Active / Inactive / Disabled are all filled, so
# the theme looks the same on a light desktop, a dark one, and an
# unfocused window.
_PALETTE_ROLES = (
    (QPalette.Window, "window"), (QPalette.WindowText, "window_text"),
    (QPalette.Base, "base"), (QPalette.AlternateBase, "alt_base"),
    (QPalette.ToolTipBase, "tooltip_bg"), (QPalette.ToolTipText, "tooltip_text"),
    (QPalette.PlaceholderText, "placeholder"),
    (QPalette.Text, "text"), (QPalette.Button, "button"),
    (QPalette.ButtonText, "button_text"), (QPalette.BrightText, "bright_text"),
    (QPalette.Light, "light"), (QPalette.Midlight, "midlight"),
    (QPalette.Dark, "dark"), (QPalette.Mid, "mid"),
    (QPalette.Shadow, "shadow"),
    (QPalette.Highlight, "highlight"),
    (QPalette.HighlightedText, "highlighted_text"),
    (QPalette.Link, "link"), (QPalette.LinkVisited, "link_visited"),
)

_GROUPS = (QPalette.Active, QPalette.Inactive, QPalette.Disabled)


def _make_palette(c: dict) -> QPalette:
    palette = QPalette()
    for group in _GROUPS:
        for role, key in _PALETTE_ROLES:
            palette.setColor(group, role, QColor(c[key]))
    accent = getattr(QPalette, "Accent", None)     # Qt 6.6+
    if accent is not None:
        for group in _GROUPS:
            palette.setColor(group, accent, QColor(c["accent"]))
    # Disabled: dimmer text, sunk fills — a real state, not an OS artefact.
    for role, key in (
            (QPalette.WindowText, "disabled_text"),
            (QPalette.Text, "disabled_text"),
            (QPalette.ButtonText, "disabled_text"),
            (QPalette.HighlightedText, "disabled_text"),
            (QPalette.Base, "disabled_base"),
            (QPalette.Button, "disabled_button"),
            (QPalette.Highlight, "disabled_button")):
        palette.setColor(QPalette.Disabled, role, QColor(c[key]))
    return palette


def _app_stylesheet(c: dict) -> str:
    return f"""
        QToolTip {{ background: {c['tooltip_bg']}; color: {c['tooltip_text']};
                    border: 1px solid {c['tooltip_border']}; }}
        /* Qt draws its own 1px frame round every dock, list, tree and the
           canvas view. Beside the divider line that made three lines where
           one was asked for, so the only lines between panels are ours. */
        QDockWidget {{ border: none; }}
        QDockWidget QAbstractScrollArea {{ border: none; }}
        QGraphicsView {{ border: none; }}
        QDockWidget::title {{ background: {c['dock_title']}; padding: 4px 8px; }}
        QTabBar::tab {{ background: {c['tab']}; padding: 5px 12px; border: none; }}
        QTabBar::tab:selected {{ background: {c['tab_selected']}; }}
        QStatusBar {{ background: {c['statusbar']}; }}
    """


def _flat_controls(c: dict) -> str:
    """What a light UI does that a dark one gets for free from contrast:
    areas told apart by hairlines and one accent, not by value; flat menus
    and thin scroll bars. Only for themes whose `[style]` asks for it, so
    the dark chrome is exactly what it was."""
    return f"""
        QDockWidget::title {{ border-bottom: 1px solid {c['line']};
                              font-weight: 600; }}
        QTabBar::tab {{ color: palette(mid);
                        border-bottom: 2px solid transparent; }}
        QTabBar::tab:hover {{ color: palette(window-text); }}
        QTabBar::tab:selected {{ color: palette(window-text);
                                 border-bottom: 2px solid {c['accent_line']}; }}
        QStatusBar {{ border-top: 1px solid {c['line']}; }}
        QToolTip {{ border-radius: 4px; padding: 4px 7px; }}
        QMainWindow::separator {{ background: {c['line']};
                                  width: 1px; height: 1px; }}
        QMenu {{ background: {c['menu']}; border: 1px solid {c['menu_border']};
                 padding: 4px 0; }}
        QMenu::item {{ padding: 5px 24px 5px 22px; background: transparent; }}
        QMenu::item:selected {{ background: {c['highlight']};
                                color: {c['highlighted_text']}; }}
        QMenu::item:disabled {{ color: {c['disabled_text']}; }}
        QMenu::separator {{ height: 1px; background: {c['line']};
                            margin: 4px 8px; }}
        QScrollBar:vertical {{ background: transparent; width: 11px;
                               margin: 0; }}
        QScrollBar:horizontal {{ background: transparent; height: 11px;
                                 margin: 0; }}
        QScrollBar::handle:vertical {{ background: {c['scrollbar']};
            min-height: 28px; border-radius: 3px; margin: 2px 3px; }}
        QScrollBar::handle:horizontal {{ background: {c['scrollbar']};
            min-width: 28px; border-radius: 3px; margin: 3px 2px; }}
        QScrollBar::handle:hover {{ background: {c['scrollbar_hover']}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0;
                                                     border: none; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
        {_input_outlines(c)}
    """


def _input_outlines(c: dict) -> str:
    """A hairline round every plain text input and a thicker `input_focus`
    outline on the one with keyboard focus (`[style] focus_width`).

    Only line edits: a combo box or spin box with a border of its own loses
    Qt's drawn arrows, so those keep the style's own focus rim. The padding
    gives back what the thicker focus line takes, so a field does not jump
    in size when it gains focus."""
    width = max(1, int(style("focus_width")))
    give = width - 1
    return f"""
        QLineEdit {{ border: 1px solid {c['input_border']};
                     border-radius: 3px; padding: 2px 4px;
                     background: palette(base); }}
        QLineEdit:focus {{ border: {width}px solid {c['input_focus']};
                           padding: {2 - min(give, 2)}px {4 - min(give, 4)}px; }}
    """


def _panel_borders(c: dict) -> str:
    """Each dock as its own card: a bordered white panel, title included,
    with a gutter of window colour between neighbours, so Properties, Log
    and the Inspector read as separate things rather than one pale sheet.
    Only for themes whose `[style]` asks for it."""
    return f"""
        QMainWindow::separator {{ background: {c['window']};
                                  width: 6px; height: 6px; }}
        QDockWidget {{ border: none; }}
        QDockWidget::title {{ background: {c['panel_title']};
                              border: none;
                              border-bottom: 1px solid {c['panel_border']};
                              padding: 2px 8px; }}
        QDockWidget > QWidget {{ background: {c['panel']}; border: none; }}
    """


def resolve_theme_pref(app: QApplication, pref: str) -> str:
    """Turn a stored preference into the name of the theme to apply."""
    if pref != "system":
        return pref
    scheme = app.styleHints().colorScheme()
    return "light" if scheme == Qt.ColorScheme.Light else "dark"


def _set_active(name: str, custom: "_themes.Theme | None" = None) -> None:
    global ACTIVE, APP_MODE
    if custom is not None:
        ACTIVE = custom           # the customiser's unsaved preview
    else:
        try:
            ACTIVE = _themes.load(name, _user_dir())
        except _themes.ThemeError:
            ACTIVE = _REFERENCE   # a broken user theme must not stop the app
    APP_MODE = ACTIVE.kind
    _apply_canvas()
    _build_skin()


def user_dir():
    """Where user themes live (`<user data dir>/themes`), or None."""
    return _user_dir()


def apply_theme(app: QApplication, pref: str = "dark",
                custom: "_themes.Theme | None" = None) -> None:
    """Style the whole application for `pref`: "system" or a theme name.

    Re-callable: a live theme switch just calls this again, and Qt's own
    StyleChange / ApplicationPaletteChange propagation re-polishes every
    open widget; listeners (`on_change`) redraw what Qt cannot.
    """
    if custom is None and pref not in theme_prefs():
        pref = "system"

    # Pin the scheme when the user chose a theme outright, so a platform
    # theme (GTK on Fedora, say) stops pushing its own palette values back
    # over ours — the cause of dark-on-dark text on a light desktop. In
    # "system" mode it is unset *first*, so the resolve below reads the OS
    # scheme and not a value pinned on a previous call.
    hints = app.styleHints()
    try:
        hints.unsetColorScheme()
    except AttributeError:
        pass                       # Qt < 6.8 — palette alone still applies
    _set_active(resolve_theme_pref(app, pref), custom)
    if pref != "system" or custom is not None:
        try:
            hints.setColorScheme(Qt.ColorScheme.Light if APP_MODE == "light"
                                 else Qt.ColorScheme.Dark)
        except AttributeError:
            pass

    colors = ACTIVE.section("ui")
    app.setStyle("Fusion")
    app.setPalette(_make_palette(colors))
    app.setStyleSheet(_app_stylesheet(colors)
                      + (_flat_controls(colors) if style("flat_controls")
                         else "")
                      + (_panel_borders(colors) if style("panel_borders")
                         else ""))
    _restyle_skinned()
    for callback in list(_listeners):
        try:
            callback()
        except RuntimeError:
            _listeners.remove(callback)      # its owner was deleted


_set_active(_REFERENCE.name)


class _BackgroundFiller(QObject):
    """Paints a scroll area's background just before the widget paints it.

    Exists so that WA_OpaquePaintEvent can stay switched on -- see
    style_scroll_area for why that matters. The filter runs ahead of the
    widget's own paint handler and returns False, so everything is drawn on
    top of the fill exactly as before; the only difference is that no pixel
    is left untouched, which is the promise the attribute makes.
    """

    def __init__(self, area, color: QColor | None) -> None:
        super().__init__(area)
        # None = the card body colour *now*, so a theme switch needs no
        # re-wiring of a grid that was filled with the old one
        self._color = QColor(color) if color is not None else None
        viewport = area.viewport()
        viewport.installEventFilter(self)
        viewport.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Paint:
            painter = QPainter(obj)
            painter.fillRect(event.rect(), self._color or NODE_BODY)
            painter.end()
        return False


def grid_stylesheet() -> str:
    """The dark table look shared by canvas cards, dashboard tiles and the
    dashboard's maximized pages — one definition so a grid reads the same
    wherever it appears. Apply it with style_scroll_area, not setStyleSheet.

    The text size is the one from Settings ▸ General when it has been
    set, so a grid on a card shrinks with the inspector's rather than
    keeping a size of its own.
    """
    from .data_table import GRID_FONT_PT, table_text_size
    points = table_text_size() or GRID_FONT_PT
    return (f"QTableView {{ background: {dark_hex('NODE_BODY')};"
            f" color: {dark_hex('NODE_TEXT')}; border: none;"
            f" gridline-color: {dark_hex('NODE_BORDER')};"
            f" font-size: {points:g}pt; }}"
            f"QHeaderView::section {{ background: {dark_hex('NODE_HEADER')};"
            f" color: {dark_hex('NODE_SUBTEXT')};"
            f" border: 1px solid {dark_hex('NODE_BORDER')}; padding: 2px; }}"
            # the corner above the row numbers, and a header's empty stretch
            # past its last section: without these the app palette shows
            # through, which is a light square in light mode
            f"QTableCornerButton::section {{ background: {dark_hex('NODE_HEADER')};"
            f" border: 1px solid {dark_hex('NODE_BORDER')}; }}"
            f"QHeaderView {{ background: {dark_hex('NODE_BODY')}; }}")


def style_scroll_area(area, stylesheet: str, background: QColor = None) -> None:
    """Style a table/list without costing it its scroll-blitting.

    A QAbstractScrollArea carrying a stylesheet has QStyleSheetStyle take
    over its viewport background, and Qt then clears WA_OpaquePaintEvent --
    at which point QWidget::scroll() can no longer shift the pixels it
    already has, so every notch of the wheel re-renders the whole visible
    area instead of the one row that came into view. Measured on a 300-row
    grid: 2,268 cells redrawn per scroll against 168, 8.3 ms against 1.0 ms.
    The cost grows with the widget, so a maximized dashboard page suffered
    worst -- and a maximized page is where data actually gets typed in.

    Setting the attribute back on alone is not enough: the area past the
    last column then paints as black, because the attribute is a promise the
    widget fills every pixel and a stylesheet-styled table does not. So the
    fill is supplied here, by an event filter, and the promise is kept.

    The palette route (QPalette::Base, ::Mid for grid lines) looks like the
    tidier answer and is not: with the app palette applied it neither
    reaches the viewport nor drives the grid line colour, so the grid comes
    out the wrong colour with no lines at all.
    """
    set_qss(area, stylesheet)
    existing = getattr(area, "_flograph_bg_filler", None)
    if existing is not None:
        existing.setParent(None)
    area._flograph_bg_filler = _BackgroundFiller(area, background)
