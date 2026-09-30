"""A report's web page given a shape: `:::` sections that fold, tabs, and
the page's Web Layout settings (core/web_layout.py, ui/report/web_layout.py).

Qt's Markdown reader keeps no <details> or <div>, so each edge of a block
rides through it as a token paragraph and is built after. Paper has nothing
to click, so there a block is written out whole — and a page using none of
this saves the HTML it always did.
"""
import re

import pandas as pd
import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph
from flograph.core.graph import Page
from flograph.core.report_assist import Vocabulary, suggest
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.core.web_layout import (BLOCK_P_RE, Block, WebSettings,
                                      expand_blocks, slug)
from flograph.ui.commands import SetPageWebCommand
from flograph.ui.report import render as R
from flograph.ui.report.html import report_html
from flograph.ui.report.web_layout import apply_layout

BODY = """# Review

::: tabs Region
== North
### North detail
North text.
== South
South text.
:::

::: details How it was worked out
The method.

```columns
Left.
---
Right.
```
:::

## Costs

::: details Assumptions|open
Kept open.
:::
"""


def render(body, live=True):
    return R.render_body(body, lambda ref, port: (None, None, None),
                         live=live)


class TestTheBlocks:
    def test_web_writes_a_token_for_each_edge(self):
        blocks = []
        text = expand_blocks(BODY, web=True, blocks=blocks)
        assert [b.kind for b in blocks] == ["tabs", "details", "details"]
        assert blocks[0] == Block("tabs", "Region", False, ["North", "South"])
        assert blocks[2].open and not blocks[1].open
        assert ":::" not in text and "== North" not in text
        for edge in ("open-0", "tab-0-0", "tab-0-1", "close-0",
                     "open-1", "close-1", "open-2", "close-2"):
            assert f"@@flograph-block-{edge}@@" in text

    def test_blocks_nest_and_a_block_sits_inside_a_column(self):
        blocks = []
        text = expand_blocks(
            "::: details Outer\n```columns\nA\n---\n::: tabs\n== X\nx\n:::\n"
            "```\n:::\n", web=True, blocks=blocks)
        assert [b.kind for b in blocks] == ["details", "tabs"]
        # the inner block closes before the outer one
        assert text.index("close-1") < text.index("close-0")
        assert "```columns" in text

    def test_code_is_left_alone(self):
        text = "```\n::: details Not me\n:::\n```\n"
        blocks = []
        assert expand_blocks(text, web=True, blocks=blocks) == text
        assert blocks == []

    def test_an_unclosed_block_ends_with_the_text(self):
        blocks = []
        text = expand_blocks("::: details Open end\nstill here", True, blocks)
        assert text.rstrip().endswith("@@flograph-block-close-0@@")
        assert "still here" in text

    def test_unknown_kinds_and_stray_closes_stay_as_written(self):
        text = "::: warning Careful\n:::\n"
        assert expand_blocks(text, web=True) == text

    def test_paper_writes_each_block_out_whole(self):
        text = expand_blocks(BODY, web=False)
        assert "@@flograph" not in text and ":::" not in text
        for title in ("**How it was worked out**", "**North**", "**South**",
                      "**Assumptions**"):
            assert title in text

    def test_ids_are_stable_and_unique(self):
        used = set()
        assert [slug(t, used) for t in ("Q3 Sales", "Q3 Sales", "!!")] == \
            ["q3-sales", "q3-sales-2", "section"]


