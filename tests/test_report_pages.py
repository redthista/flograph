"""Idea #1, pass 1: report pages — markdown that embeds what the flow made.

A third page kind beside Model and Dashboard. The body is markdown;
``![[Node Label]]`` pulls in that node's cached output — a chart as a
picture, a frame as a table, a number inline, and a *string as markdown*,
which is what lets a report be assembled by the flow rather than typed.
The same document backs the preview and the PDF.
"""
import json

import pandas as pd
import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry, Page
from flograph.core.report import (find_embeds, format_scalar,
                                  frame_to_markdown, inline_markdown,
                                  replace_embeds)
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.engine.cache import OutputCache
from flograph.ui.report.render import render_report


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def env(registry):
    """A graph with a few nodes that have produced things to embed."""
    graph = Graph()
    cache = OutputCache()

    def add(label, value):
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, label)
        cache.set(node.id, {"value": value}, 0.0)
        return node

    add("Sales", pd.DataFrame({"region": ["North", "South"],
                               "revenue": [1000, 2500]}))
    add("Total", 3500)
    add("Findings", "## Findings\n\nRevenue rose **12%**.\n")
    silent = graph.add_node(registry.instantiate("flograph.util.constant"))
    graph.set_label(silent.id, "Never Run")
    return graph, cache


def html_of(body, env):
    graph, cache = env
    return render_report(body, graph, cache).document.toHtml()


class TestTheSyntax:

    def test_a_plain_embed(self):
        found = find_embeds("text\n\n![[Sales Chart]]\n")
        assert len(found) == 1
        assert found[0].ref == "Sales Chart" and found[0].port == ""

    def test_a_port_can_be_named(self):
        assert find_embeds("![[Model|scores]]")[0].port == "scores"

    def test_surrounding_whitespace_is_ignored(self):
        embed = find_embeds("![[  Sales  |  table  ]]")[0]
        assert (embed.ref, embed.port) == ("Sales", "table")

    def test_ordinary_markdown_images_are_left_alone(self):
        assert find_embeds("![alt](path.png) and [[a wiki link]]") == []

    def test_several_in_one_body(self):
        assert [e.ref for e in find_embeds("![[a]] mid ![[b]]")] == ["a", "b"]

    def test_a_block_replacement_gets_its_own_blank_lines(self):
        """A table folded into the paragraph above it renders as one
        mangled block, so multi-line replacements are separated out."""
        out = replace_embeds("before\n![[x]]\nafter", lambda e: "| a |\n| - |")
        lines = out.splitlines()
        table = lines.index("| a |")
        assert lines[table - 1].strip() == ""      # separated from "before"
        assert lines[table + 2].strip() == ""      # ...and from "after"

    def test_a_one_line_replacement_stays_inline(self):
        assert replace_embeds("total: ![[x]].", lambda e: "42") == "total: 42."


class TestTablesAndValues:

    def test_a_frame_becomes_a_markdown_table(self):
        md = frame_to_markdown(pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}))
        assert md.splitlines()[0] == "| a | b |"
        assert md.splitlines()[2] == "| 1 | x |"

    def test_a_long_frame_says_it_was_cut(self):
        """Silently showing the first n rows of a report table would be a
        lie the reader can't detect."""
        md = frame_to_markdown(pd.DataFrame({"a": range(100)}), max_rows=5)
        assert md.count("\n|") == 6      # header + rule + 5 rows
        assert "Showing 5 of 100 rows" in md

    def test_pipes_and_newlines_cannot_break_a_row(self):
        md = frame_to_markdown(pd.DataFrame({"a": ["x|y", "p\nq"]}))
        assert r"x\|y" in md and "p q" in md

    def test_missing_values_are_blank(self):
        md = frame_to_markdown(pd.DataFrame({"a": [1.0, None]}))
        assert md.strip().endswith("|  |")

    def test_a_series_works_too(self):
        assert "| a |" in frame_to_markdown(pd.Series([1, 2], name="a"))

    def test_scalars_read_like_a_report(self):
        assert format_scalar(1234567) == "1,234,567"
        assert format_scalar("north") == "north"
        assert format_scalar(True) == "True"

    def test_a_big_float_is_not_written_in_scientific_notation(self):
        """A KPI of 114558.0 printed as "1.146e+05" is not something to put
        in a report someone else reads."""
        assert format_scalar(114558.0) == "114,558"
        assert format_scalar(114558.42) == "114,558.42"
        assert format_scalar(-4200.5) == "-4,200.5"

    def test_float_noise_is_still_trimmed(self):
        assert format_scalar(1 / 3) == "0.3333333333"

    def test_nan_and_infinity_stay_readable(self):
        assert format_scalar(float("nan")) == "nan"
        assert format_scalar(float("inf")) == "inf"


