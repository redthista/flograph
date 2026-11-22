"""No built-in theme draws a drop shadow unless asked: not under a canvas
node, not under an unformatted dashboard tile. A tile whose Format turns
Shadow on still gets one, in its theme's colour."""
import pytest

from flograph.core.tile_style import TileStyle, resolve
from flograph.ui import theme
from flograph.ui.themes import BUILTIN


@pytest.fixture
def restore_theme(qapp):
    before = theme.ACTIVE.name
    yield
    theme.apply_theme(qapp, before)


@pytest.mark.parametrize("name", BUILTIN)
def test_builtin_themes_cast_no_shadow_by_default(qapp, restore_theme, name):
    theme.apply_theme(qapp, name)
    assert not theme.style("node_shadow")
    assert not theme.card_look().shadow


def test_a_tile_can_still_turn_its_shadow_on(qapp, restore_theme):
    theme.apply_theme(qapp, "light")
    look = resolve(TileStyle(shadow=True), None, theme.card_look())
    assert look.shadow is True
    assert theme.style("card_shadow") == "soft"   # the pale one, on a pale page
