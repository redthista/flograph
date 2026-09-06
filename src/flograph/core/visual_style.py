"""Visual style — the design tokens a generated page is built from.

Qt-free on purpose, and the same shape as :mod:`flograph.core.table_format`:
the **Visual Style** node turns its parameters into a token dict and emits it
on a ``style`` port, and whatever draws the page turns those tokens into CSS.
Today that is **HTML Template**; the point of putting it here rather than in
the node is that any future visual can read the same tokens, so one node can
decide the look of a whole board.

A payload is deliberately **partial** — it holds only the tokens somebody
actually set. That is what lets a style be layered: an incoming style is the
base, the node's own settings override it, and anything nobody set falls
through to :data:`DEFAULTS`. A blank box means "inherit", never "black".

    payload = style_payload(params)          # partial: what was set
    merged  = merge_styles(incoming, payload)
    tok     = tokens(merged)                 # complete: ready to render
    css     = stylesheet(tok)

:func:`tokens` is the only function that resolves defaults, so a partial
payload can be passed around and merged as many times as you like without
picking up values nobody chose.

The defaults are the house look the shipped web visuals already use — the
same ``#0b1220`` ground, ``#e2e8f0`` text and mixed accent set as Sankey
Flow and Circle Pack — so an HTML Template dropped beside them matches
without being configured.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# --- the token vocabulary ---------------------------------------------------
#
# Keys here are what a payload may carry. Everything is a plain str/int/bool
# or a list of colours, so a payload round-trips through JSON untouched (it
# rides the ``style`` port and lands in the run cache).

_SYSTEM_FONT = ("system-ui, -apple-system, 'Segoe UI', Roboto, "
                "'Helvetica Neue', Arial, sans-serif")
_MONO_FONT = ("ui-monospace, SFMono-Regular, Menlo, Consolas, "
              "'Liberation Mono', monospace")

DEFAULTS: dict[str, Any] = {
    "theme": "dark",
    "bg": "#0b1220",
    "surface": "#131c2e",
    "fg": "#e2e8f0",
    "muted": "#94a3b8",
    "accent": "#2563eb",
    "border": "#1f2b45",
    "font": _SYSTEM_FONT,
    "heading_font": "",          # blank = use `font`
    "mono": _MONO_FONT,
    "size": 14,
    "heading_size": 26,
    "heading_weight": 700,
    "radius": 10,
    "gap": 14,
    "pad": 16,
    "shadow": True,
    "palette": ["#2563eb", "#10b981", "#f59e0b", "#ef4444", "#a855f7",
                "#14b8a6", "#f472b6", "#84cc16"],
}

#: Only the colours differ between the two themes — type, spacing and radius
#: are a house style, not a light/dark decision.
LIGHT: dict[str, Any] = {
    "theme": "light",
    "bg": "#f1f5f9",
    "surface": "#ffffff",
    "fg": "#0f172a",
    "muted": "#64748b",
    "accent": "#2563eb",
    "border": "#dbe3ec",
}

THEMES = ("dark", "light")

PALETTES: dict[str, list[str]] = {
    "mixed": list(DEFAULTS["palette"]),
    "cool": ["#1e3a8a", "#2563eb", "#38bdf8", "#67e8f9", "#a5f3fc",
             "#0ea5e9", "#6366f1", "#818cf8"],
    "warm": ["#7c2d12", "#ea580c", "#f59e0b", "#fde047", "#fb923c",
             "#dc2626", "#f472b6", "#facc15"],
    "vivid": ["#6366f1", "#ec4899", "#f59e0b", "#10b981", "#06b6d4",
              "#ef4444", "#8b5cf6", "#84cc16"],
    "earth": ["#4d7c0f", "#a16207", "#78350f", "#166534", "#0f766e",
              "#854d0e", "#3f6212", "#115e59"],
    "grey": ["#334155", "#475569", "#64748b", "#94a3b8", "#cbd5e1",
             "#1e293b", "#0f172a", "#e2e8f0"],
}

#: Friendly colour names accepted anywhere a colour is, so somebody can type
#: ``green`` instead of remembering a hex. Matches Table Style's vocabulary.
NAMED_COLOURS = {
    "green": "#10b981", "red": "#ef4444", "amber": "#f59e0b",
    "blue": "#2563eb", "grey": "#64748b", "gray": "#64748b",
    "purple": "#a855f7", "teal": "#14b8a6", "pink": "#f472b6",
    "lime": "#84cc16", "cyan": "#38bdf8", "orange": "#fb923c",
    "white": "#ffffff", "black": "#000000",
}

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}"
                  r"|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

_COLOUR_KEYS = ("bg", "surface", "fg", "muted", "accent", "border")
_INT_KEYS = {"size": (8, 96), "heading_size": (8, 160),
             "heading_weight": (100, 900), "radius": (0, 80),
             "gap": (0, 120), "pad": (0, 160)}


class StyleError(ValueError):
    """A style setting that could not be understood."""


def colour(value: str) -> str:
    """A hex string or a friendly name, normalised to hex.

    Raises :class:`StyleError` rather than quietly emitting the input, because
    an unrecognised colour reaching CSS is an invisible failure — the browser
    drops the declaration and the element inherits something plausible.
    """
    text = str(value or "").strip()
    if not text:
        raise StyleError("empty colour")
    low = text.lower()
    if low in NAMED_COLOURS:
        return NAMED_COLOURS[low]
    if _HEX.match(text):
        return text.lower()
    if not text.startswith("#") and len(text) <= 3:
        raise StyleError(f"{text!r} is not a colour")
    raise StyleError(f"{text!r} is not a colour — use #rrggbb or one of: "
                     + ", ".join(sorted(NAMED_COLOURS)))


def parse_palette(text: str) -> list[str]:
    """A palette written out by hand: colours separated by commas or lines."""
    parts = [p.strip() for p in re.split(r"[,\n]", text or "") if p.strip()]
    return [colour(p) for p in parts]


def named_palette(name: str) -> list[str]:
    try:
        return list(PALETTES[str(name).strip().lower()])
    except KeyError:
        raise StyleError(f"unknown palette {name!r} — one of: "
                         + ", ".join(sorted(PALETTES))) from None


def style_payload(params: dict) -> dict:
    """Node parameters in, a **partial** token payload out.

    Blank / "keep" settings are left out entirely rather than written as a
    default, so this payload can be layered over another one.
    """
    p = params or {}
    tok: dict[str, Any] = {}
    errors: list[str] = []

    theme = str(p.get("theme", "") or "").strip().lower()
    if theme and theme != "keep":
        if theme not in THEMES:
            errors.append(f"unknown theme {theme!r}")
        else:
            tok["theme"] = theme

    for key in _COLOUR_KEYS:
        raw = str(p.get(key, "") or "").strip()
        if not raw:
            continue
        try:
            tok[key] = colour(raw)
        except StyleError as exc:
            errors.append(f"{key}: {exc}")

    for key, (low, high) in _INT_KEYS.items():
        raw = p.get(key, "")
        if raw in ("", None):
            continue
        try:
            tok[key] = max(low, min(high, int(raw)))
        except (TypeError, ValueError):
            errors.append(f"{key}: {raw!r} is not a whole number")

    for key in ("font", "heading_font", "mono"):
        raw = str(p.get(key, "") or "").strip()
        if raw:
            tok[key] = raw

    shadow = p.get("shadow", "")
    if shadow not in ("", None, "keep"):
        tok["shadow"] = bool(shadow) and str(shadow).lower() not in (
            "false", "no", "off", "0")

    # A hand-written palette wins over the named one, so somebody can pick a
    # preset and then override it without first clearing the dropdown.
    custom = str(p.get("colors", "") or "").strip()
    preset = str(p.get("palette", "") or "").strip()
    if custom:
        try:
            found = parse_palette(custom)
            if found:
                tok["palette"] = found
        except StyleError as exc:
            errors.append(f"colors: {exc}")
    elif preset and preset.lower() != "keep":
        try:
            tok["palette"] = named_palette(preset)
        except StyleError as exc:
            errors.append(str(exc))

    return {"tokens": tok, "errors": errors}


def merge_styles(base: Optional[dict], own: Optional[dict]) -> dict:
    """Layer one payload over another; `own` wins where it says anything."""
    out_tokens: dict[str, Any] = {}
    errors: list[str] = []
    for payload in (base, own):
        if not isinstance(payload, dict):
            continue
        found = payload.get("tokens")
        if isinstance(found, dict):
            out_tokens.update(found)
        elif found is None and set(payload) & set(DEFAULTS):
            # tolerate a bare token dict, which is what a Python Script is
            # most likely to hand us; take only the keys we know
            out_tokens.update({k: v for k, v in payload.items()
                               if k in DEFAULTS})
        for message in payload.get("errors") or ():
            if message not in errors:
                errors.append(message)
    return {"tokens": out_tokens, "errors": errors}


def is_style(value: Any) -> bool:
    """Does this look like something :func:`tokens` can read?"""
    if not isinstance(value, dict):
        return False
    return isinstance(value.get("tokens"), dict) or bool(
        set(value) & set(DEFAULTS))


def tokens(payload: Optional[dict]) -> dict[str, Any]:
    """Resolve a payload to the **complete** set a renderer needs.

    The theme decides the colour base, then explicit tokens land on top — so
    "light, but with my accent" is two settings rather than seven.
    """
    merged = merge_styles(None, payload)["tokens"] if payload else {}
    theme = str(merged.get("theme", DEFAULTS["theme"])).lower()
    out = dict(DEFAULTS)
    if theme == "light":
        out.update(LIGHT)
    out.update(merged)
    out["theme"] = theme if theme in THEMES else DEFAULTS["theme"]
    if not out.get("heading_font"):
        out["heading_font"] = out["font"]
    palette = [c for c in (out.get("palette") or []) if c]
    out["palette"] = palette or list(DEFAULTS["palette"])
    return out


def css_variables(tok: dict) -> str:
    """The token set as CSS custom properties on ``:root``."""
    shadow = ("0 1px 3px rgba(0,0,0,.35), 0 8px 24px rgba(0,0,0,.18)"
              if tok.get("shadow") else "none")
    lines = [
        f"--bg:{tok['bg']}", f"--surface:{tok['surface']}",
        f"--fg:{tok['fg']}", f"--muted:{tok['muted']}",
        f"--accent:{tok['accent']}", f"--border:{tok['border']}",
        f"--font:{tok['font']}", f"--heading-font:{tok['heading_font']}",
        f"--mono:{tok['mono']}", f"--size:{tok['size']}px",
        f"--heading-size:{tok['heading_size']}px",
        f"--heading-weight:{tok['heading_weight']}",
        f"--radius:{tok['radius']}px", f"--gap:{tok['gap']}px",
        f"--pad:{tok['pad']}px", f"--shadow:{shadow}",
        "--cols:3",
    ]
    for index, value in enumerate(tok["palette"], 1):
        lines.append(f"--c{index}:{value}")
    return ":root{" + ";".join(lines) + "}"


def _palette_classes(tok: dict) -> str:
    out = []
    for index in range(1, len(tok["palette"]) + 1):
        out.append(f".c{index}{{color:var(--c{index})}}")
        out.append(f".bg{index}{{background:var(--c{index});color:#fff}}")
        out.append(f".fill{index}{{background:var(--c{index})}}")
    return "".join(out)


#: The kit. These class names are the vocabulary an HTML Template is written
#: in, and they are documented in the node — adding one is a public change.
_KIT = """
*,*::before,*::after{box-sizing:border-box}
html,body{margin:0;padding:0}
/* The margin lives on `body`, not on `.sheet`, so a page gets its breathing
   room whether or not whoever wrote the template reached for a wrapper.
   `body{padding:0}` in Extra CSS gives it back for a full-bleed design. */
