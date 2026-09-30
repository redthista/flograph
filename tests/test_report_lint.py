"""Linting a report page's Markdown and CSS (core/report_lint.py), and the
problems bar under the editor that shows what is wrong (problems_bar.py).

The lint must be right before it is anything else: a mark on good text is
one people learn to ignore. So the starter themes and the example reports
are held to linting clean.
"""
import json
from pathlib import Path

import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph
from flograph.core.graph import Page
from flograph.core.report_lint import lint_css, lint_report

ROOT = Path(__file__).resolve().parents[1]


def lines(found):
    return {(d.line, d.severity) for d in found}


def messages(found):
    return " | ".join(d.message for d in found)


class TestMarkdown:
    LABELS = {"Sales": ("table", "filtered"), "Chart": None}

    def test_an_embed_that_names_no_node(self):
        found = lint_report("x\n![[Nope]]\n", self.LABELS)
        assert lines(found) == {(2, "error")}
        assert "“Nope”" in messages(found)

    def test_a_port_the_node_does_not_have(self):
        found = lint_report("![[Sales|nport]]", self.LABELS)
        assert "no port “nport”" in messages(found)
        # ports not known: nothing to check against
        assert lint_report("![[Chart|anything]]", self.LABELS) == []

    def test_an_option_nothing_reads(self):
        found = lint_report("![[Sales|table|widht=50%]]", self.LABELS)
        assert lines(found) == {(1, "warning")}

    def test_without_labels_the_names_are_not_checked(self):
        assert lint_report("![[Anything]]") == []

    def test_an_example_in_backticks_is_left_alone(self):
        assert lint_report("Write `![[Nope]]` to embed.", self.LABELS) == []

    def test_an_embed_left_open(self):
        found = lint_report("see ![[Sales and more", self.LABELS)
        assert "no ]]" in messages(found)

    def test_blocks(self):
        text = ("::: details Open\n"          # 1: never closed
                "::: warning Hi\n"            # 2: not a kind
                "== Stray\n"                  # 3: not in tabs
                "::: tabs\n"                  # 4: no tabs
                ":::\n")
        found = lint_report(text)
        assert lines(found) == {(1, "error"), (2, "warning"),
                                (3, "warning"), (4, "warning")}
        assert "never closed" in messages(found)

    def test_a_stray_close(self):
        assert lines(lint_report("text\n:::\n")) == {(2, "warning")}

    def test_code_and_columns(self):
        found = lint_report("```python\n::: nonsense\n")
        assert lines(found) == {(1, "error")}          # the fence, open
        found = lint_report("```columns\nonly one\n```\n")
        assert lines(found) == {(1, "warning")}

    def test_page_links(self):
        found = lint_report("[a](page:Costs) [b](page:Nowhere)",
                            pages=["Costs"])
        assert "“Nowhere”" in messages(found) and "Costs”" not in messages(found)

    def test_front_matter(self):
        text = "---\ntitle: X\nsidebr: open\npages: sometimes\n---\n# Hi"
        found = lint_report(text)
        assert lines(found) == {(3, "warning"), (4, "warning")}

    def test_the_example_reports_lint_clean(self):
        data = json.loads((ROOT / "notes/flows/live_report_demo.flograph")
                          .read_text(encoding="utf-8"))
        titles = [p["title"] for p in data["graph"]["pages"]]
        for page in data["graph"]["pages"]:
            if page.get("kind") == "report":
                assert lint_report(page["body"], pages=titles) == [], page["title"]


