"""Charts follow the theme only when they are shown, and only charts that
were never styled: a figure on Plotly's default look is drawn from a dark
copy in a dark theme; an explicit template, chart rules or own colours are
left alone; the node's cached figure is never touched (UI redesign #109)."""
import pytest

from flograph.ui import theme
from flograph.ui.inspector.plotly_view import themed_for_display

px = pytest.importorskip("plotly.express")


@pytest.fixture
def dark(qapp):
    theme.apply_theme(qapp, "dark")
    yield
    theme.apply_theme(qapp, "dark")


def test_a_default_figure_is_drawn_dark_from_a_copy(dark):
    fig = px.bar(x=["a", "b"], y=[1, 2])
    before = fig.to_json()
    shown = themed_for_display(fig)
    assert shown is not fig
    assert shown.layout.paper_bgcolor == theme.color(
        "canvas", "NODE_BODY").name()
    assert fig.to_json() == before          # the node's output is untouched


@pytest.mark.parametrize("make", [
    lambda: px.bar(x=["a"], y=[1], template="plotly_white"),
    lambda: px.bar(x=["a"], y=[1]).update_layout(paper_bgcolor="#123456"),
    lambda: px.bar(x=["a"], y=[1]).update_layout(font_color="#222222"),
])
def test_a_styled_figure_is_left_alone(dark, make):
    fig = make()
    assert themed_for_display(fig) is fig


def test_light_theme_changes_nothing(qapp):
    theme.apply_theme(qapp, "light")
    try:
        fig = px.bar(x=["a"], y=[1])
        assert themed_for_display(fig) is fig
    finally:
        theme.apply_theme(qapp, "dark")


def test_raw_html_and_stacks(dark):
    assert themed_for_display("<p>hi</p>") == "<p>hi</p>"
    styled = px.bar(x=["a"], y=[1], template="plotly_white")
    plain = px.bar(x=["a"], y=[1])
    shown = themed_for_display([styled, plain])
    assert shown[0] is styled and shown[1] is not plain
    only_styled = [styled]
    assert themed_for_display(only_styled) is only_styled
