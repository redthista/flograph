"""Idea #21: hand a webview node's page to the user's real browser.

The rule under test throughout: the browser gets *the same HTML the card is
showing*, because both go through flograph.core.html.to_html. A second
renderer that merely looked similar would drift, and the drift would only
show up in whatever the user was about to print.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMenu

from flograph.core import NodeRegistry, Page, Tile
from flograph.core.html import titled, to_html
from flograph.ui import browser
from flograph.ui import mainwindow as mw
from flograph.ui.commands import AddPageCommand, AddTileCommand
from flograph.ui.mainwindow import MainWindow

PAGE = "<html><head></head><body><p>hello</p></body></html>"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


@pytest.fixture
def opened(monkeypatch):
    """Collect the URLs handed to the desktop instead of launching a real
    browser — which, on a developer's machine, this test otherwise would."""
    urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        lambda url: urls.append(url) or True)
    return urls


@pytest.fixture
def tmp_pages(tmp_path, monkeypatch):
    """Keep the written pages in the test's own tmp_path."""
    monkeypatch.setattr(browser, "_tmp_dir", lambda: tmp_path)
    return tmp_path


def add_web_node(window, label="Sales Map", html=PAGE, run=True):
    node = window.registry.instantiate("flograph.viz.show_web", pos=(0, 0))
    # Canvas preview off: rendering the card builds a real QWebEngineView,
    # and a Chromium profile per test crashes the run on teardown. Nothing
    # here is about the card — the browser path reads the cache directly.
    node.canvas_preview_enabled = False
    window.graph.add_node(node)
    if label:
        window.graph.set_label(node.id, label)
    if run:
        window.engine.cache.set(node.id, {"view": html}, 0.01)
    return node


def pick(monkeypatch, module, text):
    """Choose a context-menu entry without popping the menu — see
    test_project_lifecycle._pick_menu_action for why a subclass is needed
    rather than patching QMenu.exec."""
    class _Picker(QMenu):
        def exec(self, *args):
            return next((a for a in self.actions() if a.text() == text), None)

    monkeypatch.setattr(module, "QMenu", _Picker)


def menu_texts(monkeypatch, module):
    seen = []

    class _Recorder(QMenu):
        def exec(self, *args):
            seen.extend(a.text() for a in self.actions())
            return None

    monkeypatch.setattr(module, "QMenu", _Recorder)
    return seen


# --------------------------------------------------------------- core.html

class TestTitled:
    def test_a_page_gets_the_node_name_in_the_tab(self):
        assert "<title>Sales Map</title>" in titled(PAGE, "Sales Map")

    def test_a_library_that_titled_its_own_page_wins(self):
        page = "<html><head><title>Plotly</title></head><body></body></html>"
        assert titled(page, "Sales Map") == page

    def test_a_document_with_no_head_is_left_alone(self):
        assert titled("<p>bare</p>", "Sales Map") == "<p>bare</p>"

    def test_a_title_in_the_body_is_not_the_page_title(self):
        """Plotly's modebar ships an inline SVG <title>plotly-logomark</title>.
        Treating that as "already titled" left every Plotly page named after
        its temp file in the browser tab."""
        page = ("<html><head><meta charset='utf-8'></head><body>"
                "<svg><title>plotly-logomark</title></svg></body></html>")
        out = titled(page, "Sales Map")
        assert out.index("<title>Sales Map</title>") < out.index("</head>")
        assert "plotly-logomark" in out

    def test_an_attributed_head_tag_is_handled(self):
        page = "<html><head lang='en'><meta charset='utf-8'></head></html>"
        assert "<title>Sales Map</title>" in titled(page, "Sales Map")

    def test_a_blank_label_changes_nothing(self):
        assert titled(PAGE, "   ") == PAGE

    def test_the_label_is_escaped(self):
        out = titled(PAGE, "A & B <script>")
        assert "&amp;" in out and "<script>" not in out