class TestInlineMarkdown:
    """Reported 2026-07-26: a Python Script returning markdown showed the raw
    string. The string is built inside run(), so Python's indentation is on
    every line — and four spaces in markdown means code block. Markdown was
    behaving correctly; the trap is that the cause is invisible from the
    editor, and every user of the "build it from data" path meets it."""

    def test_the_reported_case(self):
        assert inline_markdown("\n    ## my markdown\n    ") == \
            "\n## my markdown\n"

    def test_a_flush_string_is_untouched(self):
        assert inline_markdown("## Findings\n\nUp **12%**.\n") == \
            "## Findings\n\nUp **12%**.\n"

    def test_relative_indentation_survives(self):
        """Nested lists are the everyday case — dedenting must shift the
        whole block, never flatten it."""
        assert inline_markdown("    - one\n        - nested\n") == \
            "- one\n    - nested\n"

    def test_a_deliberate_code_block_is_left_alone(self):
        """Why textwrap.dedent and not inspect.cleandoc: cleandoc measures
        the margin from every line *but the first*, so flush prose over an
        indented code block reads as uniformly indented to it and the block
        would be flattened into prose. dedent takes the common prefix of
        every line — nothing here — and leaves it be."""
        text = "Some text\n\n    def foo():\n        pass\n"
        assert inline_markdown(text) == text

    def test_tabs_and_empty_strings_survive(self):
        assert inline_markdown("") == ""
        assert inline_markdown("\t## tabbed\n") == "## tabbed\n"


class TestRendering:

    def test_a_frame_embed_renders_as_a_table(self, env):
        html = html_of("# R\n\n![[Sales]]\n", env)
        assert "<table" in html and "North" in html

    def test_a_scalar_embed_renders_inline(self, env):
        assert "3,500" in html_of("Revenue was ![[Total]] this quarter.", env)

    def test_a_string_embed_is_inlined_as_markdown(self, env):
        """The programmatic path: a node returning prose becomes real
        headings and bold, not a quoted blob."""
        html = html_of("![[Findings]]", env)
        assert "Findings</" in html          # rendered as a heading
        assert 'font-weight:700;">12%' in html

    def test_an_indented_string_still_renders_as_markdown(self, env,
                                                          registry):
        """Reported 2026-07-26: a Python Script returning markdown showed the
        raw string instead of headings. The string is built inside run(), so
        Python's own indentation is on every line — and four spaces in
        markdown means code block. Markdown was right; the trap is that the
        cause is invisible from the editor."""
        graph, cache = env
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, "Indented")
        cache.set(node.id, {"value": "\n    ## my markdown\n    "}, 0.0)
        html = html_of("![[Indented]]", env)
        assert "my markdown</" in html      # a heading, not a code block
        assert "<pre" not in html

    def test_a_figure_embed_becomes_an_image(self, env):
        from matplotlib.figure import Figure
        graph, cache = env
        figure = Figure(figsize=(4, 2))
        figure.add_subplot().plot([1, 2, 3])
        node = next(n for n in graph.nodes.values() if n.label == "Total")
        cache.set(node.id, {"value": figure}, 0.0)
        assert 'src="embed:0"' in html_of("![[Total]]", env)

    def test_the_embedded_image_is_registered_on_the_document(self, env):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QTextDocument
        from matplotlib.figure import Figure
        graph, cache = env
        figure = Figure(figsize=(4, 2))
        figure.add_subplot().plot([1, 2, 3])
        node = next(n for n in graph.nodes.values() if n.label == "Total")
        cache.set(node.id, {"value": figure}, 0.0)

        document = render_report("![[Total]]", graph, cache).document
        resource = document.resource(QTextDocument.ImageResource,
                                     QUrl("embed:0"))
        assert resource is not None and not resource.isNull()

    def test_markdown_around_the_embeds_still_works(self, env):
        html = html_of("# Title\n\n- one\n- two\n\n**bold**\n", env)
        assert "Title</" in html and "<li" in html

    def test_labels_match_case_insensitively(self, env):
        assert "<table" in html_of("![[sALES]]", env)


