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
import stat
from dataclasses import dataclass
from pathlib import Path
import tempfile

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

_H1_RE = re.compile(r"^#[ \t]+(.+?)[ \t]*$", re.MULTILINE)

# fenced blocks and inline spans — link/embed syntax inside them is a
# *quotation* of the syntax (this handbook shows report `![[embeds]]` that
# way), so it is left exactly as written.
# A ``double-tick`` span exists precisely so that its content may contain
# backticks, so it must not be written as "anything but a backtick".
# As Markdown reads them: a fence opens at the start of a line and closes on
# a line of its own, and a span closes on a run of backticks as long as the
# one that opened it. Pairing any two ``` instead let a ```` ```columns ````
# span in a sentence open a "fence" that ran on to the next real one, and
# every block after it was read inside out.
_CODE_RE = re.compile(
    r"^(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^(?P=fence)[ \t]*$"
    r"|(?P<ticks>`+)(?!`)[^\n]+?(?<!`)(?P=ticks)(?!`)",
    re.MULTILINE | re.DOTALL)


def _outside_code(text: str, fn) -> str:
    out, at = [], 0
    for match in _CODE_RE.finditer(text):
        out.append(fn(text[at:match.start()]))
        out.append(match.group(0))
        at = match.end()
    out.append(fn(text[at:]))
    return "".join(out)


def _slug(name: str) -> str:
    """Normalise a page title or filename stem to one key. `Getting Started`,
    `getting-started` and `Getting-Started` all land on the same page."""
    return name.strip().lower().replace(" ", "-")


def link_target(slug: str) -> str:
    """The href a page slug becomes in rendered Markdown — the one place the
    on-disk naming convention lives."""
    return f"{slug}.md"


def anchor_slug(heading: str) -> str:
    """The `#fragment` a heading is reachable by. Shared by `render_links`
    (which writes `[[Page#Heading]]` as `page.md#<this>`) and the renderer
    (which tags each heading with an anchor of `<this>`), so the two agree."""
    return _slug(heading)


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


def is_bundled_docs(directory: Path) -> bool:
    """Whether *directory* is flograph's installed handbook.

    The handbook is shipped as application documentation and must never be
    edited through a Wiki card. An explicit ``FLOGRAPH_DOCS_DIR`` override
    is a user folder, so it remains editable when the filesystem allows it.
    """
    try:
        bundled = Path(str(importlib.resources.files("flograph.docs")))
        return directory.resolve() == bundled.resolve()
    except (OSError, TypeError):
        return False


def _safe_page_stem(title: str) -> str:
    """A single Markdown filename component for a user-entered page title."""
    title = title.strip()
    if (not title or any(c in title for c in '/\\:*?"<>|#[]')
            or any(ord(c) < 32 for c in title)
            or title in {".", ".."} or title.endswith(".")
            or title.split(".", 1)[0].upper() in {
                "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3",
                "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
                "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6",
                "LPT7", "LPT8", "LPT9"}):
        raise ValueError("Enter a page title without filename punctuation")
    stem = re.sub(r"\s+", "-", title)
    if not stem or stem.startswith("."):
        raise ValueError("Enter a page title that can be used as a filename")
    return stem


def _atomic_write(path: Path, text: str) -> None:
    """Replace one UTF-8 text file atomically within its own directory."""
    temporary = _stage_text(path, text)
    try:
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _stage_text(path: Path, text: str, *, mode_from: Path | None = None) -> Path:
    """Write a sibling temporary file with permissions copied from a source."""
    source = mode_from or path
    try:
        mode = stat.S_IMODE(source.stat().st_mode)
    except OSError:
        mode = 0o644
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name)


def create_page(directory: Path, title: str, body: str | None = None) -> DocPage:
    """Create a root-level Markdown page and return its catalog entry."""
    stem = _safe_page_stem(title)
    path = directory / f"{stem}.md"
    slug = _slug(stem)
    if path.exists() or slug in catalog(directory):
        raise FileExistsError(f"A page named {title!r} already exists")
    content = body if body is not None else f"# {title.strip()}\n\n"
    _atomic_write(path, content)
    return DocPage.read(path, directory)


def _rewrite_page_links(text: str, old_slug: str, new_slug: str,
                        *, default_label: str | None = None) -> str:
    """Rewrite links to a renamed page, preserving labels and anchors.

    Both ``[[Page]]`` and non-image Obsidian ``![[Page]]`` embeds are
    handled. Code spans and fenced blocks remain untouched, as in
    ``render_links``.
    """
    old = _slug(old_slug)

    def matches(target: str) -> bool:
        target_slug = _slug(target)
        return target_slug == old or target_slug.rsplit("/", 1)[-1] == old

    def rewrite(segment: str) -> str:
        def link(match: re.Match[str]) -> str:
            target, anchor, label = match.group(1), match.group(2), match.group(3)
            if not matches(target):
                return match.group(0)
            result = f"[[{new_slug}"
            if anchor:
                result += f"#{anchor}"
            if label:
                result += f"|{label}"
            elif default_label is not None:
                result += f"|{default_label}"
            return result + "]]"

        def embed(match: re.Match[str]) -> str:
            target, option = match.group(1), match.group(2)
            if _is_image(target) or not matches(target):
                return match.group(0)
            result = f"![[{new_slug}"
            if option:
                result += f"|{option}"
            elif default_label is not None:
                result += f"|{default_label}"
            return result + "]]"

        return WIKILINK_RE.sub(link, EMBED_RE.sub(embed, segment))

    return _outside_code(text, rewrite)


