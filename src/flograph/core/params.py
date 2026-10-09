"""Declarative node parameters.

A node script declares PARAMS as a list of dicts; each becomes a ParamSpec
and maps to exactly one widget in the properties panel. Values are plain
JSON-serializable scalars kept on the NodeInstance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

PARAM_TYPES = {
    "string",     # QLineEdit
    "text",       # multiline QPlainTextEdit
    "int",        # QSpinBox
    "float",      # QDoubleSpinBox
    "bool",       # QCheckBox
    "choice",     # QComboBox (requires options)
    "file_open",  # line edit + browse (existing file)
    "file_save",  # line edit + browse (save path)
    "folder_open",  # line edit + browse (existing directory)
    "columns",    # free string in v1; column picker later
    "password",   # QLineEdit with masked echo + reveal toggle
    "node_ref",   # QComboBox of other nodes in the graph; stores a node id
    "page_ref",   # the project's pages; stores a page id (or, multi, a
                  # comma list of them — none ticked meaning every page)
    "date",      # QDateEdit with a calendar popup; stores an ISO "YYYY-MM-DD"
    "color",      # swatch + colour picker; stores "#rrggbb", "" for "theme"
}

_TYPE_DEFAULTS: dict[str, Any] = {
    "string": "", "text": "", "int": 0, "float": 0.0, "bool": False,
    "choice": None, "file_open": "", "file_save": "", "columns": "",
    "color": "",
    "folder_open": "",
    "password": "", "node_ref": "", "page_ref": "", "date": "",
}


INSERT_COLUMN_MODES = {"inline", "mapping"}


def _insert_columns_mode(raw: Any, name: str, where: str) -> str:
    """Normalise a param's 'insert_columns' to "" / "inline" / "line"."""
    if raw is None or raw is False:
        return ""
    if raw is True:
        return "inline"
    if raw in INSERT_COLUMN_MODES:
        return raw
    valid = ", ".join(sorted(INSERT_COLUMN_MODES))
    raise ValueError(
        f"{where}: param {name!r} has an unknown 'insert_columns' {raw!r} "
        f"(valid: True, {valid})")


def _without(value: Any, paths) -> Any:
    """A JSON value (text or parsed) with the given dotted paths removed;
    `*` steps into every item of a list. None when it isn't JSON."""
    import json
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    else:
        value = json.loads(json.dumps(value))     # a deep copy
    if not isinstance(value, dict):
        return None

    def drop(node, parts):
        if not parts:
            return
        head, rest = parts[0], parts[1:]
        if head == "*" and isinstance(node, list):
            for item in node:
                drop(item, rest)
        elif isinstance(node, dict) and head in node:
            if rest:
                drop(node[head], rest)
            else:
                del node[head]

    for path in paths:
        drop(value, path.split("."))
    return value


