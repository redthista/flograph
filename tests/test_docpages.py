"""The Qt-free side of the in-app handbook: the page catalogue and the
`[[wikilink]]` → Markdown-link rewrite. No Qt, no app."""
import textwrap

import pytest

from flograph.core import docpages
from flograph.core.docpages import (
    DocPage, catalog, docs_dir, parse_sidebar, render_links, sidebar,
)


def _pages(tmp_path, **files):
    for name, body in files.items():
        (tmp_path / name).write_text(textwrap.dedent(body), encoding="utf-8")
    return catalog(tmp_path)


class TestRenderLinks:
    def setup_method(self):
        self.cat = {
            "home": DocPage("home", "Home", None),
            "the-canvas": DocPage("the-canvas", "The Canvas", None),
        }

    def test_plain_wikilink_becomes_a_markdown_link(self):
        out, missing = render_links("see [[The Canvas]] for more", self.cat)
        assert out == "see [The Canvas](the-canvas.md) for more"
        assert missing == []

    def test_labelled_wikilink_uses_the_label(self):
        out, _ = render_links("[[The Canvas|the canvas]]", self.cat)
        assert out == "[the canvas](the-canvas.md)"

    def test_anchor_is_carried_and_slugged(self):
        out, _ = render_links("[[The Canvas#Order edges]]", self.cat)
        assert out == "[The Canvas § Order edges](the-canvas.md#order-edges)"

    def test_case_and_dashes_are_normalised(self):
        out, missing = render_links("[[the canvas]] [[The-Canvas]]", self.cat)
        assert out == "[the canvas](the-canvas.md) [The-Canvas](the-canvas.md)"
        assert missing == []

    def test_unknown_target_renders_as_plain_text_and_is_reported(self):
        out, missing = render_links("look at [[Nowhere]] please", self.cat)
        assert out == "look at Nowhere please"
        assert missing == ["Nowhere"]

    def test_embed_syntax_is_left_alone(self):
        text = "chart: ![[Revenue by Region|table]] and [[Home]]"
        out, _ = render_links(text, self.cat)
        assert "![[Revenue by Region|table]]" in out
        assert "[Home](home.md)" in out


class TestCatalog:
    def test_title_comes_from_the_first_h1(self, tmp_path):
        cat = _pages(tmp_path, **{"Getting-Started.md": "# Getting Started\n\nhi"})
        assert cat["getting-started"].title == "Getting Started"

    def test_underscore_files_are_not_pages(self, tmp_path):
        cat = _pages(tmp_path, **{
            "Home.md": "# Home\n", "_Sidebar.md": "- [[Home]]\n"})
        assert set(cat) == {"home"}

    def test_title_falls_back_to_the_filename(self, tmp_path):
        cat = _pages(tmp_path, **{"No-Heading.md": "just text\n"})
        assert cat["no-heading"].title == "No Heading"

    def test_keyed_by_normalised_slug(self, tmp_path):
        cat = _pages(tmp_path, **{"The-Canvas.md": "# The Canvas\n"})
        assert set(cat) == {"the-canvas"}


class TestSidebar:
    def _cat(self):
        return {
            "home": DocPage("home", "Home", None),
            "getting-started": DocPage("getting-started", "Getting Started", None),
            "the-canvas": DocPage("the-canvas", "The Canvas", None),
        }

    def test_nested_bullets_become_a_tree(self):
        text = textwrap.dedent("""\
            - [[Home]]
            - **Basics**
              - [[Getting Started]]
              - [[The Canvas]]
        """)
        tree = parse_sidebar(text, self._cat())
        assert [e.title for e in tree] == ["Home", "Basics"]
        assert tree[0].slug == "home" and tree[0].children == ()
        basics = tree[1]
        assert basics.slug is None  # a section header
        assert [c.title for c in basics.children] == ["Getting Started", "The Canvas"]
        assert [c.slug for c in basics.children] == ["getting-started", "the-canvas"]

    def test_label_and_emphasis_are_respected(self):
        tree = parse_sidebar("- [[Home|Start]]\n- __Section__\n", self._cat())
        assert tree[0].title == "Start"
        assert tree[1].title == "Section" and tree[1].slug is None

    def test_unknown_link_is_dropped(self):
        tree = parse_sidebar("- [[Home]]\n- [[Nope]]\n", self._cat())
        assert [e.slug for e in tree] == ["home"]

    def test_falls_back_to_a_flat_list_without_a_sidebar_file(self, tmp_path):
        (tmp_path / "Home.md").write_text("# flograph\n", encoding="utf-8")
        (tmp_path / "The-Canvas.md").write_text("# The Canvas\n", encoding="utf-8")
        monkey = sidebar(tmp_path)
        assert monkey[0].title == "Home" and monkey[0].slug == "home"
        assert [e.slug for e in monkey] == ["home", "the-canvas"]

    def test_a_page_missing_from_the_sidebar_is_appended(self, tmp_path):
        (tmp_path / "Home.md").write_text("# Home\n", encoding="utf-8")
        (tmp_path / "The-Canvas.md").write_text("# The Canvas\n", encoding="utf-8")
        (tmp_path / "Orphan.md").write_text("# Orphan\n", encoding="utf-8")
        (tmp_path / "_Sidebar.md").write_text(
            "- [[Home]]\n- [[The Canvas]]\n", encoding="utf-8")
        assert "orphan" in {e.slug for e in sidebar(tmp_path)}


class TestBundledPages:
    """Integrity of the pages that actually ship — in the spirit of
    tests/test_templates.py hard-asserting the example list."""

    def test_docs_dir_is_a_real_directory_with_pages(self):
        d = docs_dir()
        assert d.is_dir()
        assert list(d.glob("*.md")), "no bundled documentation pages found"

    def test_home_exists(self):
        assert "home" in catalog()

    def test_every_page_opens_with_an_h1(self):
        for slug, page in catalog().items():
            first = page.path.read_text(encoding="utf-8").lstrip().splitlines()[0]
            assert first.startswith("# "), f"{page.path.name} has no H1"

    def test_every_wikilink_in_every_shipped_page_resolves(self):
        cat = catalog()
        broken = {}
        for slug, page in cat.items():
            _, missing = render_links(page.path.read_text(encoding="utf-8"), cat)
            if missing:
                broken[page.path.name] = missing
        assert not broken, f"wikilinks point at missing pages: {broken}"

    def test_the_shipped_sidebar_reaches_every_page(self):
        nav_slugs = set()

        def walk(entries):
            for e in entries:
                if e.slug:
                    nav_slugs.add(e.slug)
                walk(e.children)

        walk(sidebar())
        assert nav_slugs == set(catalog()), "sidebar and pages disagree"

    def test_env_override(self, tmp_path, monkeypatch):
        (tmp_path / "Only.md").write_text("# Only\n", encoding="utf-8")
        monkeypatch.setenv("FLOGRAPH_DOCS_DIR", str(tmp_path))
        assert set(catalog()) == {"only"}
