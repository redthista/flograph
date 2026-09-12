"""A menu of ours just closed, so the context menu that follows is nobody's.

Wayland, Qt 6.11, found by Dan testing AB4 and again on the canvas tabs:
the context-menu event a right press brings is not delivered while that
press is being handled. It arrives *after* the handler has returned — and
our page-bar menus open on press and run their whole ``exec()`` inside that
handler, so by the time the event is sent the menu has been used and
dismissed. The platform then hands it to whichever widget it believes the
pointer is over, or which holds the focus, and that widget answers a
right-click nobody made: a lone "New group…" from the Library dock, a
greyed-out Paste over a dashboard, the dock list over the canvas.

Two defences came first and neither is enough alone. Taking the focus onto
the page bar either side of the menu (``PageTabBar._menu_with_the_focus``)
covers the focus half. Asking whether the position is inside the widget
covers leftovers that land outside it — but the page bar sits along the
*top* of the window and its menus drop over the Library dock and the
canvas, so the position that arrives is genuinely inside the widget it is
delivered to. Geometry cannot tell that event from a real right-click
there.

Time can. A menu of ours closing is recorded here, and a widget asked for a
context menu within a moment of that says no. Nobody right-clicks a third
of a second after dismissing a menu; the leftovers arrive in milliseconds.

Deliberately a module-level float and nothing else. No QObject — this is
imported before a QApplication exists, which is precisely the state
PySide's wrapper bookkeeping is not safe in — and no event filter, least of
all on the application, whose cost last time was a sluggish canvas and a
segfault inside WebEngine's hover flood (issue 7).
"""
from __future__ import annotations

import time

#: How long after a menu closes a context request counts as its leftovers.
#: Long enough for a slow compositor round-trip, far shorter than the gap
#: between two gestures made by hand.
SETTLE = 0.35

#: When one of our own menus last closed, on the monotonic clock so that
#: changing the system time cannot put it in the future. 0.0 = none has.
_closed_at = 0.0


def menu_closed() -> None:
    """Record that one of our menus has just finished. Called on every
    page-bar menu; cheap enough to call on any other."""
    global _closed_at
    _closed_at = time.monotonic()


def settling() -> bool:
    """True while a context request is more likely the tail of a menu that
    just closed than a right-click of its own.

    For the surfaces whose menu comes through ``customContextMenuRequested``
    (the Library tree, a sheet's headers) — a signal carrying a position and
    nothing else, so this is all there is to go on.
    """
    return _closed_at > 0.0 and (time.monotonic() - _closed_at) < SETTLE


def stray(event) -> bool:
    """True for a context-menu *event* that is such a tail.

    The platform's own mouse-driven events only: the keyboard's Menu key
    (``Reason.Keyboard``) is a deliberate ask however recently a menu
    closed, and an event that is not spontaneous was sent by our own code
    or by a test, which is nobody's leftovers either.
    """
    from PySide6.QtGui import QContextMenuEvent
    return (settling()
            and event.reason() == QContextMenuEvent.Reason.Mouse
            and event.spontaneous())
