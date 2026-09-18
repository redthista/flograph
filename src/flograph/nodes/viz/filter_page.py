"""Filter Page

One page of filters for the whole table: every column arrives with its own
control and the table flowing through narrows to the rows that match them
all. Categories get a searchable checklist, numbers get min/max sliders,
dates get a from/to picker, and anything too varied for a list gets a
contains box. Everything downstream re-runs and stays live.

Column coverage is automatic — every column gets a widget unless it is named
in "Exclude columns". A column named in "Single-select columns" picks one
value at a time (clicking it again clears it); every other checklist takes
any number of ticks. With nothing ticked, or a full range, or a blank box,
that column filters nothing, so a fresh page passes the table through
untouched.

"Update mode" decides when the page talks back: "live" re-runs on every
change, "apply" buffers edits until the Apply button is pressed (Clear
always applies at once). The page writes the "Filters" param, which is why
that box exists — it is the filter state as JSON, and clearing it clears
every filter. Dates are detected, not just declared: a text column that
reads as dates (2024-01-31, 31/01/2024, …) gets the date picker too.

Nulls follow "Keep nulls": on, a blank row survives a filter on its column;
off, it doesn't. Counts beside each value are display only.

Numbers filter on one track with two handles, Power BI-style, with the
picked span filled in. Handles snap to "Slider step" (automatic by
default — about a hundredth of the column's span, so dragging stops
producing 12.3177576959812). The "Display" section in properties holds
the cosmetic side: accent colour, card width, and switches for the
search boxes, All/None, reset links, number boxes and counts.
"""

NODE = {
    "label": "Filter Page",
    "category": "Viz",
    "version": "1.1",
    "card": "webview",
    # Lets the page write this node's "filters" param, which re-runs this
    # node and everything downstream — the same bargain a Slicer tick makes.
    "interactive": True,
    "inputs": [("table", "dataframe")],
    "outputs": [("view", "string"), ("filtered", "dataframe"),
                ("rejected", "dataframe"), ("filters", "string")],
}
PARAMS = [
    {"name": "exclude", "type": "columns", "label": "Exclude columns",
     "default": "", "multi": True,
     "placeholder": "columns with no widget, e.g. id, notes"},
    {"name": "single", "type": "columns", "label": "Single-select columns",
     "default": "", "multi": True,
     "placeholder": "checklists that pick one value, e.g. region"},
    {"name": "update", "type": "choice", "label": "Update mode",
     "options": ["live", "apply"], "default": "live"},
    {"name": "max_values", "type": "int", "label": "Max values per filter",
     "default": 200, "min": 10, "max": 5000},
    {"name": "slider_step", "type": "float", "label": "Slider step",
     "default": 0.0, "min": 0.0, "max": 1000000000.0,
     "placeholder": "0 = automatic"},
    {"name": "keep_nulls", "type": "bool", "label": "Keep nulls",
     "default": True},
    {"name": "case_sensitive", "type": "bool", "label": "Case sensitive text",
     "default": False},
    {"name": "title", "type": "string", "label": "Title", "default": "",
     "placeholder": "heading across the top of the page",
     "section": "Display"},
    {"name": "accent", "type": "color", "label": "Accent colour",
     "default": "", "placeholder": "Theme", "section": "Display"},
    {"name": "card_min_width", "type": "int", "label": "Card min width",
     "default": 240, "min": 160, "max": 800, "section": "Display"},
    {"name": "show_counts", "type": "bool", "label": "Show row counts",
     "default": True, "section": "Display"},
    {"name": "show_search", "type": "bool", "label": "Show search boxes",
     "default": True, "section": "Display"},
    {"name": "show_all_none", "type": "bool", "label": "Show All / None",
     "default": True, "section": "Display"},
    {"name": "show_reset", "type": "bool", "label": "Show reset links",
     "default": True, "section": "Display"},
    {"name": "show_numbers", "type": "bool", "label": "Show number boxes",
     "default": True, "section": "Display"},
    # Written by the page itself on every change (live) or Apply. Visible
    # rather than hidden: when the table isn't narrowing as expected, this
    # is where what the page actually sent shows up — and clearing it
    # clears every filter.
    {"name": "filters", "type": "text", "label": "Filters",
     "default": "",
     "placeholder": '{"region": {"kind": "include", "values": ["north"]}}'
                    " — blank keeps every row"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 460, "min": 260, "max": 4000, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 520, "min": 200, "max": 4000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400, "cosmetic": True},
]

#: Filter kinds the "filters" param may hold, per column.
_KINDS = ("include", "range", "dates", "contains")

#: Marker the page never sends as a real value; nulls are governed by
#: "Keep nulls" instead (see the docstring), so there is no blank tickbox
#: to keep in sync between the page and run().
_BLANK = "(blank)"

