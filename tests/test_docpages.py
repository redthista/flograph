"""The Qt-free side of the in-app handbook: the page catalogue and the
`[[wikilink]]` → Markdown-link rewrite. No Qt, no app."""
import textwrap

import pytest

from flograph.core import docpages
from flograph.core.docpages import (
    DocPage, NavEntry, anchor_slug, breadcrumb, catalog, docs_dir,
    parse_sidebar, render_links, resolve_wiki_dir, sidebar,
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
        # the renderer tags the heading with the very same slug
        assert anchor_slug("Order edges") == "order-edges"

    def test_case_and_dashes_are_normalised(self):
        out, missing = render_links("[[the canvas]] [[The-Canvas]]", self.cat)
        assert out == "[the canvas](the-canvas.md) [The-Canvas](the-canvas.md)"
        assert missing == []

    def test_unknown_target_renders_as_plain_text_and_is_reported(self):
        out, missing = render_links("look at [[Nowhere]] please", self.cat)
        assert out == "look at Nowhere please"
        assert missing == ["Nowhere"]

    def test_editable_wiki_can_link_to_create_a_missing_page(self):
        out, missing = render_links(
            "look at [[folder/Nowhere|the guide]]", self.cat,
            link_missing=True)
        assert out == "look at [the guide](newpage:nowhere)"
        assert missing == ["folder/Nowhere"]

    def test_obsidian_image_embed_becomes_a_markdown_image(self):
        out, _ = render_links("![[diagram.png]] ![[shot.png|200]]", self.cat)
        assert "![diagram.png](diagram.png)" in out
        assert "![shot.png|200](shot.png)" in out

    def test_obsidian_note_embed_becomes_a_link(self):
        out, _ = render_links("![[The Canvas]]", self.cat)
        assert out == "[The Canvas](the-canvas.md)"

    def test_folder_path_link_resolves_by_basename(self):
        out, _ = render_links("[[reference/The Canvas]]", self.cat)
        assert out == "[reference/The Canvas](the-canvas.md)"

    def test_syntax_inside_code_is_left_verbatim(self):
        text = ("Use `![[Label]]` in a report.\n\n"
                "```\n![[Total Revenue]]\n[[Not A Page]]\n```\n")
        out, missing = render_links(text, self.cat)
        assert "`![[Label]]`" in out
        assert "![[Total Revenue]]" in out
        assert "[[Not A Page]]" in out
        assert missing == []

    def test_a_double_tick_span_may_contain_backticks(self):
        """That is what the ``…`` form is *for* — quoting a backtick. Read
        as "anything but a backtick" it stopped matching, and the link
        inside was resolved after all."""
        text = "Write `` `![[Not A Page]]` `` to show the syntax.\n"
        out, missing = render_links(text, self.cat)
        assert "![[Not A Page]]" in out
        assert missing == []


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

    def test_pages_are_found_recursively(self, tmp_path):
        (tmp_path / "guide").mkdir()
        (tmp_path / "guide" / "Deep.md").write_text("# Deep\n", encoding="utf-8")
        (tmp_path / "Top.md").write_text("# Top\n", encoding="utf-8")
        cat = catalog(tmp_path)
        assert set(cat) == {"deep", "top"}
        assert cat["deep"].rel == ("guide",)

    def test_dot_folders_are_skipped(self, tmp_path):
        (tmp_path / ".obsidian").mkdir()
        (tmp_path / ".obsidian" / "config.md").write_text("# x\n", encoding="utf-8")
        (tmp_path / "Real.md").write_text("# Real\n", encoding="utf-8")
        assert set(catalog(tmp_path)) == {"real"}


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

    def test_folder_structure_is_the_fallback_tree_for_a_vault(self, tmp_path):
        (tmp_path / "Home.md").write_text("# Home\n", encoding="utf-8")
        (tmp_path / "guide").mkdir()
        (tmp_path / "guide" / "Setup.md").write_text("# Setup\n", encoding="utf-8")
        (tmp_path / "guide" / "Usage.md").write_text("# Usage\n", encoding="utf-8")
        tree = sidebar(tmp_path)
        assert tree[0].slug == "home"                     # root page first
        section = tree[1]
        assert section.slug is None and section.title == "guide"
        assert {c.slug for c in section.children} == {"setup", "usage"}

    def test_a_page_missing_from_the_sidebar_is_appended(self, tmp_path):
        (tmp_path / "Home.md").write_text("# Home\n", encoding="utf-8")
        (tmp_path / "The-Canvas.md").write_text("# The Canvas\n", encoding="utf-8")
        (tmp_path / "Orphan.md").write_text("# Orphan\n", encoding="utf-8")
        (tmp_path / "_Sidebar.md").write_text(
            "- [[Home]]\n- [[The Canvas]]\n", encoding="utf-8")
        assert "orphan" in {e.slug for e in sidebar(tmp_path)}


class TestResolveWikiDir:
    def test_blank_or_none_is_the_bundled_handbook(self):
        assert resolve_wiki_dir(None) == docs_dir()
        assert resolve_wiki_dir("") == docs_dir()
        assert resolve_wiki_dir("   ") == docs_dir()

    def test_a_missing_folder_falls_back(self, tmp_path):
        assert resolve_wiki_dir(str(tmp_path / "nope")) == docs_dir()

    def test_a_real_folder_is_used_as_given(self, tmp_path):
        assert resolve_wiki_dir(str(tmp_path)) == tmp_path
        assert resolve_wiki_dir(f"  {tmp_path}  ") == tmp_path


class TestPageEditing:
    def test_creating_a_page_uses_the_title_as_an_h1(self, tmp_path):
        page = docpages.create_page(tmp_path, "Team Guide")
        assert page.slug == "team-guide"
        assert page.path.read_text(encoding="utf-8") == "# Team Guide\n\n"

    def test_page_titles_cannot_escape_the_wiki_folder(self, tmp_path):
        for title in ("../outside", "a/b", "a\\b", ""):
            with pytest.raises(ValueError):
                docpages.create_page(tmp_path, title)
        assert list(tmp_path.iterdir()) == []

    def test_creating_an_existing_slug_is_rejected(self, tmp_path):
        (tmp_path / "Team-Guide.md").write_text("# Team Guide\n", encoding="utf-8")
        with pytest.raises(FileExistsError):
            docpages.create_page(tmp_path, "team guide")

    def test_rename_rewrites_inbound_links_and_sidebar(self, tmp_path):
        (tmp_path / "Old-Page.md").write_text("# Old Page\n\nBody\n", encoding="utf-8")
        (tmp_path / "Other.md").write_text(
            "[[Old Page#First Part|the page]] ![[old-page]] `[[Old Page]]`\n"
            "```md\n[[Old Page]]\n```\n![[image.png]]\n",
            encoding="utf-8")
        (tmp_path / "_Sidebar.md").write_text(
            "- [[Old Page|Start]]\n- [[Old Page]]\n", encoding="utf-8")
        (tmp_path / "_Footer.md").write_text("See [[Old Page]].\n", encoding="utf-8")

        renamed = docpages.rename_page(tmp_path, "old-page", "New Guide")

        assert renamed.slug == "new-guide"
        assert renamed.path.read_text(encoding="utf-8").startswith("# New Guide\n")
        assert not (tmp_path / "Old-Page.md").exists()
        other = (tmp_path / "Other.md").read_text(encoding="utf-8")
        assert "[[new-guide#First Part|the page]]" in other
        assert "![[new-guide|New Guide]]" in other
        assert "`[[Old Page]]`" in other
        assert "```md\n[[Old Page]]\n```" in other
        assert "![[image.png]]" in other
        sidebar_text = (tmp_path / "_Sidebar.md").read_text(encoding="utf-8")
        assert "[[new-guide|Start]]" in sidebar_text
        assert "[[new-guide|New Guide]]" in sidebar_text
        assert "[[new-guide|New Guide]]" in (tmp_path / "_Footer.md").read_text(
            encoding="utf-8")

    def test_rename_updates_a_real_heading_after_a_fenced_example(self, tmp_path):
        (tmp_path / "Old-Page.md").write_text(
            "```markdown\n# Example heading\n```\n\n# Old Page\n\nBody\n",
            encoding="utf-8")

        renamed = docpages.rename_page(tmp_path, "old-page", "New Guide")

        assert renamed.path.read_text(encoding="utf-8") == (
            "```markdown\n# Example heading\n```\n\n# New Guide\n\nBody\n")

    def test_rename_adds_heading_without_dropping_rewritten_self_links(
            self, tmp_path):
        (tmp_path / "Old-Page.md").write_text(
            "```markdown\n# Example heading\n```\n\nSee [[Old Page]].\n",
            encoding="utf-8")

        renamed = docpages.rename_page(tmp_path, "old-page", "New Guide")

        assert renamed.path.read_text(encoding="utf-8") == (
            "# New Guide\n\n```markdown\n# Example heading\n```\n\n"
            "See [[new-guide|New Guide]].\n")

    def test_rename_rejects_an_existing_target_without_changing_files(self, tmp_path):
        (tmp_path / "First.md").write_text("# First\n", encoding="utf-8")
        (tmp_path / "Second.md").write_text("# Second\n", encoding="utf-8")
        with pytest.raises(FileExistsError):
            docpages.rename_page(tmp_path, "first", "Second")
        assert (tmp_path / "First.md").exists()
        assert (tmp_path / "Second.md").read_text(encoding="utf-8") == "# Second\n"

    def test_delete_removes_the_page_and_keeps_links_as_text(self, tmp_path):
        (tmp_path / "Home.md").write_text("# Home\n\n[[Setup]]\n", encoding="utf-8")
        (tmp_path / "Setup.md").write_text("# Setup\n", encoding="utf-8")
        (tmp_path / "_Sidebar.md").write_text(
            "- [[Home]]\n- [[Setup]]\n", encoding="utf-8")
        docpages.delete_page(tmp_path, "setup")
        assert not (tmp_path / "Setup.md").exists()
        rendered, missing = render_links(
            (tmp_path / "Home.md").read_text(encoding="utf-8"), catalog(tmp_path))
        assert "Setup" in rendered
        assert missing == ["Setup"]
        assert "setup" not in (tmp_path / "_Sidebar.md").read_text(
            encoding="utf-8").lower()

    def test_sidebar_can_be_written_with_sections_and_reordered_pages(self, tmp_path):
        entries = [NavEntry("Basics", None, (
            NavEntry("Setup", "setup"), NavEntry("Home", "home"))),
            NavEntry("Reference", None, (NavEntry("API", "api"),))]
        docpages.write_sidebar(tmp_path, entries)
        text = (tmp_path / "_Sidebar.md").read_text(encoding="utf-8")
        assert text == (
            "- **Basics**\n  - [[setup|Setup]]\n  - [[home|Home]]\n"
            "- **Reference**\n  - [[api|API]]\n")
        pages = {slug: DocPage(slug, slug.title(), tmp_path / f"{slug}.md")
                 for slug in ("setup", "home", "api")}
        loaded = parse_sidebar(text, pages)
        assert [entry.title for entry in loaded[0].children] == ["Setup", "Home"]

    def test_bundled_handbook_is_read_only_except_for_an_explicit_override(
            self, tmp_path, monkeypatch):
        monkeypatch.delenv("FLOGRAPH_DOCS_DIR", raising=False)
        assert docpages.is_bundled_docs(docs_dir())
        monkeypatch.setenv("FLOGRAPH_DOCS_DIR", str(tmp_path))
        assert not docpages.is_bundled_docs(tmp_path)


class TestBreadcrumb:
    def _tree(self):
        return [
            NavEntry("Home", "home"),
            NavEntry("Basics", None, (
                NavEntry("Getting Started", "getting-started"),
                NavEntry("The Canvas", "the-canvas"),
            )),
        ]

    def test_trail_includes_the_section_and_the_page(self):
        trail = breadcrumb("the-canvas", self._tree())
        assert [e.title for e in trail] == ["Basics", "The Canvas"]

    def test_top_level_page_is_a_one_entry_trail(self):
        assert [e.title for e in breadcrumb("home", self._tree())] == ["Home"]

    def test_a_page_not_in_the_tree_has_no_trail(self):
        assert breadcrumb("orphan", self._tree()) == []


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


def test_a_quoted_fence_in_a_sentence_does_not_open_one():
    """A ```` ```columns ```` span in prose used to pair with the next real
    fence, so the example block after it was read as live links."""
    text = ("a ```` ```columns ```` block, and a bare ```columns too\n\n"
            "```text\n![[North sales|live]]\n```\n\n"
            "```\napponly:: ![[Refresh Data]]\n```\n")
    _out, missing = render_links(text, {})
    assert missing == []
