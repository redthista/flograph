"""The Components section of the node library.

A component row is a leaf with no NodeSpec behind it, which the palette's
filter used to mistake for an empty container and hide -- taking its section
with it, so a just-saved component was invisible in the library.
"""
import pytest
from PySide6.QtCore import QSettings

from flograph.core import user_frames
from flograph.ui.canvas.palette import LibraryTree
from flograph.ui.favorites import Favorites


@pytest.fixture(scope="module")
def registry():
    from flograph.core import NodeRegistry
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def frames_dir(tmp_path, monkeypatch):
    """A component library of one, in place of the real user's."""
    d = tmp_path / "frames"
    user_frames.write_user_frame(d, None, "gantt example", {
        "flograph_clipboard": 1,
        "nodes": [{"id": "n1", "type": "flograph.util.note",
                   "label": "Note", "pos": [0, 0], "params": {}}],
        "connections": [],
        "frames": [{"id": "f1", "title": "Gantt example", "nodes": ["n1"]}],
    })
    import flograph.paths as paths
    monkeypatch.setattr(paths, "user_frames_dir", lambda: d)
    return d


@pytest.fixture
def tree(qtbot, registry, tmp_path, frames_dir):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    widget = LibraryTree(registry, Favorites(settings))
    qtbot.addWidget(widget)
    return widget


def _frames_section(tree):
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        if top.text(0).endswith(LibraryTree.COMPONENTS_SECTION):
            return top
    return None


def _visible_names(section):
    return [section.child(i).text(0)
            for i in range(section.childCount())
            if not section.child(i).isHidden()]


class TestComponentsAreVisible:
    def test_saved_component_shows_after_reload(self, tree):
        section = _frames_section(tree)
        assert section is not None
        assert not section.isHidden()
        assert _visible_names(section) == ["gantt example"]

    def test_search_matches_a_component_by_name(self, tree):
        tree.filter("gantt")
        section = _frames_section(tree)
        assert not section.isHidden()
        assert _visible_names(section) == ["gantt example"]

    def test_search_hides_a_component_that_does_not_match(self, tree):
        tree.filter("zzzz")
        section = _frames_section(tree)
        assert section.isHidden()

    def test_clearing_the_search_brings_it_back(self, tree):
        tree.filter("zzzz")
        tree.filter("")
        section = _frames_section(tree)
        assert not section.isHidden()
        assert _visible_names(section) == ["gantt example"]
