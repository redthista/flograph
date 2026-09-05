"""Emoji that actually paint.

A conditional-formatting rule can put any character in a cell —
``sla: breach=🔥, ok=✅``. On a machine whose Qt cannot rasterise the emoji
font it resolves to, that glyph paints **nothing**: the cell reserves the
width and draws empty space, which is exactly what a missing rule looks
like. ``canvas/marks.py`` records the same trap for the node glyphs and
answers it by drawing paths instead — an option a rule's icon does not
have, because the user typed it.

Two facts make it fixable anyway:

* nothing short of painting a candidate and counting the ink tells you
  whether it will draw. ``QFontMetrics.inFont()`` answers True for the very
  glyphs Qt then declines to rasterise, so this module probes by rendering.
* ``QFont.setFamilies([base, emoji])`` keeps the UI font for ordinary text
  and reaches the second family only for what the first cannot draw — but
  only if the first entry is the *resolved* family name
  (``QFontInfo.family()``). Pass Qt's alias ("Sans Serif") and fontconfig
  may hand the whole string to the second family, which is how a table of
  numbers ends up set in an emoji font.

So: probe once with a reference emoji, remember the first family that
leaves ink, and hand out fonts that name it as the fallback. Everything is
cached — the probe paints a handful of 32px images, once per session.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QFontInfo, QGuiApplication, QImage, QPainter,
)

#: A plain non-BMP colour emoji, present in every emoji font ever shipped
#: and in none of the text fonts — so it separates "can draw emoji" from
#: "can draw ✓", which most UI fonts can.
PROBE_GLYPH = "\U0001f525"  # 🔥

#: Tried in order. The platform's own emoji font first — where it works it
#: is the one the rest of the desktop uses, so the icons match everything
#: else on screen — then the third-party sets people install when it does
#: not, then the monochrome fallbacks, which are still infinitely better
#: than a blank cell.
_CANDIDATES = (
    "Apple Color Emoji",        # macOS
    "Segoe UI Emoji",           # Windows
    "Noto Color Emoji",         # most Linux desktops
    "Twemoji",
    "Twitter Color Emoji",
    "JoyPixels",
    "EmojiOne Color",
    "OpenMoji",
    "Noto Emoji",               # monochrome from here down
    "Symbola",
    "Segoe UI Symbol",
    "Noto Sans Symbols 2",
)

_PROBE_PX = 32


def paints(font: QFont, text: str) -> bool:
    """Does `font` leave any ink when it draws `text`?

    The only honest test: render it and compare against the blank page.
    """
    if QGuiApplication.instance() is None:
        return False
    blank = QImage(_PROBE_PX, _PROBE_PX, QImage.Format_RGB32)
    blank.fill(QColor("white"))
    image = QImage(blank)
    painter = QPainter(image)
    probe = QFont(font)
    probe.setPixelSize(_PROBE_PX - 8)
    painter.setFont(probe)
    painter.setPen(QColor("black"))
    painter.drawText(QRect(0, 0, _PROBE_PX, _PROBE_PX), Qt.AlignCenter, text)
    painter.end()
    return bytes(image.constBits()) != bytes(blank.constBits())


@lru_cache(maxsize=1)
def emoji_family() -> Optional[str]:
    """The first installed family that actually rasterises `PROBE_GLYPH`,
    or None when the machine has nothing that can."""
    if QGuiApplication.instance() is None:
        return None
    installed = set(QFontDatabase.families())
    for family in _CANDIDATES:
        # an uninstalled family would be silently substituted, and we would
        # be measuring the substitute rather than the candidate
        if family in installed and paints(QFont(family), PROBE_GLYPH):
            return family
    return None


@lru_cache(maxsize=32)
def _families_for(family: str) -> Optional[list]:
    """The family list that lets `family` draw emoji, or None if it needs no
    help. Keyed on the family alone — coverage is the family's, not the
    size's — so a cell repaint costs a dict lookup rather than a font
    match."""
    if QGuiApplication.instance() is None:
        return None  # no font system to ask; the caller's font is all there is
    asked = QFont(family)
    if paints(asked, PROBE_GLYPH):
        return None  # this font already draws emoji — leave it alone
    fallback = emoji_family()
    # the *resolved* name, never the alias that was asked for: see the
    # module docstring for what "Sans Serif" does to a families list
    return None if fallback is None else [QFontInfo(asked).family(), fallback]


def with_emoji(font: QFont) -> QFont:
    """`font`, able to draw emoji — the same font back when it already can,
    or when the machine has no emoji font that works."""
    families = _families_for(font.family())
    if families is None:
        return font
    out = QFont(font)
    out.setFamilies(families)
    return out


def apply_emoji_font(widget) -> None:
    """Give `widget` its own font plus the emoji fallback. For fields that
    hold a glyph the user typed, and for views that display one."""
    widget.setFont(with_emoji(widget.font()))
