"""The sliding on/off switch (ui/switch.py)."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from flograph.ui.switch import ON, TRACK_W, Switch


def _has_accent(widget) -> bool:
    """Is the on colour anywhere on the track? The track only: the label's
    antialiased text has coloured fringes that can land near a violet."""
    image = widget.grab().toImage()
    for x in range(0, min(image.width(), TRACK_W + 4), 2):
        for y in range(0, image.height(), 2):
            c = QColor(image.pixel(x, y))
            if abs(c.red() - ON.red()) < 30 and abs(c.green() - ON.green()) < 30 \
                    and abs(c.blue() - ON.blue()) < 30:
                return True
    return False


def test_a_click_toggles_it_and_the_knob_slides_across(qtbot):
    switch = Switch("Live")
    qtbot.addWidget(switch)
    switch.show()
    seen = []
    switch.toggled.connect(seen.append)
    qtbot.mouseClick(switch, Qt.LeftButton)
    assert switch.isChecked() and seen == [True]
    qtbot.waitUntil(lambda: switch.position() == 1.0, timeout=2000)
    qtbot.mouseClick(switch, Qt.LeftButton)
    assert not switch.isChecked()
    qtbot.waitUntil(lambda: switch.position() == 0.0, timeout=2000)


def test_space_toggles_it_too(qtbot):
    switch = Switch("Live")
    qtbot.addWidget(switch)
    switch.show()
    switch.setFocus()
    qtbot.keyClick(switch, Qt.Key_Space)
    assert switch.isChecked()


def test_set_before_it_shows_there_is_no_slide(qtbot):
    """A page loading its saved state sets the switch while hidden."""
    switch = Switch("Live")
    qtbot.addWidget(switch)
    switch.setChecked(True)
    assert switch.position() == 1.0


def test_it_is_the_accent_when_on_and_not_when_off(qtbot):
    switch = Switch("Live")
    qtbot.addWidget(switch)
    switch.setChecked(True)
    switch.show()
    switch.clearFocus()     # the focus ring is a violet too — test the track
    assert _has_accent(switch)
    switch.setChecked(False)
    qtbot.waitUntil(lambda: switch.position() == 0.0, timeout=2000)
    assert not _has_accent(switch)


def test_the_label_is_part_of_its_size_and_is_clickable(qtbot):
    bare, labelled = Switch(), Switch("Live preview")
    qtbot.addWidget(bare)
    qtbot.addWidget(labelled)
    assert labelled.sizeHint().width() > bare.sizeHint().width()
    labelled.resize(labelled.sizeHint())
    labelled.show()
    # a click on the words, well right of the track
    word = labelled.rect().center()
    word.setX(labelled.width() - 6)
    qtbot.mouseClick(labelled, Qt.LeftButton, pos=word)
    assert labelled.isChecked()