class TestTheSettings:
    def test_defaults_write_nothing(self):
        assert WebSettings().to_dict() == {}
        assert WebSettings().is_default()

    def test_round_trip_and_bad_values(self):
        web = WebSettings(sidebar="closed", depth=2, topbar=True,
                          split=False, paged="headings", width=1100,
                          share_state=False)
        assert WebSettings.from_dict(web.to_dict()) == web
        odd = WebSettings.from_dict({"sidebar": "sideways", "depth": 99,
                                     "width": "wide"})
        assert odd == WebSettings(depth=6)

    def test_every_heading_level_unless_told(self):
        assert WebSettings().depth == 0          # Auto
        assert WebSettings.from_dict({"depth": -3}).depth == 0

    def test_pages_need_something_to_go_between_them_by(self):
        assert not WebSettings(paged="sections").has_nav()
        assert WebSettings(paged="sections", sidebar="open").has_nav()
        assert WebSettings(paged="sections", topbar=True).has_nav()

    def test_paging_that_was_on_or_off_reads_as_sections(self):
        assert WebSettings.from_dict({"paged": True}).paged == "sections"
        assert WebSettings.from_dict({"paged": "pages"}).paged == "off"

    def test_saved_with_the_page(self, qapp):
        graph = Graph()
        graph.add_page(Page(id="p1", kind="report",
                            web=WebSettings(sidebar="open", topbar=True)))
        graph.add_page(Page(id="p2", kind="report"))
        data = graph_to_dict(graph)
        pages = {p["id"]: p for p in data["graph"]["pages"]}
        assert pages["p1"]["web"] == {"sidebar": "open", "topbar": True}
        assert "web" not in pages["p2"]      # a page nobody set up says nothing
        from flograph.core.registry import NodeRegistry
        back = graph_from_dict(data, NodeRegistry())
        assert back.pages["p1"].web == WebSettings(sidebar="open",
                                                   topbar=True)
        assert back.pages["p2"].web == WebSettings()

    def test_changing_them_is_one_undo_step(self, qapp):
        graph = Graph()
        graph.add_page(Page(id="p1", kind="report"))
        stack = QUndoStack()
        wanted = WebSettings(sidebar="open")
        stack.push(SetPageWebCommand(graph, "p1", wanted))
        assert graph.pages["p1"].web == wanted
        assert graph.pages["p1"].web is not wanted    # a copy, not shared
        stack.undo()
        assert graph.pages["p1"].web == WebSettings()


class TestTheWebPage:
    def test_blocks_become_elements(self, qapp):
        html = report_html(render(BODY), "Review")
        assert "@@flograph-block" not in html
        assert not BLOCK_P_RE.search(html)
        assert '<div class="fg-tabs" id="region">' in html
        assert re.search(r'<section class="fg-tab"[^>]*data-tab="south"',
                         html)
        assert re.search(r'<details class="fg-details" id="assumptions"'
                         r'[^>]*data-fg-default="open" open>', html)
        assert "<summary>How it was worked out</summary>" in html
        assert html.count("<details") == html.count("</details>") == 2
        assert html.count("<section") == html.count("</section>") == 2

    def test_headings_get_ids_that_do_not_clash_with_blocks(self, qapp):
        html = report_html(render("# Region\n\n::: tabs Region\n== A\na\n"
                                  ":::\n"), "t")
        assert re.search(r'<h1 id="region"', html)
        assert 'class="fg-tabs" id="region-2"' in html

    def test_a_page_using_none_of_it_is_unchanged(self, qapp):
        rendered = render("# Plain\n\nJust text.")
        assert report_html(rendered, "t", web=WebSettings()) == \
            report_html(rendered, "t")
        assert "fg-layout-config" not in report_html(rendered, "t")

    def test_settings_alone_switch_the_layout_on(self, qapp):
        rendered = render("# Plain\n\n## One\n\n## Two")
        html = report_html(rendered, "Plain",
                           web=WebSettings(sidebar="open", topbar=True,
                                           paged="headings"))
        config = re.search(r'id="fg-layout-config">(.*?)</script>',
                           html).group(1)
        assert '"paged": "headings"' in config
        assert '"title": "Plain"' in config
        assert '"topbar": true' in config and '"depth": 0' in config
        assert '<h2 id="one"' in html

    def test_drop_downs_only_come_with_a_top_bar(self, qapp):
        rendered = render("# A\n\n## B\n\n### B1\n\n## C")
        on = report_html(rendered, "t",
                         web=WebSettings(topbar=True, menus=True))
        assert '"menus": true' in on and ".fg-drop" in on
        off = report_html(rendered, "t",
                          web=WebSettings(sidebar="open", menus=True))
        assert '"menus": false' in off

    def test_previous_and_next_are_asked_for(self, qapp):
        rendered = render("# A\n\n## B\n\n## C")
        off = report_html(rendered, "t", web=WebSettings(
            sidebar="open", paged="headings"))
        assert '"pager": false' in off
        on = report_html(rendered, "t", web=WebSettings(
            sidebar="open", paged="headings", pager=True))
        assert '"pager": true' in on

    def test_paged_with_no_way_round_is_not_paged(self, qapp):
        html = report_html(render("# A\n\n## B\n\n## C"), "t",
                           web=WebSettings(paged="headings", width=820))
        assert '"paged": "off"' in html

    def test_width_holds_the_text_to_a_column(self, qapp):
        html = report_html(render("# x"), "t", web=WebSettings(width=820))
        assert "--fg-width: 820px" in html

    def test_a_title_cannot_close_the_script(self, qapp):
        html = apply_layout("<html><head></head><body></body></html>",
                            render("x"), WebSettings(topbar=True),
                            "</script><b>")
        assert "</script><b>" not in html

    def test_paper_shows_every_block_whole(self, qapp):
        rendered = render(BODY, live=False)
        text = rendered.document.toPlainText()
        assert "@@" not in text
        for words in ("North text.", "South text.", "The method.",
                      "How it was worked out", "Kept open."):
            assert words in text


