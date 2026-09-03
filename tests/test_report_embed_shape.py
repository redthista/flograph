"""Idea N3: per-embed shape and density — `![[chart|ratio=16:9]]`,
`![[chart|height=180]]`, `![[chart|scale=2]]` and `![[chart|fit]]`.

`width=` (test_embed_options.py) answers "how wide"; these answer "what
shape", "how sharp" and "make it fit what's left of the page". A chart is
*redrawn* at the asked-for shape rather than stretched, so its axes and
labels lay out for it.
"""
import re

import pytest

from flograph.core import Graph, NodeRegistry
from flograph.core.page_setup import PageSetup
from flograph.engine.cache import OutputCache
from flograph.ui.report.render import parse_aspect, render_body, render_report


@pytest.fixture(autouse=True)
def _app(qapp):
    return qapp


@pytest.fixture
def figure():
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    fig = Figure(figsize=(6, 3))
    fig.add_subplot(111).plot([1, 2, 3])
    return fig


def render(body, value, **kw):
    return render_body(body, lambda ref, port: (value, "", ""), **kw)


def one_image(rendered):
    assert rendered.images, "expected an embedded image"
    return rendered.images[0]


def img_widths(rendered):
    return [int(w) for w in re.findall(
        r'<img[^>]*width="(\d+)"', rendered.document.toHtml())]


class TestParseAspect:

    @pytest.mark.parametrize("text,expected", [
        ("16:9", 16 / 9),
        ("4x3", 4 / 3),
        ("3/2", 1.5),
        ("1.5", 1.5),
        (" 2 : 1 ", 2.0),
    ])
    def test_the_spellings_that_mean_a_ratio(self, text, expected):
        assert parse_aspect(text) == pytest.approx(expected)

    @pytest.mark.parametrize("text", ["", "wide", "0:1", "-2", "1:0", "a:b"])
    def test_nonsense_is_none(self, text):
        assert parse_aspect(text) is None


class TestRatio:

    def test_a_matplotlib_chart_is_redrawn_square(self, figure):
        rendered = render("![[c|ratio=1:1]]", figure)
        image = one_image(rendered)
        assert image.width() == pytest.approx(image.height(), rel=0.02)

    def test_a_wide_ratio_comes_out_letterbox(self, figure):
        rendered = render("![[c|ratio=3:1]]", figure)
        image = one_image(rendered)
        assert image.width() / image.height() == pytest.approx(3.0, rel=0.03)

    def test_the_placement_width_is_unchanged_by_a_ratio(self, figure):
        """`ratio` changes the shape, not how wide it sits on the page —
        that is still `width`'s job."""
        from flograph.ui.report.render import FIGURE_WIDTH
        assert img_widths(render("![[c|ratio=2:1]]", figure)) == [FIGURE_WIDTH]

    def test_the_figure_is_left_as_it_was_found(self, figure):
        """The size is borrowed for the draw and put back — the same
        figure is live on a canvas card."""
        before = tuple(figure.get_size_inches())
        render("![[c|ratio=1:1]]", figure)
        assert tuple(figure.get_size_inches()) == before

    def test_a_nonsense_ratio_is_reported_not_guessed(self, figure):
        rendered = render("![[c|ratio=widescreen]]", figure)
        assert rendered.problems and "not a ratio" in rendered.problems[0]

    def test_height_in_points_is_the_other_way_to_say_a_shape(self, figure):
        """`height=` is an absolute; at the default page width a tall
        number is a tall chart."""
        short = one_image(render("![[c|height=120]]", figure))
        tall = one_image(render("![[c|height=360]]", figure))
        assert tall.height() / tall.width() > short.height() / short.width()

    def test_a_nonsense_height_is_reported(self, figure):
        rendered = render("![[c|height=short]]", figure)
        assert rendered.problems and "not a height" in rendered.problems[0]


class TestScale:

    def test_scale_renders_a_denser_bitmap(self, figure):
        plain = one_image(render("![[c]]", figure))
        dense = one_image(render("![[c|scale=3]]", figure))
        assert dense.width() > plain.width()

    def test_scale_is_capped(self, figure):
        capped = one_image(render("![[c|scale=99]]", figure))
        at_max = one_image(render("![[c|scale=4]]", figure))
        assert capped.width() == at_max.width()

    def test_scale_never_goes_below_one(self, figure):
        plain = one_image(render("![[c]]", figure))
        down = one_image(render("![[c|scale=0.2]]", figure))
        assert down.width() == plain.width()

    def test_a_nonsense_scale_is_reported(self, figure):
        rendered = render("![[c|scale=big]]", figure)
        assert rendered.problems and "not a scale" in rendered.problems[0]


class TestFit:

    def _page(self, value):
        registry = NodeRegistry()
        registry.load_builtins()
        graph, cache = Graph(), OutputCache()
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, "Chart")
        cache.set(node.id, {"value": value}, 0.0)
        return graph, cache

    def _tall_figure(self):
        from matplotlib.figure import Figure
        fig = Figure(figsize=(6, 7))
        fig.add_subplot(111).plot([1, 2, 3])
        return fig

    def test_a_chart_low_on_the_page_is_shrunk_to_fit(self):
        pytest.importorskip("matplotlib")
        graph, cache = self._page(self._tall_figure())
        setup = PageSetup(size="A5")   # a short page, easy to overflow
        filler = ("word " * 40 + "\n\n") * 2
        body = f"# Report\n\n{filler}\n\n![[Chart|fit]]\n"

        fitted = render_report(body, graph, cache, setup=setup)
        loose = render_report(body.replace("|fit", ""), graph, cache,
                              setup=setup)

        fw = [int(w) for w in re.findall(
            r'<img[^>]*width="(\d+)"', fitted.document.toHtml())]
        lw = [int(w) for w in re.findall(
            r'<img[^>]*width="(\d+)"', loose.document.toHtml())]
        assert fw and lw and fw[0] < lw[0]

    def test_a_chart_with_almost_no_room_is_not_shrunk_to_a_stamp(self):
        """Past the floor `fit` gives up: the chart is more use whole on
        the next page than tiny on this one."""
        pytest.importorskip("matplotlib")
        graph, cache = self._page(self._tall_figure())
        setup = PageSetup(size="A5")
        filler = ("word " * 40 + "\n\n") * 4   # leaves a sliver
        body = f"# Report\n\n{filler}\n\n![[Chart|fit]]\n"

        fitted = render_report(body, graph, cache, setup=setup)
        loose = render_report(body.replace("|fit", ""), graph, cache,
                              setup=setup)
        fw = re.findall(r'<img[^>]*width="(\d+)"', fitted.document.toHtml())
        lw = re.findall(r'<img[^>]*width="(\d+)"', loose.document.toHtml())
        assert fw == lw

    def test_a_chart_with_room_is_left_alone(self):
        pytest.importorskip("matplotlib")
        graph, cache = self._page(self._tall_figure())
        setup = PageSetup()
        body = "# Report\n\n![[Chart|fit]]\n"

        fitted = render_report(body, graph, cache, setup=setup)
        loose = render_report("# Report\n\n![[Chart]]\n", graph, cache,
                              setup=setup)
        fw = re.findall(r'<img[^>]*width="(\d+)"', fitted.document.toHtml())
        lw = re.findall(r'<img[^>]*width="(\d+)"', loose.document.toHtml())
        assert fw == lw

    def test_fit_on_a_card_says_it_does_not_apply(self, figure):
        rendered = render("![[c|fit]]", figure)   # no page_height
        assert rendered.problems
        assert "only works on a report page" in rendered.problems[0]
