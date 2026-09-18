"""The Chart rules… dialog: the rules on a chart as a list, and a form per
rule that writes the line for you.

The language (`flograph.core.chart_rules`) is the thing itself — this only
composes and reads back its lines, so a rule typed by hand and one built
here are the same text. Every form field starts on "leave it alone", and a
field left alone contributes no word to the line, which is what keeps a
built rule as short as a written one.

Mirrors `table_rule_wizard.RuleManager` in shape (a list down the left,
add / edit / duplicate / remove / reorder down the right) so the two
wizards are learnt once.
"""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from flograph.core import chart_rules

#: "leave this out of the line"
_NONE = "—"


def _combo(options, current: str = "") -> QComboBox:
    combo = QComboBox()
    combo.addItem(_NONE, "")
    for option in options:
        combo.addItem(str(option), str(option))
    if current:
        index = combo.findData(str(current))
        combo.setCurrentIndex(index if index >= 0 else 0)
    return combo


def _quote(text: str) -> str:
    """Text the rule carries, always quoted — a title of one word needs no
    quotes, but a line that keeps them reads the same when the title grows
    a second word."""
    return '"{}"'.format(str(text).strip().replace('"', "'"))


class _RuleForm(QDialog):
    """One rule, as a form. `line()` is what it writes."""

    #: verb -> the fields it offers, in the order they join the line.
    FIELDS: dict[str, list[tuple]] = {
        "series": [
            ("what", "What to plot", "text",
             "a column, or total / average / min / max / count"),
            ("of", "Columns to total", "text", "blank = the chart's own"),
            ("source", "From", "choice", ("compare",)),
            ("style", "Draw as", "choice", tuple(chart_rules.SERIES_STYLES)),
            ("axis", "On axis", "choice", ("left", "right")),
            ("thick", "Thick", "choice", ("thick",)),
            ("colour", "Colour", "colour", ()),
            ("label", "Legend label", "text", "blank = the column's name"),
        ],
        "axis": [
            ("axis", "Axis", "choice", ("x", "y", "y2")),
            ("title", "Title", "text", 'blank leaves it as plotted'),
            ("hide", "Hide", "choice", ("title", "ticks", "axis")),
            ("format", "Tick format", "text", ",.0f  or  %b %Y"),
            ("grid", "Gridlines", "choice", ("on", "off")),
            ("log", "Log scale", "choice", ("log",)),
            ("low", "Range from", "number", ()),
            ("high", "Range to", "number", ()),
            ("angle", "Tick angle", "number", ()),
            ("order", "Sort categories", "choice",
             chart_rules._CATEGORY_ORDERS),
        ],
        "legend": [
            ("show", "Show", "choice", ("show", "hide")),
            ("position", "Position", "choice",
             tuple(chart_rules.LEGEND_POSITIONS)),
            ("orientation", "Layout", "choice", ("horizontal", "vertical")),
            ("title", "Title", "text", ""),
            ("hide_title", "Hide title", "choice", ("hide title",)),
            ("size", "Text size", "number", ()),
            ("background", "Background", "colour", ()),
            ("border", "Border", "colour", ()),
            ("clicks", "Clicks", "choice", ("off", "toggle", "isolate")),
        ],
        "title": [("text", "Title", "text", ""),
                  ("align", "Position", "choice",
                   ("left", "center", "right"))],
        "subtitle": [("text", "Subtitle", "text", "")],
        "note": [("text", "Note", "text", ""),
                 ("position", "Corner", "choice",
                  ("top left", "top right", "bottom left", "bottom right"))],
        "line": [("at", "Value", "number", ()),
                 ("axis", "On axis", "choice", ("y", "x")),
                 ("dash", "Style", "choice",
                  ("dashed", "dotted", "solid", "dashdot")),
                 ("colour", "Colour", "colour", ()),
                 ("label", "Label", "text", "")],
        "font": [("family", "Family", "text", "e.g. Georgia"),
                 ("size", "Size", "number", ()),
                 ("colour", "Colour", "colour", ())],
        "background": [("plot", "Plot area", "colour", ()),
                       ("paper", "Card", "colour", ())],
        "margin": [("left", "Left", "number", ()),
                   ("right", "Right", "number", ()),
                   ("top", "Top", "number", ()),
                   ("bottom", "Bottom", "number", ())],
        "hover": [("mode", "Hover", "choice",
                   ("unified", "x", "y", "closest", "off"))],
        "bars": [("mode", "Bars", "choice",
                  ("group", "stack", "overlay", "relative")),
                 ("gap", "Gap", "number", ())],
        "colorbar": [("hide", "Hide it", "choice", ("hide",)),
                     ("title", "Title", "text", "")],
        "layout": [("json", "Layout JSON", "json",
                    '{"bargap": 0.3}  —  plotly.com/python/reference/layout')],
        "traces": [("json", "Traces JSON", "json",
                    '{"marker_line_width": 1}')],
        "config": [("json", "Interactivity JSON", "json",
                    '{"scrollZoom": true, "displayModeBar": false}')],
    }

    def __init__(self, line: str = "", columns=(), parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Chart rule")
        self.setModal(True)
        self.resize(460, 420)
        self._columns = list(columns or [])
        self._widgets: dict[str, QWidget] = {}

        outer = QVBoxLayout(self)
        self._verb = QComboBox()
        for verb in self.FIELDS:
            self._verb.addItem(verb, verb)
        self._verb.currentIndexChanged.connect(self._rebuild)
        top = QFormLayout()
        top.addRow("Rule", self._verb)
        outer.addLayout(top)

        self._body = QWidget()
        self._form = QFormLayout(self._body)
        outer.addWidget(self._body, 1)

        self._preview = QLabel()
        self._preview.setWordWrap(True)
        self._preview.setStyleSheet("color: palette(mid);")
        outer.addWidget(self._preview)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        rule = None
        if line.strip():
            _, rule, _ = chart_rules.parse_rule_lines(line)[0]
        if rule is not None:
            index = self._verb.findData(
                "line" if rule.kind == "refline" else rule.kind)
            self._verb.setCurrentIndex(max(0, index))
        self._rebuild(fill=rule)

    # ------------------------------------------------------------ building

    def _rebuild(self, *_args, fill=None) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)
        self._widgets = {}
        verb = self._verb.currentData()
        for name, label, kind, extra in self.FIELDS[verb]:
            widget = self._field(kind, extra)
            self._widgets[name] = widget
            self._form.addRow(label, widget)
        if fill is not None:
            self._fill(verb, fill)
        self._refresh_preview()

    def _field(self, kind: str, extra) -> QWidget:
        if kind == "choice":
            widget = _combo(extra)
            widget.currentIndexChanged.connect(self._refresh_preview)
            return widget
        if kind == "colour":
            widget = QComboBox()
            widget.setEditable(True)
            widget.addItem("")
            for name in chart_rules.BASIC_COLORS:
                widget.addItem(name)
            widget.currentTextChanged.connect(self._refresh_preview)
            return widget
        if kind == "number":
            widget = QLineEdit()
            widget.setPlaceholderText("a number")
            widget.textChanged.connect(self._refresh_preview)
            return widget
        if kind == "json":
            widget = QPlainTextEdit()
            widget.setPlaceholderText(str(extra))
            widget.setMaximumHeight(90)
            widget.textChanged.connect(self._refresh_preview)
            return widget
        widget = QLineEdit()
        widget.setPlaceholderText(str(extra))
        if self._columns:
            from PySide6.QtWidgets import QCompleter
            widget.setCompleter(QCompleter(self._columns, widget))
        widget.textChanged.connect(self._refresh_preview)
        return widget

    def _value(self, name: str) -> str:
        widget = self._widgets.get(name)
        if widget is None:
            return ""
        if isinstance(widget, QComboBox):
            data = widget.currentData()
            return str(data if data is not None else widget.currentText())
        if isinstance(widget, QPlainTextEdit):
            return widget.toPlainText().strip()
        if isinstance(widget, QDoubleSpinBox):
            return str(widget.value())
        return widget.text().strip()

    def _set(self, name: str, value: Any) -> None:
        widget = self._widgets.get(name)
        if widget is None or value in (None, ""):
            return
        text = str(value)
        if isinstance(widget, QComboBox):
            index = widget.findData(text)
            if index < 0:
                index = widget.findText(text)
            if index >= 0:
                widget.setCurrentIndex(index)
            elif widget.isEditable():
                widget.setCurrentText(text)
        elif isinstance(widget, QPlainTextEdit):
            widget.setPlainText(text)
        else:
            widget.setText(text)

    def _fill(self, verb: str, rule) -> None:
        """Put a rule already written back into the form."""
        opts = dict(rule.opts)
        if verb == "series":
            self._set("what", opts.get("column") or opts.get("aggregate", ""))
            self._set("of", ", ".join(opts.get("columns", [])))
            self._set("thick", "thick" if opts.get("width") == 3 else "")
        elif verb == "axis":
            hide = ("title" if opts.get("hide_title") else
                    "ticks" if opts.get("hide_ticks") else
                    "axis" if opts.get("hide") else "")
            self._set("hide", hide)
            self._set("log", "log" if opts.get("log") else "")
            if "grid" in opts:
                self._set("grid", "on" if opts["grid"] else "off")
            if opts.get("range"):
                self._set("low", opts["range"][0])
                self._set("high", opts["range"][1])
        elif verb == "legend":
            self._set("show", "show" if opts.get("show") else
                      "hide" if opts.get("show") is False else "")
            self._set("hide_title", "hide title" if opts.get("hide_title")
                      else "")
            self._set("orientation", {"h": "horizontal",
                                      "v": "vertical"}.get(
                                          opts.get("orientation", ""), ""))
        elif verb == "margin":
            for name, value in zip(("left", "right", "top", "bottom"),
                                   opts.get("values", [])):
                self._set(name, value)
        elif verb == "line":
            self._set("dash", {"dash": "dashed", "dot": "dotted",
                               "solid": "solid",
                               "dashdot": "dashdot"}.get(opts.get("dash", "")))
        elif verb == "colorbar":
            self._set("hide", "hide" if opts.get("hide") else "")
        elif verb in ("layout", "traces", "config"):
            import json
            self._set("json", json.dumps(opts.get("json", {})))
        elif verb == "hover":
            mode = opts.get("mode")
            self._set("mode", "off" if mode is False
                      else str(mode).replace("x unified", "unified"))
        for name, _, _, _ in self.FIELDS[verb]:
            if name not in self._widgets:
                continue
            if name in opts and not self._value(name):
                self._set(name, opts[name])

    # ------------------------------------------------------------- the line

    def line(self) -> str:
        verb = self._verb.currentData()
        words: list[str] = [verb]
        get = self._value
        if verb == "series":
            what = get("what")
            if not what:
                return ""
            words.append(what)
            if get("of"):
                words.append("of " + get("of"))
            for name, prefix in (("source", "from "), ("style", ""),
                                 ("axis", ""), ("thick", ""), ("colour", "")):
                # the chart's own axis is where a series goes unless it is
                # sent to the right, so "left" is a word worth not writing
                if get(name) and not (name == "axis" and get(name) == "left"):
                    words.append(prefix + get(name))
            if get("label"):
                words.append("as " + _quote(get("label")))
        elif verb == "axis":
            words.append(get("axis") or "y")
            if get("title"):
                words.append("title " + _quote(get("title")))
            if get("hide"):
                words.append("hide" if get("hide") == "axis"
                             else "hide " + get("hide"))
            if get("format"):
                words.append("format " + get("format"))
            if get("grid"):
                words.append("grid " + get("grid"))
            if get("log"):
                words.append("log")
            if get("low") and get("high"):
                words.append(f"range {get('low')} {get('high')}")
            if get("angle"):
                words.append("angle " + get("angle"))
            if get("order"):
                words.append("order " + get("order"))
        elif verb == "legend":
            for name, prefix in (("show", ""), ("position", ""),
                                 ("orientation", "")):
                if get(name):
                    words.append(get(name))
            if get("hide_title"):
                words.append("hide title")
            if get("title"):
                words.append("title " + _quote(get("title")))
            for name in ("size", "background", "border"):
                if get(name):
                    words.append(f"{name} {get(name)}")
            if get("clicks"):
                words.append("clicks " + get("clicks"))
        elif verb in ("title", "subtitle", "note"):
            if not get("text"):
                return ""
            words.append(_quote(get("text")))
            words.append(get("align") or get("position"))
        elif verb == "line":
            if not get("at"):
                return ""
            words.append("at " + get("at"))
            if get("axis"):
                words.append("on " + get("axis"))
            for name in ("dash", "colour"):
                if get(name):
                    words.append(get(name))
            if get("label"):
                words.append("label " + _quote(get("label")))
        elif verb == "font":
            words += [get("family"), get("size"), get("colour")]
        elif verb == "background":
            for name in ("plot", "paper"):
                if get(name):
                    words.append(f"{name} {get(name)}")
        elif verb == "margin":
            values = [get(n) for n in ("left", "right", "top", "bottom")]
            if not all(values):
                return ""
            words += values
        elif verb == "bars":
            words += [get("mode"), f"gap {get('gap')}" if get("gap") else ""]
        elif verb == "colorbar":
            if get("hide"):
                words.append("hide")
            elif get("title"):
                words.append("title " + _quote(get("title")))
            else:
                return ""
        elif verb in ("layout", "traces", "config", "hover"):
            words.append(get("json") or get("mode"))
        return " ".join(word for word in words if word).strip()

    def _refresh_preview(self) -> None:
        line = self.line()
        if not line:
            self._preview.setText("Fill the form in and the rule shows here.")
            return
        _, rule, error = chart_rules.parse_rule_lines(line)[0]
        self._preview.setText(error if error else line)


