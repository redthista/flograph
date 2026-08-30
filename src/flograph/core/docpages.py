"""A folder of Markdown pages linked with `[[wikilinks]]` — the in-app
handbook, and any folder the Markdown Wiki node is pointed at.

The bundled pages under `flograph/docs/` are *GitHub-wiki compatible* —
`[[Page Title]]` links, one `# H1` per file, `Title-Case-Dashes.md`
filenames — so they can be pushed to a hosted wiki with no rewriting. An
outside folder is taken as it comes: pages are found recursively, an
Obsidian vault's `[[Note]]` links and `![[image.png]]` embeds are
understood, and the nav tree falls back to the folder structure.

This module is the Qt-free side: finding the pages and turning `[[...]]`
into ordinary Markdown links. Rendering them (images included) is the UI's
job (`ui/wiki/`), the same split as `core/report.py` ↔ `ui/report/render.py`.
"""
from __future__ import annotations

import importlib.resources
import os
import re
from dataclasses import dataclass
from pathlib import Path

# `[[Target]]`, `[[Target#anchor]]`, `[[Target|shown label]]`, or a
# combination. The negative lookbehind leaves the `![[embed]]` form to
# EMBED_RE below (and the report card's own `![[...]]`, see core/report.py).
WIKILINK_RE = re.compile(
    r"(?<!!)\[\[\s*([^\]|#]+?)\s*(?:#([^\]|]+?)\s*)?(?:\|\s*([^\]]+?)\s*)?\]\]"
)

# Obsidian embeds: `![[image.png]]`, `![[image.png|200]]`, `![[note]]`.
EMBED_RE = re.compile(r"!\[\[\s*([^\]|#]+?)\s*(?:\|\s*([^\]]*?)\s*)?\]\]")

IMAGE_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".svgz",
})

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

# fenced blocks and inline spans — link/embed syntax inside them is a
# *quotation* of the syntax (this handbook shows report `![[embeds]]` that
# way), so it is left exactly as written.
_CODE_RE = re.compile(r"(```.*?```|~~~.*?~~~|``[^`]+``|`[^`\n]+`)", re.DOTALL)


def _outside_code(text: str, fn) -> str:
    parts = _CODE_RE.split(text)
    return "".join(fn(p) if i % 2 == 0 else p for i, p in enumerate(parts))


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
    rel: tuple[str, ...] = ()   # folders between the wiki root and this page

    @classmethod
    def read(cls, path: Path, root: Path | None = None) -> "DocPage":
        text = path.read_text(encoding="utf-8")
        h1 = _H1_RE.search(text)
        title = h1.group(1) if h1 else path.stem.replace("-", " ")
        rel = ()
        if root is not None:
            rel = path.relative_to(root).parts[:-1]
        return cls(slug=_slug(path.stem), title=title, path=path, rel=rel)


def docs_dir() -> Path:
    """The folder the handbook pages live in. `FLOGRAPH_DOCS_DIR` overrides
    it (house style, matches paths.py); otherwise the bundled `flograph/docs`."""
    override = os.environ.get("FLOGRAPH_DOCS_DIR")
    if override and Path(override).is_dir():
        return Path(override)
    return Path(str(importlib.resources.files("flograph.docs")))


def resolve_wiki_dir(folder: str | None) -> Path:
    """Which folder a wiki shows. A real directory path is used as given;
    blank, whitespace or a missing path falls back to the bundled handbook
    (`docs_dir()`) — so the Markdown Wiki node with no folder set shows
    flograph's own docs."""
    if folder and folder.strip():
        candidate = Path(folder.strip())
        if candidate.is_dir():
            return candidate
    return docs_dir()


def _md_files(directory: Path):
    """Every `.md` file under `directory`, recursively. Skips `_`-prefixed
    files (`_Sidebar.md` and the other GitHub-wiki specials) and anything
    inside a dot folder (`.obsidian`, `.trash`, `.git`)."""
    for path in sorted(directory.rglob("*.md")):
        rel = path.relative_to(directory)
        if path.name.startswith("_"):
            continue
        if any(part.startswith(".") for part in rel.parts):
            continue
        yield path