class TestEmbeddingAReportCardOnAPage:
    """Reported 2026-07-26: "when i create a report page from a report node it
    shows the text like ![[a]]". A page embedding a report card was inlining
    the card's *source*, because the page resolves one embed, gets a string,
    and a substituted string is not re-scanned. The card's contents are now
    rendered in place — resolved against the card's own wired inputs, not
    the page's labels."""

    @pytest.fixture
    def carded(self, env, registry):
        graph, cache = env
        card = graph.add_node(registry.instantiate("flograph.viz.report_card"))
        graph.set_label(card.id, "Summary")
        source = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(source.id, "Feeder")
        graph.connect(source.id, "value", card.id, "a")
        cache.set(source.id, {"value": 48250}, 0.0)
        return graph, cache, card, source

    def test_the_card_s_contents_land_on_the_page(self, carded, env):
        graph, _cache, card, _source = carded
        graph.set_param(card.id, "text", "Total was ![[a]].")
        html = html_of("# Report\n\n![[Summary]]\n", env)
        assert "48,250" in html
        assert "![[a]]" not in html

    def test_a_chart_inside_the_card_arrives_as_a_picture(self, carded, env):
        """The nested render shares the page's resolver, so images collected
        inside a card are spliced into the page's one document."""
        from matplotlib.figure import Figure
        graph, cache, card, source = carded
        figure = Figure(figsize=(4, 2))
        figure.add_subplot().plot([1, 2, 3])
        cache.set(source.id, {"value": figure}, 0.0)
        graph.set_param(card.id, "text", "![[a]]")
        assert 'src="embed:0"' in html_of("![[Summary]]", env)

    def test_a_nested_embed_resolves_the_card_s_inputs_first(self, carded,
                                                             env):
        """A card embedded on a page still resolves its own inputs first,
        exactly as it does on the canvas — being embedded must not change
        what its text means."""
        graph, _cache, card, _source = carded
        graph.set_param(card.id, "text", "![[a]] and ![[Sales]]")
        html = html_of("![[Summary]]", env)
        assert "48,250" in html     # ![[a]] — the card's own wired input
        assert "North" in html      # ![[Sales]] — by label, now permitted

    def test_a_card_input_still_beats_a_page_node_of_the_same_name(
            self, carded, env, registry):
        """The priority rule, checked from inside a page embed too: a name
        that is one of the card's inputs resolves as that input even when a
        node on the canvas answers to it."""
        graph, cache, card, _source = carded
        twin = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(twin.id, "a")
        cache.set(twin.id, {"value": 999}, 0.0)
        graph.set_param(card.id, "text", "![[a]]")
        html = html_of("![[Summary]]", env)
        assert "48,250" in html and "999" not in html

    def test_text_after_the_embed_resolves_against_the_page_again(
            self, carded, env):
        """The lookup swap has to be put back, or everything following an
        embedded card would resolve against that card's inputs."""
        graph, _cache, card, _source = carded
        graph.set_param(card.id, "text", "![[a]]")
        html = html_of("![[Summary]]\n\nAnd ![[Total]].", env)
        assert "48,250" in html and "3,500" in html

    def test_a_card_wired_into_a_card_renders_its_contents(self, carded, env,
                                                           registry):
        """One level in: `![[b]]` on a card, where b is fed by another report
        card, shows that card's contents rather than its source."""
        from flograph.ui.report.render import render_card
        graph, cache, card, source = carded
        inner = graph.add_node(registry.instantiate("flograph.viz.report_card"))
        graph.set_param(inner.id, "text", "inner says ![[a]]")
        graph.connect(source.id, "value", inner.id, "a")
        graph.connect(inner.id, "text", card.id, "b")
        html = render_card("![[b]]", graph, cache, card.id).document.toHtml()
        assert "inner says" in html and "48,250" in html

    def test_nesting_stops_at_a_sane_depth(self, env, registry):
        """Wires are acyclic so this can't run away, but a single ![[...]]
        should still have a bound on how much it can pull in."""
        from flograph.ui.report.render import _Resolver, render_card
        graph, cache = env
        cards = [graph.add_node(registry.instantiate("flograph.viz.report_card"))
                 for _ in range(_Resolver.MAX_DEPTH + 2)]
        for outer, inner in zip(cards, cards[1:]):
            graph.connect(inner.id, "text", outer.id, "a")
            graph.set_param(outer.id, "text", "![[a]]")
        graph.set_param(cards[-1].id, "text", "the bottom")
        rendered = render_card("![[a]]", graph, cache, cards[0].id)
        assert any("nests reports" in p for p in rendered.problems)

    def test_a_plain_string_node_is_still_inlined_as_before(self, env):
        """Only report *cards* nest. An ordinary node returning markdown is
        inlined verbatim — it has no inputs to resolve embeds against."""
        assert "Findings</" in html_of("![[Findings]]", env)

    def test_two_cards_of_the_same_name_still_complain(self, carded, env,
                                                       registry):
        graph, _cache, _card, _source = carded
        twin = graph.add_node(registry.instantiate("flograph.viz.report_card"))
        graph.set_label(twin.id, "Summary")
        assert "2 nodes are called" in html_of("![[Summary]]", env)