class ChartRuleManager(QDialog):
    """The chart's rules as a list, with add / edit / remove / reorder."""

    def __init__(self, text: str, columns=(), parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Chart rules")
        self.setModal(True)
        self.resize(560, 400)
        self._columns = list(columns or [])
        self._lines = [raw for raw in str(text or "").splitlines()]

        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "Rules run top to bottom, after the settings above — a later "
            "rule wins where two touch the same thing."))
        body = QHBoxLayout()
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda *_: self._edit())
        body.addWidget(self._list, 1)

        side = QVBoxLayout()
        for label, slot in (("＋  Add rule", self._add), ("Edit…", self._edit),
                            ("Duplicate", self._duplicate),
                            ("Remove", self._remove),
                            ("Move up", lambda: self._move(-1)),
                            ("Move down", lambda: self._move(1))):
            button = QPushButton(label)
            button.clicked.connect(slot)
            side.addWidget(button)
        side.addStretch(1)
        body.addLayout(side)
        outer.addLayout(body, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self._refresh()

    def result_text(self) -> str:
        return "\n".join(self._lines)

    # --------------------------------------------------------------- list

    def _refresh(self, select: Optional[int] = None) -> None:
        self._list.clear()
        for raw in self._lines:
            _, rule, error = chart_rules.parse_rule_lines(raw)[0]
            item = QListWidgetItem(raw.strip() or "(blank)")
            if error:
                # the line keeps its own width; why it is wrong is a hover
                # away, so one bad rule cannot stretch the list
                item.setText(f"\N{WARNING SIGN}  {raw.strip()}")
                item.setToolTip(error)
                item.setForeground(Qt.red)
            elif rule is None:
                item.setForeground(Qt.gray)      # a comment or a blank line
            self._list.addItem(item)
        if select is not None and 0 <= select < self._list.count():
            self._list.setCurrentRow(select)

    def _current(self) -> int:
        return self._list.currentRow()

    def _add(self) -> None:
        dialog = _RuleForm("", self._columns, self)
        if dialog.exec() == QDialog.Accepted and dialog.line():
            self._lines.append(dialog.line())
            self._refresh(len(self._lines) - 1)

    def _edit(self) -> None:
        row = self._current()
        if row < 0:
            return
        dialog = _RuleForm(self._lines[row], self._columns, self)
        if dialog.exec() == QDialog.Accepted and dialog.line():
            self._lines[row] = dialog.line()
            self._refresh(row)

    def _duplicate(self) -> None:
        row = self._current()
        if row >= 0:
            self._lines.insert(row + 1, self._lines[row])
            self._refresh(row + 1)

    def _remove(self) -> None:
        row = self._current()
        if row >= 0:
            del self._lines[row]
            self._refresh(min(row, len(self._lines) - 1))

    def _move(self, step: int) -> None:
        row = self._current()
        target = row + step
        if row < 0 or not 0 <= target < len(self._lines):
            return
        self._lines[row], self._lines[target] = (self._lines[target],
                                                 self._lines[row])
        self._refresh(target)