class TestTheEditor:
    def test_colons_offer_the_blocks_once_a_letter_is_typed(self):
        found = suggest("::: ta", "", Vocabulary())
        assert found.items[0].label == "tabs"
        assert found.items[0].text == "tabs "
        # a bare ::: also ends a block: the list must not jump up for it
        assert suggest(":::", "", Vocabulary()).eager is False


class TestTheToolbar:
    @pytest.fixture
    def page(self, qtbot):
        from flograph.core.registry import NodeRegistry
        from flograph.engine import ExecutionEngine
        from flograph.ui.report import ReportPage
        graph = Graph()
        graph.add_page(Page(id="p1", title="Q3", kind="report"))
        stack = QUndoStack()
        widget = ReportPage(graph, ExecutionEngine(graph), stack, "p1")
        qtbot.addWidget(widget)
        yield widget, graph, stack
        widget.dispose()

    def test_web_layout_takes_page_setups_place(self, page):
        widget, _graph, _stack = page
        # this page was made on Pages (the model's default)
        assert widget._web_btn.isHidden() and not widget._setup_btn.isHidden()
        widget._set_preview_mode("pages")
        assert widget._web_btn.isHidden() and not widget._setup_btn.isHidden()
        widget._set_preview_mode("web")
        assert not widget._web_btn.isHidden() and widget._setup_btn.isHidden()

    def test_the_menu_sets_the_page_one_undo_step_at_a_time(self, page):
        widget, graph, stack = page
        menu = widget.web_menu()
        sidebar = next(a for a in menu.actions()
                       if a.text() == "Sidebar of headings").menu()
        next(a for a in sidebar.actions() if a.text() == "Shown").trigger()
        assert graph.pages["p1"].web.sidebar == "open"
        menu = widget.web_menu()
        pages = next(a for a in menu.actions() if a.text() == "Pages").menu()
        assert pages.isEnabled()        # the sidebar is there to go by
        next(a for a in pages.actions()
             if a.text() == "One per heading").trigger()
        assert graph.pages["p1"].web.paged == "headings"
        # Previous / Next: off to start with, there once there are pages
        pages = next(a for a in widget.web_menu().actions()
                     if a.text() == "Pages").menu()
        pager = next(a for a in pages.actions()
                     if a.text().startswith("Previous / Next"))
        assert pager.isEnabled() and not pager.isChecked()
        pager.trigger()
        assert graph.pages["p1"].web.pager
        stack.undo()                    # Previous / Next
        assert not graph.pages["p1"].web.pager
        stack.undo()                    # the pages
        assert graph.pages["p1"].web == WebSettings(sidebar="open")
        # the menu shows what the page has
        menu = widget.web_menu()
        sidebar = next(a for a in menu.actions()
                       if a.text() == "Sidebar of headings").menu()
        assert next(a for a in sidebar.actions()
                    if a.text() == "Shown").isChecked()

    def test_the_sidebar_split_waits_for_a_top_bar(self, page):
        widget, graph, _stack = page

        def split_action():
            side = next(a for a in widget.web_menu().actions()
                        if a.text() == "Sidebar of headings").menu()
            return next(a for a in side.actions()
                        if a.text().startswith("Only what is under"))

        assert not split_action().isEnabled()
        top = next(a for a in widget.web_menu().actions()
                   if a.text() == "Top bar of the top-level sections")
        top.trigger()
        assert graph.pages["p1"].web.topbar
        assert split_action().isEnabled() and split_action().isChecked()
        menus = next(a for a in widget.web_menu().actions()
                     if a.text() == "Drop-down of each section's headings")
        assert menus.isEnabled() and not menus.isChecked()
        menus.trigger()
        assert graph.pages["p1"].web.menus

    def test_heading_levels_start_on_auto(self, page):
        widget, _graph, _stack = page
        side = next(a for a in widget.web_menu().actions()
                    if a.text() == "Sidebar of headings").menu()
        levels = next(a for a in side.actions()
                      if a.text() == "Heading levels listed").menu()
        checked = [a.text() for a in levels.actions() if a.isChecked()]
        assert checked == ["Auto (every level)"]