def catalog(directory: Path | None = None) -> dict[str, DocPage]:
    """Every page under `directory`, keyed by slug. Pages are found
    recursively, so an Obsidian vault or a nested wiki shows all of its
    notes. A note name is the key, matching how `[[Note]]` links resolve; if
    two folders hold a same-named note the one sorted last wins (rare, and
    the folder-path link `[[folder/Note]]` still reaches either)."""
    directory = directory or docs_dir()
    pages = (DocPage.read(p, directory) for p in _md_files(directory))
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
            page = _lookup(link.group(1), pages)
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


def _folder_nav(pages: dict[str, DocPage]) -> list[NavEntry]:
    """A nav tree from the folder structure: each subfolder is a section,
    root-level pages first, everything alphabetical."""
    roots: list[_Node] = []
    folders: dict[tuple[str, ...], _Node] = {(): _Node("", None)}
    folders[()].children = roots

    def folder_node(rel: tuple[str, ...]) -> _Node:
        if rel in folders:
            return folders[rel]
        parent = folder_node(rel[:-1])
        node = _Node(rel[-1].replace("-", " ").replace("_", " "), None)
        parent.children.append(node)
        folders[rel] = node
        return node

    for page in sorted(pages.values(), key=lambda p: (p.rel, p.title.lower())):
        folder_node(page.rel).children.append(_Node(page.title, page.slug))

    # root pages before subfolders
    roots.sort(key=lambda n: (n.slug is None, n.title.lower()))
    return [n.freeze() for n in roots]


def sidebar(directory: Path | None = None) -> list[NavEntry]:
    """The nav tree. `_Sidebar.md` if the folder has one (with any page it
    forgot appended flat); otherwise the folder structure when there are
    subfolders (an Obsidian vault), or a flat list — Home first — when the
    pages are all at the top level."""
    directory = directory or docs_dir()
    pages = catalog(directory)
    sb = directory / "_Sidebar.md"

    if sb.is_file():
        tree = parse_sidebar(sb.read_text(encoding="utf-8"), pages)
        listed = _slugs_in(tree)
        extra = [NavEntry(p.title, p.slug) for s, p in sorted(pages.items())
                 if s not in listed and s != "home"]
        return tree + extra

    if any(p.rel for p in pages.values()):
        return _folder_nav(pages)

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


def breadcrumb(slug: str, entries: list[NavEntry]) -> list[NavEntry]:
    """The trail from a nav-tree root down to `slug` — section headers and
    the page itself, in order. `[]` if the page is not in the tree."""
    for entry in entries:
        if entry.slug == slug:
            return [entry]
        below = breadcrumb(slug, list(entry.children))
        if below:
            return [entry, *below]
    return []


def _lookup(target: str, pages: dict[str, DocPage]) -> DocPage | None:
    """Resolve a wikilink target to a page — by full slug, then by the last
    path segment, so `[[folder/Note]]` reaches `Note` too."""
    return pages.get(_slug(target)) or pages.get(_slug(target.rsplit("/", 1)[-1]))


def _is_image(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in IMAGE_SUFFIXES


def render_links(text: str, pages: dict[str, DocPage]) -> tuple[str, list[str]]:
    """Rewrite `[[wikilinks]]` and Obsidian `![[embeds]]` to ordinary
    Markdown. `![[image.png]]` becomes a Markdown image (the UI resolves and
    loads it); `![[Note]]` and `[[Note]]` become links. Returns the new text
    and the link targets that matched no page (the integrity test uses the
    second value — a shipped page must not point at a missing one)."""
    missing: list[str] = []

    def embed(m: re.Match[str]) -> str:
        target, opt = m.group(1), (m.group(2) or "").strip()
        if _is_image(target):
            alt = f"|{opt}" if opt else ""
            return f"![{target}{alt}]({target})"
        page = _lookup(target, pages)
        if page is None:
            missing.append(target)
            return target
        return f"[{opt or target}]({link_target(page.slug)})"

    def link(m: re.Match[str]) -> str:
        target, anchor, label = m.group(1), m.group(2), m.group(3)
        shown = label or (target if not anchor else f"{target} § {anchor}")
        page = _lookup(target, pages)
        if page is None:
            missing.append(target)
            return shown  # brackets dropped; reads as plain text, like GitHub
        href = link_target(page.slug)
        if anchor:
            href += "#" + _slug(anchor)
        return f"[{shown}]({href})"

    text = _outside_code(text, lambda s: EMBED_RE.sub(embed, s))
    text = _outside_code(text, lambda s: WIKILINK_RE.sub(link, s))
    return text, missing
