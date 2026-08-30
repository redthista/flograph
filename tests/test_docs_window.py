"""The documentation window: the nav tree, navigation, history, breadcrumb,
and that Help ▸ Documentation reuses one instance. Runs on a bare DocsWindow
— never a shown MainWindow (see the teardown-crash note in the testing
memory)."""
import pytest
from PySide6.QtCore import Qt, QUrl

from flograph.core import NodeRegistry
from flograph.ui.docs import DocsWindow
from flograph.ui.wiki import browser as browser_mod


@pytest.fixture
def win(qtbot):
    w = DocsWindow()
    qtbot.addWidget(w)
    return w


@pytest.fixture
def view(win):
    return win.view


class TestNavigation:
    def test_opens_on_home(self, view):
        assert view.browser.current_slug() == "home"
        assert "flograph" in view.browser.toPlainText()

    def test_nav_tree_has_sections_and_reaches_every_page(self, view):
        from flograph.core.docpages import catalog

        titles, slugs = [], set()

        def walk(item):
            for i in range(item.childCount()):
                child = item.child(i)
                titles.append(child.text(0))
                s = child.data(0, Qt.UserRole)
                if s:
                    slugs.add(s)
                walk(child)

        walk(view.nav.invisibleRootItem())
        assert "Basics" in titles  # a section header from _Sidebar.md
        assert slugs == set(catalog())

    def test_clicking_a_nav_item_navigates(self, view):
        view.nav.setCurrentItem(view._slug_items["running-headless"])
        assert view.browser.current_slug() == "running-headless"

    def test_nav_selection_follows_a_wikilink(self, view):
        view.browser._on_anchor(QUrl("the-canvas.md"))
        assert view.nav.currentItem() is view._slug_items["the-canvas"]

    def test_breadcrumb_shows_the_trail(self, view):
        view.browser.show_page("the-canvas")
        html = view._crumb.text()
        assert "Basics" in html and "The Canvas" in html

    def test_following_a_wikilink_navigates_and_records_history(self, view):
        view.browser._on_anchor(QUrl("the-canvas.md"))
        assert view.browser.current_slug() == "the-canvas"
        assert view.browser.can_go_back() and not view.browser.can_go_forward()

        view.browser.go_back()
        assert view.browser.current_slug() == "home"
        assert view.browser.can_go_forward()

        view.browser.go_forward()
        assert view.browser.current_slug() == "the-canvas"

    def test_nav_toggle_hides_and_shows_the_tree(self, view):
        assert view.nav_visible()
        view.set_nav_visible(False)
        assert not view.nav_visible()
        view._nav_toggle.setChecked(True)
        assert view.nav_visible()

    def test_toolbar_buttons_track_history(self, view):
        assert not view._back.isEnabled() and not view._forward.isEnabled()
        view.browser.show_page("getting-started")
        assert view._back.isEnabled()

    def test_page_changed_signal_fires_on_a_new_destination(self, view, qtbot):
        with qtbot.waitSignal(view.page_changed, timeout=500) as sig:
            view.browser.show_page("flow-variables")
        assert sig.args == ["flow-variables"]

    def test_unknown_page_shows_a_message_not_a_crash(self, view):
        view.browser.show_page("does-not-exist")
        assert "no page called" in view.browser.toPlainText().lower()

    def test_bare_fragment_stays_on_the_page(self, view):
        view.browser.show_page("the-canvas")
        view.browser._on_anchor(QUrl("#running"))
        assert view.browser.current_slug() == "the-canvas"

    def test_external_link_opens_the_real_browser(self, view, monkeypatch):
        opened = []
        monkeypatch.setattr(browser_mod.QDesktopServices, "openUrl",
                            lambda url: opened.append(url.toString()))
        before = view.browser.current_slug()
        view.browser._on_anchor(QUrl("https://github.com/redthista/flograph"))
        assert opened == ["https://github.com/redthista/flograph"]
        assert view.browser.current_slug() == before


class TestRendering:
    """Every page goes Markdown → toHtml → fix-ups → setHtml, so a fenced
    code block is shaded and indented and a heading carries an anchor."""

    def test_a_fenced_code_block_keeps_its_indentation(self, view):
        view.browser.show_page("writing-a-node")
        text = view.browser.toPlainText()
        # the Anatomy sample is indented Python — the leading spaces survive
        assert "\n    ctx.log(" in text

    def test_a_code_block_is_monospaced(self, view):
        view.browser.show_page("flow-variables")
        assert "monospace" in view.browser.document().toHtml()

    def test_headings_get_an_anchor_for_in_page_links(self, view):
        view.browser.show_page("the-canvas")
        html = view.browser.document().toHtml()
        assert '<a name="order-edges">' in html

    def test_following_a_heading_link_stays_on_the_page(self, view):
        view.browser.show_page("the-canvas")
        view.browser._on_anchor(QUrl("the-canvas.md#order-edges"))
        assert view.browser.current_slug() == "the-canvas"


class TestHelpMenuWiring:
    def test_documentation_action_reuses_one_window(self, qtbot, monkeypatch):
        # a constructed-but-never-shown MainWindow is the pattern test_templates
        # uses; stub the window's show so nothing actually appears on screen.
        monkeypatch.setattr(DocsWindow, "show", lambda self: None)
        monkeypatch.setattr(DocsWindow, "raise_", lambda self: None)
        monkeypatch.setattr(DocsWindow, "activateWindow", lambda self: None)

        from flograph.ui.mainwindow import MainWindow
        reg = NodeRegistry()
        reg.load_builtins()
        window = MainWindow(reg)
        window.confirm_close = False
        qtbot.addWidget(window)

        assert window._docs_window is None
        window._show_docs()
        first = window._docs_window
        assert isinstance(first, DocsWindow)
        window._show_docs()
        assert window._docs_window is first

        assert window.action_docs.shortcut().toString() == "F1"
