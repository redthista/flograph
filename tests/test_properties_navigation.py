"""Getting round the Properties panel: sections that fold, a search box,
changed settings marked and filtered, Reset to Default, the one-line
header with its ⓘ, and the section heading that sticks while scrolling.

A node that declares no sections has to look as it always did, so most of
the suite (which walks `topLevelItem`s) is untouched by any of this.
"""
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QAbstractItemView

from flograph.core import Graph, ParamSpec
from tests.conftest import make_node

SOURCE = '''
"""Sectioned

A test node with its settings in sections. A second sentence here.

Not in the header.
"""
NODE = {
    "label": "Sectioned", "category": "Test", "version": "3.1",
    "inputs": [], "outputs": [("out", "any")],
}
PARAMS = [
    {"name": "kind", "type": "choice", "label": "Kind",
     "options": ["bar", "line"], "default": "bar"},
    {"name": "x", "type": "string", "label": "X column", "default": "",
     "section": "Data"},
    {"name": "y", "type": "string", "label": "Y column", "default": "",
     "placeholder": "the height of each bar", "section": "Data"},
    {"name": "legend_pos", "type": "choice", "label": "Legend position",
     "options": ["right", "bottom"], "default": "right",
     "section": "Legend", "folded": True},
    {"name": "legend_size", "type": "int", "label": "Legend size",
     "default": 10, "section": "Legend"},
    {"name": "bins", "type": "int", "label": "Bins", "default": 0,
     "section": "Data", "visible_when": {"kind": ["bar"]}},
]
for i in range(30):
    PARAMS.append({"name": f"extra{i}", "type": "string",
                   "label": f"Extra {i}", "default": "", "section": "Extras"})
def run(ctx):
    return None
'''

PLAIN = '''
NODE = {"label": "Plain", "category": "Test", "inputs": [],
        "outputs": [("out", "any")]}
PARAMS = [
    {"name": "a", "type": "string", "label": "A", "default": ""},
    {"name": "b", "type": "int", "label": "B", "default": 1},
]
def run(ctx):
    return None
'''

SECTION_ROLE = Qt.UserRole + 1


@pytest.fixture(autouse=True)
def _fresh_settings():
    QSettings("flograph", "flograph").remove("properties")
    yield
    QSettings("flograph", "flograph").remove("properties")


def _panel(qtbot, source=SOURCE, type_id="test.sectioned"):
    from flograph.ui.properties.params_panel import ParamsPanel
    graph = Graph()
    node = make_node(source, type_id)
    graph.add_node(node)
    stack = QUndoStack()
    panel = ParamsPanel(graph, stack)
    qtbot.addWidget(panel)
    panel.resize(360, 400)
    panel.set_node(node.id)
    return panel, graph, node, stack


def _top_labels(panel):
    tree = panel.tree
    return [tree.topLevelItem(i).data(0, SECTION_ROLE)
            or tree.topLevelItem(i).text(0)
            for i in range(tree.topLevelItemCount())]


class TestTheSpec:
    def test_section_and_folded_default_to_none(self):
        spec = ParamSpec.from_dict({"name": "a", "type": "string"})
        assert spec.section == "" and spec.folded is False

    def test_they_are_read(self):
        spec = ParamSpec.from_dict({"name": "a", "type": "string",
                                    "section": " Legend ", "folded": True})
        assert spec.section == "Legend" and spec.folded


