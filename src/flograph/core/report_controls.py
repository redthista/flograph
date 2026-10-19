"""Input controls inside a report's web page — Qt-free.

A Slider embedded in a report used to print its value: `![[Threshold]]`
was `50`. In the report page's Web preview it is now the slider itself,
and moving it re-runs the flow the way the canvas card does; the report
follows. That is the "interactive web app in the report view" (flograph
issue #14).

Three things are decided here, so the page, the paper and the window
cannot disagree:

* **What the widget shows** (`widget_state`). Bounds, clamping, options and
  the "never touched" defaults all come from `core.controls` — the same
  functions the canvas card and the node's run() use — so the number on
  the web page is the number the flow carries.
* **How it is drawn** (`widget_html`, `paper_text`). Native HTML inputs,
  built from that state. Enabled only in the app's own Web preview, which
  is the one page with a flow behind it; a saved file draws the same
  widget disabled at its current setting, and paper prints
  "Caption: value".
* **What a page may write back** (`accept`). A page can ask to change one
  control's value and nothing else: a control writes `value`, a slicer
  writes `selected`. The value is vetted against the widget's own state —
  a slider's number is clamped into its range, a choice must be one it
  offers — before the host turns it into an undoable command.

When an embed becomes a widget (`wants_widget`): a control embedded on a
line of its own, or any control or slicer with `|control`. A control inside
a sentence stays its value, and a Slicer — whose embed has always been its
filtered table — only becomes a picker when asked, so no existing report
changes what it shows.
"""
from __future__ import annotations

import html as _html
import json
from typing import Any, Optional

from . import control_apply as ca
from . import controls as cc

#: The embed flag that asks for the widget (core.report.EMBED_FLAGS).
FLAG = "control"

#: The control shapes the web page can draw. Others (File, Checklist,
#: Input Panel, Date Range) keep printing their value until they have a
#: web widget of their own.
SHAPES = frozenset({"slider", "range", "number", "text", "date", "toggle",
                    "choice", "multi", "time", "datetime", "colour"})


class ControlWriteError(ValueError):
    """A page asked a control for something it does not allow."""


# ------------------------------------------------------------- deciding

def kind_of(node) -> str:
    """"slicer", a control shape in SHAPES, or "" for anything else."""
    if node is None:
        return ""
    card = getattr(node.spec, "card", None)
    if card == "slicer":
        return "slicer"
    if card == "control" and (node.spec.control or "") in SHAPES:
        return node.spec.control
    return ""


def wants_widget(node, alone: bool, options: Optional[dict]) -> bool:
    """Whether this embed draws as a widget rather than as its value."""
    kind = kind_of(node)
    if not kind:
        return False
    if (options or {}).get(FLAG):
        return True
    return alone and kind != "slicer"


# --------------------------------------------------------------- state

def widget_state(node, upstream: Optional[dict] = None,
                 slicer_options=None, shown: bool = True) -> Optional[dict]:
    """What `node`'s widget shows, as plain JSON-able data; None when it
    has no web widget.

    `upstream` is what the control's own input ports supply
    (engine.introspect.control_upstream); `slicer_options` a Slicer's
    SlicerOptions. `shown` draws a held change (a draft waiting for
    Apply), as the canvas card does; False is the value the flow has —
    what paper prints.
    """
    kind = kind_of(node)
    if not kind:
        return None
    params = ca.shown_params(node.params) if shown else dict(node.params)
    upstream = dict(upstream or {})
    caption = str(params.get("caption", "") or "").strip()
    state: dict = {"id": node.id, "kind": kind, "caption": caption,
                   "label": node.label, "help":
                   str(params.get("help", "") or "").strip(),
                   "accent": str(params.get("accent", "") or "").strip(),
                   "mode": ca.apply_mode(node),
                   "pending": bool(ca.draft_text(node.params))}
    build = _BUILDERS[kind]
    if kind == "slicer":
        build(state, params, slicer_options)
    else:
        build(state, params, upstream)
    return state


def _wired(upstream: dict, port: str, fallback):
    value = upstream.get(port)
    return fallback if value is None else value


def _numeric(state: dict, params: dict, upstream: dict,
             low: float, high: float) -> None:
    minimum = cc.as_number(_wired(upstream, "minimum",
                                  params.get("minimum", low)), low)
    maximum = cc.as_number(_wired(upstream, "maximum",
                                  params.get("maximum", high)), high)
    if maximum < minimum:
        maximum = minimum
    state["min"], state["max"] = minimum, maximum
    state["step"] = float(params.get("step", 1) or 1) or 1.0
    state["decimals"] = max(0, int(params.get("decimals", 0) or 0))


