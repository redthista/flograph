"""Describe a page and the artwork replacing it — without disclosing either.

For getting help with an SVG retrofit that is not working on files you
cannot send. It reports the *shape* of the problem: how many elements of
what kind, which ids and classes the page reaches into the artwork for, and
— the part that usually explains everything — what the new artwork has
sitting where each of the old elements used to be.

Every id, class, layer name and piece of text is replaced by a stable token
(`id01`, `cls03`, `name02`), the same token in every file, so the
*relationships* survive and the words do not. Geometry is kept as it is: it
is coordinates rather than content, and it is the whole diagnosis — if the
new export is drawn at twice the scale, or shifted, or is all one path, this
is where it shows.

    python svg_shape_report.py PAGE.html NEW.svg
    python svg_shape_report.py PAGE.html NEW.svg --old OLD.svg
    python svg_shape_report.py PAGE.html NEW.svg --emit shape/
    python svg_shape_report.py ... --key key.txt    # token -> real, KEEP LOCAL

`--emit` also writes an anonymised, runnable pair of SVGs carrying your
geometry and nothing else — flattened, one element per line, with parent
transforms already applied, which is geometrically what the matcher sees
anyway. If the retrofit fails on those the same way it fails on the real
ones, they are a complete bug report on their own.

Read the output before sending it. Stdlib only — nothing here needs the
flograph package, so it runs wherever the files are.
"""
from __future__ import annotations

import argparse
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path

# --------------------------------------------------------------- geometry

_NUM = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_TRANSFORM = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
_PATH_TOKEN = re.compile(
    r"([MmZzLlHhVvCcSsQqTtAa])|([-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?)")
_PATH_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1,
              "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}
_SKIP = {"metadata", "style", "script", "title", "desc"}


def _numbers(text):
    return [float(n) for n in _NUM.findall(text or "")]


def _multiply(outer, inner):
    a1, b1, c1, d1, e1, f1 = outer
    a2, b2, c2, d2, e2, f2 = inner
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def _matrix(text):
    result = _IDENTITY
    for kind, args in _TRANSFORM.findall(text or ""):
        n = _numbers(args)
        if kind == "matrix" and len(n) >= 6:
            step = tuple(n[:6])
        elif kind == "translate" and n:
            step = (1, 0, 0, 1, n[0], n[1] if len(n) > 1 else 0.0)
        elif kind == "scale" and n:
            step = (n[0], 0, 0, n[1] if len(n) > 1 else n[0], 0, 0)
        elif kind == "rotate" and n:
            rad = math.radians(n[0])
            cos, sin = math.cos(rad), math.sin(rad)
            step = (cos, sin, -sin, cos, 0, 0)
            if len(n) >= 3:
                step = _multiply((1, 0, 0, 1, n[1], n[2]), step)
                step = _multiply(step, (1, 0, 0, 1, -n[1], -n[2]))
        elif kind in ("skewX", "skewY") and n:
            t = math.tan(math.radians(n[0]))
            step = (1, t, 0, 1, 0, 0) if kind == "skewY" else (1, 0, t, 1, 0, 0)
        else:
            continue
        result = _multiply(result, step)
    return result


def _path_points(data):
    """The points a path visits — arc radii and flags are not coordinates."""
    tokens = [letter or float(number)
              for letter, number in _PATH_TOKEN.findall(data or "")]
    points = []
    x = y = start_x = start_y = 0.0
    index, command = 0, ""
    while index < len(tokens):
        token = tokens[index]
        if isinstance(token, str):
            command = token
            index += 1
        elif not command:
            index += 1
            continue
        upper, relative = command.upper(), command.islower()
        if upper == "Z":
            x, y = start_x, start_y
            points.append((x, y))
            command = ""
            continue
        need = _PATH_ARGS.get(upper, 0)
        if not need or index + need > len(tokens):
            break
        args = tokens[index:index + need]
        if any(isinstance(arg, str) for arg in args):
            break
        index += need
        if upper == "H":
            x = x + args[0] if relative else args[0]
        elif upper == "V":
            y = y + args[0] if relative else args[0]
        elif upper == "A":
            x = x + args[5] if relative else args[5]
            y = y + args[6] if relative else args[6]
        else:
            base_x, base_y = (x, y) if relative else (0.0, 0.0)
            for k in range(0, need, 2):
                points.append((base_x + args[k], base_y + args[k + 1]))
            x, y = points[-1]
            if upper == "M":
                start_x, start_y = x, y
                command = "l" if relative else "L"
        points.append((x, y))
    return points


