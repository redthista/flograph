"""Qt's HTML, said in fewer bytes — and only in ways a browser cannot see.

QTextDocument.toHtml writes every declaration it knows, on every element:
a table cell carries its padding, then each of its four borders three
times over (width, colour, style), and the paragraph inside it its four
margins and two of Qt's own properties. A 30-row table came out at
107 KB, 91% of it `style=` attributes — most of it the same 400 bytes
again in every cell.

Most of that does nothing in a browser at all:

* `-qt-block-indent`, `-qt-paragraph-type`, … are Qt's — a browser drops
  any property it does not know.
* `padding-left:7` has no unit. The page is in standards mode (Qt's
  doctype says HTML 4.0 strict), where a length without a unit is invalid
  and the declaration is thrown away; the cell is drawn with no padding
  either way. A *zero* stays — `0` needs no unit, and it is what beats a
  `<td>`'s own 1px.
* `text-indent:0px` is the initial value. It is inherited, so it only goes
  when nothing in the document indents.

and the rest says in one declaration what it said in four or twelve:
four equal margins are `margin`, four sides of one border are `border`.

What a theme reads stays as it was. The themes pick out Qt's markup by the
text of its inline styles (`[style*="margin-left:40px; margin-right:40px"]`
for a quote, `[style*=" color:"]` for a span that has a colour of its
own), so this keeps Qt's spelling — a space before each declaration, `; `
between them — and only shortens a margin whose four sides are the same,
which a quote's are not. The `[style*="border-top"]` cell selectors were
already matching nothing in a browser (`table > tr` — the parser puts a
`<tbody>` in between), so folding the borders cannot lose them.

Run on Qt's own output, before anything is spliced into it: the live
tables are written lean already, and Plotly's script and a chart's JSON
must never meet a regex looking for `style="`.
"""
from __future__ import annotations

import re

#: A style attribute inside a tag. Inside a tag only: Qt writes `"` in text
#: as `&quot;` and `<` as `&lt;`, so text can never look like this.
_STYLE_ATTR = re.compile(r'(<[A-Za-z][^<>]*?\sstyle=")([^"]*)(")')

#: A length or number with no unit — `7`, `-2`, `0.5`. Zero is valid.
_UNITLESS = re.compile(r"-?\d*\.?\d+")

_SIDES = ("top", "right", "bottom", "left")

#: What may fold to a shorthand when its four sides agree, and the family
#: of properties that could also set it.
_FOLDS = (("margin-{}", "margin"), ("padding-{}", "padding"),
          ("border-{}-color", "border"), ("border-{}-style", "border"))

#: Any text-indent in the document that is not the initial value.
_INDENTED = re.compile(r"text-indent:\s*(?!0(?:px)?\s*(?:;|$|\"))", re.I)


def compact_qt_html(html: str) -> str:
    """`html` (QTextDocument.toHtml's) with its inline styles shortened —
    see the module's docstring for what may and may not go."""
    drop_indent = not _INDENTED.search(html)

    def one(match: re.Match) -> str:
        style = _compact_style(match.group(2), drop_indent)
        return match.group(1) + style + match.group(3)

    html = _STYLE_ATTR.sub(one, html)
    # an attribute left with nothing in it
    return html.replace(' style=""', "")


def _compact_style(style: str, drop_indent: bool) -> str:
    decls = []
    for part in _split(style):
        name, colon, value = part.partition(":")
        if not colon:
            continue
        name, value = name.strip(), value.strip()
        key = name.lower()
        if key.startswith("-qt-"):
            continue
        if key.startswith("padding") and _is_unitless(value):
            continue
        if key == "text-indent" and drop_indent and value in ("0", "0px"):
            continue
        decls.append((name, value))
    if not decls:
        return ""
    decls = _fold_border(decls)
    for template, family in _FOLDS:
        decls = _fold_sides(decls, template, family)
    # Qt's own spelling, which the themes' selectors are written against
    return " " + "; ".join(f"{n}:{v}" for n, v in decls) + ";"


def _split(style: str) -> list:
    """`style` at its top-level semicolons: not inside quotes, not inside
    `url(data:image/png;base64,…)`."""
    parts, depth, quote, start = [], 0, "", 0
    for i, ch in enumerate(style):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == ";" and depth == 0:
            parts.append(style[start:i])
            start = i + 1
    parts.append(style[start:])
    return [p for p in parts if p.strip()]


def _is_unitless(value: str) -> bool:
    return (_UNITLESS.fullmatch(value) is not None
            and float(value) != 0)


def _fold_sides(decls: list, template: str, family: str) -> list:
    """Four equal sides as one shorthand — `margin-top:0px; …` as
    `margin:0px`, `border-top-color:#000; …` as `border-color:#000`.
    `template` names a side's property (`margin-{}`), `family` everything
    that could also set it (`border` for a border colour)."""
    found = {n.lower(): v for n, v in decls}
    names = [template.format(s) for s in _SIDES]
    values = {found.get(n) for n in names}
    if not all(n in found for n in names) or len(values) != 1:
        return decls
    return _replace(decls, set(names), (template.replace("-{}", ""),
                                        values.pop()), family)


def _fold_border(decls: list) -> list:
    """`border-top:1px; …; border-top-color:#999; …; border-top-style:solid;
    …` — the same on all four sides — as one `border`."""
    found = {n.lower(): v for n, v in decls}
    widths = [found.get(f"border-{s}") for s in _SIDES]
    colours = [found.get(f"border-{s}-color") for s in _SIDES]
    styles = [found.get(f"border-{s}-style") for s in _SIDES]
    if any(v is None for v in widths + colours + styles):
        return decls
    if len(set(widths)) != 1 or len(set(colours)) != 1 \
            or len(set(styles)) != 1:
        return decls
    # each side's shorthand must be a width alone, or folding it into one
    # shorthand with the colour and style would mean something else
    if not re.fullmatch(r"-?\d*\.?\d+[a-z%]*", widths[0]):
        return decls
    # and come first: `border-top:1px` resets the top's colour and style,
    # so a colour written before it never showed
    order = [n.lower() for n, _ in decls]
    shorthands = {f"border-{s}" for s in _SIDES}
    last_width = max(i for i, n in enumerate(order) if n in shorthands)
    if any(n.startswith("border-") and n not in shorthands
           for n in order[:last_width]):
        return decls
    names = {f"border-{s}{tail}" for s in _SIDES
             for tail in ("", "-color", "-style")}
    return _replace(decls, names,
                    ("border", f"{widths[0]} {styles[0]} {colours[0]}"),
                    "border")


def _replace(decls: list, names: set, new: tuple, family: str) -> list:
    """`decls` with every one in `names` gone and `new` where the first of
    them stood — unless another of the same `family` stands among them
    (`border-right:1px` between two border colours resets one of them),
    when moving them together could change what wins, and `decls` is left
    as it was."""
    at = [i for i, (n, _) in enumerate(decls) if n.lower() in names]
    if any(n.lower().startswith(family) and n.lower() not in names
           for n, _ in decls[at[0]:at[-1]]):
        return decls
    out = []
    for i, (name, value) in enumerate(decls):
        if i == at[0]:
            out.append(new)
        elif i not in at:
            out.append((name, value))
    return out
