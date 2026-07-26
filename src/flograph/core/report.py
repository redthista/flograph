"""Report bodies: markdown text with node embeds.

A report page is *written*, not laid out — the body is markdown, and
anything the flow produced is pulled in by name:

    ![[Sales Chart]]            the node labelled "Sales Chart"
    ![[Summary|table]]          a particular output port of it

That is the whole syntax. Everything else in the body is ordinary markdown.

What an embed turns into depends on what the node produced, and the
important case is the plain string: a node that *returns markdown* is
inlined verbatim, so a report can be assembled by the flow rather than
typed. Build the prose in a Python Script node — headings, a paragraph per
region, a table you formatted yourself — and embed it.

This module is the parsing and the text side of that, kept Qt-free and
duck-typed so it can be tested without a canvas or pandas. Turning a figure
into pixels belongs to the UI (see ui/report/render.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ![[Label]] or ![[Label|port]] — the label runs to a "|" or "]]", so it may
# contain spaces and punctuation, which node labels routinely do.
EMBED_RE = re.compile(r"!\[\[\s*([^\]|]+?)\s*(?:\|\s*([^\]|]+?)\s*)?\]\]")

# What a resolved image becomes in the markdown before it is rendered. Qt's
# markdown reader silently drops image syntax, so images are carried through
# as a token in a paragraph of their own and swapped for real <img> tags in
# the HTML — see ui/report/render.py. The token has to be something no
# markdown construct will mangle and no user will type by accident.
IMAGE_TOKEN = "@@flograph-embed-{}@@"


@dataclass(frozen=True)
class Embed:
    """One ![[...]] in the body."""
    ref: str                  # the node label as written
    port: str                 # "" when unspecified — the node's first output
    raw: str                  # the full "![[...]]" text
    start: int
    end: int


def find_embeds(text: str) -> list[Embed]:
    """Every embed in the body, in the order they appear."""
    return [
        Embed(ref=match.group(1), port=(match.group(2) or "").strip(),
              raw=match.group(0), start=match.start(), end=match.end())
        for match in EMBED_RE.finditer(text or "")
    ]


def replace_embeds(text: str, render) -> str:
    """The body with every embed replaced by `render(embed)`.

    A replacement that isn't already surrounded by blank lines gets them:
    an embed sitting on its own line is a block, and markdown would
    otherwise fold a table or heading into the paragraph above it.
    """
    def substitute(match: re.Match) -> str:
        embed = Embed(ref=match.group(1), port=(match.group(2) or "").strip(),
                      raw=match.group(0), start=match.start(), end=match.end())
        replacement = render(embed)
        if replacement and "\n" in replacement.strip():
            return f"\n\n{replacement.strip()}\n\n"
        return replacement

    return EMBED_RE.sub(substitute, text or "")


def missing_embed(ref: str) -> str:
    """What an embed that resolves to nothing shows.

    Loudly, on the page: a report is something you hand to someone else, so
    a section that silently vanished because a node was renamed is the worst
    possible outcome.
    """
    return f"> **⚠ No node called “{ref}”** — check the name, or run the flow."


def unrun_embed(ref: str) -> str:
    return f"> **⚠ “{ref}” hasn’t run yet** — run the flow to fill this in."


#: Significant digits kept when writing a float into report prose. Ten is
#: enough that ordinary money and counts print in full — four turned
#: 114558.0 into "1.146e+05", which is not a thing to put in a report —
#: while still cutting the float noise off something like 1/3.
SCALAR_PRECISION = 10


def format_scalar(value) -> str:
    """A single value as report text — thousands separated, no scientific
    notation for anything a person would recognise as a number."""
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        return f"{value:,.{SCALAR_PRECISION}g}"
    return str(value)


def frame_to_markdown(frame, max_rows: int = 30) -> str:
    """A DataFrame (or Series) as a markdown table.

    Duck-typed — this module must not import pandas. Long frames are cut
    with a note saying so rather than silently, because a report that
    quietly shows the first 30 of 4000 rows is a lie.
    """
    if hasattr(frame, "to_frame") and not hasattr(frame, "columns"):
        frame = frame.to_frame()          # a Series
    columns = [str(c) for c in frame.columns]
    if not columns:
        return "> *(no columns)*"

    total = len(frame)
    shown = frame.head(max_rows) if total > max_rows else frame
    lines = ["| " + " | ".join(_cell(c) for c in columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    for record in shown.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(_cell(v) for v in record) + " |")
    if total > max_rows:
        lines.append("")
        lines.append(f"*Showing {max_rows:,} of {total:,} rows.*")
    return "\n".join(lines)


def _cell(value) -> str:
    """One table cell: missing values blank, pipes escaped so they can't
    break the row apart, newlines flattened so they can't end it."""
    try:
        if value is None or value != value:      # NaN/NaT; pd.NA raises
            return ""
    except Exception:
        return ""
    return format_scalar(value).replace("|", "\\|").replace("\n", " ")