class TestWhenAnEmbedFails:
    """A report is handed to other people — an embed that resolved to
    nothing has to be visible, not a gap."""

    def test_an_unknown_node_is_called_out_on_the_page(self, env):
        graph, cache = env
        rendered = render_report("![[Nope]]", graph, cache)
        assert "No node called" in rendered.document.toHtml()
        assert rendered.problems == ["no node called “Nope”"]

    def test_a_node_that_has_not_run_is_called_out(self, env):
        graph, cache = env
        rendered = render_report("![[Never Run]]", graph, cache)
        assert "hasn’t run yet" in rendered.document.toHtml()
        assert rendered.problems == ["“Never Run” hasn’t run"]

    def test_a_missing_port_is_called_out(self, env):
        graph, cache = env
        assert render_report("![[Sales|nope]]", graph, cache).problems

    def test_a_healthy_report_reports_no_problems(self, env):
        graph, cache = env
        assert render_report("![[Sales]] ![[Total]]", graph, cache).problems == []


class TestThePageModel:

    def test_a_page_is_a_dashboard_unless_it_says_otherwise(self):
        assert Page(id="p").kind == "dashboard"

    def test_kind_and_body_round_trip(self, registry):
        graph = Graph()
        graph.add_page(Page(id="p1", title="Q3", kind="report",
                            body="# Q3\n\n![[Sales]]\n"))
        data = json.loads(json.dumps(graph_to_dict(graph)))
        page = graph_from_dict(data, registry).pages["p1"]
        assert page.kind == "report"
        assert page.body == "# Q3\n\n![[Sales]]\n"

    def test_a_file_written_before_reports_loads_as_a_dashboard(self, registry):
        graph = Graph()
        graph.add_page(Page(id="p1", title="Board"))
        data = json.loads(json.dumps(graph_to_dict(graph)))
        del data["graph"]["pages"][0]["kind"]
        del data["graph"]["pages"][0]["body"]
        page = graph_from_dict(data, registry).pages["p1"]
        assert page.kind == "dashboard" and page.body == ""

    def test_setting_the_body_announces_itself(self):
        graph = Graph()
        graph.add_page(Page(id="p1", kind="report"))
        seen = []
        graph.events.page_body_changed.connect(lambda p: seen.append(p.body))
        graph.set_page_body("p1", "hello")
        assert seen == ["hello"]

    def test_typing_merges_into_one_undo_step(self):
        from flograph.ui.commands import SetPageBodyCommand
        graph = Graph()
        graph.add_page(Page(id="p1", kind="report", body="a"))
        stack = QUndoStack()
        for text in ("ab", "abc", "abcd"):
            stack.push(SetPageBodyCommand(graph, "p1", text))
        assert stack.count() == 1
        stack.undo()
        assert graph.pages["p1"].body == "a"

    def test_duplicating_a_report_page_copies_its_body(self):
        from flograph.ui.commands import DuplicatePageCommand
        graph = Graph()
        graph.add_page(Page(id="p1", kind="report", body="# hi"))
        QUndoStack().push(DuplicatePageCommand(graph, "p1"))
        copy = next(p for p in graph.pages.values() if p.id != "p1")
        assert copy.kind == "report" and copy.body == "# hi"