class TestCoercionStillLivesInOneePlace:
    """The extraction that makes this feature honest: the view's to_html and
    core's are the same object, so the card and the browser cannot diverge."""

    def test_the_view_re_exports_core(self):
        from flograph.ui.inspector import plotly_view
        assert plotly_view.to_html is to_html

    def test_core_html_needs_no_qt(self):
        import subprocess
        import sys
        check = ("import sys, flograph.core.html;"
                 "assert not [m for m in sys.modules"
                 " if m.split('.')[0] in ('PySide6', 'pandas', 'matplotlib')]")
        result = subprocess.run([sys.executable, "-c", check],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


# ------------------------------------------------------------- ui.browser

class TestSlug:
    @pytest.mark.parametrize("label,expected", [
        ("Sales Map", "Sales-Map"),
        ("Sales / Region: 2026", "Sales-Region-2026"),
        ("  spaced  out  ", "spaced-out"),
        ("../../etc/passwd", "etcpasswd"),
        ("", "view"),
        ("!!!", "view"),
    ])
    def test_labels_become_safe_filenames(self, label, expected):
        assert browser.slug(label) == expected

    def test_a_very_long_label_is_cut(self):
        assert len(browser.slug("x" * 500)) == 60


class TestHtmlFor:
    def test_nothing_cached_means_nothing_to_open(self, window):
        node = add_web_node(window, run=False)
        assert browser.html_for(node, None) is None
        assert not browser.can_open(node, None)

    def test_the_cached_page_comes_back_titled(self, window):
        node = add_web_node(window)
        html = browser.html_for(node, window.engine.cache.get(node.id))
        assert "<p>hello</p>" in html
        assert "<title>Sales Map</title>" in html

    def test_it_reads_the_node_s_own_output_port(self, window, registry):
        """The bug class that broke Chart per Value on the canvas: a card
        kind must never assume what its node called its output port.

        A whole fork rather than a poked PortSpec — the registry hands out
        one shared spec per type, so editing it here would rename the port
        for every other test in the run."""
        from flograph.core import NodeInstance
        from flograph.core.script import parse_spec
        source = registry.get("flograph.viz.show_web").source
        node = window.graph.add_node(NodeInstance.create(
            parse_spec(source.replace('("view", "object")', '("page", "object")'),
                       "user.forked_web")))
        assert node.spec.outputs[0].name == "page"
        window.engine.cache.set(node.id, {"page": PAGE}, 0.01)
        assert browser.can_open(node, window.engine.cache.get(node.id))

    def test_a_list_output_is_laid_out_on_the_node_s_grid(self, window):
        node = add_web_node(window, run=False)
        node.params["columns"] = 2
        window.engine.cache.set(
            node.id, {"view": ["<p>a</p>", "<p>b</p>", "<p>c</p>"]}, 0.01)
        html = browser.html_for(node, window.engine.cache.get(node.id))
        assert "grid-template-columns:repeat(2" in html

    def test_an_unrenderable_output_is_not_offered(self, window):
        node = add_web_node(window, run=False)
        window.engine.cache.set(node.id, {"view": object()}, 0.01)
        assert not browser.can_open(node, window.engine.cache.get(node.id))


class TestOpening:
    def test_the_page_is_written_and_handed_to_the_desktop(
            self, window, opened, tmp_pages):
        node = add_web_node(window)
        path = browser.open_node(node, window.engine.cache.get(node.id))
        assert path is not None
        assert "<p>hello</p>" in open(path, encoding="utf-8").read()
        assert len(opened) == 1
        assert opened[0].isLocalFile()
        assert opened[0].toLocalFile() == path

    def test_the_filename_names_the_node(self, window, opened, tmp_pages):
        node = add_web_node(window, label="Sales Map")
        path = browser.open_node(node, window.engine.cache.get(node.id))
        assert "Sales-Map" in path and path.endswith(".html")

    def test_re_opening_reuses_the_path_so_a_refresh_works(
            self, window, opened, tmp_pages):
        """One tab per node, not one per run: after a re-run the browser
        window the user already has open shows the new output on F5."""
        node = add_web_node(window)
        first = browser.open_node(node, window.engine.cache.get(node.id))
        window.engine.cache.set(node.id, {"view": "<p>second</p>"}, 0.01)
        second = browser.open_node(node, window.engine.cache.get(node.id))
        assert first == second
        assert "second" in open(second, encoding="utf-8").read()
        assert len(list(tmp_pages.glob("*.html"))) == 1

    def test_two_nodes_sharing_a_label_get_their_own_pages(
            self, window, opened, tmp_pages):
        one = add_web_node(window, label="Chart")
        two = add_web_node(window, label="Chart")
        assert (browser.open_node(one, window.engine.cache.get(one.id))
                != browser.open_node(two, window.engine.cache.get(two.id)))

    def test_nothing_cached_opens_nothing(self, window, opened, tmp_pages):
        node = add_web_node(window, run=False)
        assert browser.open_node(node, None) is None
        assert opened == []


class TestRefreshingAnOpenTab:
    """Reported 2026-07-26: "when i refresh the webpage ... and change the
    data, rerun the flow, it doesnt refresh to the same as the canvas."

    A stable path is not enough on its own — something has to rewrite the
    file when the node runs again, or the tab silently shows an older chart
    than the canvas does, with nothing on screen to say so."""

    @pytest.fixture(autouse=True)
    def _clean(self):
        browser.forget_all()
        yield
        browser.forget_all()

    def rerun(self, window, node, html):
        window.engine.cache.set(node.id, {"view": html}, 0.01)
        window.engine.node_succeeded.emit(node.id)

    def test_a_re_run_rewrites_the_open_page(self, window, opened, tmp_pages):
        node = add_web_node(window)
        path = window._open_in_browser(node.id)
        self.rerun(window, node, "<p>new data</p>")
        assert "new data" in open(path, encoding="utf-8").read()

    def test_it_matches_what_the_card_would_show(self, window, opened,
                                                 tmp_pages):
        node = add_web_node(window)
        path = window._open_in_browser(node.id)
        self.rerun(window, node, "<p>new data</p>")
        expected = browser.html_for(node, window.engine.cache.get(node.id))
        assert open(path, encoding="utf-8").read() == expected

    def test_the_refresh_does_not_pop_a_second_tab(self, window, opened,
                                                   tmp_pages):
        """A re-run must never steal focus — you could be mid-edit."""
        node = add_web_node(window)
        window._open_in_browser(node.id)
        self.rerun(window, node, "<p>new data</p>")
        assert len(opened) == 1

    def test_a_node_never_opened_writes_nothing(self, window, opened,
                                                tmp_pages):
        node = add_web_node(window)
        self.rerun(window, node, "<p>new data</p>")
        assert list(tmp_pages.glob("*.html")) == []
        assert not browser.is_open(node.id)

    def test_a_run_producing_nothing_leaves_the_page_alone(self, window,
                                                           opened, tmp_pages):
        """Better a chart from the last good run than an empty tab that
        can't say whether the node broke or the refresh did."""
        node = add_web_node(window)
        path = window._open_in_browser(node.id)
        window.engine.cache.set(node.id, {"view": object()}, 0.01)
        window.engine.node_succeeded.emit(node.id)
        assert "<p>hello</p>" in open(path, encoding="utf-8").read()

    def test_another_node_running_does_not_touch_it(self, window, opened,
                                                    tmp_pages):
        node = add_web_node(window, label="Mine")
        other = add_web_node(window, label="Theirs")
        path = window._open_in_browser(node.id)
        window.engine.cache.set(other.id, {"view": "<p>theirs</p>"}, 0.01)
        window.engine.node_succeeded.emit(other.id)
        assert "<p>hello</p>" in open(path, encoding="utf-8").read()

    def test_opening_a_project_forgets_the_old_one_s_pages(self, window,
                                                           opened, tmp_pages):
        from flograph.core import Graph
        node = add_web_node(window)
        window._open_in_browser(node.id)
        window._replace_graph(Graph())
        assert not browser.is_open(node.id)

    def test_a_renamed_node_still_refreshes_the_tab_it_opened(
            self, window, opened, tmp_pages):
        """The path is fixed when the tab opens. Renaming the node afterwards
        must not start writing somewhere the browser isn't looking."""
        node = add_web_node(window)
        path = window._open_in_browser(node.id)
        window.graph.set_label(node.id, "Renamed")
        self.rerun(window, node, "<p>new data</p>")
        assert "new data" in open(path, encoding="utf-8").read()
        assert len(list(tmp_pages.glob("*.html"))) == 1


class TestStatusMessage:
    def test_it_names_the_node_and_the_file(self, window):
        node = add_web_node(window)
        message = browser.status_message(node, "/tmp/x/Sales-Map.html")
        assert "Sales Map" in message and "/tmp/x/Sales-Map.html" in message

    def test_a_dirty_node_says_the_page_is_the_last_run(self, window):
        node = add_web_node(window)
        window.graph.mark_dirty(node.id)
        assert "dirty" in browser.status_message(node, "/tmp/x.html")

    def test_a_clean_node_says_nothing_about_staleness(self, window):
        node = add_web_node(window)
        node.dirty = False
        assert "dirty" not in browser.status_message(node, "/tmp/x.html")

    def test_nothing_to_open_says_to_run_it(self, window):
        node = add_web_node(window, run=False)
        assert "run the node" in browser.status_message(node, None)


# --------------------------------------------------------- the canvas menu

class TestCanvasMenu:
    def test_offered_once_a_webview_node_has_run(self, window, monkeypatch):
        node = add_web_node(window)
        texts = menu_texts(monkeypatch, mw)
        window._show_node_menu(node.id, window.mapToGlobal(window.pos()))
        assert "Open in Browser" in texts

    def test_omitted_before_it_has_run(self, window, monkeypatch):
        node = add_web_node(window, run=False)
        texts = menu_texts(monkeypatch, mw)
        window._show_node_menu(node.id, window.mapToGlobal(window.pos()))
        assert "Open in Browser" not in texts

    def test_omitted_for_a_node_that_merely_outputs_a_string(self, window,
                                                             monkeypatch):
        """A raw string always coerces to HTML, so 'anything that coerces'
        would put this entry on half the library. Card kind is the rule."""
        node = window.registry.instantiate("flograph.util.constant", pos=(0, 0))
        window.graph.add_node(node)
        port = node.spec.outputs[0].name
        window.engine.cache.set(node.id, {port: "<p>text</p>"}, 0.01)
        assert not window._can_open_in_browser(node.id)
        texts = menu_texts(monkeypatch, mw)
        window._show_node_menu(node.id, window.mapToGlobal(window.pos()))
        assert "Open in Browser" not in texts

    def test_choosing_it_opens_the_page(self, window, monkeypatch, opened,
                                        tmp_pages):
        node = add_web_node(window)
        pick(monkeypatch, mw, "Open in Browser")
        window._show_node_menu(node.id, window.mapToGlobal(window.pos()))
        assert len(opened) == 1
        assert "Sales-Map" in opened[0].toLocalFile()

    def test_it_says_so_on_the_status_bar(self, window, opened, tmp_pages):
        node = add_web_node(window)
        window._open_in_browser(node.id)
        assert "Sales Map" in window.statusBar().currentMessage()

    def test_a_deleted_node_is_survivable(self, window, opened):
        assert window._open_in_browser("nope") is None
        assert not window._can_open_in_browser("nope")


# ------------------------------------------------------ the dashboard menu

class TestDashboardMenu:
    @pytest.fixture
    def tiled(self, window):
        """The tile goes down before anything is cached, then the cache is
        filled — a tile with content builds a real QWebEngineView, and one
        Chromium profile per test crashes the run on teardown. The menu
        only ever reads the cache, so it can't tell the difference."""
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="p1", title="Board")))
        node = add_web_node(window, run=False)
        window.undo_stack.push(AddTileCommand(
            window.graph, "p1", Tile(id="t1", node_id=node.id, port="view")))
        window.engine.cache.set(node.id, {"view": PAGE}, 0.01)
        page = window._dashboard_pages["p1"]
        return page.view, page.scene.tile_items["t1"], node

    def test_a_webview_tile_offers_it(self, tiled):
        view, item, node = tiled
        assert view._browsable_node(item) is node

    def test_a_tile_whose_node_has_not_run_does_not(self, tiled, window):
        view, item, node = tiled
        window.engine.cache.evict(node.id)
        assert view._browsable_node(item) is None

    def test_a_non_webview_tile_does_not(self, tiled, window):
        view, item, node = tiled
        table = window.registry.instantiate("flograph.viz.show_table")
        window.graph.add_node(table)
        item.tile.node_id = table.id
        assert view._browsable_node(item) is None

    def test_opening_from_a_tile_writes_the_same_page(self, tiled, window,
                                                      opened, tmp_pages):
        view, item, node = tiled
        from flograph.ui.browser import open_node_from
        path = open_node_from(view, node, window.engine.cache.get(node.id))
        assert "<p>hello</p>" in open(path, encoding="utf-8").read()
        assert len(opened) == 1
