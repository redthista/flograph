"""NODE['version'] — the node type's own edition number.

It exists to answer one question the package version cannot: *is the node in
front of me the one I just edited?* Two checkouts of flograph 0.1.10 report
0.1.10 apiece, and a node file copied into a user-nodes folder reports the
version of whatever flograph happens to load it. Only a number living in the
node's own source travels with the node and changes when the node changes.
"""
import pytest

from flograph.core import NodeRegistry, NodeScriptError, parse_spec


@pytest.fixture(scope="module")
def builtin_specs():
    registry = NodeRegistry()
    registry.load_builtins()
    return list(registry.all())


BARE = """
NODE = {{"label": "X", "category": "Y"{extra}}}
def run(ctx):
    return None
"""


def spec_with(extra: str):
    return parse_spec(BARE.format(extra=extra), "test.versioned")


class TestParsing:
    def test_a_declared_version_reaches_the_spec(self):
        assert spec_with(', "version": "2.0"').version == "2.0"

    def test_a_node_without_one_reports_empty(self):
        # Deliberately not "1.0": a node that never said dates itself to
        # before versions existed, and the panel shows nothing at all.
        assert spec_with("").version == ""

    @pytest.mark.parametrize("declared", ['2', '"2"', '2.0', '"v3 (beta)"'])
    def test_numbers_are_accepted_and_stringified(self, declared):
        # "2.0" is the obvious thing to type and 2.0 the obvious thing to
        # mistype; refusing the second would be pedantry.
        assert isinstance(spec_with(f', "version": {declared}').version, str)

    def test_whitespace_is_trimmed(self):
        assert spec_with(', "version": "  2.0  "').version == "2.0"

    @pytest.mark.parametrize("declared", ['None', '""', '"   "'])
    def test_blank_forms_all_mean_unversioned(self, declared):
        assert spec_with(f', "version": {declared}').version == ""

    def test_a_nonsense_version_is_rejected(self):
        with pytest.raises(NodeScriptError, match="NODE\\['version'\\]"):
            spec_with(', "version": ["2", "0"]')

    def test_the_version_survives_a_round_trip_through_source(self):
        # Forking a node copies its text, so re-parsing must give it back —
        # this is what makes a copied file carry its own version.
        first = spec_with(', "version": "2.0"')
        assert parse_spec(first.source, "test.forked").version == "2.0"


class TestEveryBuiltinDeclaresOne:
    """A missing version on a builtin is now the bug, not the default.

    Without this, the mechanism decays the first time someone adds a node
    and forgets — and a half-versioned library is worse than none, because
    a blank stops meaning "old" and starts meaning "maybe nobody bothered".
    """

    def test_the_library_is_not_empty(self, builtin_specs):
        # Guards the guard: an empty registry would pass every test below.
        assert len(builtin_specs) > 50

    def test_all_of_them(self, builtin_specs):
        missing = sorted(s.type_id for s in builtin_specs if not s.version)
        assert not missing, f"builtin nodes with no NODE['version']: {missing}"

    def test_the_rewritten_plotly_nodes_say_so(self, builtin_specs):
        # The two nodes this whole feature came out of: they were rebuilt
        # from a handful of params to the full Plotly Express surface, and
        # a user looking at one needs to see which of those they have.
        by_id = {s.type_id: s.version for s in builtin_specs}
        assert by_id["flograph.viz.show_plotly"] == "2.0"
        assert by_id["flograph.viz.chart_per_value_plotly"] == "2.0"


class TestOlderFlographsIgnoreIt:
    """The key isn't in any allow-list, so a flograph that predates this
    reads a versioned node without complaint — which matters because these
    node files get copied into user-nodes folders on older installs."""

    def test_parse_spec_ignores_keys_it_does_not_know(self):
        spec = spec_with(', "version": "2.0", "invented_later": 42')
        assert spec.label == "X"


class TestTheVersionIsVisible:
    """A version nobody can see solves nothing — the whole point is being
    able to look at a node and tell which one it is."""

    def _panel(self, qtbot, registry, type_id):
        from PySide6.QtGui import QUndoStack

        from flograph.core import Graph
        from flograph.ui.properties.params_panel import ParamsPanel

        graph = Graph()
        node = graph.add_node(registry.instantiate(type_id))
        panel = ParamsPanel(graph, QUndoStack())
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        return panel

    def test_the_properties_panel_shows_it(self, qtbot, registry):
        panel = self._panel(qtbot, registry, "flograph.viz.show_plotly")
        assert panel._version_label.text() == "version 2.0"
        assert not panel._version_label.isHidden()

    def test_it_goes_away_with_the_selection(self, qtbot, registry):
        panel = self._panel(qtbot, registry, "flograph.viz.show_plotly")
        panel.set_node(None)
        assert panel._version_label.isHidden()

    def test_the_palette_tooltip_carries_it(self, qtbot, registry):
        # Before dragging one out, even — which is where the question
        # "am I about to place the new one?" actually gets asked.
        from PySide6.QtCore import QSettings, Qt

        from flograph.ui.canvas.palette import LibraryTree
        from flograph.ui.favorites import Favorites

        tree = LibraryTree(registry, Favorites(QSettings("flograph", "t")))
        qtbot.addWidget(tree)
        tips = []
        for i in range(tree.topLevelItemCount()):
            section = tree.topLevelItem(i)
            for j in range(section.childCount()):
                child = section.child(j)
                if child.data(0, Qt.UserRole) == "flograph.viz.show_plotly":
                    tips.append(child.toolTip(0))
        assert tips, "Show Plotly is not in the library tree"
        assert all("version 2.0" in tip for tip in tips)