# The page. A plain string with /*PLACEHOLDER*/ markers filled in by run(),
# not an f-string — a page is mostly `{` and `}` and doubling every one
# would make it unreadable.
_PAGE = """
<style>
  html, body { margin: 0; padding: 0; background: #ffffff; color: #111827;
               font-family: system-ui, -apple-system, sans-serif; }
  .sheet { padding: 14px 16px 20px; }
  h2 { margin: 0 0 2px; font-size: 16px; font-weight: 650; }
  .meta { color: #6b7280; font-size: 12.5px; margin: 0 0 10px; }
  .bar { display: flex; gap: 8px; align-items: center; margin: 0 0 12px;
         flex-wrap: wrap; }
  .bar button { font: inherit; font-size: 13px; padding: 6px 14px;
                border-radius: 8px; border: 1px solid #d1d5db;
                background: #f9fafb; color: #111827; cursor: pointer; }
  .bar button.primary { background: var(--accent); border-color: var(--accent);
                        color: #fff; }
  .bar button:disabled { opacity: .45; cursor: default; }
  .bar button:not(:disabled):hover { border-color: #9ca3af; }
  .bar button.primary:not(:disabled):hover { filter: brightness(.92); }
  .dirty { font-size: 12.5px; color: #b45309; display: none; }
  .dirty.on { display: inline; }
  .grid { display: grid; grid-template-columns:
          repeat(auto-fill, minmax(min(100%, var(--cardmin, 240px)), 1fr));
          gap: 10px; }
  .card { border: 1px solid #e5e7eb; border-radius: 10px; padding: 10px 12px;
          background: #fff; }
  .card.active { border-color: #93c5fd; background: #eff6ff; }
  .chead { display: flex; align-items: baseline; gap: 6px;
           margin-bottom: 6px; }
  .cname { font-weight: 600; font-size: 13px; word-break: break-word; }
  .ctag { font-size: 11px; color: #6b7280; background: #f3f4f6;
          border-radius: 999px; padding: 1px 8px; white-space: nowrap; }
  .creset { margin-left: auto; font-size: 12px; color: var(--accent);
            background: none; border: none; cursor: pointer; padding: 0; }
  .creset:hover { text-decoration: underline; }
  .search { width: 100%; box-sizing: border-box; font: inherit; font-size: 13px;
            padding: 5px 8px; margin-bottom: 6px; border: 1px solid #d1d5db;
            border-radius: 7px; }
  .mini { display: flex; gap: 10px; font-size: 12px; color: #374151;
          margin-bottom: 6px; }
  .mini button { background: none; border: none; color: var(--accent);
                 cursor: pointer; font: inherit; padding: 0; }
  .mini button:hover { text-decoration: underline; }
  .opts { max-height: 168px; overflow-y: auto; display: flex;
          flex-direction: column; gap: 2px; }
  .opts label { display: flex; align-items: center; gap: 7px; font-size: 13px;
                padding: 2px 4px; border-radius: 6px; cursor: pointer;
                word-break: break-word; }
  .opts label:hover { background: #f3f4f6; }
  .cnt { margin-left: auto; color: #9ca3af; font-size: 12px;
         white-space: nowrap; }
  .row2 { display: flex; gap: 6px; align-items: center; min-width: 0; }
  .row2 input[type="number"], .row2 input[type="date"],
  .row2 input[type="text"] { font: inherit; font-size: 13px; padding: 5px 7px;
      border: 1px solid #d1d5db; border-radius: 7px; flex: 1 1 0; min-width: 0;
      width: auto; box-sizing: border-box; color: #111827; background: #fff; }
  input[type="checkbox"], input[type="radio"] { accent-color: var(--accent);
      flex: none; }
  /* One track, two handles: the inputs overlap exactly, their own tracks
     are transparent, and only the thumbs take the pointer — so either
     handle grabs wherever it sits. */
  .dual { position: relative; height: 26px; margin: 2px 0 4px; }
  .dtrack { position: absolute; top: 11px; left: 8px; right: 8px; height: 4px;
            border-radius: 2px; background: #d1d5db; }
  .dfill { position: absolute; top: 11px; height: 4px; border-radius: 2px;
           background: var(--accent); }
  .dual input[type="range"] { -webkit-appearance: none; appearance: none;
      position: absolute; left: 0; top: 0; width: 100%; height: 26px;
      margin: 0; background: transparent; pointer-events: none; }
  .dual input[type="range"]::-webkit-slider-runnable-track {
      height: 26px; background: transparent; }
  .dual input[type="range"]::-webkit-slider-thumb { -webkit-appearance: none;
      height: 16px; width: 16px; border-radius: 50%; background: #fff;
      border: 2px solid var(--accent); margin-top: 5px; pointer-events: auto;
      cursor: ew-resize; }
  .dual input[type="range"]::-moz-range-track { height: 4px;
      background: transparent; }
  .dual input[type="range"]::-moz-range-thumb { height: 12px; width: 12px;
      border-radius: 50%; background: #fff; border: 2px solid var(--accent);
      pointer-events: auto; cursor: ew-resize; }
  .rangeval { font-size: 12.5px; color: #374151; margin-top: 2px; }
  .note { font-size: 12.5px; color: #6b7280; }
  .hint { margin-top: 12px; font-size: 12px; color: #9ca3af; }
  @media (prefers-color-scheme: dark) {
    html, body { background: #111827; color: #f3f4f6; }
    .card { background: #1f2937; border-color: #374151; }
    .card.active { background: #1e3a5f; border-color: #3b82f6; }
    .bar button { background: #1f2937; border-color: #4b5563; color: #f3f4f6; }
    .ctag { background: #374151; color: #d1d5db; }
    .opts label:hover { background: #374151; }
    .search, .row2 input { background: #111827; border-color: #4b5563;
                           color: #f3f4f6; }
    .meta, .note, .mini, .rangeval { color: #9ca3af; }
  }
</style>
<div class="sheet" style="--accent:/*ACCENT*/;--cardmin:/*CARDMIN*/px;">
  <h2>/*TITLE*/</h2>
  <p class="meta">/*META*/</p>
  <div class="bar">
    <button id="apply" class="primary" disabled>Apply filters</button>
    <button id="clear">Clear all</button>
    <span class="dirty" id="dirty">● unsaved changes</span>
  </div>
  <div class="grid">/*SECTIONS*/</div>
  <p class="hint" id="hint"></p>
</div>
<script>
  var MODE = /*MODE*/;
  var applyBtn = document.getElementById("apply");
  var clearBtn = document.getElementById("clear");
  var dirty = document.getElementById("dirty");

  function push(state) {
    // Guarded: the same page survives Open in Browser and Save View as
    // HTML, where there is no channel — there a change only touches the
    // page, rather than throwing.
    if (window.flograph && flograph.set) { flograph.set("filters", state); }
  }

  function sectionState(sec) {
    var name = sec.getAttribute("data-filter-col");
    var kind = sec.getAttribute("data-kind");
    var i, el;
    if (kind === "categorical") {
      var single = sec.getAttribute("data-single") === "1";
      var boxes = sec.querySelectorAll("input[data-val]");
      var all = [], ticked = [];
      for (i = 0; i < boxes.length; i++) {
        all.push(boxes[i].getAttribute("data-val"));
        if (boxes[i].checked) { ticked.push(boxes[i].getAttribute("data-val")); }
      }
      if (single) {
        var real = ticked.filter(function (v) { return v !== "__all__"; });
        if (!real.length) { return null; }
        return {name: name, rule: {kind: "include", values: real.slice(0, 1)}};
      }
      // Everything ticked is no filter — keeps the stored JSON small and
      // means "untick one" reads as the exclusion it is.
      if (ticked.length === 0 || ticked.length === all.length) {
        return ticked.length === 0
          ? {name: name, rule: {kind: "include", values: []}}
          : null;
      }
      return {name: name, rule: {kind: "include", values: ticked}};
    }
    if (kind === "numeric") {
      var cmin = parseFloat(sec.getAttribute("data-min"));
      var cmax = parseFloat(sec.getAttribute("data-max"));
      var loBox = sec.querySelector(".lo"), hiBox = sec.querySelector(".hi");
      var lo = loBox ? parseFloat(loBox.value)
                     : parseFloat(sec.querySelector(".rlo").value);
      var hi = hiBox ? parseFloat(hiBox.value)
                     : parseFloat(sec.querySelector(".rhi").value);
      if (isNaN(lo)) { lo = cmin; }
      if (isNaN(hi)) { hi = cmax; }
      // A hair of tolerance: the boxes show trimmed values, so an untouched
      // span can sit a rounding-dust inside the true span.
      var eps = (cmax - cmin) * 1e-9 + 1e-12;
      if (lo <= cmin + eps && hi >= cmax - eps) { return null; }
      return {name: name, rule: {kind: "range", min: lo, max: hi}};
    }
    if (kind === "date") {
      var from = sec.querySelector(".dfrom").value;
      var to = sec.querySelector(".dto").value;
      var sfrom = sec.getAttribute("data-from");
      var sto = sec.getAttribute("data-to");
      if ((!from || from === sfrom) && (!to || to === sto)) { return null; }
      var rule = {kind: "dates"};
      if (from) { rule.from = from; }
      if (to) { rule.to = to; }
      return {name: name, rule: rule};
    }
    if (kind === "text") {
      el = sec.querySelector(".txt");
      var needle = el.value.trim();
      if (!needle) { return null; }
      return {name: name, rule: {kind: "contains", text: needle}};
    }
    return null;
  }

  function collect() {
    var state = {};
    var secs = document.querySelectorAll("[data-filter-col]");
    for (var i = 0; i < secs.length; i++) {
      var found = sectionState(secs[i]);
      if (found) { state[found.name] = found.rule; }
    }
    return state;
  }

  function markActive() {
    // Shade the sections that are actually narrowing the table.
    var secs = document.querySelectorAll("[data-filter-col]");
    for (var i = 0; i < secs.length; i++) {
      var on = sectionState(secs[i]) !== null;
      if (on) { secs[i].classList.add("active"); }
      else { secs[i].classList.remove("active"); }
    }
  }

  function changed() {
    markActive();
    if (MODE === "live") { push(collect()); }
    else {
      applyBtn.disabled = false;
      dirty.classList.add("on");
    }
  }

  function trimNum(value) {
    // 12.3177576959812 -> "12.3178", 42 -> "42": six significant digits
    // with the trailing zeros gone, for the boxes and the span label.
    if (!isFinite(value)) { return ""; }
    return Number(value.toPrecision(6)).toString();
  }

  function snap(sec, value) {
    // A dragged handle lands on the step grid; a typed one is only
    // clamped. Either way the value stays inside the column's span.
    var cmin = parseFloat(sec.getAttribute("data-min"));
    var cmax = parseFloat(sec.getAttribute("data-max"));
    var step = parseFloat(sec.getAttribute("data-step"));
    if (isNaN(value)) { return value; }
    if (step > 0) {
      value = Math.round((value - cmin) / step) * step + cmin;
      value = Number(value.toPrecision(12));  // the stepping's own dust
    }
    return Math.min(cmax, Math.max(cmin, value));
  }

  function paintDual(sec) {
    // The ranges are the truth; the fill and the boxes mirror them.
    var cmin = parseFloat(sec.getAttribute("data-min"));
    var cmax = parseFloat(sec.getAttribute("data-max"));
    var rlo = sec.querySelector(".rlo"), rhi = sec.querySelector(".rhi");
    var lo = parseFloat(rlo.value), hi = parseFloat(rhi.value);
    var span = cmax - cmin;
    var pct = function (v) {
      return span > 0 ? ((v - cmin) / span * 100) : 50;
    };
    var fill = sec.querySelector(".dfill");
    fill.style.left = pct(lo) + "%";
    fill.style.width = Math.max(0, pct(hi) - pct(lo)) + "%";
    // Stacked handles bury the lower thumb — raise it while they touch so
    // it can still be dragged back apart.
    rlo.style.zIndex = (lo >= hi) ? 6 : 4;
    var loBox = sec.querySelector(".lo"), hiBox = sec.querySelector(".hi");
    if (loBox) { loBox.value = trimNum(lo); }
    if (hiBox) { hiBox.value = trimNum(hi); }
    sec.querySelector(".rangeval").textContent =
      trimNum(lo) + " – " + trimNum(hi);
  }

  function setWas(sec) {
    // Remembers which radio is picked, so clicking the picked one again
    // can clear the column back to All (radios don't untick on their own,
    // and that click fires no input event).
    var radios = sec.querySelectorAll('input[type="radio"][data-val]');
    for (var i = 0; i < radios.length; i++) {
      radios[i].setAttribute("data-was", radios[i].checked ? "1" : "");
    }
  }

  var secs = document.querySelectorAll("[data-filter-col]");
  for (var s = 0; s < secs.length; s++) {
    (function (sec) {
      sec.addEventListener("input", function (event) {
        var t = event.target;
        if (t.type === "radio") { return; }  // handled on click, below
        if (sec.getAttribute("data-kind") === "numeric") {
          var rlo = sec.querySelector(".rlo");
          var rhi = sec.querySelector(".rhi");
          var cmin = parseFloat(sec.getAttribute("data-min"));
          var cmax = parseFloat(sec.getAttribute("data-max"));
          var lo = parseFloat(rlo.value), hi = parseFloat(rhi.value);
          if (t.classList.contains("lo")) {
            lo = snap(sec, parseFloat(t.value));
            if (isNaN(lo)) { lo = cmin; }
            rlo.value = Math.min(lo, hi);
          } else if (t.classList.contains("hi")) {
            hi = snap(sec, parseFloat(t.value));
            if (isNaN(hi)) { hi = cmax; }
            rhi.value = Math.max(lo, hi);
          } else if (t.classList.contains("rlo")) {
            // A dragged handle snaps and never crosses the other one.
            rlo.value = Math.min(snap(sec, lo), hi);
          } else if (t.classList.contains("rhi")) {
            rhi.value = Math.max(snap(sec, hi), lo);
          }
          paintDual(sec);
        }
        changed();
      });
      sec.addEventListener("click", function (event) {
        var t = event.target;
        if (t.type === "radio") {
          if (t.getAttribute("data-val") !== "__all__" &&
              t.getAttribute("data-was") === "1") {
            var all = sec.querySelector('input[data-val="__all__"]');
            if (all) { all.checked = true; }
          }
          setWas(sec);
          changed();
          return;
        }
        if (t.classList && t.classList.contains("creset")) {
          resetSection(sec);
          changed();
        }
        if (t.classList && t.classList.contains("allbtn")) {
          var boxes = sec.querySelectorAll('input[type="checkbox"][data-val]');
          for (var i = 0; i < boxes.length; i++) { boxes[i].checked = true; }
          changed();
        }
        if (t.classList && t.classList.contains("nonebtn")) {
          var boxes2 = sec.querySelectorAll('input[type="checkbox"][data-val]');
          for (var j = 0; j < boxes2.length; j++) { boxes2[j].checked = false; }
          changed();
        }
      });
      var search = sec.querySelector(".search");
      if (search) {
        search.addEventListener("input", function () {
          var q = search.value.toLowerCase();
          var labels = sec.querySelectorAll(".opts label");
          for (var i = 0; i < labels.length; i++) {
            var text = labels[i].textContent.toLowerCase();
            labels[i].style.display =
              (q === "" || text.indexOf(q) !== -1) ? "" : "none";
          }
        });
      }
    })(secs[s]);
  }

  function resetSection(sec) {
    var kind = sec.getAttribute("data-kind");
    var i, boxes;
    if (kind === "categorical") {
      if (sec.getAttribute("data-single") === "1") {
        var all = sec.querySelector('input[data-val="__all__"]');
        if (all) { all.checked = true; }
      } else {
        boxes = sec.querySelectorAll('input[type="checkbox"][data-val]');
        for (i = 0; i < boxes.length; i++) { boxes[i].checked = true; }
      }
      var search = sec.querySelector(".search");
      if (search) { search.value = ""; }
      var labels = sec.querySelectorAll(".opts label");
      for (i = 0; i < labels.length; i++) { labels[i].style.display = ""; }
    } else if (kind === "numeric") {
      var spanMin = sec.getAttribute("data-min");
      var spanMax = sec.getAttribute("data-max");
      sec.querySelector(".rlo").value = spanMin;
      sec.querySelector(".rhi").value = spanMax;
      paintDual(sec);
    } else if (kind === "date") {
      sec.querySelector(".dfrom").value = sec.getAttribute("data-from");
      sec.querySelector(".dto").value = sec.getAttribute("data-to");
    } else if (kind === "text") {
      sec.querySelector(".txt").value = "";
    }
  }

  applyBtn.addEventListener("click", function () {
    push(collect());
    applyBtn.disabled = true;
    dirty.classList.remove("on");
  });

  clearBtn.addEventListener("click", function () {
    for (var i = 0; i < secs.length; i++) { resetSection(secs[i]); }
    markActive();
    // Clear always applies at once, even in apply mode — it is the way
    // back to the full table, not another buffered edit.
    push({});
    applyBtn.disabled = true;
    dirty.classList.remove("on");
  });

  if (MODE === "apply") { applyBtn.style.display = ""; }
  else { applyBtn.style.display = "none"; }
  for (var p = 0; p < secs.length; p++) {
    if (secs[p].getAttribute("data-kind") === "numeric") {
      paintDual(secs[p]);
    }
  }
  markActive();
  var hint = document.getElementById("hint");
  hint.textContent = "Outside flograph — changes stay on this page.";
  flograph.ready(function () {
    hint.textContent = MODE === "live"
      ? "Live: every change re-runs the flow."
      : "Buffered: change what you like, then Apply re-runs the flow.";
  });
</script>
"""