class TestTheWidget:

    @pytest.fixture
    def env(self, qtbot, registry, tmp_path):
        from flograph.engine import ExecutionEngine
        from flograph.ui.report import ReportPage
        graph = Graph()
        graph.add_page(Page(id="p1", title="Q3", kind="report"))
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, "Total")
        engine = ExecutionEngine(graph)
        engine.cache.set(node.id, {"value": 42}, 0.0)
        stack = QUndoStack()
        page = ReportPage(graph, engine, stack, "p1")
        qtbot.addWidget(page)
        yield page, graph, stack, tmp_path
        page.dispose()

    def test_typing_reaches_the_model(self, env):
        page, graph, _stack, _tmp = env
        page.editor.setPlainText("# Hello")
        assert graph.pages["p1"].body == "# Hello"

    def test_undo_puts_the_text_back_in_the_editor(self, env):
        page, graph, stack, _tmp = env
        page.editor.setPlainText("# Hello")
        stack.undo()
        assert graph.pages["p1"].body == ""
        assert page.editor.toPlainText() == ""

    def test_the_preview_renders_the_body(self, env):
        page, _graph, _stack, _tmp = env
        page.editor.setPlainText("Answer: ![[Total]]")
        page.refresh_preview()
        assert "42" in page.preview.document().toHtml()

    def test_problems_are_shown_beside_the_toolbar(self, env):
        page, _graph, _stack, _tmp = env
        page.editor.setPlainText("![[Ghost]]")
        page.refresh_preview()
        assert page.problems and "⚠" in page._status.text()

    def test_only_nodes_with_output_are_offered(self, env):
        page, graph, _stack, _tmp = env
        from flograph.core import NodeRegistry
        reg = NodeRegistry(); reg.load_builtins()
        graph.set_label(
            graph.add_node(reg.instantiate("flograph.util.constant")).id,
            "Not Run Yet")
        assert [n.label for n in page.embeddable_nodes()] == ["Total"]

    def test_insert_embed_puts_it_on_its_own_line(self, env):
        page, _graph, _stack, _tmp = env
        page.editor.setPlainText("Intro text.")
        cursor = page.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        page.editor.setTextCursor(cursor)
        page.insert_embed("Total")
        assert page.editor.toPlainText() == "Intro text.\n\n![[Total]]\n"

    def test_exporting_writes_a_pdf(self, env):
        from flograph.ui.report import export_pdf
        page, _graph, _stack, tmp_path = env
        page.editor.setPlainText("# Q3\n\nTotal was ![[Total]].\n")
        target = tmp_path / "report.pdf"
        export_pdf(page.rendered().document, str(target), title="Q3")
        assert target.exists() and target.stat().st_size > 1000
        assert target.read_bytes()[:5] == b"%PDF-"

    def test_the_pdf_matches_the_preview(self, env):
        """One document backs both, which is the whole reason to render
        into a QTextDocument rather than print a second time."""
        page, _graph, _stack, _tmp = env
        page.editor.setPlainText("# Q3\n\n![[Total]]\n")
        page.refresh_preview()
        assert page.rendered().document.toPlainText() \
            == page.preview.document().toPlainText()


