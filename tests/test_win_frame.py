"""The Windows-Snap shim (ui/win_frame.py).

The real work happens inside the Win32 message loop, which no CI platform
here can drive — so these tests cover the parts that are plain Python: the
platform guard, the lParam coordinate unpacking, and the hit-test mapping
of a point to a resize / caption / client code.
"""
import sys

import pytest

from flograph.ui import win_frame


def test_enable_is_a_noop_off_windows():
    if sys.platform == "win32":
        pytest.skip("this asserts the non-Windows path")
    assert win_frame.enable_windows_snap(object(), object()) is None


@pytest.mark.parametrize("packed, x, y", [
    (0x00000000, 0, 0),
    (0x0001000A, 10, 1),
    (0xFFFFFFFB, -5, -1),          # both words negative
    ((100 << 16) | (0xFFF6 & 0xFFFF), -10, 100),
])
def test_lparam_unpacks_to_signed_screen_coords(packed, x, y):
    assert win_frame._loword_signed(packed) == x
    assert win_frame._loword_signed(packed >> 16) == y


class _FakeRect:
    def __init__(self, w, h):
        self._w, self._h = w, h

    def contains(self, pt):
        return 0 <= pt.x() < self._w and 0 <= pt.y() < self._h


class _FakeBar:
    """Stands in for the TitleBar: a 34px-tall strip with no child at the
    probed point (so the bare strip is draggable)."""

    def mapFromGlobal(self, pt):
        return pt

    def rect(self):
        return _FakeRect(800, 34)

    def childAt(self, _pt):
        return None


class _FakeWindow:
    def __init__(self, w=800, h=600):
        self._w, self._h = w, h

    def mapFromGlobal(self, pt):
        return pt

    def width(self):
        return self._w

    def height(self):
        return self._h

    def isVisible(self):
        return True


def _frame(monkeypatch, maximized=False):
    frame = win_frame._SnapFrame.__new__(win_frame._SnapFrame)
    frame._window = _FakeWindow()
    frame._title_bar = _FakeBar()
    frame._margin = 6
    monkeypatch.setattr(frame, "_is_maximized", lambda: maximized)
    return frame


def _pack(x, y):
    return (y & 0xFFFF) << 16 | (x & 0xFFFF)


def test_hit_test_reports_resize_edges_and_corners(monkeypatch):
    frame = _frame(monkeypatch)
    assert frame._on_nchittest(_pack(2, 2)) == win_frame._HTTOPLEFT
    assert frame._on_nchittest(_pack(798, 2)) == win_frame._HTTOPRIGHT
    assert frame._on_nchittest(_pack(2, 598)) == win_frame._HTBOTTOMLEFT
    assert frame._on_nchittest(_pack(798, 598)) == win_frame._HTBOTTOMRIGHT
    assert frame._on_nchittest(_pack(1, 300)) == win_frame._HTLEFT
    assert frame._on_nchittest(_pack(799, 300)) == win_frame._HTRIGHT
    assert frame._on_nchittest(_pack(400, 1)) == win_frame._HTTOP
    assert frame._on_nchittest(_pack(400, 599)) == win_frame._HTBOTTOM


def test_hit_test_reports_caption_over_the_bar_and_client_below(monkeypatch):
    frame = _frame(monkeypatch)
    assert frame._on_nchittest(_pack(400, 15)) == win_frame._HTCAPTION
    assert frame._on_nchittest(_pack(400, 300)) == win_frame._HTCLIENT


def test_hit_test_has_no_resize_border_when_maximized(monkeypatch):
    frame = _frame(monkeypatch, maximized=True)
    assert frame._on_nchittest(_pack(2, 2)) == win_frame._HTCAPTION
    assert frame._on_nchittest(_pack(1, 300)) == win_frame._HTCLIENT


def test_hit_test_ignores_points_outside_the_window(monkeypatch):
    frame = _frame(monkeypatch)
    assert frame._on_nchittest(_pack(5000, 5000)) is None


def test_caption_yields_to_a_child_widget(monkeypatch):
    frame = _frame(monkeypatch)
    frame._title_bar.childAt = lambda _pt: object()
    assert frame._on_nchittest(_pack(400, 15)) == win_frame._HTCLIENT