def _rounded(state: dict, value: float):
    decimals = state.get("decimals", 0)
    return round(value, decimals) if decimals else int(round(value))


def _snap(state: dict, value: float):
    """`value` on the slider's grid of steps, inside its range — what the
    canvas slider can actually be set to."""
    step = state["step"]
    value = cc.clamp(value, state["min"], state["max"])
    steps = round((value - state["min"]) / step)
    snapped = cc.clamp(state["min"] + steps * step, state["min"], state["max"])
    return _rounded(state, snapped)


def _slider(state, params, upstream) -> None:
    _numeric(state, params, upstream, 0.0, 100.0)
    state["value"] = _snap(state, cc.as_number(params.get("value"),
                                               state["min"]))


def _range(state, params, upstream) -> None:
    _numeric(state, params, upstream, 0.0, 100.0)
    low, high = cc.range_values(params.get("value"), state["min"],
                                state["max"])
    state["value"] = [_snap(state, low), _snap(state, high)]


def _number(state, params, upstream) -> None:
    _numeric(state, params, upstream, 0.0, 100.0)
    state["value"] = _rounded(state, cc.clamp(
        cc.as_number(params.get("value"), state["min"]),
        state["min"], state["max"]))
    state["prefix"] = str(params.get("prefix", "") or "")
    state["suffix"] = str(params.get("suffix", "") or "")


def _text(state, params, upstream) -> None:
    state["value"] = str(params.get("value", "") or "")
    state["placeholder"] = str(_wired(upstream, "placeholder",
                                      params.get("placeholder", "")) or "")
    state["multiline"] = bool(params.get("multiline", False))
    state["mask"] = bool(params.get("mask", False))
    state["pattern"] = str(params.get("pattern", "") or "")
    state["pattern_message"] = str(params.get("pattern_message", "") or "")


def _date(state, params, upstream) -> None:
    state["allow_blank"] = bool(params.get("allow_blank", False))
    state["min"] = cc.as_iso_date(_wired(upstream, "minimum",
                                         params.get("minimum")))
    state["max"] = cc.as_iso_date(_wired(upstream, "maximum",
                                         params.get("maximum")))
    state["value"] = cc.date_value(params.get("value"),
                                   params.get("preset", "fixed"),
                                   params.get("days", 0),
                                   state["allow_blank"])


def _toggle(state, params, upstream) -> None:
    state["value"] = bool(params.get("value", False))
    state["text"] = str(_wired(upstream, "text",
                               params.get("text", "")) or "")
    state["style"] = str(params.get("style", "checkbox") or "checkbox")


def _choice(state, params, upstream) -> None:
    options = upstream.get("options")
    if options is None:
        options = cc.lines_to_values(params.get("items"))
    options = [str(o) for o in options]
    all_option = bool(params.get("all_option"))
    entries = [[cc.ALL_LABEL, ""]] if all_option else []
    entries += [[o, o] for o in options]
    value = cc.choice_value(params.get("value"), options, all_option)
    if value and value not in [v for _l, v in entries]:
        # kept, marked, never silently swapped — the canvas card's rule
        entries.append([f"{value}  (not in list)", value])
    state["entries"] = entries
    state["value"] = value
    state["style"] = str(params.get("style", "dropdown") or "dropdown")
    state["value_type"] = str(params.get("value_type", "text") or "text")


def _multi(state, params, upstream) -> None:
    options = upstream.get("options")
    if options is None:
        options = cc.lines_to_values(params.get("items"))
    options = [str(o) for o in options]
    picked = cc.selected_values(params.get("value"))
    state["options"] = options + [p for p in picked if p not in options]
    state["offered"] = options
    state["value"] = picked
    state["none_means"] = str(params.get("none_means", "all") or "all")


def _time(state, params, upstream) -> None:
    state["value"] = cc.time_value(params.get("value"))


def _datetime(state, params, upstream) -> None:
    state["value"] = cc.datetime_value(params.get("value"))


def _colour(state, params, upstream) -> None:
    state["value"] = cc.colour_value(params.get("value"))


def _slicer(state, params, options) -> None:
    from .slicer import path_label, selected_paths

    paths = list(getattr(options, "paths", None) or [])
    counts = dict(getattr(options, "counts", None) or {})
    picked = [tuple(p) for p in selected_paths(params.get("selected", ""))]
    state["single"] = str(params.get("mode", "multi")).strip() == "single"
    if state["single"]:
        picked = picked[:1]
    offered = set(paths)
    # a ticked value no longer in the data stays listed, as on the card
    rows = paths + [p for p in picked if p not in offered]
    state["entries"] = [[list(p), path_label(p), counts.get(p)]
                        for p in rows]
    state["value"] = [list(p) for p in picked]
    state["layout"] = ("dropdown" if params.get("layout") == "dropdown"
                       else "list")
    state["search"] = bool(params.get("show_search", True))
    state["buttons"] = bool(params.get("show_buttons", True))
    state["counts"] = bool(params.get("show_counts", False))
    # a slicer has no caption param: the columns it filters say what it
    # is, when it has been given any (heading() falls back to the label)
    from .slicer import slicer_columns
    state["caption"] = state["caption"] or ", ".join(
        slicer_columns(params.get("column", "")))