class TestInTheWindow:

    @pytest.fixture
    def window(self, qtbot, registry, tmp_path, monkeypatch):
        from PySide6.QtCore import QSettings
        from flograph.ui import mainwindow as mod
        monkeypatch.setattr(
            mod, "QSettings",
            lambda *a, **k: QSettings(str(tmp_path / "s.ini"),
                                      QSettings.IniFormat))
        win = mod.MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def test_adding_a_report_page_builds_a_report_widget(self, window):
        from flograph.ui.report import ReportPage
        window._add_page("report")
        page_id = next(iter(window.graph.pages))
        assert window.graph.pages[page_id].kind == "report"
        assert isinstance(window._dashboard_pages[page_id], ReportPage)

    def test_it_starts_with_the_syntax_explained(self, window):
        window._add_page("report")
        page_id = next(iter(window.graph.pages))
        assert "![[" in window.graph.pages[page_id].body

    def test_report_pages_are_titled_as_reports(self, window):
        window._add_page("report")
        window._add_page("dashboard")
        titles = [p.title for p in window.graph.pages.values()]
        assert titles[0].startswith("Report") and titles[1].startswith("Page")

    def test_canvas_settings_skip_report_pages(self, window):
        """Snap, LOD, colour muting and the GPU viewport all sweep every
        page — a report has no scene or view for them to touch."""
        window._add_page("report")
        window._add_page("dashboard")
        assert len(window._canvas_pages()) == 1
        window._repaint_tinted()
        window._apply_snap_settings()
        window._apply_lod_settings()
        window._refresh_zoom_indicator()

    def test_a_report_page_cannot_be_given_tiles(self, window):
        """"Add to Page" offers dashboards only — a report embeds by name
        and holds no tiles at all."""
        from PySide6.QtWidgets import QMenu
        window._add_page("report")
        window._add_page("dashboard")
        offered = [p.title for p in window.graph.pages.values()
                   if p.kind == "dashboard"]
        assert len(offered) == 1

    def test_switching_to_a_report_page_works(self, window):
        window._add_page("report")
        page_id = next(iter(window.graph.pages))
        window._on_current_page_changed(page_id)
        assert window._canvas_stack.currentWidget() \
            is window._dashboard_pages[page_id]

    def test_removing_a_report_page_disposes_it(self, window):
        window._add_page("report")
        page_id = next(iter(window.graph.pages))
        window._on_page_removed(page_id)
        assert page_id not in window._dashboard_pages


class TestDuplicateLabels:
    """Embeds resolve by label, so two nodes with one name is a question
    with no answer — say so rather than picking whichever was made first."""

    @pytest.fixture
    def env(self, registry):
        from flograph.engine.cache import OutputCache
        graph, cache = Graph(), OutputCache()
        for _ in range(2):
            node = graph.add_node(
                registry.instantiate("flograph.util.constant"))
            graph.set_label(node.id, "Sales")
            cache.set(node.id, {"value": 1}, 0.0)
        return graph, cache

    def test_it_refuses_to_guess(self, env):
        graph, cache = env
        rendered = render_report("![[Sales]]", graph, cache)
        assert "2 nodes are called" in rendered.document.toHtml()
        assert rendered.problems == ["2 nodes are called “Sales”"]

    def test_renaming_one_fixes_it(self, env):
        graph, cache = env
        graph.set_label(list(graph.nodes)[1], "Sales North")
        assert render_report("![[Sales]]", graph, cache).problems == []

    def test_the_insert_menu_knows_which_are_ambiguous(self, qtbot, env):
        """The menu greys those out — offering an embed that could only ever
        render a warning is worse than not offering it."""
        from flograph.engine import ExecutionEngine
        from flograph.ui.report import ReportPage
        graph, _cache = env
        graph.add_page(Page(id="p1", kind="report"))
        page = ReportPage(graph, ExecutionEngine(graph), QUndoStack(), "p1")
        qtbot.addWidget(page)
        try:
            assert page.duplicate_labels() == {"sales"}
            graph.set_label(list(graph.nodes)[1], "Sales North")
            assert page.duplicate_labels() == set()
        finally:
            page.dispose()