@dataclass
class ParamSpec:
    name: str
    type: str
    label: str = ""
    default: Any = None
    options: list[str] = field(default_factory=list)  # choice only
    # choice only: a friendlier label for the option that means "leave this
    # alone" (by convention the default). The stored value is unchanged —
    # this only stops a bare sentinel like "keep" reading as a real choice
    # in the dropdown. "" leaves every option shown as written.
    unset_label: str = ""
    placeholder: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    # columns: comma list (True) or single column. page_ref: a set of pages
    # (True) or one page — which is its default, see from_dict.
    multi: bool = True
    hidden: bool = False  # not shown in the properties panel (edited elsewhere)
    # node_ref: card kind the referenced node must have. page_ref: the page
    # kind ("report", "dashboard") the picker offers; "" offers every page.
    ref_kind: str = ""
    # text only: offer a picker that inserts an upstream column name. For
    # boxes whose content is *about* columns but isn't a list of them -- a
    # rename mapping, an expression -- where a 'columns' param can't express
    # the value but the names are still what you're reaching for. Purely an
    # input aid: the stored value is the text either way. "" is off;
    # otherwise it says how the picker behaves, which is decided by what a
    # line in that box means:
    #   "inline"  -- insert the name at the cursor. For a line that names
    #                several columns at once, like `margin = revenue - cost`,
    #                which is built up a piece at a time.
    #   "mapping" -- the box is one `column = value` entry per line, so the
    #                picker is a set of ticks over the columns: ticking adds
    #                that column's line, unticking deletes it. Blank and #
    #                lines are carried through untouched.
    # True is accepted as a synonym for "inline".
    insert_columns: str = ""
    # Show this row only while other params hold certain values:
    # {"format": ["auto", "csv"]} means "visible when format is auto or csv".
    # Several keys are ANDed. A node that reads five file types would
    # otherwise show all five sets of options at once; this lets it show the
    # ones that apply. Purely presentational — run() still receives every
    # param, visible or not, so a hidden value is never silently dropped.
    visible_when: dict[str, list[str]] = field(default_factory=dict)
    # Presentation-only: changing it cannot change what run() produces, so
    # the node is NOT marked dirty and its cached output survives. For
    # things like how a list of charts is arranged — re-running a heavy
    # node because someone asked for two columns would be absurd.
    cosmetic: bool = False
    # A JSON param that is partly presentation: these paths inside it
    # ("freeze", "columns.*.width") cannot change what run() produces, so
    # an edit that changes only them leaves the node clean, like a
    # cosmetic param. The Table's data holds its sheet *and* how the sheet
    # looks; freezing a pane or hiding a column should not re-run a flow.
    presentation: tuple = ()
    # text only: offer a "build a rule…" button beside the box that opens
    # the conditional-formatting wizard and appends the line it builds.
    rule_wizard: bool = False
    # text only: which builder the box offers beside it — "table" is the
    # conditional-formatting rules manager (what rule_wizard says), "chart"
    # the chart-rules one. Blank is a plain box.
    wizard: str = ""
    # Properties-panel grouping: rows sharing a section sit under one
    # heading that folds. Rows with none stay at the top level, so a node
    # that declares no sections looks exactly as it always has. `folded`
    # on any row of a section starts that section folded until someone
    # opens it (the panel remembers per node type after that).
    section: str = ""
    folded: bool = False

    @classmethod
    def from_dict(cls, d: dict[str, Any], where: str = "PARAMS") -> "ParamSpec":
        if not isinstance(d, dict):
            raise ValueError(f"{where}: each param must be a dict, got {type(d).__name__}")
        name = d.get("name")
        if not name or not isinstance(name, str) or not name.isidentifier():
            raise ValueError(f"{where}: param needs a 'name' that is a valid identifier, got {name!r}")
        ptype = d.get("type")
        if ptype not in PARAM_TYPES:
            valid = ", ".join(sorted(PARAM_TYPES))
            raise ValueError(f"{where}: param {name!r} has unknown type {ptype!r} (valid: {valid})")
        cosmetic = bool(d.get("cosmetic", False))
        options = list(d.get("options", []))
        raw_when = d.get("visible_when") or {}
        if not isinstance(raw_when, dict):
            raise ValueError(
                f"{where}: param {name!r} has a 'visible_when' that is not a "
                f"dict of param -> allowed values, got {type(raw_when).__name__}")
        visible_when: dict[str, list[str]] = {}
        for controller, allowed in raw_when.items():
            if not isinstance(controller, str) or not controller.isidentifier():
                raise ValueError(
                    f"{where}: param {name!r} has a 'visible_when' key that is "
                    f"not a param name, got {controller!r}")
            if controller == name:
                raise ValueError(
                    f"{where}: param {name!r} cannot depend on its own value")
            # A bare string is the obvious way to write a single value, and
            # rejecting it would only teach people to type a one-item list.
            values = [allowed] if isinstance(allowed, str) else list(allowed)
            if not values:
                raise ValueError(
                    f"{where}: param {name!r} has an empty 'visible_when' for "
                    f"{controller!r} — it could never be shown")
            visible_when[controller] = [str(v) for v in values]
        if ptype == "choice" and not options:
            raise ValueError(f"{where}: choice param {name!r} requires non-empty 'options'")
        default = d.get("default", _TYPE_DEFAULTS[ptype])
        if ptype == "choice" and default is None:
            default = options[0]
        return cls(
            name=name,
            type=ptype,
            label=d.get("label", name.replace("_", " ").capitalize()),
            default=default,
            options=options,
            unset_label=str(d.get("unset_label", "")),
            placeholder=d.get("placeholder", ""),
            minimum=d.get("min"),
            maximum=d.get("max"),
            # a list is what a columns param is usually for; a page is what a
            # page_ref usually is, so the set of pages is the one asked for
            multi=bool(d.get("multi", ptype != "page_ref")),
            hidden=bool(d.get("hidden", False)),
            ref_kind=str(d.get("ref_kind", "")),
            insert_columns=_insert_columns_mode(
                d.get("insert_columns"), name, where),
            cosmetic=cosmetic,
            presentation=tuple(str(p) for p in d.get("presentation") or ()),
            rule_wizard=bool(d.get("rule_wizard", False)),
            wizard=str(d.get("wizard") or
                       ("table" if d.get("rule_wizard") else "")),
            visible_when=visible_when,
            section=str(d.get("section") or "").strip(),
            folded=bool(d.get("folded", False)),
        )

    def only_presentation_changed(self, old: Any, new: Any) -> bool:
        """Do `old` and `new` differ only in the `presentation` paths?"""
        if not self.presentation or old == new:
            return bool(self.presentation) and old == new
        a = _without(old, self.presentation)
        b = _without(new, self.presentation)
        return a is not None and a == b

    def visible_for(self, values: dict[str, Any]) -> bool:
        """Should this param have a row, given the node's current params?

        Unknown controllers show the param rather than hide it: a typo in a
        script's `visible_when` should leave an option findable, not make it
        vanish with no way to get it back.
        """
        if self.hidden:
            return False
        for controller, allowed in self.visible_when.items():
            if controller not in values:
                continue
            if str(values[controller]) not in allowed:
                return False
        return True


def controllers(specs: list["ParamSpec"]) -> set[str]:
    """Names whose value decides whether some other param is shown."""
    return {name for spec in specs for name in spec.visible_when}