def _rename_page_heading(text: str, title: str) -> tuple[str, bool]:
    """Rename the first real H1, without treating an example as a heading."""
    found = False

    def update(segment: str) -> str:
        nonlocal found
        if found:
            return segment
        changed, count = _H1_RE.subn(
            lambda _match: f"# {title}", segment, count=1)
        found = bool(count)
        return changed

    return _outside_code(text, update), found


def rename_page(directory: Path, slug: str, title: str) -> DocPage:
    """Rename a page and update inbound wiki links plus `_Sidebar.md`.

    All rewritten files are staged beside their originals before any replace
    so a read/encoding/write failure leaves the wiki untouched. Individual
    filesystem replacements are atomic; filesystem-wide transactions are
    not available, so a replace failure is reported to the caller.
    """
    pages = catalog(directory)
    page = pages.get(_slug(slug))
    if page is None:
        raise FileNotFoundError(f"Page {slug!r} no longer exists")
    stem = _safe_page_stem(title)
    destination = page.path.with_name(f"{stem}.md")
    new_slug = _slug(stem)
    if (destination != page.path and destination.exists()) or (
            new_slug != page.slug and new_slug in pages):
        raise FileExistsError(f"A page named {title!r} already exists")

    staged: list[tuple[Path, Path]] = []
    try:
        for path in _all_wiki_markdown(directory):
            original = path.read_text(encoding="utf-8")
            changed = _rewrite_page_links(
                original, page.slug, new_slug,
                default_label=title.strip())
            if path == page.path:
                changed, has_heading = _rename_page_heading(
                    changed, title.strip())
                if not has_heading:
                    changed = f"# {title.strip()}\n\n" + changed
            if changed == original:
                continue
            staged.append((_stage_text(path, changed), path))
        if destination != page.path:
            # Stage the page's rewritten text at its new filename; its old
            # path is removed only after every other staged file is ready.
            page_stage = next((tmp for tmp, original in staged
                               if original == page.path), None)
            if page_stage is None:
                page_stage = _stage_text(
                    destination, f"# {title.strip()}\n\n", mode_from=page.path)
                staged.append((page_stage, destination))
            else:
                staged.remove((page_stage, page.path))
                staged.append((page_stage, destination))
        for temporary, target in staged:
            os.replace(temporary, target)
        if destination != page.path:
            page.path.unlink()
    except BaseException:
        for temporary, _target in staged:
            temporary.unlink(missing_ok=True)
        raise
    return DocPage.read(destination, directory)


def delete_page(directory: Path, slug: str) -> None:
    """Delete a page and remove it from an existing sidebar.

    Links in page content remain as plain unresolved text; this preserves a
    useful hint for a reader without silently changing authored prose.
    """
    page = catalog(directory).get(_slug(slug))
    if page is None:
        raise FileNotFoundError(f"Page {slug!r} no longer exists")
    page.path.unlink()
    if (directory / "_Sidebar.md").is_file():
        def without(entries):
            kept = []
            for entry in entries:
                if entry.slug == page.slug:
                    continue
                children = tuple(without(entry.children))
                if entry.slug is None and not children:
                    continue
                kept.append(NavEntry(entry.title, entry.slug, children))
            return kept
        write_sidebar(directory, without(sidebar(directory)))


def write_sidebar(directory: Path, entries: list[NavEntry]) -> None:
    """Persist the displayed navigation hierarchy as GitHub-wiki Markdown."""
    def lines(items: list[NavEntry] | tuple[NavEntry, ...], depth: int) -> list[str]:
        out = []
        for entry in items:
            bullet = " " * (depth * 2) + "- "
            if entry.slug:
                out.append(f"{bullet}[[{entry.slug}|{entry.title}]]")
            else:
                out.append(f"{bullet}**{entry.title}**")
            out.extend(lines(entry.children, depth + 1))
        return out

    _atomic_write(directory / "_Sidebar.md", "\n".join(lines(entries, 0)) + "\n")


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


def _all_wiki_markdown(directory: Path):
    """All Markdown documents in a wiki, including `_Sidebar` and specials."""
    for path in sorted(directory.rglob("*.md")):
        rel = path.relative_to(directory)
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


def render_links(text: str, pages: dict[str, DocPage], *,
                 link_missing: bool = False) -> tuple[str, list[str]]:
    """Rewrite `[[wikilinks]]` and Obsidian `![[embeds]]` to ordinary
    Markdown. `![[image.png]]` becomes a Markdown image (the UI resolves and
    loads it); `![[Note]]` and `[[Note]]` become links. When `link_missing`
    is true, an unresolved `[[Target]]` becomes a `newpage:` link so an
    editable Wiki card can offer to create it. Returns the new text and the
    missing targets; the handbook integrity test checks the latter.
    """
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
            if link_missing:
                from urllib.parse import quote
                slug = _slug(target.rsplit("/", 1)[-1])
                return f"[{shown}](newpage:{quote(slug, safe='-_.~')})"
            return shown  # brackets dropped; reads as plain text, like GitHub
        href = link_target(page.slug)
        if anchor:
            href += "#" + anchor_slug(anchor)
        return f"[{shown}]({href})"

    text = _outside_code(text, lambda s: EMBED_RE.sub(embed, s))
    text = _outside_code(text, lambda s: WIKILINK_RE.sub(link, s))
    return text, missing