class TestSections:
    def test_a_node_without_sections_is_a_flat_list(self, qtbot):
        panel, *_ = _panel(qtbot, PLAIN, "test.plain")
        assert _top_labels(panel) == ["Name", "A", "B"]
        assert not panel._sections

    def test_rows_gather_under_their_headings_in_order(self, qtbot):
        panel, *_ = _panel(qtbot)
        assert _top_labels(panel) == ["Name", "Kind", "Data", "Legend",
                                      "Extras"]
        rows = panel.rows()
        # Bins is declared after Legend but gathers under the first Data
        assert rows["Bins"].parent() is panel._sections["Data"]
        assert "Data" not in rows      # headings aren't rows

    def test_a_folded_section_starts_folded(self, qtbot):
        panel, *_ = _panel(qtbot)
        assert panel._sections["Data"].isExpanded()
        assert not panel._sections["Legend"].isExpanded()

    def test_clicking_a_heading_folds_it_and_it_is_remembered(self, qtbot):
        panel, graph, node, _ = _panel(qtbot)
        data = panel._sections["Data"]
        panel._on_item_clicked(data, 0)
        assert not data.isExpanded()
        panel._on_item_clicked(panel._sections["Legend"], 0)
        # a fresh panel on another node of the same type
        again, *_ = _panel(qtbot)
        assert not again._sections["Data"].isExpanded()
        assert again._sections["Legend"].isExpanded()

    def test_a_section_with_every_row_gated_away_has_no_heading(self, qtbot):
        source = SOURCE.replace(
            '"section": "Legend", "folded": True}',
            '"section": "Legend", "folded": True, '
            '"visible_when": {"kind": ["line"]}}').replace(
            '"default": 10, "section": "Legend"}',
            '"default": 10, "section": "Legend", '
            '"visible_when": {"kind": ["line"]}}')
        panel, *_ = _panel(qtbot, source)
        assert "Legend" not in panel._sections

    def test_open_and_fold_all(self, qtbot):
        panel, *_ = _panel(qtbot)
        panel.set_all_sections_expanded(False)
        assert not any(h.isExpanded() for h in panel._sections.values())
        panel.set_all_sections_expanded(True)
        assert all(h.isExpanded() for h in panel._sections.values())

    def test_the_expand_and_collapse_buttons(self, qtbot):
        panel, *_ = _panel(qtbot)
        assert not panel.expand_all.isHidden()
        panel.collapse_all.click()
        assert not any(h.isExpanded() for h in panel._sections.values())
        again, *_ = _panel(qtbot)
        assert not again._sections["Data"].isExpanded()
        again.expand_all.click()
        assert all(h.isExpanded() for h in again._sections.values())

    def test_no_buttons_without_sections(self, qtbot):
        panel, *_ = _panel(qtbot, PLAIN, "test.plain")
        assert panel.expand_all.isHidden() and panel.collapse_all.isHidden()

    def test_the_heading_arrow_follows_the_fold(self, qtbot):
        panel, *_ = _panel(qtbot)
        data = panel._sections["Data"]
        assert data.text(0).startswith("\N{BLACK DOWN-POINTING SMALL TRIANGLE}")
        data.setExpanded(False)
        assert data.text(0).startswith(
            "\N{BLACK RIGHT-POINTING SMALL TRIANGLE}")


class TestChanged:
    def test_a_changed_setting_is_bold_and_counted(self, qtbot):
        panel, graph, node, _ = _panel(qtbot)
        rows = panel.rows()
        assert not rows["X column"].font(0).bold()
        graph.set_param(node.id, "x", "region")
        assert rows["X column"].font(0).bold()
        assert "1 changed" in panel._sections["Data"].text(0)
        graph.set_param(node.id, "x", "")
        assert not rows["X column"].font(0).bold()
        assert "changed" not in panel._sections["Data"].text(0)

    def test_a_renamed_node_marks_the_name_row(self, qtbot):
        panel, graph, node, _ = _panel(qtbot)
        graph.set_label(node.id, "Mine")
        assert panel.rows()["Name"].font(0).bold()

    def test_changed_only_hides_the_rest(self, qtbot):
        panel, graph, node, _ = _panel(qtbot)
        graph.set_param(node.id, "legend_size", 14)
        panel.changed_only.setChecked(True)
        visible = [label for label, item in panel.rows().items()
                   if not item.isHidden()]
        assert visible == ["Legend size"]
        assert panel._sections["Data"].isHidden()
        # a match inside a folded section opens it while filtering...
        assert panel._sections["Legend"].isExpanded()
        panel.changed_only.setChecked(False)
        # ...and it goes back to how it was left afterwards
        assert not panel._sections["Legend"].isExpanded()
        assert not panel.rows()["X column"].isHidden()

    def test_nothing_changed_says_so(self, qtbot):
        panel, *_ = _panel(qtbot)
        panel.changed_only.setChecked(True)
        assert not panel._no_match.isHidden()
        assert "changed" in panel._no_match.text()


class TestReset:
    def test_reset_one_setting(self, qtbot):
        panel, graph, node, stack = _panel(qtbot)
        graph.set_param(node.id, "y", "units")
        panel.reset_to_defaults(["y"])
        assert graph.node(node.id).params["y"] == ""
        assert not panel.rows()["Y column"].font(0).bold()
        stack.undo()
        assert graph.node(node.id).params["y"] == "units"

    def test_reset_a_section_is_one_undo_step(self, qtbot):
        panel, graph, node, stack = _panel(qtbot)
        graph.set_param(node.id, "x", "region")
        graph.set_param(node.id, "y", "units")
        panel.reset_to_defaults(["x", "y"], "Reset Data")
        params = graph.node(node.id).params
        assert (params["x"], params["y"]) == ("", "")
        assert stack.count() == 1
        stack.undo()
        params = graph.node(node.id).params
        assert (params["x"], params["y"]) == ("region", "units")

    def test_reset_the_name(self, qtbot):
        panel, graph, node, _ = _panel(qtbot)
        graph.set_label(node.id, "Mine")
        panel.reset_to_defaults(["__label__"])
        assert graph.node(node.id).label_override is None
        assert panel._label_edit.text() == ""

    def test_a_locked_node_is_not_reset(self, qtbot):
        panel, graph, node, _ = _panel(qtbot)
        graph.set_param(node.id, "x", "region")
        graph.set_locked(node.id, True)
        panel.reset_to_defaults(["x"])
        assert graph.node(node.id).params["x"] == "region"


