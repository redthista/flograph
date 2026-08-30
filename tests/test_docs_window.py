"""The documentation window: navigation, history, the jump box, and that
Help ▸ Documentation reuses one instance. Runs on a bare DocsWindow — never a
shown MainWindow (see the teardown-crash note in the testing memory)."""
import pytest
from PySide6.QtCore import Qt, QUrl

from flograph.core import NodeRegistry
from flograph.ui.docs import DocsWindow
from flograph.ui.docs import browser as browser_mod


@pytest.fixture
def win(qtbot):
    w = DocsWindow()
    qtbot.addWidget(w)
    return w


class TestNavigation:
    def test_opens_on_home(self, win):
        assert win.browser.current_slug() == "home"
        assert "flograph" in win.browser.toPlainText()

    def test_nav_tree_has_sections_and_reaches_every_page(self, win):
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

        walk(win.nav.invisibleRootItem())
        assert "Basics" in titles  # a section header from _Sidebar.md
        assert slugs == set(catalog())

    def test_clicking_a_nav_item_navigates(self, win):
        item = win._slug_items["running-headless"]
        win.nav.setCurrentItem(item)
        assert win.browser.current_slug() == "running-headless"

    def test_nav_selection_follows_a_wikilink(self, win):
        win.browser._on_anchor(QUrl("the-canvas.md"))
        assert win.nav.currentItem() is win._slug_items["the-canvas"]

    def test_following_a_wikilink_navigates_and_records_history(self, win):
        win.browser._on_anchor(QUrl("the-canvas.md"))
        assert win.browser.current_slug() == "the-canvas"
        assert win.browser.can_go_back() and not win.browser.can_go_forward()

        win.browser.go_back()
        assert win.browser.current_slug() == "home"
        assert win.browser.can_go_forward()

        win.browser.go_forward()
        assert win.browser.current_slug() == "the-canvas"

    def test_home_button_returns(self, win):
        win.browser.show_page("keyboard-shortcuts")
        win._home.click()
        assert win.browser.current_slug() == "home"

    def test_toolbar_buttons_track_history(self, win):
        assert not win._back.isEnabled() and not win._forward.isEnabled()
        win.browser.show_page("getting-started")
        assert win._back.isEnabled()

    def test_unknown_page_shows_a_message_not_a_crash(self, win):
        win.browser.show_page("does-not-exist")
        assert "not found" in win.browser.toPlainText().lower()

    def test_bare_fragment_stays_on_the_page(self, win):
        win.browser.show_page("the-canvas")
        win.browser._on_anchor(QUrl("#running"))
        assert win.browser.current_slug() == "the-canvas"

    def test_external_link_opens_the_real_browser(self, win, monkeypatch):
        opened = []
        monkeypatch.setattr(browser_mod.QDesktopServices, "openUrl",
                            lambda url: opened.append(url.toString()))
        before = win.browser.current_slug()
        win.browser._on_anchor(QUrl("https://github.com/redthista/flograph"))
        assert opened == ["https://github.com/redthista/flograph"]
        assert win.browser.current_slug() == before


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