def _column_list(value):
    """A comma-separated columns param as a list of names, blanks dropped."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [c.strip() for c in str(value).split(",") if c.strip()]


def _parse_state(raw):
    """The "filters" param as `{column: rule}` — {} when blank.

    Raises ValueError with an actionable message when the text is not a
    JSON object of known rule kinds, so a hand edit that breaks it says
    what broke rather than silently filtering nothing.
    """
    import json

    if raw is None:
        return {}
    if isinstance(raw, dict):
        state = raw
    else:
        text = str(raw).strip()
        if not text:
            return {}
        try:
            state = json.loads(text)
        except ValueError:
            raise ValueError(
                "the 'Filters' param holds text that is not JSON — "
                "clear it to reset every filter") from None
        if not isinstance(state, dict):
            raise ValueError(
                "the 'Filters' param must be a JSON object mapping column "
                f"names to rules, got {type(state).__name__} — clear it "
                "to reset every filter")
    clean = {}
    for column, rule in state.items():
        if not isinstance(rule, dict) or rule.get("kind") not in _KINDS:
            raise ValueError(
                f"filter on column {str(column)!r} has an unknown shape — "
                f"each rule needs a 'kind' of {', '.join(_KINDS)}; clear "
                "the 'Filters' param to reset every filter")
        clean[str(column)] = rule
    return clean


def _detects_as_dates(series):
    """Whether a non-numeric, non-datetime column reads as dates.

    At least four in five of a 40-value sample must parse, and at least
    half must look date-shaped (digits around a `-` or `/`), so plain
    words and bare numbers never qualify — only separated, date-like
    text does.
    """
    import re

    import pandas as pd

    sample = series.dropna().astype(str).head(40).tolist()
    if len(sample) < 2:
        return False
    shaped = re.compile(r"\d.*[-/].*\d")
    looks = sum(1 for value in sample if shaped.search(value))
    if looks < max(1, len(sample) // 2):
        return False
    try:
        parsed = pd.to_datetime(pd.Series(sample), errors="coerce")
    except (ValueError, TypeError):
        return False
    return bool((parsed.notna().sum() / len(sample)) >= 0.8)


def _detect_kind(series, max_values):
    """The widget kind for a column: categorical, numeric, date or text."""
    import pandas as pd

    if pd.api.types.is_bool_dtype(series.dtype):
        return "categorical"
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return "date"
    if pd.api.types.is_numeric_dtype(series.dtype):
        if series.dropna().empty:
            return "text"
        return "numeric"
    if _detects_as_dates(series):
        return "date"
    try:
        distinct = int(series.nunique(dropna=True))
    except TypeError:
        return "text"
    if distinct <= max(1, max_values):
        return "categorical"
    return "text"


def _normalise_rule(column, rule, kind, single):
    """A stored rule reconciled with its column — None when inactive.

    Rules for a missing or retyped column are dropped (logged by the
    caller), never fatal: the board should survive an upstream rename.
    A single-select column keeps only its first value, like a Slicer in
    single mode.
    """
    if rule is None:
        return None
    wanted = {"categorical": "include", "numeric": "range",
              "date": "dates", "text": "contains"}[kind]
    if rule.get("kind") != wanted:
        return None
    if kind == "categorical":
        values = rule.get("values", [])
        if not isinstance(values, list):
            values = [values]
        values = [str(v) for v in values]
        if single and len(values) > 1:
            values = values[:1]
        if not values:
            # Unticked everything matches nothing — the one categorical
            # state that is a real filter rather than the absence of one.
            return {"kind": "include", "values": []}
        return {"kind": "include", "values": values}
    if kind == "numeric":
        try:
            low = float(rule.get("min"))
            high = float(rule.get("max"))
        except (TypeError, ValueError):
            return None
        return {"kind": "range", "min": min(low, high),
                "max": max(low, high)}
    if kind == "date":
        import datetime

        def iso(raw):
            if raw is None or str(raw).strip() == "":
                return None
            try:
                return datetime.date.fromisoformat(str(raw).strip()[:10])
            except ValueError:
                return None

        start, end = iso(rule.get("from")), iso(rule.get("to"))
        if start is None and end is None:
            return None
        return {"kind": "dates",
                "from": start.isoformat() if start else None,
                "to": end.isoformat() if end else None}
    text = str(rule.get("text", "") or "")
    if not text.strip():
        return None
    return {"kind": "contains", "text": text}


def _escape(value):
    import html as html_mod

    return html_mod.escape(str(value), quote=True)


def _trim(value):
    """A number for display: 12.3177576959812 -> "12.3178", 42.0 -> "42"."""
    try:
        number = float(f"{float(value):.6g}")
    except (TypeError, ValueError):
        return str(value)
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    return repr(number)


def _nice_step(span, integral=False):
    """An automatic slider step near a hundredth of the span, on a
    1/2/2.5/5/10 grid — whole numbers for integer columns."""
    import math

    if not span or span <= 0 or span != span:  # zero or NaN
        return 1.0
    raw = span / 100.0
    mag = 10.0 ** math.floor(math.log10(raw))
    for multiple in (1, 2, 2.5, 5, 10):
        if multiple * mag >= raw:
            step = multiple * mag
            break
    else:
        step = 10 * mag
    if integral:
        step = max(1.0, step)
    if step == int(step):
        step = float(int(step))
    return step


def _render_categorical(name, values, blank, rule, single, show_counts,
                        show_search, show_all_none, show_reset):
    """A searchable checklist — radios plus an All row for single-select."""
    picked = set(rule["values"]) if rule else None
    rows = []
    if single:
        # No rule, or a rule naming nothing tickable, reads as All.
        all_on = not picked
        rows.append(
            '<label><input type="radio" data-val="__all__"'
            + (" checked data-was=\"1\"" if all_on else " data-was=\"\"")
            + ">All</label>")
        for item in values:
            on = picked is not None and item["v"] in picked
            count = (f"<span class=\"cnt\">{item['c']}</span>"
                     if show_counts else "")
            rows.append(
                f"<label><input type=\"radio\" data-val=\"{_escape(item['v'])}\""
                + (" checked data-was=\"1\"" if on else " data-was=\"\"")
                + f">{_escape(item['v'])}{count}</label>")
    else:
        for item in values:
            on = picked is None or item["v"] in picked
            count = (f"<span class=\"cnt\">{item['c']}</span>"
                     if show_counts else "")
            rows.append(
                f"<label><input type=\"checkbox\" data-val=\"{_escape(item['v'])}\""
                + (" checked" if on else "")
                + f">{_escape(item['v'])}{count}</label>")
    search = ("<input class=\"search\" placeholder=\"Search values…\">"
              if show_search else "")
    tools = ("<div class=\"mini\"><button class=\"allbtn\">All</button>"
             "<button class=\"nonebtn\">None</button></div>"
             if show_all_none and not single else "")
    blank_note = (f"<div class=\"note\">{blank} blank "
                  f"row{'s' if blank != 1 else ''}</div>" if blank else "")
    active = " active" if rule else ""
    reset = "<button class=\"creset\">reset</button>" if show_reset else ""
    return (
        f"<div class=\"card{active}\" data-filter-col=\"{_escape(name)}\" "
        f"data-kind=\"categorical\" data-single=\"{'1' if single else '0'}\">"
        f"<div class=\"chead\"><span class=\"cname\">{_escape(name)}</span>"
        f"<span class=\"ctag\">{'single' if single else 'multi'}</span>"
        f"{reset}</div>"
        f"{search}{tools}<div class=\"opts\">" + "".join(rows) + "</div>"
        f"{blank_note}</div>")


def _render_numeric(name, minimum, maximum, step, rule, show_numbers,
                    show_reset, kept_note):
    low = _trim(rule["min"]) if rule else _trim(minimum)
    high = _trim(rule["max"]) if rule else _trim(maximum)
    active = " active" if rule else ""
    boxes = (f"<div class=\"row2\"><input class=\"lo\" type=\"number\" "
             f"step=\"any\" value=\"{low}\">"
             f"<input class=\"hi\" type=\"number\" step=\"any\" "
             f"value=\"{high}\"></div>" if show_numbers else "")
    reset = "<button class=\"creset\">reset</button>" if show_reset else ""
    return (
        f"<div class=\"card{active}\" data-filter-col=\"{_escape(name)}\" "
        f"data-kind=\"numeric\" data-min=\"{minimum!r}\" "
        f"data-max=\"{maximum!r}\" data-step=\"{step!r}\">"
        f"<div class=\"chead\"><span class=\"cname\">{_escape(name)}</span>"
        f"<span class=\"ctag\">range</span>{reset}</div>"
        f"<div class=\"dual\"><div class=\"dtrack\"></div>"
        f"<div class=\"dfill\"></div>"
        f"<input class=\"rlo\" type=\"range\" min=\"{minimum!r}\" "
        f"max=\"{maximum!r}\" step=\"any\" value=\"{low}\">"
        f"<input class=\"rhi\" type=\"range\" min=\"{minimum!r}\" "
        f"max=\"{maximum!r}\" step=\"any\" value=\"{high}\"></div>"
        f"{boxes}"
        f"<div class=\"rangeval\">{low} – {high}</div>"
        f"<div class=\"note\">{_escape(kept_note)}</div></div>")


def _render_date(name, start, end, rule, blank_note, show_reset):
    start_val = (rule.get("from") or start) if rule else start
    end_val = (rule.get("to") or end) if rule else end
    active = " active" if rule else ""
    note = (f"<div class=\"note\">{_escape(blank_note)}</div>"
            if blank_note else "")
    reset = "<button class=\"creset\">reset</button>" if show_reset else ""
    return (
        f"<div class=\"card{active}\" data-filter-col=\"{_escape(name)}\" "
        f"data-kind=\"date\" data-from=\"{_escape(start)}\" "
        f"data-to=\"{_escape(end)}\">"
        f"<div class=\"chead\"><span class=\"cname\">{_escape(name)}</span>"
        f"<span class=\"ctag\">dates</span>{reset}</div>"
        f"<div class=\"row2\"><input class=\"dfrom\" type=\"date\" "
        f"value=\"{_escape(start_val or '')}\">"
        f"<input class=\"dto\" type=\"date\" value=\"{_escape(end_val or '')}\">"
        f"</div>{note}</div>")


def _render_text(name, rule, show_reset):
    needle = rule["text"] if rule else ""
    active = " active" if rule else ""
    reset = "<button class=\"creset\">reset</button>" if show_reset else ""
    return (
        f"<div class=\"card{active}\" data-filter-col=\"{_escape(name)}\" "
        f"data-kind=\"text\">"
        f"<div class=\"chead\"><span class=\"cname\">{_escape(name)}</span>"
        f"<span class=\"ctag\">contains</span>{reset}</div>"
        f"<div class=\"row2\"><input class=\"txt\" type=\"text\" "
        f"value=\"{_escape(needle)}\" placeholder=\"Type to filter…\"></div>"
        f"</div>")


def run(ctx, table):
    import json
    import re

    import pandas as pd

    params = ctx.params
    by_name = {str(c): c for c in table.columns}

    excluded = _column_list(params.get("exclude"))
    unknown = [c for c in excluded if c not in by_name]
    if unknown:
        available = ", ".join(str(c) for c in table.columns)
        raise ValueError(
            f"excluded column {unknown[0]!r} is not in the table "
            f"(has: {available})")
    singles = _column_list(params.get("single"))
    unknown = [c for c in singles if c not in by_name]
    if unknown:
        available = ", ".join(str(c) for c in table.columns)
        raise ValueError(
            f"single-select column {unknown[0]!r} is not in the table "
            f"(has: {available})")
    single_set = set(singles)

    update = str(params.get("update", "live") or "live")
    if update not in ("live", "apply"):
        raise ValueError(
            f"unknown update mode {update!r} — one of: live, apply")
    max_values = max(1, int(params.get("max_values", 200) or 200))
    keep_nulls = bool(params.get("keep_nulls", True))
    case_sensitive = bool(params.get("case_sensitive", False))
    title = str(params.get("title", "") or "").strip() or "Filter Page"
    show_counts = bool(params.get("show_counts", True))
    show_search = bool(params.get("show_search", True))
    show_all_none = bool(params.get("show_all_none", True))
    show_reset = bool(params.get("show_reset", True))
    show_numbers = bool(params.get("show_numbers", True))
    try:
        step_param = float(params.get("slider_step", 0) or 0)
    except (TypeError, ValueError):
        step_param = 0.0
    if step_param < 0:
        step_param = 0.0
    try:
        card_min_width = int(params.get("card_min_width", 240) or 240)
    except (TypeError, ValueError):
        card_min_width = 240
    card_min_width = max(160, min(800, card_min_width))
    accent = str(params.get("accent", "") or "").strip() or "#2563eb"
    if not re.match(r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$", accent):
        accent = "#2563eb"

    state = _parse_state(params.get("filters", ""))
    dropped = sorted(set(state) - set(by_name))
    if dropped:
        ctx.log("ignoring filters on missing columns: "
                + ", ".join(dropped))
        state = {c: r for c, r in state.items() if c in by_name}

    columns = [c for c in table.columns if str(c) not in set(excluded)]
    if not columns:
        raise ValueError(
            "every column is excluded — clear 'Exclude columns' to filter "
            "something")

    mask = pd.Series(True, index=table.index)
    sections, active, normalised = [], [], {}
    for column in columns:
        name = str(column)
        series = table[column]
        nulls = series.isna()
        blank = int(nulls.sum())
        kind = _detect_kind(series, max_values)
        single = name in single_set and kind == "categorical"
        rule = _normalise_rule(name, state.get(name), kind, single)
        if rule is not None and rule.get("kind") != {
                "categorical": "include", "numeric": "range",
                "date": "dates", "text": "contains"}[kind]:
            rule = None
        if rule is None and state.get(name) is not None:
            ctx.log(f"ignoring a stale filter on {name!r} "
                    f"(column is now {kind})")

        if kind == "categorical":
            counts = series[~nulls].astype(str).value_counts()
            values = [{"v": str(v), "c": int(c)}
                      for v, c in counts.items()]
            if rule is None:
                keep = pd.Series(True, index=table.index)
            elif not rule["values"]:
                keep = nulls & pd.Series(keep_nulls, index=table.index)
            else:
                keep = series.astype(str).isin(set(rule["values"]))
                if keep_nulls:
                    keep = keep | nulls
            mask &= keep
            sections.append(_render_categorical(
                name, values, blank if keep_nulls else 0,
                rule, single, show_counts, show_search, show_all_none,
                show_reset))
        elif kind == "numeric":
            numbers = pd.to_numeric(series, errors="coerce")
            minimum = numbers.min(skipna=True)
            maximum = numbers.max(skipna=True)
            if pd.isna(minimum) or pd.isna(maximum):
                sections.append(
                    f"<div class=\"card\" data-filter-col=\"{_escape(name)}\" "
                    f"data-kind=\"text\">"
                    f"<div class=\"chead\">"
                    f"<span class=\"cname\">{_escape(name)}</span>"
                    f"<span class=\"ctag\">no values</span></div>"
                    f"<div class=\"note\">Nothing to filter.</div></div>")
                mask &= nulls & pd.Series(keep_nulls, index=table.index)
                continue
            minimum, maximum = float(minimum), float(maximum)
            integral = pd.api.types.is_integer_dtype(series.dtype)
            step = (step_param if step_param > 0
                    else _nice_step(maximum - minimum, integral))
            if rule is not None and (rule["min"] > minimum
                                     or rule["max"] < maximum):
                low, high = rule["min"], rule["max"]
                keep = (numbers >= low) & (numbers <= high)
                if keep_nulls:
                    keep = keep | nulls
                mask &= keep.fillna(False)
            else:
                rule = None
            kept_note = (f"{_trim(minimum)} – {_trim(maximum)}"
                         + (f", {blank} blank" if blank else ""))
            sections.append(_render_numeric(
                name, minimum, maximum, step, rule, show_numbers,
                show_reset, kept_note))
        elif kind == "date":
            stamps = pd.to_datetime(series, errors="coerce")
            valid = stamps.dropna()
            if valid.empty:
                sections.append(
                    f"<div class=\"card\" data-filter-col=\"{_escape(name)}\" "
                    f"data-kind=\"text\">"
                    f"<div class=\"chead\">"
                    f"<span class=\"cname\">{_escape(name)}</span>"
                    f"<span class=\"ctag\">no dates</span></div>"
                    f"<div class=\"note\">Nothing to filter.</div></div>")
                mask &= nulls & pd.Series(keep_nulls, index=table.index)
                continue
            start = valid.min().date().isoformat()
            end = valid.max().date().isoformat()
            detected = "" if pd.api.types.is_datetime64_any_dtype(
                series.dtype) else " (read as dates)"
            if rule is None:
                pass
            else:
                low = rule.get("from") or start
                high = rule.get("to") or end
                if low != start or high != end:
                    days = stamps.dt.normalize()
                    keep = ((days >= pd.Timestamp(low))
                            & (days <= pd.Timestamp(high)))
                    if keep_nulls:
                        keep = keep | nulls
                    mask &= keep.fillna(False)
                else:
                    rule = None
            note = (f"{start} → {end}{detected}"
                    + (f", {blank} blank" if blank else ""))
            sections.append(_render_date(name, start, end, rule, note,
                                         show_reset))
        else:
            if rule is None:
                pass
            else:
                needle = rule["text"]
                hay = series.astype(str)
                if not case_sensitive:
                    keep = hay.str.lower().str.contains(
                        needle.lower(), na=False)
                else:
                    keep = hay.str.contains(needle, na=False)
                if keep_nulls:
                    keep = keep | nulls
                mask &= keep.fillna(False)
            sections.append(_render_text(name, rule, show_reset))

        if rule is not None:
            active.append(name)
            normalised[name] = rule

    mask = mask.fillna(False)
    filtered = table[mask]
    rejected = table[~mask]
    ctx.log(f"kept {len(filtered)} of {len(table)} rows"
            + (f" ({len(active)} filter(s): {', '.join(active)})"
               if active else " (no filters)"))

    meta = (f"{len(filtered)} of {len(table)} rows"
            + (f" · filtering on {', '.join(active)}" if active else "")
            + (" · live" if update == "live" else " · buffered until Apply"))
    page = (_PAGE
            .replace("/*TITLE*/", _escape(title))
            .replace("/*META*/", _escape(meta))
            .replace("/*MODE*/", json.dumps(update))
            .replace("/*ACCENT*/", accent)
            .replace("/*CARDMIN*/", str(card_min_width))
            .replace("/*SECTIONS*/", "".join(sections)))
    html = ("<!doctype html><html><head><meta charset='utf-8'>"
            f"</head><body>{page}</body></html>")
    return {"view": html, "filtered": filtered, "rejected": rejected,
            "filters": json.dumps(normalised, sort_keys=True)
            if normalised else ""}
