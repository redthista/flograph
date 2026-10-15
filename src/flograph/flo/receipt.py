"""What one reply actually sent, in plain words — the dock's receipt.

Read from the outbox, not from the dials: it reports what the requests
*held*, so if the disclosure rules ever let something through that the
level should not have, the receipt shows it rather than repeating the
promise. Only what this reply added counts — the user's words and the tool
results. The system prompt holds no data, and the model's own messages came
from the server in the first place.

Column names are found by walking the tool results' JSON *values* (never
keys, so a column called "name" isn't found in every result) for an exact
column name or alias, and by a whole-word search of free text: the user's
message and node settings.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..core import ai_disclosure as disc

_FREE_TEXT_KEYS = {"settings", "value", "label"}


@dataclass
class Receipt:
    destination: str = ""
    local: bool = False
    requests: int = 0
    message: bool = False                # the user's own words went
    nodes: int = 0                       # nodes described (structure)
    columns: list = field(default_factory=list)     # sent under their real name
    aliased: list = field(default_factory=list)     # (real, alias) pairs
    profiled: list = field(default_factory=list)    # shown names with stats
    ranges: list = field(default_factory=list)      # shown names with min/max
    values: list = field(default_factory=list)      # shown names, values shared
    settings_nodes: int = 0              # nodes whose settings were sent
    text_hidden: bool = False            # typed setting text was withheld

    @property
    def sent_anything(self) -> bool:
        return self.requests > 0

    def summary(self) -> str:
        """One line: where, then what."""
        if not self.requests:
            return "Nothing was sent."
        where = ("Stayed on this PC" if self.local
                 else f"Sent to {self.destination}")
        parts = []
        if self.message:
            parts.append("your message")
        if self.nodes:
            parts.append(f"the flow ({self.nodes} node{_s(self.nodes)})")
        names = len(self.columns) + len(self.aliased)
        if names:
            parts.append(f"{names} column name{_s(names)}")
        if self.ranges:
            parts.append(f"value ranges of {len(self.ranges)} "
                         f"column{_s(len(self.ranges))}")
        elif self.profiled:
            parts.append(f"counts for {len(self.profiled)} "
                         f"column{_s(len(self.profiled))}")
        if self.values:
            parts.append(f"the values of {len(self.values)} "
                         f"column{_s(len(self.values))} you share")
        parts.append("no rows")
        return f"{where}: " + ", ".join(parts) + "."

    def details(self) -> list[str]:
        out = []
        if self.columns:
            out.append("Column names: " + ", ".join(self.columns))
        if self.aliased:
            out.append("Under an alias: " + ", ".join(
                f"{real} (as {alias})" for real, alias in self.aliased))
        if self.profiled:
            out.append("Empty share and distinct count: "
                       + ", ".join(self.profiled))
        if self.ranges:
            out.append("Smallest and largest value: " + ", ".join(self.ranges))
        if self.values:
            out.append("Distinct values (you chose to share): "
                       + ", ".join(self.values))
        if self.settings_nodes:
            out.append(f"Settings of {self.settings_nodes} node"
                       f"{_s(self.settings_nodes)}, "
                       + ("with text you typed hidden"
                          if self.text_hidden else
                          "including text you typed (hide it in Privacy)"))
        out.append("Never sent: rows of your data, passwords, full file paths.")
        return out


def _s(n: int) -> str:
    return "" if n == 1 else "s"


def _strings(value: Any, path: tuple = ()) -> Iterable[tuple[tuple, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, path + (str(key),))
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item, path)


def _columns_in(value: Any) -> Iterable[dict]:
    """Every column description in a get_output result."""
    if isinstance(value, dict):
        if "name" in value and "type" in value and (
                "empty_percent" in value or "distinct" in value
                or "min" in value or "values" in value):
            yield value
        for item in value.values():
            yield from _columns_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from _columns_in(item)


def build(entries: list, before: list, disclosure: disc.Disclosure, *,
          destination: str, local: bool) -> Receipt:
    receipt = Receipt(destination=destination, local=local,
                      requests=len(entries),
                      text_hidden=disclosure.privacy.hide_text)
    if not entries:
        return receipt
    last = entries[-1].get("messages") or []
    new = [m for m in last[len(before):] if m.get("role") in ("user", "tool")]

    real = {name for name in disclosure._known}
    aliases = {rule.alias: name for name, rule in disclosure.privacy.columns.items()
               if rule.alias}
    found_real: set[str] = set()
    found_alias: set[str] = set()
    described: set[str] = set()
    with_settings: set[str] = set()

    def words(text: str) -> None:
        for name in real:
            if name in text and re.search(
                    r"(?<![\w])" + re.escape(name) + r"(?![\w])", text):
                found_real.add(name)
        for alias in aliases:
            if alias in text and re.search(
                    r"(?<![\w])" + re.escape(alias) + r"(?![\w])", text):
                found_alias.add(alias)

    for message in new:
        content = str(message.get("content") or "")
        if message["role"] == "user":
            receipt.message = True
            words(content)
            continue
        try:
            data = json.loads(content)
        except (TypeError, ValueError):
            words(content)
            continue
        for path, text in _strings(data):
            if text in real:
                found_real.add(text)
            elif text in aliases:
                found_alias.add(text)
            elif _FREE_TEXT_KEYS & set(path):
                words(text)
        nodes = data.get("nodes") if isinstance(data, dict) else None
        for node in (nodes if isinstance(nodes, list) else
                     [data] if isinstance(data, dict) and "node" in data else []):
            if isinstance(node, dict) and node.get("node"):
                if "type" in node:
                    described.add(str(node["node"]))
                if node.get("settings"):
                    with_settings.add(str(node["node"]))
        for column in _columns_in(data):
            shown = str(column.get("name"))
            if "empty_percent" in column or "distinct" in column:
                receipt.profiled.append(shown)
            if "min" in column:
                receipt.ranges.append(shown)
            if "values" in column:
                receipt.values.append(shown)

    receipt.nodes = len(described)
    receipt.settings_nodes = len(with_settings)
    receipt.aliased = sorted((aliases[a], a) for a in found_alias)
    receipt.columns = sorted(found_real - {real_name for real_name, _ in receipt.aliased})
    receipt.profiled = sorted(set(receipt.profiled))
    receipt.ranges = sorted(set(receipt.ranges))
    receipt.values = sorted(set(receipt.values))
    return receipt
