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

Tokens are the server's own count, from each request's reply (`usage` on
the outbox entry). Every request repeats the conversation so far, so the
input count of a long build grows with each step — which is the point of
showing it. A server that reports nothing is said to, never estimated; a
cost is shown only at prices the user typed into the connection.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..core import ai_disclosure as disc

_FREE_TEXT_KEYS = {"settings", "value", "label", "markdown", "title", "code"}


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
    rows: int = 0                        # rows of data that went (FULL only)
    settings_nodes: int = 0              # nodes whose settings were sent
    reports: int = 0                     # report pages whose text was sent
    code_nodes: int = 0                  # nodes whose own (user) code was sent
    text_hidden: bool = False            # typed setting text was withheld
    tokens_in: int = 0                   # as the server counted them
    tokens_out: int = 0
    counted: int = 0                     # requests whose reply had a count
    chat_in: int = 0                     # the whole chat so far
    chat_out: int = 0
    chat_requests: int = 0
    prices: Any = None                   # (in, out, currency) per million

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
                         f"column{_s(len(self.values))}")
        parts.append(f"{self.rows} row{_s(self.rows)} of your data"
                     if self.rows else "no rows")
        return f"{where}: " + ", ".join(parts) + "." + self._tokens_line()

    def _tokens_line(self) -> str:
        if not self.counted:
            return ""
        some = "At least " if self.counted < self.requests else ""
        line = (f" {some}{_short(self.tokens_in)} tokens in, "
                f"{_short(self.tokens_out)} out")
        cost = self.cost(self.tokens_in, self.tokens_out)
        return line + (f" ({cost})." if cost else ".")

    def cost(self, spent: int, made: int) -> str:
        """'≈ $0.04' at the connection's prices; '' when it has none."""
        if not self.prices:
            return ""
        price_in, price_out, currency = self.prices
        amount = (spent * price_in + made * price_out) / 1_000_000
        if amount and amount < 0.01:
            return f"under {currency}0.01"
        return f"≈ {currency}{amount:,.2f}"

    def token_details(self) -> list[str]:
        if not self.requests:
            return []
        if not self.counted:
            return ["Tokens: the server didn't say how many — some local "
                    "servers and gateways don't."]
        line = (f"Tokens: {self.tokens_in:,} in, {self.tokens_out:,} out, "
                f"over {self.requests} request{_s(self.requests)}")
        if self.counted < self.requests:
            line += f" ({self.counted} of them gave a count)"
        out = [line + "."]
        if self.chat_requests > self.requests:
            cost = self.cost(self.chat_in, self.chat_out)
            out.append(f"This chat so far: {self.chat_in:,} tokens in, "
                       f"{self.chat_out:,} out" + (f" ({cost})" if cost else "")
                       + ".")
        if self.prices:
            price_in, price_out, currency = self.prices
            out.append(f"Cost is worked out at the prices on this connection "
                       f"({currency}{price_in:g} in, {currency}{price_out:g} out "
                       "per million tokens), before any discount.")
        return out

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
            out.append("Values: "
                       + ", ".join(self.values))
        if self.settings_nodes:
            out.append(f"Settings of {self.settings_nodes} node"
                       f"{_s(self.settings_nodes)}, "
                       + ("with text you typed hidden"
                          if self.text_hidden else
                          "including text you typed into them"))
        if self.reports:
            out.append(f"Text of {self.reports} report page{_s(self.reports)}")
        if self.code_nodes:
            out.append(f"Code you wrote or changed, of {self.code_nodes} "
                       f"node{_s(self.code_nodes)}")
        if self.rows:
            out.append(f"Rows of your data: {self.rows} (you chose All my data)")
            out.append("Never sent: hidden columns, passwords, full file paths.")
        else:
            out.append("Never sent: rows of your data, passwords, full file paths.")
        return out + self.token_details()


def _s(n: int) -> str:
    return "" if n == 1 else "s"


def _short(n: int) -> str:
    """812, 4,210, 18.4k, 1.2M — a count to read at a glance."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1000:.1f}k"
    return f"{n:,}"


def tally(entries: Iterable) -> tuple[int, int, int]:
    """(tokens in, tokens out, requests that gave a count)."""
    spent = made = counted = 0
    for entry in entries:
        usage = entry.get("usage") if isinstance(entry, dict) else None
        if isinstance(usage, dict):
            spent += int(usage.get("input") or 0)
            made += int(usage.get("output") or 0)
            counted += 1
    return spent, made, counted


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


def _count_rows(value) -> int:
    """Rows in a tool result: a table's sample, or a get_rows page."""
    if isinstance(value, dict):
        total = 0
        for key in ("sample_rows", "rows"):
            if isinstance(value.get(key), list):
                total += len(value[key])
        return total + sum(_count_rows(v) for k, v in value.items()
                           if k not in ("sample_rows", "rows"))
    if isinstance(value, list):
        return sum(_count_rows(v) for v in value)
    return 0


def build(entries: list, before: list, disclosure: disc.Disclosure, *,
          destination: str, local: bool, chat: Iterable = (),
          prices=None) -> Receipt:
    """`chat` is every request of the conversation so far, this reply's
    included, for the running token total."""
    receipt = Receipt(destination=destination, local=local,
                      requests=len(entries),
                      text_hidden=not disclosure.allows(disc.SCHEMA),
                      prices=prices)
    receipt.tokens_in, receipt.tokens_out, receipt.counted = tally(entries)
    chat = list(chat)
    receipt.chat_in, receipt.chat_out, _ = tally(chat)
    receipt.chat_requests = len(chat)
    if not entries:
        return receipt
    last = entries[-1].get("messages") or []
    new = [m for m in last[len(before):] if m.get("role") in ("user", "tool")]

    # a hidden name should never be in what went; if one is, it is counted
    # like any other — the receipt reports what left, not what should have
    real = {name for name in disclosure._known}
    aliases: dict[str, str] = {}
    found_real: set[str] = set()
    found_alias: set[str] = set()
    described: set[str] = set()
    with_settings: set[str] = set()
    reports: set[str] = set()
    code: set[str] = set()

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
        if isinstance(data, dict) and isinstance(data.get("markdown"), str) \
                and not data["markdown"].startswith("<text,"):
            reports.add(str(data.get("page")))
        if isinstance(data, dict) and isinstance(data.get("code"), str) \
                and not data["code"].startswith("<code of") \
                and not data.get("library_code"):
            # the library's own code is no one's data; the user's may be
            code.add(str(data.get("node")))
        receipt.rows += _count_rows(data)
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
    receipt.reports = len(reports)
    receipt.code_nodes = len(code)
    receipt.aliased = sorted((aliases[a], a) for a in found_alias)
    receipt.columns = sorted(found_real - {real_name for real_name, _ in receipt.aliased})
    receipt.profiled = sorted(set(receipt.profiled))
    receipt.ranges = sorted(set(receipt.ranges))
    receipt.values = sorted(set(receipt.values))
    return receipt
