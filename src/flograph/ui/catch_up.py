"""Refreshes put off while nobody could see them, caught up a card at a time.

A card out of view, flattened, or on a page behind another does not
rebuild when its node runs (`NodeGraphScene.defer_refresh`,
`DashboardScene.defer_tile`) — that is what took the freeze out of a busy
flow's runs (AE1). Done only once the card came into sight, though, the
work landed at the worst moment: under the pointer, mid-pan, every card
that scrolled in rebuilding in one burst.

So the put-off work is done here instead, while nobody is doing anything:

- one card per turn of the event loop, so a frame carries at most one
  rebuild and a pan or a click that arrives in between is served first;
- nearest first: cards in view or within `PREFETCH` screens of it once the
  view has been still for `SETTLE_S`, so they are ready before a pan
  reaches them; everything else once the view and the run have both been
  quiet for `IDLE_S`, so a few seconds after a run nothing is left waiting;
- nothing while a mouse button is held *and the view is moving* — a pan.
  A held button alone is not trusted: Wayland loses a release now and
  then (a click that switches page, a menu), and a button Qt believes is
  still down would otherwise hold everything back for good;
- a page just switched to is filled at once, a tile per turn, with no
  quiet to wait for (tier `NOW`) — looking at it is the whole reason;
- nothing slow ahead of time: a refresh that took longer than `SLOW_S`
  (a report card laying out a long table takes seconds) is a freeze the
  user walks into if they touch anything meanwhile, so it keeps waiting
  until its card is actually on screen, as before (`slow`).

One scheduler for the whole app, not one per scene: two pages draining at
once would put two rebuilds in one turn again.

A scene takes part by `register()`ing itself and answering
``catch_up_candidate()`` with its most deserving put-off refresh, as
``(tier, distance, run, key)`` — tier `NOW` for "on a page just shown",
0 for "in or near view", 1 for the rest, distance in screens, `key` the card or tile, which is what its time
is remembered against — or None when it has nothing it can do yet. `run`
must take the refresh off the scene's books before doing it, so one that
raises is not picked again forever.
"""
from __future__ import annotations

import time
import weakref

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtWidgets import QApplication

# how long the view must have been still before a card in or near it is
# rebuilt: long enough that a pause in a drag or a trackpad glide doesn't
# count, short enough that a card just scrolled to fills at once
SETTLE_S = 0.15
# how long everything must have been quiet before the far cards go
IDLE_S = 0.6
# "near": this many screens beyond the edge of the view, either way
PREFETCH = 1.0
# a catch-up that took longer than this is not done ahead of time again
SLOW_S = 0.3
# re-check this often while a button is held
_HANDS_ON_MS = 100
# a held button counts only if the view moved this recently
_HANDS_ON_MOVING_S = 1.0
# the tier that waits for nothing
NOW = -1

_sources: "weakref.WeakSet" = weakref.WeakSet()
_last_stir = 0.0
_timer: QTimer | None = None
# how long each card's last catch-up took, by card
_took: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def register(source) -> None:
    _sources.add(source)


def stirred() -> None:
    """The view moved, or a refresh was just put off: the quiet starts
    over. Cheap enough to call from every paint."""
    global _last_stir
    _last_stir = time.monotonic()


def poke() -> None:
    """Something may be waiting: look soon. A look already booked stands —
    it measures the quiet when it fires, not when it was booked."""
    timer = _ensure_timer()
    if timer is not None and not timer.isActive():
        timer.start(0)


def slow(key) -> bool:
    """Did this card's last catch-up take long enough that doing it before
    it is on screen risks a freeze under the user's hand?"""
    return _took.get(key, 0.0) > SLOW_S


def screens_away(rect: QRectF, area: QRectF) -> float:
    """How far `rect` lies outside `area`, in widths or heights of it —
    0 when they overlap."""
    if area.width() <= 0 or area.height() <= 0:
        return 0.0
    dx = max(area.left() - rect.right(), rect.left() - area.right(), 0.0)
    dy = max(area.top() - rect.bottom(), rect.top() - area.bottom(), 0.0)
    return max(dx / area.width(), dy / area.height())


def _ensure_timer() -> QTimer | None:
    global _timer
    if _timer is None:
        if QApplication.instance() is None:
            return None
        _timer = QTimer()
        _timer.setSingleShot(True)
        _timer.timeout.connect(_tick)
    return _timer


def _best():
    best = None
    for source in list(_sources):
        try:
            candidate = source.catch_up_candidate()
        except RuntimeError:            # the scene's C++ side is gone
            _sources.discard(source)
            continue
        if candidate is not None and (
                best is None or candidate[:2] < best[:2]):
            best = candidate
    return best


def _tick() -> None:
    best = _best()
    if best is None:
        return
    if best[0] != NOW:
        quiet = time.monotonic() - _last_stir
        if quiet < _HANDS_ON_MOVING_S \
                and QApplication.mouseButtons() != Qt.NoButton:
            _timer.start(_HANDS_ON_MS)
            return
        left = (SETTLE_S if best[0] == 0 else IDLE_S) - quiet
        if left > 0:
            _timer.start(int(left * 1000) + 1)
            return
    started = time.monotonic()
    try:
        best[2]()
    finally:
        try:
            _took[best[3]] = time.monotonic() - started
        except TypeError:               # a key that can't be weakly held
            pass
        # back to the event loop before the next one
        _timer.start(0)
