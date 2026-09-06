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


class TestRadius:
    """`radius=14` — a rounded picture instead of a sharp rectangle.

    Applied to the picture, in `_token`, which every image in a report
    passes through: a matplotlib figure, a plotly chart and a printed web
    view all get it from one place rather than each growing its own idea of
    a corner.
    """

    @staticmethod
    def _corners(image):
        from PySide6.QtGui import QColor
        return [QColor.fromRgba(image.pixel(x, y)).alpha()
                for x, y in ((0, 0), (image.width() - 1, 0),
                             (0, image.height() - 1),
                             (image.width() - 1, image.height() - 1))]

    def test_without_it_the_corners_are_square(self, figure):
        rendered = render("![[c]]", figure)
        assert self._corners(one_image(rendered)) == [255] * 4

    def test_with_it_the_corners_are_cut_away(self, figure):
        rendered = render("![[c|radius=16]]", figure)
        assert self._corners(one_image(rendered)) == [0] * 4

    def test_the_middle_of_the_picture_is_untouched(self, figure):
        from PySide6.QtGui import QColor
        rendered = render("![[c|radius=16]]", figure)
        image = one_image(rendered)
        middle = QColor.fromRgba(
            image.pixel(image.width() // 2, image.height() // 2))
        assert middle.alpha() == 255

    def test_the_corners_are_transparent_not_white(self, figure):
        """A white notch on tinted paper is worse than a square corner."""
        from PySide6.QtGui import QColor
        rendered = render("![[c|radius=16]]", figure)
        corner = QColor.fromRgba(one_image(rendered).pixel(0, 0))
        assert corner.alpha() == 0

    def test_it_does_not_leak_into_the_next_embed(self, figure):
        rendered = render("![[a|radius=20]]\n\n![[b]]", figure)
        assert len(rendered.images) == 2
        assert self._corners(rendered.images[0]) == [0] * 4
        assert self._corners(rendered.images[1]) == [255] * 4

    def test_a_radius_bigger_than_the_picture_is_clamped(self, figure):
        """Past half the shorter side the corners meet and it stops being a
        rounded rectangle; it must not become a lozenge or vanish."""
        from PySide6.QtGui import QColor
        rendered = render("![[c|radius=5000]]", figure)
        image = one_image(rendered)
        middle = QColor.fromRgba(
            image.pixel(image.width() // 2, image.height() // 2))
        assert middle.alpha() == 255

    def test_zero_leaves_it_alone(self, figure):
        rendered = render("![[c|radius=0]]", figure)
        assert self._corners(one_image(rendered)) == [255] * 4

    def test_a_value_that_is_not_a_number_is_reported(self, figure):
        rendered = render("![[c|radius=soft]]", figure)
        assert rendered.problems
        assert "not a corner radius" in rendered.problems[0]

    def test_pt_may_be_written_out(self, figure):
        rendered = render("![[c|radius=16pt]]", figure)
        assert not rendered.problems
        assert self._corners(one_image(rendered)) == [0] * 4

    def test_it_is_a_known_option_not_a_typo(self, figure):
        """The option set is closed, so an unknown one is reported — this
        checks `radius` was actually added to it."""
        rendered = render("![[c|radius=14]]", figure)
        assert not rendered.problems

    def test_on_a_table_it_says_it_does_not_apply(self):
        """A table is set as real text so it can break across a page; it
        has no picture whose corners could be cut. Said rather than
        ignored, the way `ratio` already is."""
        pd = pytest.importorskip("pandas")
        frame = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        rendered = render("![[t|radius=14]]", frame)
        assert any("radius only applies to a picture" in problem
                   for problem in rendered.problems), rendered.problems
