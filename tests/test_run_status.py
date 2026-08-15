"""The status line during a run: what is running, how far in, how long it
has taken, and whether it has gone quiet.

Driven directly rather than through a real run — the interesting states are
timing-dependent and a test that sleeps its way to them is slow and flaky.
"""
import pytest

from flograph.engine.runstats import NodeRun, RunHistory, RunRecord
from flograph.ui import mainwindow as mw


class TestLastWallTime:
    def history(self, *runs):
        history = RunHistory()
        for nodes in runs:
            history.add(RunRecord(nodes=list(nodes)))
        return history

    def test_reads_the_most_recent_successful_run(self):
        history = self.history(
            [NodeRun(node_id="a", label="A", wall_time=9.0)],
            [NodeRun(node_id="a", label="A", wall_time=3.0)],
        )
        assert history.last_wall_time("a") == 3.0

    def test_ignores_a_run_that_failed_or_was_cancelled(self):
        """A node that stopped early says nothing about how long the work
        takes, so it must not become the estimate."""
        history = self.history(
            [NodeRun(node_id="a", label="A", wall_time=8.0)],
            [NodeRun(node_id="a", label="A", wall_time=0.2, outcome="cancelled")],
            [NodeRun(node_id="a", label="A", wall_time=0.1, outcome="failed")],
        )
        assert history.last_wall_time("a") == 8.0

    def test_none_when_never_run(self):
        assert RunHistory().last_wall_time("a") is None


@pytest.fixture
def win(qtbot, registry):
    window = mw.MainWindow(registry)
    window.confirm_close = False
    qtbot.addWidget(window)
    return window


def status(window, *, elapsed=0.0, quiet=0.0, fraction=0.0,
           prior=None, had_output=False, index=1, total=3):
    """Put the window in a given run state and read the line back."""
    import time
    now = time.monotonic()
    window._run_node_label = "Read Excel"
    window._run_index, window._run_total = index, total
    window._run_fraction = fraction
    window._run_prior = prior
    window._run_had_output = had_output
    window._run_node_started = now - elapsed
    window._run_last_output = now - quiet
    window._update_run_status()
    return window.status_message()


class TestRunStatusLine:
    def test_names_the_node_and_its_place_in_the_plan(self, win):
        assert status(win, index=3, total=12) == \
            "Running Read Excel  ·  node 3 of 12"

    def test_a_quick_node_gets_no_stopwatch(self, win):
        """A timer on a step that takes 200ms is noise."""
        assert "s" not in status(win, elapsed=0.3).split("node")[1]

    def test_elapsed_appears_once_it_is_worth_reading(self, win):
        assert "2.0 s" in status(win, elapsed=2.0)

    def test_prior_duration_turns_slow_into_slower_than_usual(self, win):
        assert "(usually 3.0 s)" in status(win, elapsed=2.0, prior=3.0)

    def test_fraction_shown_when_the_node_reports_one(self, win):
        assert "35%" in status(win, fraction=0.35)

    def test_silence_is_not_reported_before_the_threshold(self, win):
        line = status(win, elapsed=9.0, quiet=9.0)
        assert "Cancel" not in line

    def test_a_node_that_never_spoke_says_no_output_yet(self, win):
        line = status(win, elapsed=20.0, quiet=20.0, had_output=False)
        assert "no output yet — Cancel to stop it" in line
        # the elapsed time above already is the silence; don't say it twice
        assert line.count("20.0 s") == 1

    def test_a_node_that_fell_silent_says_how_long_for(self, win):
        line = status(win, elapsed=60.0, quiet=15.0, had_output=True)
        assert "quiet for 15.0 s — Cancel to stop it" in line


class TestRunProgressBar:
    def test_hidden_until_a_run_starts(self, win):
        assert not win._run_bar.isVisible()

    def test_it_sits_at_the_left_ahead_of_the_run_message(self, win):
        """The bar heads the run's own line at the bottom left, so it has to
        be left of the message rather than parked among the permanent
        widgets on the right."""
        assert win._run_bar.x() < win._status_label.x()
        assert win._status_label.x() < win.resource_monitor.x()

    def test_it_is_a_thin_track_not_a_full_height_control(self, win):
        """A default-height bar was the tallest thing in the status bar and
        set the height of the whole strip."""
        assert win._run_bar.height() == 6

    def test_tracks_nodes_finished_plus_the_current_fraction(self, win):
        win._run_total, win._run_index = 4, 3
        win._run_fraction = 0.5
        assert win._run_completion() == pytest.approx((2 + 0.5) / 4)

    def test_zero_before_the_first_node_claims_the_floor(self, win):
        win._run_total = win._run_index = 0
        assert win._run_completion() == 0.0

    def test_never_exceeds_one_when_a_run_overruns_its_plan(self, win):
        """_prune_downstream can shrink the plan mid-run, so the index can
        outrun the total that was recorded when it was built."""
        win._run_total, win._run_index, win._run_fraction = 2, 5, 1.0
        assert win._run_completion() == 1.0


class TestShowStatus:
    """The status line is ours now rather than QStatusBar's temporary
    message, so the parts of showMessage() that callers relied on have to
    keep working."""

    def test_an_untimed_message_stays_up(self, win, qtbot):
        win.show_status("Running…")
        qtbot.wait(30)
        assert win.status_message() == "Running…"

    def test_a_timed_message_lapses_into_a_blank_line(self, win, qtbot):
        win.show_status("Saved /tmp/x.flograph", 20)
        qtbot.waitUntil(lambda: win.status_message() == "", timeout=1000)

    def test_a_newer_message_outlives_the_last_one_countdown(self, win, qtbot):
        """The old message's timer must not blank the new message."""
        win.show_status("Saved /tmp/x.flograph", 20)
        win.show_status("Running…")
        qtbot.wait(80)
        assert win.status_message() == "Running…"