body{background:var(--bg);color:var(--fg);font-family:var(--font);
  font-size:var(--size);line-height:1.45;-webkit-font-smoothing:antialiased;
  padding:var(--pad);print-color-adjust:exact;
  -webkit-print-color-adjust:exact}
img{max-width:100%}
.sheet{display:flex;flex-direction:column;gap:var(--gap)}
h1,h2,h3,.title{font-family:var(--heading-font);
  font-weight:var(--heading-weight);margin:0;letter-spacing:-.01em}
.title{font-size:var(--heading-size);line-height:1.15}
.subtitle{color:var(--muted);margin:0}
.grid{display:grid;gap:var(--gap);
  grid-template-columns:repeat(var(--cols),minmax(0,1fr))}
.row{display:flex;flex-wrap:wrap;gap:var(--gap)}
.row>*{flex:1 1 0;min-width:0}
.stack{display:flex;flex-direction:column;gap:calc(var(--gap)/2);min-width:0}
.split{display:flex;align-items:center;justify-content:space-between;
  gap:var(--gap)}
.card{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);padding:var(--pad);box-shadow:var(--shadow);
  min-width:0;break-inside:avoid}
.flat{box-shadow:none;background:transparent;border-color:transparent}
.big{font-size:calc(var(--size)*2.4);font-weight:var(--heading-weight);
  line-height:1.1;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.huge{font-size:calc(var(--size)*3.6);font-weight:var(--heading-weight);
  line-height:1;font-variant-numeric:tabular-nums;letter-spacing:-.03em}
.label{font-size:calc(var(--size)*.78);color:var(--muted);
  text-transform:uppercase;letter-spacing:.09em;font-weight:600}
.muted{color:var(--muted)}
.accent{color:var(--accent)}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.num{font-variant-numeric:tabular-nums}
.chip{display:inline-block;padding:2px 10px;border-radius:999px;
  background:var(--accent);color:#fff;font-size:calc(var(--size)*.8);
  font-weight:600}
.track{background:var(--border);border-radius:999px;height:8px;
  overflow:hidden;width:100%}
.bar{background:var(--accent);height:100%;border-radius:999px;
  width:calc(var(--v,0)*1%)}
.dot{display:inline-block;width:.6em;height:.6em;border-radius:50%;
  background:var(--accent);vertical-align:baseline}
.up{color:#10b981}
.down{color:#ef4444}
/* Semantic fills, deliberately not from the palette: "at risk" has to be
   red whichever accent run somebody picked. */
.good{background:#10b981;color:#fff}
.warn{background:#f59e0b;color:#1b1c20}
.bad{background:#ef4444;color:#fff}
.rule{height:1px;background:var(--border);border:0;margin:0}
.pick{cursor:pointer;transition:border-color .12s ease}
.pick:hover{border-color:var(--accent)}
.picked{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.dim{opacity:.42}
.right{text-align:right}
.center{text-align:center}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-size:calc(var(--size)*.8);text-transform:uppercase;
  letter-spacing:.06em}
a{color:var(--accent)}
/* No print override on `.sheet`: the breathing room around a visual is
   wanted on paper too, and stripping it there made a report embed sit hard
   against its own edge while the same page looked right on the card. */
"""


def stylesheet(tok: dict) -> str:
    """The complete CSS for a page: variables, the kit, palette classes."""
    return css_variables(tok) + _KIT + _palette_classes(tok)


def page(body: str, tok: dict, title: str = "", extra_css: str = "") -> str:
    """Wrap rendered markup in a complete, self-contained document.

    Nothing here is fetched — no font link, no script, no stylesheet href —
    so the page behaves the same on the card, in a dashboard tile, printed
    into a report and opened from a `file://` URL somewhere else entirely.
    """
    head = ("<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,"
            "initial-scale=1'>")
    if title:
        head += f"<title>{escape(title)}</title>"
    head += "<style>" + stylesheet(tok)
    if extra_css.strip():
        head += "\n" + extra_css
    head += "</style></head>"
    return head + f"<body>{body}</body></html>"


def escape(text: Any) -> str:
    """HTML-escape a value on its way into markup."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