class TestThePdfGeometry:
    """The export used to lay the document into a page measured in 300dpi
    device pixels while its fonts stayed in points, so a report came out as
    a tiny block in the corner of a correctly-sized sheet. These measure the
    produced PDF rather than trusting the call not to regress."""

    def rendered_page(self, path, zoom=1):
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QColor, QImage, QPainter
        from PySide6.QtPdf import QPdfDocument
        document = QPdfDocument()
        document.load(str(path))
        size = document.pagePointSize(0)
        raw = document.render(
            0, QSize(int(size.width() * zoom), int(size.height() * zoom)))
        # unpainted pixels come back transparent; flatten so "dark" means ink
        flat = QImage(raw.size(), QImage.Format_RGB32)
        flat.fill(QColor("white"))
        painter = QPainter(flat)
        painter.drawImage(0, 0, raw)
        painter.end()
        return document, flat

    def ink_bounds(self, image):
        left, right, top, bottom = image.width(), 0, image.height(), 0
        for y in range(image.height()):
            for x in range(image.width()):
                if image.pixelColor(x, y).lightness() < 160:
                    left, right = min(left, x), max(right, x)
                    top, bottom = min(top, y), max(bottom, y)
        return left, right, top, bottom

    @pytest.fixture
    def exported(self, registry, tmp_path):
        from flograph.ui.report import export_pdf
        graph, cache = Graph(), None
        body = ("# Heading\n\n"
                + "Body text that should run close to the full printable "
                  "width of the page. " * 6)
        rendered = render_report(body, graph, cache)
        path = tmp_path / "r.pdf"
        export_pdf(rendered.document, str(path), title="R")
        return path

    def test_the_page_is_a4(self, exported):
        document, _image = self.rendered_page(exported)
        size = document.pagePointSize(0)
        assert round(size.width()) == 595 and round(size.height()) == 842

    def test_the_margins_are_the_ones_asked_for(self, exported):
        from flograph.ui.report.export import MARGIN_MM
        _document, image = self.rendered_page(exported)
        left, right, _top, _bottom = self.ink_bounds(image)
        to_mm = 210.0 / image.width()
        assert abs(left * to_mm - MARGIN_MM) < 3
        # The right edge is ragged — even the longest line stops a word
        # short of the measure — so this only pins that the text reaches
        # roughly the right-hand margin rather than stopping mid-page.
        assert abs(210 - right * to_mm - MARGIN_MM) < 12

    def test_the_text_fills_the_page_rather_than_a_corner(self, exported):
        """The symptom of the old bug: content laid out as though the page
        were 2480pt wide, so it printed at about a fifth of the size."""
        _document, image = self.rendered_page(exported)
        left, right, top, bottom = self.ink_bounds(image)
        assert (right - left) / image.width() > 0.7
        assert (bottom - top) > 40      # more than one crushed strip

    def test_a_long_report_paginates(self, registry, tmp_path):
        from flograph.ui.report import export_pdf
        body = "\n\n".join(f"## Section {i}\n\n" + "Filler text. " * 60
                           for i in range(12))
        rendered = render_report(body, Graph(), None)
        path = tmp_path / "long.pdf"
        export_pdf(rendered.document, str(path))
        document, _image = self.rendered_page(path)
        assert document.pageCount() > 1

    def test_landscape_swaps_the_page(self, registry, tmp_path):
        from flograph.ui.report import export_pdf
        rendered = render_report("# Wide", Graph(), None)
        path = tmp_path / "wide.pdf"
        export_pdf(rendered.document, str(path), landscape=True)
        document, _image = self.rendered_page(path)
        size = document.pagePointSize(0)
        assert size.width() > size.height()

    def test_print_rendering_does_not_disturb_the_figure(self, registry):
        """Charts are rasterised denser for print by borrowing the cached
        Figure's dpi — the canvas card is showing that same object."""
        from matplotlib.figure import Figure
        from flograph.engine.cache import OutputCache
        graph, cache = Graph(), OutputCache()
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, "Chart")
        figure = Figure(figsize=(4, 2), dpi=100)
        figure.add_subplot().plot([1, 2, 3])
        cache.set(node.id, {"value": figure}, 0.0)

        render_report("![[Chart]]", graph, cache, image_scale=2.0)
        assert figure.get_dpi() == 100

    def test_printing_does_not_reflow_the_live_preview(self, registry,
                                                       tmp_path):
        from flograph.ui.report import export_pdf
        rendered = render_report("# Hi\n\nsome text", Graph(), None)
        rendered.document.setTextWidth(300)
        export_pdf(rendered.document, str(tmp_path / "x.pdf"))
        assert rendered.document.textWidth() == 300