_BUILDERS = {"slider": _slider, "range": _range, "number": _number,
             "text": _text, "date": _date, "toggle": _toggle,
             "choice": _choice, "multi": _multi, "time": _time,
             "datetime": _datetime, "colour": _colour, "slicer": _slicer}


# ------------------------------------------------------------ the writes

def accept(state: dict, message: Any) -> tuple[str, Any]:
    """Vet one message from the page against the widget it came from.

    `message` is what the page sent: `{"value": ...}` to move the control,
    or `{"apply": true}` to press a held control's ✓. Returns
    `("value", stored)`, `("selected", stored)` for a slicer, or
    `("apply", None)`. Raises ControlWriteError for anything else — a page
    writing nonsense should show up as a message, not as a param quietly
    holding something run() will trip over.
    """
    if isinstance(message, str):
        try:
            message = json.loads(message) if message else None
        except ValueError:
            raise ControlWriteError("the page sent something that isn't "
                                    "JSON") from None
    if not isinstance(message, dict):
        raise ControlWriteError("the page sent no value")
    if message.get("apply"):
        if state["kind"] == "slicer" or state["mode"] != ca.BUTTON:
            raise ControlWriteError("this control has no ✓ to press")
        return "apply", None
    if "value" not in message:
        raise ControlWriteError("the page sent no value")
    value = message["value"]
    kind = state["kind"]
    if kind == "slicer":
        return "selected", _slicer_value(state, value)
    return "value", _VETTERS[kind](state, value)