class TestCss:
    def test_structure(self):
        css = ("body {\n"
               "  color red;\n"                 # 2: no colon
               "  background: blue\n"           # 3: no semicolon
               "  margin: 0;\n"
               "  content: \"open\n"            # 5: string never closed
               "}\n"
               "}\n"                            # 7: closes nothing
               "a { color: red;\n"              # 8: never closed
               "/* never closed\n")             # 9
        found = lint_css(css)
        assert lines(found) == {(2, "error"), (3, "error"), (5, "error"),
                                (7, "error"), (8, "error"), (9, "error")}

    def test_anything_that_would_reach_the_internet(self):
        css = ('@import url("https://fonts.googleapis.com/css");\n'
               "b { background: url(//cdn.example/x.png); }\n"
               "/* url(https://in-a-comment) */\n"
               "c { background: url(data:image/png;base64,AAAA); }\n")
        found = lint_css(css)
        assert lines(found) == {(1, "warning"), (2, "warning")}

    def test_values_over_several_lines_are_fine(self):
        css = ("body {\n  background:\n    radial-gradient(a),\n"
               "    var(--sky) !important;\n"
               "  background: var(--band) no-repeat 10px 50% /\n"
               "    13px url(\"x\");\n  margin: 0\n}\n")
        assert lint_css(css) == []

    def test_every_starter_theme_lints_clean(self):
        from flograph.ui.report.html import CSS_TEMPLATES
        from flograph.ui.report.live import LIVE_CSS
        from flograph.ui.report.web_layout import LAYOUT_CSS
        for name, css in [*CSS_TEMPLATES.items(), ("live", LIVE_CSS),
                          ("layout", LAYOUT_CSS)]:
            assert lint_css(css) == [], name


class TestTheProblemsBar:
    @pytest.fixture
    def page(self, qtbot, registry):
        from flograph.engine import ExecutionEngine
        from flograph.ui.report import ReportPage
        graph = Graph()
        graph.add_page(Page(id="p1", title="Q3", kind="report",
                            preview_mode="web"))
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, "Total")
        stack = QUndoStack()
        widget = ReportPage(graph, ExecutionEngine(graph), stack, "p1")
        qtbot.addWidget(widget)
        yield widget
        widget.dispose()

    @pytest.fixture(scope="class")
    def registry(self):
        from flograph.core import NodeRegistry
        reg = NodeRegistry()
        reg.load_builtins()
        return reg

    def test_a_clean_page_shows_no_bar(self, page):
        page.editor.setPlainText("# Fine\n\n![[Total]]")
        page.run_lint()
        assert page.problem_list() == []
        assert page._problems_bar.isHidden()

    def test_problems_are_one_row_that_opens_into_a_list(self, page):
        page.editor.setPlainText("# T\n\n![[Nope]]\n\n::: details Open")
        page.css_editor.setPlainText("body { color red; }")
        page.run_lint()
        found = page.problem_list()
        assert {(p.source, p.line) for p in found} == {
            ("markdown", 3), ("markdown", 5), ("css", 1)}
        bar = page._problems_bar
        assert not bar.isHidden() and not bar.is_open()
        assert "3 errors" in bar._row.text()
        bar.toggle()
        assert bar.is_open()
        # the editors are marked where the problems are
        assert len(page.editor.extraSelections()) == 2
        assert len(page.css_editor.extraSelections()) == 1

    def test_clicking_a_problem_goes_to_its_line(self, page):
        page.editor.setPlainText("a\nb\nc\n![[Nope]]")
        page.css_editor.setPlainText("x {\n  color red;\n}")
        page.run_lint()
        page._jump_to("markdown", 4)
        assert page.editor.textCursor().blockNumber() == 3
        page._jump_to("css", 2)
        assert page._editor_tabs.currentIndex() == 1
        assert page.css_editor.textCursor().blockNumber() == 1

    def test_the_css_is_not_linted_on_pages(self, page):
        page._set_preview_mode("pages")
        page.css_editor.setPlainText("body { color red; }")
        page.run_lint()
        assert page.problem_list() == []

    def test_a_render_problem_finds_its_line(self, page):
        page.editor.setPlainText("# T\n\n![[Total]]")
        page.problems = ["“Total” hasn’t run"]
        page.run_lint()
        (found,) = page.problem_list()
        assert (found.source, found.line) == ("preview", 3)

    def test_a_render_problem_the_lint_already_marked_is_not_said_twice(self, page):
        page.editor.setPlainText("![[Nope]]")
        page.problems = ["no node called “Nope”"]
        page.run_lint()
        assert len(page.problem_list()) == 1