class TestSearch:
    def _visible(self, panel):
        return [label for label, item in panel.rows().items()
                if not item.isHidden()]

    def test_words_match_labels(self, qtbot):
        panel, *_ = _panel(qtbot)
        panel.search.setText("legend pos")
        assert self._visible(panel) == ["Legend position"]
        assert panel._sections["Legend"].isExpanded()
        assert panel._sections["Data"].isHidden()

    def test_a_section_title_finds_its_rows(self, qtbot):
        panel, *_ = _panel(qtbot)
        panel.search.setText("legend")
        assert self._visible(panel) == ["Legend position", "Legend size"]

    def test_param_names_placeholders_and_choices_match(self, qtbot):
        panel, *_ = _panel(qtbot)
        panel.search.setText("legend_size")
        assert self._visible(panel) == ["Legend size"]
        panel.search.setText("height of each")
        assert self._visible(panel) == ["Y column"]
        panel.search.setText("bottom")
        assert self._visible(panel) == ["Legend position"]

    def test_no_match_says_so_and_clearing_restores(self, qtbot):
        panel, *_ = _panel(qtbot)
        panel.search.setText("zzzz")
        assert not panel._no_match.isHidden()
        panel.search.clear()
        assert panel._no_match.isHidden()
        assert not panel.rows()["X column"].isHidden()
        assert not panel._sections["Legend"].isExpanded()

    def test_a_folded_section_opened_by_search_is_not_remembered(self,
                                                                 qtbot):
        panel, *_ = _panel(qtbot)
        panel.search.setText("legend")
        panel.search.clear()
        again, *_ = _panel(qtbot)
        assert not again._sections["Legend"].isExpanded()

    def test_the_search_survives_selecting_another_node(self, qtbot):
        panel, graph, node, _ = _panel(qtbot)
        other = make_node(SOURCE, "test.sectioned")
        graph.add_node(other)
        panel.search.setText("bins")
        panel.set_node(other.id)
        assert self._visible(panel) == ["Bins"]

    def test_ctrl_f_focuses_the_search(self, qtbot):
        panel, *_ = _panel(qtbot)
        panel.show()
        panel.activateWindow()
        qtbot.waitExposed(panel)
        panel._focus_search()
        qtbot.waitUntil(panel.search.hasFocus, timeout=1000)


class TestHeader:
    def test_one_line_and_the_rest_behind_the_i(self, qtbot):
        panel, *_ = _panel(qtbot)
        assert panel._summary.text().startswith(
            "A test node with its settings in sections.")
        assert "Not in the header" not in panel._summary.text()
        assert panel._details.isHidden()
        panel._info_button.setChecked(True)
        assert not panel._details.isHidden()
        assert panel._version_label.text() == "version 3.1"

    def test_the_i_is_remembered(self, qtbot):
        panel, *_ = _panel(qtbot)
        panel._info_button.setChecked(True)
        again, *_ = _panel(qtbot)
        assert not again._details.isHidden()

    def test_nothing_selected_shows_none_of_it(self, qtbot):
        panel, *_ = _panel(qtbot)
        panel.set_node(None)
        assert panel._header.isHidden()
        assert panel._filter_bar.isHidden()


class TestStickyHeading:
    def test_it_shows_the_section_scrolled_into(self, qtbot):
        panel, *_ = _panel(qtbot)
        panel.show()
        qtbot.waitExposed(panel)
        tree = panel.tree
        tree.scrollToItem(panel.rows()["Extra 20"],
                        QAbstractItemView.PositionAtTop)
        panel._update_sticky()
        assert panel._sticky.isVisible()
        assert panel._sticky.property("section") == "Extras"

    def test_clicking_it_folds_that_section(self, qtbot):
        panel, *_ = _panel(qtbot)
        panel.show()
        qtbot.waitExposed(panel)
        tree = panel.tree
        tree.scrollToItem(panel.rows()["Extra 20"],
                        QAbstractItemView.PositionAtTop)
        panel._update_sticky()
        panel._fold_sticky_section()
        assert not panel._sections["Extras"].isExpanded()

    def test_at_the_top_there_is_none(self, qtbot):
        panel, *_ = _panel(qtbot)
        panel.show()
        qtbot.waitExposed(panel)
        panel.tree.scrollToTop()
        panel._update_sticky()
        assert not panel._sticky.isVisible()
