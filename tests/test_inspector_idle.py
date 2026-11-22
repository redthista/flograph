"""With nothing selected the Inspector says what it is for and how the
last run went, from the engine's own record, instead of a blank (#122)."""
from types import SimpleNamespace

from flograph.ui.inspector.inspector_dock import idle_text


def _record(outcomes, cancelled=False):
    return SimpleNamespace(
        when=0.0, wall_time=1.24, cancelled=cancelled,
        nodes=[SimpleNamespace(outcome=o) for o in outcomes])


def test_before_any_run_it_only_says_what_to_do():
    assert idle_text(None) == "Select a node to preview its output here."


def test_a_clean_run():
    text = idle_text(_record(["ok", "ok", "ok"]))
    assert "3 nodes in 1.2 s, no errors" in text


def test_a_failed_run_points_at_the_log():
    text = idle_text(_record(["ok", "failed"]))
    assert "1 node failed" in text and "Log" in text


def test_a_cancelled_run():
    assert "stopped before it finished" in idle_text(_record(["ok"], True))