def _number_in(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ControlWriteError(f"expected a number, got {value!r}")
    try:
        number = float(value)
    except ValueError:
        raise ControlWriteError(f"expected a number, got {value!r}") from None
    if number != number or number in (float("inf"), float("-inf")):
        raise ControlWriteError(f"a control cannot hold {number}")
    return number


def _vet_slider(state, value):
    return _snap(state, _number_in(value))


def _vet_range(state, value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ControlWriteError("a range is two numbers")
    low, high = sorted(_snap(state, _number_in(v)) for v in value)
    # the string the canvas card's RangeControl writes
    return json.dumps([low, high])


def _vet_number(state, value):
    return _rounded(state, cc.clamp(_number_in(value), state["min"],
                                    state["max"]))


def _vet_text(state, value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ControlWriteError(f"expected text, got {value!r}")
    return value


def _vet_date(state, value):
    text = str(value or "").strip()
    if not text:
        if state["allow_blank"]:
            return ""
        raise ControlWriteError("this date cannot be blank")
    day = cc.as_iso_date(text)
    if not day:
        raise ControlWriteError(f"{text!r} is not a date")
    if state["min"] and day < state["min"]:
        day = state["min"]
    if state["max"] and day > state["max"]:
        day = state["max"]
    return day


def _vet_toggle(state, value):
    if not isinstance(value, bool):
        raise ControlWriteError(f"expected ticked or not, got {value!r}")
    return value


def _vet_choice(state, value):
    text = "" if value is None else str(value)
    if text not in [v for _l, v in state["entries"]]:
        raise ControlWriteError(f"{text!r} is not one of the options")
    return text


def _vet_multi(state, value):
    if not isinstance(value, (list, tuple)):
        raise ControlWriteError("expected a list of ticked values")
    offered = state["options"]
    picked = [str(v) for v in value]
    stray = [v for v in picked if v not in offered]
    if stray:
        raise ControlWriteError(f"{stray[0]!r} is not one of the options")
    # in the options' order, the order the card's chips write
    return json.dumps([o for o in offered if o in picked])


def _vet_time(state, value):
    return cc.time_value(value)


def _vet_datetime(state, value):
    return cc.datetime_value(value)


def _vet_colour(state, value):
    return cc.colour_value(value, state["value"])


def _slicer_value(state, value) -> str:
    from .slicer import dump_paths

    if not isinstance(value, (list, tuple)):
        raise ControlWriteError("expected a list of ticked values")
    known = {tuple(path): path for path, _label, _count in state["entries"]}
    picked = []
    for item in value:
        path = tuple(str(v) for v in (item if isinstance(item, (list, tuple))
                                      else [item]))
        if path not in known:
            raise ControlWriteError(
                f"{' > '.join(path)!r} is not one of the slicer's values")
        if path not in picked:
            picked.append(path)
    if state["single"]:
        picked = picked[:1]
    return dump_paths(picked)


_VETTERS = {"slider": _vet_slider, "range": _vet_range,
            "number": _vet_number, "text": _vet_text, "date": _vet_date,
            "toggle": _vet_toggle, "choice": _vet_choice,
            "multi": _vet_multi, "time": _vet_time,
            "datetime": _vet_datetime, "colour": _vet_colour}


# ------------------------------------------------------------ the words

def display_value(state: dict) -> str:
    """The value as a person reads it — what paper prints after the
    caption, and what a disabled widget's readout says."""
    kind, value = state["kind"], state["value"]
    if kind == "slider":
        return _format_number(state, value)
    if kind == "range":
        return " – ".join(_format_number(state, v) for v in value)
    if kind == "number":
        return state["prefix"] + _format_number(state, value) + state["suffix"]
    if kind == "toggle":
        return "Yes" if value else "No"
    if kind == "choice":
        return value or cc.ALL_LABEL
    if kind == "multi":
        if value:
            return ", ".join(value)
        return "All" if state["none_means"] == "all" else "None"
    if kind == "slicer":
        if not value:
            return "All"
        from .slicer import path_label
        return ", ".join(path_label(p) for p in value)
    if kind == "date":
        return value or "No date"
    if kind == "datetime":
        return str(value).replace("T", " ")
    return str(value)


def _format_number(state: dict, value) -> str:
    decimals = state.get("decimals", 0)
    try:
        return (f"{float(value):,.{decimals}f}" if decimals
                else f"{int(round(float(value))):,}")
    except (TypeError, ValueError):
        return str(value)


def heading(state: dict) -> str:
    """The words in front of the value: the caption, else the node's
    label — a printed "50" with nothing to say what it is of tells a
    reader nothing."""
    return state["caption"] or state["label"]


def paper_text(state: dict) -> str:
    """"Caption: value", for paper and the Pages preview."""
    return f"{heading(state)}: {display_value(state)}"


# ------------------------------------------------------------- the HTML

def _esc(text: Any) -> str:
    return _html.escape(str(text), quote=True)


def _attr_json(value: Any) -> str:
    return _esc(json.dumps(value))


def widget_html(state: dict, enabled: bool) -> str:
    """The widget as HTML for the web page. `enabled` only in the app's
    own Web preview — anywhere else there is no flow for it to move."""
    kind = state["kind"]
    off = "" if enabled else " disabled"
    caption = _esc(heading(state))
    help_text = state.get("help") or ""
    tip = f' title="{_esc(help_text)}"' if help_text else ""
    info = (f'<span class="fg-ctl-help"{tip}>ⓘ</span>' if help_text else "")
    pending = state.get("pending") and enabled
    apply_button = ""
    if state.get("mode") == ca.BUTTON and kind != "slicer":
        lit = " fg-pending" if pending else ""
        apply_button = (f'<button type="button" class="fg-ctl-apply{lit}"'
                        f' data-fg-apply{off}>✓ Apply</button>')
    accent = cc.colour_value(state.get("accent"), "") if state.get(
        "accent") else ""
    style = f' style="--fg-ctl-accent:{accent}"' if accent else ""
    body = _BODIES[kind](state, off)
    return (f'<div class="fg-ctl fg-ctl-{kind}" data-fg-ctl="{_esc(state["id"])}"'
            f' data-fg-kind="{kind}"{style}>'
            f'<div class="fg-ctl-head"><span class="fg-ctl-caption">'
            f'{caption}</span>{info}{apply_button}</div>'
            f'{body}</div>')


def _body_slider(state, off) -> str:
    return (f'<div class="fg-ctl-row"><span class="fg-ctl-end">'
            f'{_esc(_format_number(state, state["min"]))}</span>'
            f'<input type="range" min="{state["min"]}" max="{state["max"]}"'
            f' step="{state["step"]}" value="{state["value"]}"'
            f' data-fg-decimals="{state["decimals"]}"{off}>'
            f'<span class="fg-ctl-end">'
            f'{_esc(_format_number(state, state["max"]))}</span></div>'
            f'<output class="fg-ctl-readout">'
            f'{_esc(display_value(state))}</output>')


def _body_range(state, off) -> str:
    low, high = state["value"]
    common = (f'min="{state["min"]}" max="{state["max"]}"'
              f' step="{state["step"]}"{off}')
    span = (state["max"] - state["min"]) or 1.0
    band = (f'--lo:{(low - state["min"]) / span * 100:.2f}%;'
            f'--hi:{(high - state["min"]) / span * 100:.2f}%')
    return (f'<div class="fg-ctl-row"><span class="fg-ctl-end">'
            f'{_esc(_format_number(state, state["min"]))}</span>'
            f'<div class="fg-ctl-twin" data-fg-decimals="{state["decimals"]}"'
            f' style="{band}">'
            f'<input type="range" data-fg-end="low" value="{low}" {common}>'
            f'<input type="range" data-fg-end="high" value="{high}" {common}>'
            f'</div><span class="fg-ctl-end">'
            f'{_esc(_format_number(state, state["max"]))}</span></div>'
            f'<output class="fg-ctl-readout">'
            f'{_esc(display_value(state))}</output>')


def _body_number(state, off) -> str:
    prefix = (f'<span class="fg-ctl-affix">{_esc(state["prefix"])}</span>'
              if state["prefix"] else "")
    suffix = (f'<span class="fg-ctl-affix">{_esc(state["suffix"])}</span>'
              if state["suffix"] else "")
    return (f'<div class="fg-ctl-row">{prefix}'
            f'<input type="number" min="{state["min"]}" max="{state["max"]}"'
            f' step="{state["step"]}" value="{state["value"]}"'
            f' data-fg-decimals="{state["decimals"]}"{off}>{suffix}</div>')


def _body_text(state, off) -> str:
    hint = (f' placeholder="{_esc(state["placeholder"])}"'
            if state["placeholder"] else "")
    pattern = (f' pattern="{_esc(state["pattern"])}"'
               if state["pattern"] else "")
    if state["pattern_message"]:
        pattern += f' title="{_esc(state["pattern_message"])}"'
    if state["multiline"]:
        return (f'<textarea rows="3"{hint}{off}>'
                f'{_esc(state["value"])}</textarea>')
    kind = "password" if state["mask"] else "text"
    return (f'<input type="{kind}" value="{_esc(state["value"])}"'
            f'{hint}{pattern}{off}>')


def _body_date(state, off) -> str:
    bounds = ""
    if state["min"]:
        bounds += f' min="{state["min"]}"'
    if state["max"]:
        bounds += f' max="{state["max"]}"'
    blank = ' data-fg-blank' if state["allow_blank"] else ""
    return (f'<input type="date" value="{_esc(state["value"])}"'
            f'{bounds}{blank}{off}>')


def _body_toggle(state, off) -> str:
    ticked = " checked" if state["value"] else ""
    switch = " fg-ctl-switch" if state["style"] == "switch" else ""
    return (f'<label class="fg-ctl-tick{switch}">'
            f'<input type="checkbox"{ticked}{off}>'
            f'<span>{_esc(state["text"])}</span></label>')


def _body_choice(state, off) -> str:
    value = state["value"]
    if state["style"] in ("buttons", "radio"):
        group = f'fg-{_esc(state["id"])}'
        items = []
        for label, option in state["entries"]:
            on = " checked" if option == value else ""
            items.append(f'<label><input type="radio" name="{group}"'
                         f' value="{_esc(option)}"{on}{off}>'
                         f'<span>{_esc(label)}</span></label>')
        style = "fg-ctl-buttons" if state["style"] == "buttons" \
            else "fg-ctl-radios"
        return f'<div class="{style}">{"".join(items)}</div>'
    items = []
    for label, option in state["entries"]:
        on = " selected" if option == value else ""
        items.append(f'<option value="{_esc(option)}"{on}>'
                     f'{_esc(label)}</option>')
    return f'<select{off}>{"".join(items)}</select>'


def _body_multi(state, off) -> str:
    picked = set(state["value"])
    offered = set(state["offered"])
    chips = []
    for option in state["options"]:
        on = " checked" if option in picked else ""
        label = option if option in offered else f"{option}  (not in list)"
        chips.append(f'<label><input type="checkbox"'
                     f' value="{_esc(option)}"{on}{off}>'
                     f'<span>{_esc(label)}</span></label>')
    return f'<div class="fg-ctl-buttons fg-ctl-chips">{"".join(chips)}</div>'


def _body_time(state, off) -> str:
    return f'<input type="time" value="{_esc(state["value"])}"{off}>'


def _body_datetime(state, off) -> str:
    return (f'<input type="datetime-local" value="{_esc(state["value"])}"'
            f'{off}>')


def _body_colour(state, off) -> str:
    return f'<input type="color" value="{_esc(state["value"])}"{off}>'


def _body_slicer(state, off) -> str:
    picked = {tuple(p) for p in state["value"]}
    kind = "radio" if state["single"] else "checkbox"
    group = f'fg-{_esc(state["id"])}'
    rows = []
    for path, label, count in state["entries"]:
        on = " checked" if tuple(path) in picked else ""
        tally = (f'<span class="fg-ctl-count">{count:,}</span>'
                 if state["counts"] and count is not None else "")
        rows.append(f'<label data-fg-label="{_esc(label.casefold())}">'
                    f'<input type="{kind}" name="{group}"'
                    f' value="{_attr_json(path)}"{on}{off}>'
                    f'<span>{_esc(label)}</span>{tally}</label>')
    tools = ""
    if state["search"]:
        tools += (f'<input type="search" class="fg-ctl-find"'
                  f' placeholder="Search…"{off}>')
    if state["buttons"] and not state["single"]:
        tools += (f'<button type="button" data-fg-all="1"{off}>All</button>'
                  f'<button type="button" data-fg-all="0"{off}>None</button>')
    tools = f'<div class="fg-ctl-tools">{tools}</div>' if tools else ""
    listing = f'<div class="fg-ctl-list">{"".join(rows)}</div>'
    if state["layout"] == "dropdown":
        return (f'<details class="fg-ctl-drop"><summary>'
                f'{_esc(display_value(state))}</summary>'
                f'{tools}{listing}</details>')
    return tools + listing


_BODIES = {"slider": _body_slider, "range": _body_range,
           "number": _body_number, "text": _body_text, "date": _body_date,
           "toggle": _body_toggle, "choice": _body_choice,
           "multi": _body_multi, "time": _body_time,
           "datetime": _body_datetime, "colour": _body_colour,
           "slicer": _body_slicer}


# The look. Read through the page's own --fg- variables, so a starter theme
# colours the widgets with the rest of the page; the fallbacks are what a
# page with no theme gets.
CSS = """
.fg-ctl { --fg-ctl-ink: var(--fg-head, inherit);
  margin: 0.6em 0; padding: 0.55em 0.75em; max-width: 30em;
  border: 1px solid rgba(127,127,127,0.35); border-radius: 8px;
  font-size: 0.95em; box-sizing: border-box; }
.fg-ctl * { box-sizing: border-box; }
.fg-ctl input[type=range], .fg-ctl input[type=checkbox],
.fg-ctl input[type=radio] {
  accent-color: var(--fg-ctl-accent, var(--fg-accent, #7c3aed)); }
.fg-ctl-head { display: flex; align-items: center; gap: 0.4em;
  margin-bottom: 0.3em; font-weight: 600; color: var(--fg-ctl-ink); }
.fg-ctl-caption { flex: 1; }
.fg-ctl-help { cursor: help; opacity: 0.6; font-weight: normal; }
.fg-ctl-apply { font: inherit; font-size: 0.85em; padding: 0.1em 0.6em;
  border: 1px solid rgba(127,127,127,0.5); border-radius: 5px;
  background: transparent; color: inherit; cursor: pointer; }
.fg-ctl-apply.fg-pending { background: #f59e0b; border-color: #f59e0b;
  color: #111; }
.fg-ctl-row { display: flex; align-items: center; gap: 0.5em; }
.fg-ctl-row input[type=range], .fg-ctl-twin { flex: 1; min-width: 6em; }
.fg-ctl-end, .fg-ctl-count { font-size: 0.8em; opacity: 0.65;
  font-variant-numeric: tabular-nums; }
.fg-ctl-readout { display: block; text-align: center;
  font-variant-numeric: tabular-nums; }
.fg-ctl input[type=number], .fg-ctl input[type=text],
.fg-ctl input[type=password], .fg-ctl input[type=date],
.fg-ctl input[type=time], .fg-ctl input[type=datetime-local],
.fg-ctl input[type=search], .fg-ctl select, .fg-ctl textarea {
  font: inherit; padding: 0.25em 0.45em; width: 100%;
  border: 1px solid rgba(127,127,127,0.5); border-radius: 5px;
  background: transparent; color: inherit; }
.fg-ctl select option { color: initial; }
.fg-ctl input:invalid { border-color: #dc2626; }
.fg-ctl-row input[type=number] { flex: 1; }
/* Between: two range inputs over one drawn track, the chosen band lit
   (--lo/--hi, kept up to date by the script as a handle moves) */
.fg-ctl-twin { position: relative; height: 1.4em; }
.fg-ctl-twin::before { content: ""; position: absolute; left: 0; right: 0;
  top: 50%; height: 4px; margin-top: -2px; border-radius: 2px;
  background: linear-gradient(to right, rgba(127,127,127,0.35) var(--lo),
    var(--fg-ctl-accent, var(--fg-accent, #7c3aed)) var(--lo),
    var(--fg-ctl-accent, var(--fg-accent, #7c3aed)) var(--hi),
    rgba(127,127,127,0.35) var(--hi)); }
.fg-ctl-twin input[type=range] { position: absolute; left: 0; top: 0;
  width: 100%; height: 100%; margin: 0; pointer-events: none;
  background: none; -webkit-appearance: none; appearance: none; }
.fg-ctl-twin input[type=range]::-webkit-slider-runnable-track {
  background: none; }
.fg-ctl-twin input[type=range]::-moz-range-track { background: none; }
.fg-ctl-twin input[type=range]::-webkit-slider-thumb {
  -webkit-appearance: none; pointer-events: auto; width: 1em; height: 1em;
  border-radius: 50%; cursor: pointer; background: #fff;
  border: 2px solid var(--fg-ctl-accent, var(--fg-accent, #7c3aed)); }
.fg-ctl-twin input[type=range]::-moz-range-thumb { pointer-events: auto;
  width: 0.8em; height: 0.8em; border-radius: 50%; cursor: pointer;
  background: #fff;
  border: 2px solid var(--fg-ctl-accent, var(--fg-accent, #7c3aed)); }
.fg-ctl-tick { display: flex; align-items: center; gap: 0.45em;
  cursor: pointer; }
.fg-ctl-switch input { appearance: none; -webkit-appearance: none;
  width: 2.2em; height: 1.2em; border-radius: 0.6em; margin: 0;
  background: rgba(127,127,127,0.45); position: relative; cursor: pointer;
  transition: background 0.15s; }
.fg-ctl-switch input::after { content: ""; position: absolute; top: 0.15em;
  left: 0.15em; width: 0.9em; height: 0.9em; border-radius: 50%;
  background: #fff; transition: left 0.15s; }
.fg-ctl-switch input:checked {
  background: var(--fg-ctl-accent, var(--fg-accent, #7c3aed)); }
.fg-ctl-switch input:checked::after { left: 1.15em; }
.fg-ctl-buttons { display: flex; flex-wrap: wrap; gap: 0.3em; }
.fg-ctl-buttons label { cursor: pointer; }
.fg-ctl-buttons input { position: absolute; opacity: 0; pointer-events: none; }
.fg-ctl-buttons span { display: inline-block; padding: 0.2em 0.7em;
  border: 1px solid rgba(127,127,127,0.5); border-radius: 999px; }
.fg-ctl-buttons input:checked + span {
  background: var(--fg-ctl-accent, var(--fg-accent, #7c3aed));
  border-color: var(--fg-ctl-accent, var(--fg-accent, #7c3aed));
  color: #fff; }
.fg-ctl-buttons input:focus-visible + span { outline: 2px solid
  var(--fg-ctl-accent, var(--fg-accent, #7c3aed)); outline-offset: 1px; }
.fg-ctl-radios label, .fg-ctl-list label { display: flex;
  align-items: center; gap: 0.45em; cursor: pointer; padding: 0.1em 0; }
.fg-ctl-list label span:first-of-type { flex: 1; }
.fg-ctl-list { max-height: 14em; overflow-y: auto; }
.fg-ctl-tools { display: flex; gap: 0.35em; margin-bottom: 0.35em; }
.fg-ctl-tools button { font: inherit; font-size: 0.85em;
  padding: 0.1em 0.6em; border: 1px solid rgba(127,127,127,0.5);
  border-radius: 5px; background: transparent; color: inherit;
  cursor: pointer; }
.fg-ctl-drop summary { cursor: pointer; padding: 0.25em 0.45em;
  border: 1px solid rgba(127,127,127,0.5); border-radius: 5px; }
.fg-ctl-drop[open] summary { margin-bottom: 0.4em; }
.fg-ctl [disabled] { cursor: default; }
.fg-ctl-busy { opacity: 0.6; }
@media print { .fg-ctl { border: none; padding: 0; }
  .fg-ctl-tools, .fg-ctl-apply { display: none; } }
"""

# Binds every enabled widget to `flograph.set(<node id>, {"value": ...})`.
# A slider commits on release (`change`), not per pixel of travel — each
# write re-runs the flow and the page is drawn again after it — and a text
# box on Enter or leaving it. A widget remembers what it last sent, so a
# blur after an Enter does not send the same text twice.
JS = r"""
(function () {
  function send(box, message) {
    if (!window.flograph || !window.flograph.set) { return; }
    box.classList.add("fg-ctl-busy");
    window.flograph.set(box.getAttribute("data-fg-ctl"), message);
  }
  function number(input) {
    var d = parseInt(input.getAttribute("data-fg-decimals") ||
      (input.parentNode.getAttribute && input.parentNode.getAttribute(
        "data-fg-decimals")) || "0", 10);
    var v = parseFloat(input.value);
    if (isNaN(v)) { return null; }
    return d ? Number(v.toFixed(d)) : Math.round(v);
  }
  function fmt(v, d) {
    return Number(v).toLocaleString(undefined, {
      minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function bind(box) {
    var kind = box.getAttribute("data-fg-kind"), last = null;
    function commit(value) {
      var key = JSON.stringify(value);
      if (key === last) { return; }
      last = key;
      send(box, {value: value});
    }
    var apply = box.querySelector("[data-fg-apply]");
    if (apply) {
      apply.addEventListener("click", function () {
        send(box, {apply: true});
      });
    }
    var readout = box.querySelector(".fg-ctl-readout");
    if (kind === "slider") {
      var s = box.querySelector("input[type=range]");
      var d = parseInt(s.getAttribute("data-fg-decimals") || "0", 10);
      s.addEventListener("input", function () {
        if (readout) { readout.textContent = fmt(s.value, d); }
      });
      s.addEventListener("change", function () { commit(number(s)); });
    } else if (kind === "range") {
      var twin = box.querySelector(".fg-ctl-twin");
      var dd = parseInt(twin.getAttribute("data-fg-decimals") || "0", 10);
      var lo = box.querySelector("[data-fg-end=low]");
      var hi = box.querySelector("[data-fg-end=high]");
      var pair = function () {
        var a = number(lo), b = number(hi);
        return a <= b ? [a, b] : [b, a];
      };
      var low = parseFloat(lo.min), span = (parseFloat(lo.max) - low) || 1;
      [lo, hi].forEach(function (input) {
        input.addEventListener("input", function () {
          var p = pair();
          twin.style.setProperty("--lo", (p[0] - low) / span * 100 + "%");
          twin.style.setProperty("--hi", (p[1] - low) / span * 100 + "%");
          if (readout) {
            readout.textContent = fmt(p[0], dd) + " – " + fmt(p[1], dd);
          }
        });
        input.addEventListener("change", function () { commit(pair()); });
      });
    } else if (kind === "number") {
      var n = box.querySelector("input");
      n.addEventListener("change", function () {
        var v = number(n);
        if (v !== null) { commit(v); }
      });
    } else if (kind === "text") {
      var t = box.querySelector("input, textarea");
      var done = function () {
        if (t.checkValidity && !t.checkValidity()) { return; }
        commit(t.value);
      };
      t.addEventListener("change", done);
      t.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && t.tagName !== "TEXTAREA") { done(); }
        if (e.key === "Enter" && t.tagName === "TEXTAREA" &&
            (e.ctrlKey || e.metaKey)) { done(); }
      });
    } else if (kind === "toggle") {
      var c = box.querySelector("input");
      c.addEventListener("change", function () { commit(c.checked); });
    } else if (kind === "choice") {
      var sel = box.querySelector("select");
      if (sel) {
        sel.addEventListener("change", function () { commit(sel.value); });
      }
      box.querySelectorAll("input[type=radio]").forEach(function (r) {
        r.addEventListener("change", function () {
          if (r.checked) { commit(r.value); }
        });
      });
    } else if (kind === "multi") {
      var ticks = box.querySelectorAll("input[type=checkbox]");
      ticks.forEach(function (tick) {
        tick.addEventListener("change", function () {
          var on = [];
          ticks.forEach(function (x) { if (x.checked) { on.push(x.value); } });
          commit(on);
        });
      });
    } else if (kind === "slicer") {
      var boxes = box.querySelectorAll(".fg-ctl-list input");
      var picked = function () {
        var on = [];
        boxes.forEach(function (x) {
          if (x.checked) { on.push(JSON.parse(x.value)); }
        });
        return on;
      };
      boxes.forEach(function (x) {
        x.addEventListener("change", function () { commit(picked()); });
      });
      box.querySelectorAll("[data-fg-all]").forEach(function (b) {
        b.addEventListener("click", function () {
          var on = b.getAttribute("data-fg-all") === "1";
          boxes.forEach(function (x) {
            if (x.closest("label").style.display !== "none") { x.checked = on; }
          });
          commit(picked());
        });
      });
      var find = box.querySelector(".fg-ctl-find");
      if (find) {
        find.addEventListener("input", function () {
          var q = find.value.trim().toLowerCase();
          box.querySelectorAll(".fg-ctl-list label").forEach(function (l) {
            var hit = !q || l.getAttribute("data-fg-label").indexOf(q) !== -1;
            l.style.display = hit ? "" : "none";
          });
        });
      }
    } else {
      // date, time, datetime, colour: one native input, one value
      var one = box.querySelector("input");
      one.addEventListener("change", function () { commit(one.value); });
    }
  }
  document.querySelectorAll(".fg-ctl").forEach(function (box) {
    if (!box.querySelector("[disabled]")) { bind(box); }
  });
})();
"""
