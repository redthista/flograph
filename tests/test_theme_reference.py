"""The theme reference, the handbook page built from it, and the checks."""
import sys
from pathlib import Path

import pytest

from flograph.ui import themes
from flograph.ui.themes import reference
from flograph.ui.themes.check import check, contrast

ROOT = Path(__file__).resolve().parent.parent


def test_every_key_has_a_description_and_none_is_left_over():
    dark = themes.load("dark")
    have = {f"{s}.{k}" for s, items in dark.values.items() for k in items}
    assert have - set(reference.REFERENCE) == set()
    assert set(reference.REFERENCE) - have == set()


def test_the_handbook_page_is_current():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import gen_theme_docs
    finally:
        sys.path.pop(0)
    page = ROOT / "src" / "flograph" / "docs" / "Themes.md"
    assert page.read_text(encoding="utf-8") == gen_theme_docs.build(), (
        "run: python scripts/gen_theme_docs.py")


def test_the_light_themes_pass_their_own_checks():
    for name in ("light", "light_steel"):
        assert check(themes.load(name)) == [], name


def test_low_contrast_is_flagged_with_the_settings_involved():
    t = themes.with_overrides(themes.load("light"), {
        "ui": {"input_focus": "#fafafa"},
        "wires": {"dataframe": "#e0e0e0"}})
    found = check(t)
    text = " | ".join(i.message for i in found)
    assert "keyboard focus ring" in text and "dataframe wires" in text
    focus = next(i for i in found if "focus ring on an input" in i.message)
    assert ("ui", "input_focus") in focus.where
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)


def test_a_user_theme_with_bad_values_loads_and_says_what_it_ignored(tmp_path):
    (tmp_path / "messy.toml").write_text(
        '[meta]\nlabel = "Messy"\nbased_on = "light"\n'
        '[canvas]\nCANVAS_BG = "nope"\nNODE_BODY = "#123456"\n'
        '[ui]\nnot_a_setting = "#ffffff"\n'
        '[style]\nnode_width = 5\nnode_corner_radius = 3\n', encoding="utf-8")
    t = themes.load("messy", tmp_path)
    light = themes.load("light")
    # the good values apply …
    assert t.get("canvas", "NODE_BODY") == "#123456"
    assert t.get("style", "node_corner_radius") == 3
    # … the bad ones fall back to what the theme sits on
    assert t.get("canvas", "CANVAS_BG") == light.get("canvas", "CANVAS_BG")
    assert t.get("style", "node_width") == light.get("style", "node_width")
    assert "not_a_setting" not in t.values["ui"]
    text = " | ".join(t.problems)
    assert "messy.toml line 5" in text and "CANVAS_BG" in text
    assert "not_a_setting" in text and "node_width" in text
    assert themes.load("light").problems == []


def test_input_checks_wait_for_flat_controls():
    dark = themes.with_overrides(themes.load("dark"), {
        "ui": {"input_focus": "#1e2024"}})
    assert not any("focus ring" in i.message for i in check(dark))
