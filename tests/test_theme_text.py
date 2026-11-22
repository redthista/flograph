"""The customiser's text form of a theme: written out, and read back."""
from flograph.ui import themes
from flograph.ui.themes.text import full_text, parse_text


def test_an_untouched_theme_reads_back_as_no_changes():
    base = themes.load("light")
    result = parse_text(full_text(base), base)
    assert result.problems == [] and result.overrides == {}


def test_a_changed_value_is_the_only_override():
    base = themes.load("light")
    old = base.get("canvas", "CANVAS_BG")
    text = full_text(base).replace(f'CANVAS_BG = "{old}"',
                                   'CANVAS_BG = "#ABCDEF"')
    result = parse_text(text, base)
    assert result.problems == []
    assert result.overrides == {"canvas": {"CANVAS_BG": "#abcdef"}}


def test_every_kind_of_mistake_names_its_line():
    base = themes.load("light")
    text = ('[ui]\nwindow = "red"\nbogus = 1\n'
            '[style]\nnode_shadow = 3\ndivider_width = 1.5\n'
            '[frame]\nFRAME_FILL = 7\n[nope]\nx = 1\n')
    problems = {p.line: p.message for p in parse_text(text, base).problems}
    assert "window" in problems[2]
    assert "bogus" in problems[3]
    assert "node_shadow" in problems[5]
    assert "divider_width" in problems[6]
    assert "FRAME_FILL" in problems[8]
    assert "nope" in problems[9]


def test_node_shape_settings_are_range_checked():
    base = themes.load("light")
    ok = parse_text('[style]\nnode_corner_radius = 0\nnode_width = 220\n',
                    base)
    assert ok.problems == []
    assert ok.overrides == {"style": {"node_corner_radius": 0,
                                      "node_width": 220}}
    bad = parse_text('[style]\nnode_corner_radius = 99\nnode_width = 5\n',
                     base)
    assert [p.line for p in bad.problems] == [2, 3]
    assert "from 0 to 40" in bad.problems[0].message


def test_broken_toml_is_one_problem_with_a_line():
    base = themes.load("light")
    problems = parse_text('[ui]\nwindow = "#fff\n', base).problems
    assert len(problems) == 1 and problems[0].line == 2
