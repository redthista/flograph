"""The in-app handbook: a folder of Markdown pages linked with `[[wikilinks]]`.

The pages ship under `flograph/docs/` and are written to be
*GitHub-wiki compatible* — `[[Page Title]]` links, one `# H1` per file,
`Title-Case-Dashes.md` filenames — so the same files can be pushed to a
hosted wiki with no rewriting.

This module is the Qt-free side: finding the pages and turning `[[...]]`
into ordinary Markdown links. Rendering them is the UI's job
(`ui/docs/`), the same split as `core/report.py` ↔ `ui/report/render.py`.
"""
from __future__ import annotations

import importlib.resources
import os
import re
from dataclasses import dataclass
from pathlib import Path

# `[[Target]]`, `[[Target#anchor]]`, `[[Target|shown label]]`, or a
# combination. The negative lookbehind leaves the report `![[embed]]` form
# (see core/report.py) alone — a docs page could legitimately mention it.
WIKILINK_RE = re.compile(
    r"(?<!!)\[\[\s*([^\]|#]+?)\s*(?:#([^\]|]+?)\s*)?(?:\|\s*([^\]]+?)\s*)?\]\]"
)

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _slug(name: str) -> str:
    """Normalise a page title or filename stem to one key. `Getting Started`,
    `getting-started` and `Getting-Started` all land on the same page."""
    return name.strip().lower().replace(" ", "-")


def link_target(slug: str) -> str:
    """The href a page slug becomes in rendered Markdown — the one place the
    on-disk naming convention lives."""
    return f"{slug}.md"


@dataclass(frozen=True)
class DocPage:
    slug: str
    title: str
    path: Path

    @classmethod
    def read(cls, path: Path) -> "DocPage":
        text = path.read_text(encoding="utf-8")
        h1 = _H1_RE.search(text)
        title = h1.group(1) if h1 else path.stem.replace("-", " ")
        return cls(slug=_slug(path.stem), title=title, path=path)


def docs_dir() -> Path:
    """The folder the handbook pages live in. `FLOGRAPH_DOCS_DIR` overrides
    it (house style, matches paths.py); otherwise the bundled `flograph/docs`."""
    override = os.environ.get("FLOGRAPH_DOCS_DIR")
    if override and Path(override).is_dir():
        return Path(override)
    return Path(str(importlib.resources.files("flograph.docs")))


def catalog(directory: Path | None = None) -> dict[str, DocPage]:
    """Every `*.md` page, keyed by slug. `_`-prefixed files (`_Sidebar.md`,
    `_Footer.md` — the GitHub-wiki specials) are not pages."""
    directory = directory or docs_dir()
    pages = (DocPage.read(p) for p in sorted(directory.glob("*.md"))
             if not p.name.startswith("_"))
    return {page.slug: page for page in pages}


@dataclass(frozen=True)
class NavEntry:
    """One row of the navigation tree. `slug` is None for a section header."""
    title: str
    slug: str | None
    children: tuple["NavEntry", ...] = ()


_BULLET_RE = re.compile(r"^(?P<indent>[ \t]*)[-*]\s+(?P<body>.+?)\s*$")
_ONLY_LINK_RE = re.compile(r"^\s*" + WIKILINK_RE.pattern + r"\s*$")


class _Node:
    """Build helper — NavEntry is frozen, so the tree is assembled mutably
    and frozen once at the end."""

    def __init__(self, title: str, slug: str | None) -> None:
        self.title, self.slug, self.children = title, slug, []

    def freeze(self) -> NavEntry:
        return NavEntry(self.title, self.slug,
                        tuple(c.freeze() for c in self.children))


def parse_sidebar(text: str, pages: dict[str, DocPage]) -> list[NavEntry]:
    """Turn a GitHub-wiki `_Sidebar.md` (a nested bullet list) into a nav
    tree. A bullet that is exactly one `[[link]]` is a page; any other
    bullet is a section header (Markdown emphasis stripped). Unknown link
    targets are dropped."""
    roots: list[_Node] = []
    stack: list[tuple[int, list[_Node]]] = [(-1, roots)]  # (indent, sibling list)

    for line in text.splitlines():
        m = _BULLET_RE.match(line)
        if not m:
            continue
        indent = len(m.group("indent").replace("\t", "    "))
        body = m.group("body")

        link = _ONLY_LINK_RE.match(body)
        if link:
            page = pages.get(_slug(link.group(1)))
            if page is None:
                continue
            node = _Node((link.group(3) or link.group(1)).strip(), page.slug)
        else:
            node = _Node(re.sub(r"[*_`]", "", body).strip(), None)

        while stack[-1][0] >= indent:
            stack.pop()
        stack[-1][1].append(node)
        stack.append((indent, node.children))

    return [n.freeze() for n in roots]


def sidebar(directory: Path | None = None) -> list[NavEntry]:
    """The nav tree: `_Sidebar.md` if the folder has one (with any page it
    forgot appended flat), otherwise Home then the rest alphabetically."""
    directory = directory or docs_dir()
    pages = catalog(directory)
    sb = directory / "_Sidebar.md"

    if sb.is_file():
        tree = parse_sidebar(sb.read_text(encoding="utf-8"), pages)
        listed = _slugs_in(tree)
        extra = [NavEntry(p.title, p.slug) for s, p in sorted(pages.items())
                 if s not in listed and s != "home"]
        return tree + extra

    rest = sorted((NavEntry(p.title, p.slug)
                   for s, p in pages.items() if s != "home"),
                  key=lambda e: e.title)
    home = [NavEntry("Home", "home")] if "home" in pages else []
    return home + rest


def _slugs_in(entries) -> set[str]:
    out: set[str] = set()
    for e in entries:
        if e.slug:
            out.add(e.slug)
        out |= _slugs_in(e.children)
    return out


def render_links(text: str, pages: dict[str, DocPage]) -> tuple[str, list[str]]:
    """Rewrite `[[wikilinks]]` to ordinary Markdown links. Returns the new
    text and the list of link targets that matched no page (for the
    integrity test — a shipped page must not point at a missing one)."""
    missing: list[str] = []

    def repl(m: re.Match[str]) -> str:
        target, anchor, label = m.group(1), m.group(2), m.group(3)
        slug = _slug(target)
        shown = label or (target if not anchor else f"{target} § {anchor}")
        page = pages.get(slug)
        if page is None:
            missing.append(target)
            return shown  # brackets dropped; reads as plain text, like GitHub
        href = link_target(page.slug)
        if anchor:
            href += "#" + _slug(anchor)
        return f"[{shown}]({href})"

    return WIKILINK_RE.sub(repl, text), missing