def _box(el, tag):
    get = el.get
    if tag in ("rect", "image", "svg", "foreignObject", "use"):
        x, y = _numbers(get("x", "0")), _numbers(get("y", "0"))
        w, h = _numbers(get("width", "0")), _numbers(get("height", "0"))
        x, y = (x[0] if x else 0.0), (y[0] if y else 0.0)
        w, h = (w[0] if w else 0.0), (h[0] if h else 0.0)
        if tag == "svg" and not (w and h):
            view = _numbers(get("viewBox", ""))
            if len(view) >= 4:
                x, y, w, h = view[:4]
        return x, y, w, h
    if tag in ("circle", "ellipse"):
        cx = (_numbers(get("cx", "0")) or [0.0])[0]
        cy = (_numbers(get("cy", "0")) or [0.0])[0]
        if tag == "circle":
            rx = ry = (_numbers(get("r", "0")) or [0.0])[0]
        else:
            rx = (_numbers(get("rx", "0")) or [0.0])[0]
            ry = (_numbers(get("ry", "0")) or [0.0])[0]
        return cx - rx, cy - ry, rx * 2, ry * 2
    if tag == "line":
        x1, y1, x2, y2 = [(_numbers(get(k, "0")) or [0.0])[0]
                          for k in ("x1", "y1", "x2", "y2")]
        return min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)
    if tag in ("path", "polygon", "polyline"):
        data = get("d") or get("points") or ""
        if tag == "path":
            points = _path_points(data)
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
        else:
            n = _numbers(data)
            xs, ys = n[0::2], n[1::2]
        if xs and ys:
            return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
        return 0.0, 0.0, 0.0, 0.0
    if tag in ("text", "tspan"):
        x = (_numbers(get("x", "0")) or [0.0])[0]
        y = (_numbers(get("y", "0")) or [0.0])[0]
        return x, y, 0.0, 0.0
    return 0.0, 0.0, 0.0, 0.0


def _apply(matrix, box):
    a, b, c, d, e, f = matrix
    x, y, w, h = box
    corners = [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]
    xs = [a * px + c * py + e for px, py in corners]
    ys = [b * px + d * py + f for px, py in corners]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


# ------------------------------------------------------------------ parse

