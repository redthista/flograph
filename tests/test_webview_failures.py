"""A webview that fails says so.

Chromium fails quietly. A page that will not load and a page whose renderer
process is killed both leave the card a blank white rectangle, which looks
exactly like a node that produced an empty chart — so neither the user nor
anyone reading a bug report can tell which happened. These pin the two
messages, and the one reload a dead renderer is given before the view gives
up on it.
"""
import pytest
from PySide6.QtWidgets import QWidget

from flograph.ui.inspector.plotly_view import (
    LOAD_FAILED, RENDERER_GONE, RUN_PROMPT, PlotlyView, termination_reason,
)

PAGE = "<html><body><p>hello</p></body></html>"


class FakeView(QWidget):
    """Stands in for the QWebEngineView: building a real one starts
    Chromium, which is far too much for asking what the label says."""

    def __init__(self):
        super().__init__()
        self.loaded = []

    def load(self, url):
        self.loaded.append(url.toLocalFile())


@pytest.fixture
def view(qtbot, monkeypatch):
    plot = PlotlyView()
    qtbot.addWidget(plot)
    fake = FakeView()
    qtbot.addWidget(fake)

    def ensure():
        # the real one sets .view as well as returning it, and _reload
        # leans on exactly that
        plot.view = fake
        return fake

    monkeypatch.setattr(plot, "_ensure_view", ensure)
    plot.view = fake
    return plot


class TestTheReason:
    @pytest.mark.parametrize("status,words", [
        (0, "exited normally"),
        (1, "exited abnormally"),
        (2, "crashed"),
        (3, "was killed"),
    ])
    def test_each_status_is_put_into_words(self, status, words):
        assert words in termination_reason(status, 9)

    def test_the_exit_code_is_carried(self):
        assert "exit code 133" in termination_reason(2, 133)

    def test_a_status_qt_grows_later_still_reads(self):
        assert "the renderer stopped" in termination_reason(77, 0)


class TestAPageThatWillNotLoad:
    def test_the_card_says_so(self, view):
        view._on_load_finished(False)
        assert view.placeholder.text() == LOAD_FAILED

    def test_the_blank_webview_is_taken_off_the_card(self, view):
        view.view.show()
        view._on_load_finished(False)
        assert view.view.isHidden()

    def test_a_load_that_worked_says_nothing(self, view):
        view.placeholder.setText(LOAD_FAILED)
        view._on_load_finished(True)
        assert view.placeholder.isHidden()


class TestARendererThatDied:
    def test_it_is_reloaded_once(self, view):
        view.set_content(PAGE)
        before = list(view.view.loaded)
        view._on_renderer_gone(2, 5)
        assert view.view.loaded == before + before[-1:]

    def test_the_second_death_is_reported_instead(self, view):
        view.set_content(PAGE)
        view._on_renderer_gone(2, 5)
        view._on_renderer_gone(2, 5)
        assert view.placeholder.text() == RENDERER_GONE.format(
            why=termination_reason(2, 5))

    def test_the_second_death_stops_reloading(self, view):
        view.set_content(PAGE)
        view._on_renderer_gone(2, 5)
        loaded = list(view.view.loaded)
        view._on_renderer_gone(2, 5)
        assert view.view.loaded == loaded

    def test_nothing_loaded_yet_is_reported_not_retried(self, view):
        view._on_renderer_gone(3, 0)
        assert view.placeholder.text().startswith("Qt WebEngine gave up")
        assert view.view.loaded == []

    def test_new_content_gets_its_own_second_chance(self, view):
        view.set_content(PAGE)
        view._on_renderer_gone(2, 5)
        view.set_content(PAGE + "<!-- again -->")
        assert view._retried is False
        loaded = list(view.view.loaded)
        view._on_renderer_gone(2, 5)
        assert len(view.view.loaded) == len(loaded) + 1


class TestWhatWasThereBefore:
    def test_content_of_none_still_clears_back_to_the_prompt(self, view):
        view.set_content(PAGE)
        view.set_content(None)
        assert view.placeholder.text() == RUN_PROMPT
        assert view.view is None

    def test_and_forgets_the_page_it_had(self, view):
        view.set_content(PAGE)
        view.set_content(None)
        assert view._path is None
