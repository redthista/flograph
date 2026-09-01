"""FlowLayout: wraps its widgets onto a new line when the width runs out."""
from PySide6.QtWidgets import QWidget

from flograph.ui.flow_layout import FlowLayout


def _host(qtbot, n_buttons=5):
    from PySide6.QtWidgets import QToolButton
    host = QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host, spacing=3)
    buttons = []
    for i in range(n_buttons):
        b = QToolButton(text=f"Button{i}")
        layout.addWidget(b)
        buttons.append(b)
    return host, layout, buttons


def test_all_on_one_row_when_wide(qtbot):
    host, layout, buttons = _host(qtbot)
    host.resize(2000, 40)
    host.show()
    qtbot.waitExposed(host)
    ys = {b.y() for b in buttons}
    assert len(ys) == 1


def test_wraps_to_more_rows_when_narrow(qtbot):
    host, layout, buttons = _host(qtbot)
    host.resize(120, 200)
    host.show()
    qtbot.waitExposed(host)
    ys = sorted({b.y() for b in buttons})
    assert len(ys) > 1
    # every button still fits inside the host's width
    assert all(b.x() + b.width() <= host.width() + 1 for b in buttons)


def test_height_for_width_grows_as_width_shrinks(qtbot):
    _host_w, layout, _b = _host(qtbot, n_buttons=6)
    assert layout.heightForWidth(100) > layout.heightForWidth(2000)