class _Lenient(HTMLParser):
    """Markup a browser reads and an XML parser refuses."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = None
        self._stack = []

    def handle_starttag(self, tag, attrs):
        element = ET.Element(tag.lower(),
                             {k.lower(): (v or "") for k, v in attrs})
        if self._stack:
            self._stack[-1].append(element)
        elif self.root is None:
            self.root = element
        self._stack.append(element)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self._stack.pop()

    def handle_endtag(self, tag):
        for depth in range(len(self._stack) - 1, -1, -1):
            if self._stack[depth].tag == tag.lower():
                del self._stack[depth:]
                return

    def handle_data(self, data):
        if not self._stack:
            return
        current = self._stack[-1]
        if len(current):
            current[-1].tail = (current[-1].tail or "") + data
        else:
            current.text = (current.text or "") + data


def _parse(text):
    repaired = re.sub(r"&(?![a-zA-Z#][a-zA-Z0-9]*;)", "&amp;", text or "")
    try:
        return ET.fromstring(repaired)
    except ET.ParseError:
        parser = _Lenient()
        parser.feed(text or "")
        parser.close()
        return parser.root


_SVG_TAG = re.compile(r"<(/?)svg\b((?:\"[^\"]*\"|'[^']*'|[^>])*)>", re.I | re.S)


def _inline_svg(page):
    """Every top-level <svg>…</svg>, as (text, start, end), counted by depth."""
    found, depth, start = [], 0, None
    for match in _SVG_TAG.finditer(page):
        if match.group(1):
            depth = max(depth - 1, 0)
            if depth == 0 and start is not None:
                found.append((page[start:match.end()], start, match.end()))
                start = None
        elif not match.group(2).rstrip().endswith("/"):
            if depth == 0:
                start = match.start()
            depth += 1
    if start is not None:
        found.append((page[start:], start, len(page)))
    return found


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _attr(el, *names):
    plain = {k.rsplit("}", 1)[-1].rsplit(":", 1)[-1].lower(): v
             for k, v in el.attrib.items()}
    for name in names:
        if plain.get(name):
            return plain[name].strip()
    return ""


def elements(svg_text):
    """One dict per element, parent transforms applied."""
    root = _parse(svg_text)
    if root is None:
        return []
    rows = []

    def walk(el, matrix, depth, in_defs):
        if not isinstance(el.tag, str):
            return
        tag = _local(el.tag)
        if tag in _SKIP:
            return
        here = _multiply(matrix, _matrix(el.get("transform", "")))
        if tag != "defs":
            x, y, w, h = _apply(here, _box(el, tag))
            rows.append({
                "tag": tag, "depth": depth, "in_defs": in_defs,
                "id": (el.get("id") or "").strip(),
                "cls": (el.get("class") or "").strip(),
                "name": _attr(el, "data-name", "label", "aria-label"),
                "text": (re.sub(r"\s+", " ", "".join(el.itertext())).strip()
                         if tag in ("text", "tspan") else ""),
                "x": round(x, 2), "y": round(y, 2),
                "w": round(w, 2), "h": round(h, 2),
                "d": (el.get("d") or el.get("points") or "").strip(),
                "transform": (el.get("transform") or "").strip(),
            })
        for child in el:
            walk(child, here, depth + 1, in_defs or tag == "defs")

    walk(root, _IDENTITY, 0, False)
    return rows


# ------------------------------------------------------------------ hooks

_PATTERNS = [
    (r"getElementById\s*\(\s*['\"]([^'\"]+)['\"]", "getElementById", None),
    (r"getElementsByClassName\s*\(\s*['\"]([^'\"]+)['\"]", "byClassName", "class"),
    (r"querySelector(?:All)?\s*\(\s*['\"]([^'\"]+)['\"]", "querySelector", True),
    (r"\$\(\s*['\"]([^'\"]+)['\"]\s*\)", "jquery", True),
    (r"(?:xlink:)?href\s*=\s*['\"](#[\w:.-]+)['\"]", "href", True),
    (r"url\(\s*['\"]?(#[\w:.-]+)['\"]?\s*\)", "url()", True),
]
_SELECTOR = re.compile(r"[#.]([A-Za-z_][\w-]*)")
_STYLE_BLOCK = re.compile(r"<style\b[^>]*>(.*?)</style\s*>", re.S | re.I)


def hooks(page, svg_spans):
    """How often the page names each id/class, and from where."""
    found = Counter()

    def internal(position):
        return any(a <= position < b for a, b in svg_spans)

    def record(ref, kind, how, position):
        ref = (ref or "").strip().lstrip("#")
        if ref:
            found[(ref, kind, "internal" if internal(position) else how)] += 1

    for pattern, how, selector in _PATTERNS:
        for match in re.finditer(pattern, page, re.I):
            captured = match.group(1)
            if selector is True:
                for token in _SELECTOR.finditer(captured):
                    record(token.group(1),
                           "class" if token.group(0)[0] == "." else "id",
                           how, match.start())
            else:
                record(captured, selector or "id", how, match.start())
    for block in _STYLE_BLOCK.finditer(page):
        body = re.sub(r"/\*.*?\*/", " ", block.group(1), flags=re.S)
        for rule in re.finditer(r"([^{}]+)\{", body):
            offset = block.start(1) + rule.start(1)
            for token in _SELECTOR.finditer(rule.group(1)):
                record(token.group(1),
                       "class" if token.group(0)[0] == "." else "id",
                       "css", offset)
    return found


# ------------------------------------------------------------ anonymising

class Tokens:
    """Stable real -> token, one map across every file, never printed."""

    def __init__(self):
        self._seen = {}
        self._counts = Counter()

    def of(self, kind, value):
        value = (value or "").strip()
        if not value:
            return ""
        key = (kind, value)
        if key not in self._seen:
            self._counts[kind] += 1
            self._seen[key] = f"{kind}{self._counts[kind]:02d}"
        return self._seen[key]

    def key_file(self):
        return "\n".join(f"{token}\t{kind}\t{value}"
                         for (kind, value), token in sorted(
                             self._seen.items(), key=lambda kv: kv[1]))


# --------------------------------------------------------------- reporting

def _fmt(row):
    return (f"{row['tag']:<7} {row['x']:>8.1f},{row['y']:<8.1f} "
            f"{row['w']:>7.1f}x{row['h']:<7.1f}")


def _centre(row):
    return row["x"] + row["w"] / 2, row["y"] + row["h"] / 2


def _content_box(rows):
    drawn = [r for r in rows if (r["w"] or r["h"]) and r["tag"] != "svg"]
    if not drawn:
        return None
    x = min(r["x"] for r in drawn)
    y = min(r["y"] for r in drawn)
    return (x, y,
            max(r["x"] + r["w"] for r in drawn) - x,
            max(r["y"] + r["h"] for r in drawn) - y)


def _view_box(text):
    match = re.search(r'viewBox\s*=\s*["\']([^"\']+)', text or "")
    return match.group(1).strip() if match else ""


def report(page_text, old_text, new_text, tokens, say):
    old, new = elements(old_text), elements(new_text)
    inline = _inline_svg(page_text)
    found = hooks(page_text, [(a, b) for _t, a, b in inline])

    say("== files")
    say(f"  page          {len(page_text):>9,} chars · {len(inline)} inline <svg>"
        f" · {len(re.findall(r'<script', page_text, re.I))} <script>"
        f" · {len(re.findall(r'<link', page_text, re.I))} <link>")
    for label, text, rows in (("old artwork", old_text, old),
                              ("new artwork", new_text, new)):
        box = _content_box(rows)
        say(f"  {label}   {len(text or ''):>9,} chars · {len(rows):>5} elements"
            f" · viewBox {_view_box(text) or '(none)'}"
            + (f" · content {box[0]:g},{box[1]:g} {box[2]:g}x{box[3]:g}"
               if box else " · nothing drawn"))

    old_box, new_box = _content_box(old), _content_box(new)
    if old_box and new_box and old_box[2] and old_box[3]:
        sx, sy = new_box[2] / old_box[2], new_box[3] / old_box[3]
        say(f"  new vs old    scale {sx:.3f} x {sy:.3f} · "
            f"offset {new_box[0] - old_box[0]:+g},{new_box[1] - old_box[1]:+g}")
        if abs(sx - 1) > 0.02 or abs(sy - 1) > 0.02:
            say("  ^^ the two are not drawn at the same scale, so no box or "
                "position match can succeed until that is reconciled")

    for label, rows in (("old artwork", old), ("new artwork", new)):
        say("")
        say(f"== {label}")
        tags = Counter(r["tag"] for r in rows)
        say("  tags                     " +
            ", ".join(f"{t}x{n}" for t, n in tags.most_common(12)))
        for field, name in (("id", "carry an id"),
                            ("name", "carry a layer name"),
                            ("cls", "carry a class"),
                            ("transform", "carry a transform")):
            say(f"  {name:<24} {sum(1 for r in rows if r[field]):>5} of {len(rows)}")
        # id-less elements nothing tells apart: the retrofit declines to
        # guess between these, so a big number here is an answer in itself
        locators = Counter((r["tag"], r["d"], r["transform"], r["cls"], r["name"])
                           for r in rows if not r["id"])
        twins = {k: n for k, n in locators.items() if n > 1}
        say(f"  {'identical and id-less':<24} {sum(twins.values()):>5}"
            f" in {len(twins)} group(s)")
        say(f"  {'deepest nesting':<24} "
            f"{max((r['depth'] for r in rows), default=0):>5}")

    say("")
    say("== what the page reaches into the artwork for")
    by_old = {r["id"]: r for r in old if r["id"]}
    hooked = defaultdict(list)
    for (ref, kind, how), n in sorted(found.items()):
        hooked[(ref, kind)].append(f"{how}x{n}")
    for (ref, kind), hows in sorted(hooked.items()):
        if all(h.startswith("internal") for h in hows):
            continue
        token = tokens.of("id" if kind == "id" else "cls", ref)
        source = by_old.get(ref)
        say(f"  {'#' if kind == 'id' else '.'}{token:<7} "
            f"{', '.join(hows):<38}"
            + (f"old: {_fmt(source)}" if source else
               "(not an element of the old artwork)"))

    say("")
    say("== for each hooked id, what the new artwork has in that place")
    say("   (same box = the retrofit's strongest geometric match;")
    say("    nothing in any column = the two files do not line up at all)")
    ids = [ref for (ref, kind), hows in hooked.items()
           if kind == "id" and not all(h.startswith("internal") for h in hows)]
    landed = 0
    for (ref, kind), _hows in sorted(hooked.items()):
        if kind != "id" or ref not in by_old:
            continue
        source, token = by_old[ref], tokens.of("id", ref)
        cx, cy = _centre(source)
        area = source["w"] * source["h"]
        exact, near, similar = [], [], []
        for row in new:
            row_cx, row_cy = _centre(row)
            if (abs(row["x"] - source["x"]) < .05
                    and abs(row["y"] - source["y"]) < .05
                    and abs(row["w"] - source["w"]) < .05
                    and abs(row["h"] - source["h"]) < .05):
                exact.append(row)
            elif abs(row_cx - cx) + abs(row_cy - cy) <= 8:
                near.append(row)
            elif area and 0.75 <= (row["w"] * row["h"]) / area <= 1.33:
                similar.append(row)
        landed += 1 if len(exact) == 1 else 0
        say(f"  #{token:<7} old {_fmt(source)}"
            + ("  (named)" if (source["name"] or source["text"]) else ""))
        for name, hits in (("same box", exact), ("within 8", near),
                           ("same area", similar)):
            say(f"  {'':10}{name:<10}{len(hits):>4}"
                + (f"   e.g. {_fmt(hits[0])}"
                   f"{' (named)' if (hits[0]['name'] or hits[0]['text']) else ''}"
                   if hits else ""))

    say("")
    say("== the number that decides it")
    inside = sum(1 for ref in ids if ref in by_old)
    say(f"  {len(ids):>4} id(s) the page reaches into the artwork for")
    say(f"  {inside:>4} of those are elements of the OLD artwork "
        f"{'' if inside else '<- if this is 0, the old side is the wrong <svg>'}")
    say(f"  {landed:>4} of those have exactly one same-box element in the new "
        f"artwork")
    if inside and not landed:
        say("  -> nothing can be matched on geometry. Either the two are not "
            "the same drawing, or they are not in the same coordinate space.")
    return old, new


def anonymise(rows, tokens, view_box):
    """A runnable SVG with your structure and geometry and none of your words."""
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'viewBox="{view_box or "0 0 100 100"}">']
    for row in rows:
        if row["tag"] == "svg":
            continue
        bits = [row["tag"]]
        if row["id"]:
            bits.append(f'id="{tokens.of("id", row["id"])}"')
        if row["cls"]:
            bits.append('class="' + " ".join(
                tokens.of("cls", c) for c in row["cls"].split()) + '"')
        if row["name"]:
            bits.append(f'data-name="{tokens.of("name", row["name"])}"')
        if row["tag"] in ("text", "tspan"):
            bits.append(f'x="{row["x"]:g}" y="{row["y"]:g}"')
            out.append(f'  <{" ".join(bits)}>{tokens.of("text", row["text"])}'
                       f'</{row["tag"]}>')
            continue
        if row["d"]:
            bits.append(f'd="{row["d"]}"')
        elif row["w"] or row["h"]:
            # every other shape written as the box it occupies: the retrofit
            # matches on boxes, so this preserves the problem exactly
            bits[0] = "rect"
            bits.append(f'x="{row["x"]:g}" y="{row["y"]:g}" '
                        f'width="{row["w"]:g}" height="{row["h"]:g}"')
        elif row["tag"] not in ("g", "a", "switch"):
            continue
        out.append(f'  <{" ".join(bits)}/>')
    out.append("</svg>")
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Describe a page and its artwork without disclosing them.")
    parser.add_argument("page", type=Path, help="the page, as it is served")
    parser.add_argument("new", type=Path, help="the new artwork (.svg)")
    parser.add_argument("--old", type=Path, default=None,
                        help="the old artwork, if it is not inline in the page")
    parser.add_argument("--emit", type=Path, default=None,
                        help="directory to write an anonymised pair into")
    parser.add_argument("--key", type=Path, default=None,
                        help="write the token -> real map here. KEEP IT LOCAL.")
    args = parser.parse_args(argv)

    page_text = args.page.read_text(errors="replace")
    new_text = args.new.read_text(errors="replace")
    if args.old:
        old_text = args.old.read_text(errors="replace")
    else:
        inline = _inline_svg(page_text)
        if not inline:
            parser.error("no inline <svg> in the page — pass --old with the "
                         "artwork the page is wired to")
        old_text = inline[0][0]

    tokens, lines = Tokens(), []
    old, new = report(page_text, old_text, new_text, tokens, lines.append)
    print("\n".join(lines))

    if args.emit:
        args.emit.mkdir(parents=True, exist_ok=True)
        for name, rows, text in (("old.svg", old, old_text),
                                 ("new.svg", new, new_text)):
            (args.emit / name).write_text(
                anonymise(rows, tokens, _view_box(text)))
        (args.emit / "report.txt").write_text("\n".join(lines) + "\n")
        print(f"\nwrote {args.emit}/old.svg, new.svg and report.txt — open "
              f"them and satisfy yourself before sending any of it")
    if args.key:
        args.key.write_text(tokens.key_file() + "\n")
        print(f"wrote {args.key}, which translates the tokens back. "
              f"Keep it. Do not send it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
