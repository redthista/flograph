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
from dataclasses import dataclass, field

# ![[Label]], ![[Label|port]], ![[Label|width=50%]], ![[Label|port|width=50%]]
#
# The label runs to a "|" or "]]", so it may contain spaces and punctuation,
# which node labels routinely do. Everything after it is a list of
# "|"-separated segments, sorted out by `parse_options` — a segment with an
# "=" in it is an option, a bare one that names a known flag is that flag,
# and any other bare one is the port name. That rule is what lets the port
# stay optional without a placeholder: `![[c|width=50%]]` is unambiguous
# because "width=50%" cannot be a port.
EMBED_RE = re.compile(r"!\[\[\s*([^\]|]+?)\s*((?:\|[^\]|]*)*)\]\]")

#: Options an embed understands, each written `key=value`. Deliberately a
#: closed set: a typo'd option is worth reporting, and silently ignoring
#: `widht=50%` would leave someone staring at an unchanged chart.
#:
#: `width`  — the placement width, `50%` of the text column or `280` points.
#: `ratio`  — the shape the chart is drawn at, `16:9` / `4x3` / `1.5`. The
#:            one option a table cannot take: it is as tall as its rows.
#: `height` — an exact height in points. A chart is redrawn at it; a table
#:            reads it as a budget of page and shows the rows that fit.
#: `scale`  — a chart's render density, `2` for fine detail (capped, never
#:            below 1). A table's *text size*, which does go below 1.
#: `rows`   — how many rows of a table to show before it is cut with a
#:            note. Only a table has rows; on a chart it says so.
EMBED_OPTIONS = ("width", "ratio", "height", "scale", "rows")

#: Bare-word flags an embed understands, written with no `=`. Matched
#: before the port, so a node whose label collides with one cannot be
#: embedded by that bare name — in practice none do.
#:
#: `fit` — shrink this chart, or trim this table, so it fits the space left
#: on the page rather than starting a new one and leaving a gap.
EMBED_FLAGS = ("fit",)


def parse_options(rest: str) -> "tuple[str, dict, list]":
    """Split the "|"-separated tail of an embed.

    Returns (port, options, unknown) — the port name, the options and flags
    that were recognised (a flag lands in the dict as ``True``), and any
    segments that were neither, which the renderer reports rather than
    swallowing.
    """
    port = ""
    options: dict = {}
    unknown: list = []
    for segment in (rest or "").split("|"):
        segment = segment.strip()
        if not segment:
            continue
        if segment.lower() in EMBED_FLAGS:
            options[segment.lower()] = True
        elif "=" in segment:
            key, _, value = segment.partition("=")
            key = key.strip().lower()
            if key in EMBED_OPTIONS:
                options[key] = value.strip()
            else:
                unknown.append(segment)
        elif not port:
            port = segment
        else:
            unknown.append(segment)
    return port, options, unknown

# What a resolved image becomes in the markdown before it is rendered. Qt's
# markdown reader silently drops image syntax, so images are carried through
# as a token in a paragraph of their own and swapped for real <img> tags in
# the HTML — see ui/report/render.py. The token has to be something no
# markdown construct will mangle and no user will type by accident.
IMAGE_TOKEN = "@@flograph-embed-{}@@"

# The URL that token's <img> ends up pointing at, and that the image is
# registered under as a document resource. Shared so the renderer that
# writes it and the animator that swaps frames behind it cannot drift.
IMAGE_TOKEN_URL = "embed:{}"

# A forced page break, written on a line of its own. Three spellings
# because there is no CommonMark one: `\pagebreak` and `\newpage` are what
# anyone who has met LaTeX or pandoc will try first, and the HTML comment
# is what someone who has met neither will guess — and it has the virtue of
# being invisible in any other markdown renderer.
PAGEBREAK_RE = re.compile(
    r"^[ \t]*(?:\\pagebreak|\\newpage|<!--[ \t]*(?:page ?break|new ?page)"
    r"[ \t]*-->)[ \t]*$",
    re.MULTILINE | re.IGNORECASE)

# Carried through the markdown pass the same way images are, and for the
# same reason: what it has to become is a *block property*, which markdown
# has no syntax for at all. See ui/report/render.py.
PAGEBREAK_TOKEN = "@@flograph-pagebreak@@"


# A columns block:
#
#     ```columns 2 1
#     Text down the left.
#     ---
#     ![[Chart]]
#     ```
#
# A fenced block rather than anything inline, for three reasons: a column
# holds *blocks* (headings, paragraphs, an embed) so it needs somewhere
# multi-line to live; the info string is somewhere to put the widths; and
# any other markdown renderer shows it as a code block rather than as
# mangled prose, which is the polite way to not be understood.
COLUMNS_RE = re.compile(
    r"^```[ \t]*columns[ \t]*([^\n]*)\n(.*?)\n?^```[ \t]*$",
    re.MULTILINE | re.DOTALL)

#: What separates one column from the next, on a line of its own. It is
#: consumed before any markdown is parsed, so it never reaches the reader
#: as a thematic break or a setext heading.
COLUMN_SPLIT_RE = re.compile(r"^---[ \t]*$", re.MULTILINE)