class TestPrintResolution:
    """Charts are raster by the time they reach a PDF, so how densely they
    are rasterised is the whole of their print quality."""

    def figure(self, inches=7.0, dpi=100.0):
        from matplotlib.figure import Figure
        figure = Figure(figsize=(inches, inches * 0.5), dpi=dpi)
        figure.add_subplot().plot([1, 2, 3])
        return figure

    def test_print_scale_targets_a_dpi_not_a_multiplier(self):
        """A flat 2x put a 7in figure at 198dpi however it was authored;
        aiming at a DPI makes every chart come out the same on paper."""
        from flograph.ui.report.render import PRINT_DPI, print_scale
        # matplotlib's own default is 6.4in wide, so this covers the range
        # anyone actually authors in
        for inches in (6.0, 6.4, 7.0, 12.0):
            figure = self.figure(inches)
            scale = print_scale(figure, 510)
            landed = inches * 100 * scale / 510 * 72
            assert abs(landed - PRINT_DPI) < 1

    def test_only_unusually_small_figures_fall_short_of_the_target(self):
        """Below about 5.3in at 100dpi the cap bites before 300dpi does.
        Worth knowing where that line is rather than discovering it in a
        printout."""
        from flograph.ui.report.render import PRINT_DPI, print_scale
        assert print_scale(self.figure(5.4), 510) < 4.0        # reaches it
        landed = 4.0 * 100 * print_scale(self.figure(4.0), 510) / 510 * 72
        assert 200 < landed < PRINT_DPI                        # capped, still fine

    def test_it_never_downscales(self):
        """A figure already denser than the target is left alone rather
        than thrown away."""
        from flograph.ui.report.render import print_scale
        assert print_scale(self.figure(7.0, dpi=600), 510) == 1.0

    def test_the_upscale_is_capped(self):
        """The cost is quadratic and a stack can hold forty charts."""
        from flograph.ui.report.render import MAX_IMAGE_SCALE, print_scale
        assert print_scale(self.figure(0.2), 510) == MAX_IMAGE_SCALE

    def test_a_junk_value_does_not_break_the_render(self):
        from flograph.ui.report.render import print_scale
        assert print_scale(object(), 510) == 1.0

    def test_printing_rasterises_denser_than_the_preview(self, registry):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QTextDocument
        from flograph.engine.cache import OutputCache
        from flograph.ui.report.render import PRINT_DPI

        graph, cache = Graph(), OutputCache()
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, "Chart")
        cache.set(node.id, {"value": self.figure()}, 0.0)

        def width_of(scale):
            document = render_report("![[Chart]]", graph, cache,
                                     image_scale=scale).document
            return document.resource(QTextDocument.ImageResource,
                                     QUrl("embed:0")).width()

        preview, printed = width_of(1.0), width_of(2.0)
        assert preview == 700                      # the figure's own pixels
        assert abs(printed / 510 * 72 - PRINT_DPI) < 2