def parse_weights(spec: str, count: int) -> list:
    """The info string as one relative width per column.

    `2 1` is two-thirds and one-third; `60% 40%` is the same idea written
    the other way, and the % is decoration. Anything unparseable, or the
    wrong number of them, falls back to equal columns — a report with a
    typo in a width should still show its content.
    """
    parts = (spec or "").replace(",", " ").split()
    weights = []
    for part in parts:
        try:
            weights.append(max(0.01, float(part.rstrip("%"))))
        except ValueError:
            return [1.0] * count
    if len(weights) != count:
        return [1.0] * count
    return weights


def split_columns(block: str) -> list:
    """The body of a columns block, split into its columns."""
    return [part.strip("\n") for part in COLUMN_SPLIT_RE.split(block)]


def replace_columns(text: str, render) -> str:
    """Every columns block replaced by `render(columns, weights)`.

    Runs *before* embeds are resolved, so that an embed inside a column can
    be rendered knowing how wide its column is — a chart drawn at the full
    page width and then squeezed into a third of it would be unreadable.
    """
    def substitute(match: re.Match) -> str:
        columns = split_columns(match.group(2))
        if len(columns) < 2:
            # One column is not a layout. Returning the content unwrapped
            # keeps it visible rather than swallowing it into a table of
            # one cell, which would look like nothing happened but subtly
            # change the width everything inside was drawn at.
            return columns[0] if columns else ""
        return "\n\n" + render(columns,
                               parse_weights(match.group(1),
                                             len(columns))) + "\n\n"

    return COLUMNS_RE.sub(substitute, text or "")


def mark_page_breaks(text: str) -> str:
    """Swap every forced-break line for its token.

    Surrounded by blank lines so the token is always a paragraph of its
    own: written tight against the paragraph above it, markdown would fold
    it into that paragraph and the break would silently do nothing.
    """
    if not text:
        return ""
    return PAGEBREAK_RE.sub("\n\n" + PAGEBREAK_TOKEN + "\n\n", text)


@dataclass(frozen=True)
class Embed:
    """One ![[...]] in the body."""
    ref: str                  # the node label as written
    port: str                 # "" when unspecified — the node's first output
    raw: str                  # the full "![[...]]" text
    start: int
    end: int
    #: recognised per-embed options, e.g. {"width": "50%"}
    options: dict = field(default_factory=dict)
    #: segments that were neither a port nor a known option
    unknown: tuple = ()


def _embed_at(match: re.Match) -> Embed:
    port, options, unknown = parse_options(match.group(2))
    return Embed(ref=match.group(1), port=port, raw=match.group(0),
                 start=match.start(), end=match.end(), options=options,
                 unknown=tuple(unknown))


#: Where an embed is text about an embed rather than an embed: a fenced
#: code block, an inline code span, or the `<code>` a column's cell text has
#: already been turned into. Writing `` `![[Sales]]` `` in a report is how
#: you explain the syntax to whoever reads it, and resolving it there put
#: the *table's HTML* on the page as literal code.
#:
#: A ```columns block is not code and is not protected — it is consumed by
#: `replace_columns` before this runs, so anything still fenced by then is
#: a real code block.
_PROTECTED_RE = re.compile(
    r"^(?P<fence>```|~~~).*?^(?P=fence)[ \t]*$"   # fenced block
    r"|`+[^`\n]+`+"                               # inline code span
    r"|<code\b[^>]*>.*?</code>",                  # already HTML
    re.MULTILINE | re.DOTALL)


def _protected_spans(text: str) -> list:
    return [match.span() for match in _PROTECTED_RE.finditer(text or "")]


def _is_protected(spans, position: int) -> bool:
    return any(start <= position < end for start, end in spans)


def find_embeds(text: str) -> list[Embed]:
    """Every embed in the body, in the order they appear — not counting the
    ones written inside code, which are examples of the syntax rather than
    uses of it."""
    spans = _protected_spans(text)
    return [_embed_at(match) for match in EMBED_RE.finditer(text or "")
            if not _is_protected(spans, match.start())]


def replace_embeds(text: str, render) -> str:
    """The body with every embed replaced by `render(embed)`.

    A replacement that isn't already surrounded by blank lines gets them:
    an embed sitting on its own line is a block, and markdown would
    otherwise fold a table or heading into the paragraph above it.

    An embed inside code is left exactly as written — see `_PROTECTED_RE`.
    """
    spans = _protected_spans(text)

    def substitute(match: re.Match) -> str:
        if _is_protected(spans, match.start()):
            return match.group(0)
        replacement = render(_embed_at(match))
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


def inline_markdown(text: str) -> str:
    """A node's string output, ready to drop into a report body.

    The one thing this does is remove the indentation Python put there. A
    node builds its markdown inside `run()`, so the natural way to write it

        def run(ctx):
            return '''
            ## Summary
            '''

    hands us four spaces on every line — and four spaces in markdown means
    *code block*, so the heading came out as literal text. Every user
    writing the "build the report from data" path hits this, and the cause
    is invisible: the string looks right in the editor and wrong on the
    page.

    textwrap.dedent, deliberately, and not inspect.cleandoc. cleandoc also
    handles the case where the first line is flush and the rest are
    indented, but it computes the margin from the *remaining* lines only —
    so prose followed by a genuinely indented code block

        Some text

            def foo(): ...

    has a margin of four by its reckoning, and cleandoc would strip the
    code block's indentation and turn it into prose. dedent takes the
    common prefix of every line, which is nothing here, and leaves it
    alone. Fixing the common case must not break the deliberate one.
    """
    import textwrap
    return textwrap.dedent(text)


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
