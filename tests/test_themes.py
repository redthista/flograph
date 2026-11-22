"""Themes as data: the loader (Qt-free), the built-in files, user themes,
and the one promise the light theme makes — readable text."""
import pytest

from flograph.ui import themes


def _ratio(a: str, b: str) -> float:
    """WCAG contrast ratio of two #rrggbb colours."""
    def lum(h):
        out = []
        for i in (1, 3, 5):
            c = int(h[i:i + 2], 16) / 255
            out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class TestBuiltins:
    def test_both_ship(self):
        assert themes.available()[:2] == ["light", "dark"]

    @pytest.mark.parametrize("name", themes.BUILTIN)
    def test_sets_nothing_the_reference_does_not_know(self, name):
        """A misspelt key in a theme would silently do nothing."""
        ref = themes.load(themes.REFERENCE)
        raw = themes._read(themes.HERE / f"{name}.toml")
        for section in themes.SECTIONS:
            unknown = set(raw.get(section, {})) - set(ref.section(section))
            assert not unknown, f"{name}.{section}: {unknown}"

    def test_light_is_light(self):
        light = themes.load("light")
        assert light.kind == "light" and light.label == "Light"
        assert light.builtin

    @pytest.mark.parametrize("bg_section,bg,fg_section,fg,minimum", [
        ("ui", "base", "ui", "text", 7.0),
        ("ui", "window", "ui", "window_text", 7.0),
        ("ui", "window", "ui", "mid", 4.5),          # secondary text
        ("ui", "highlight", "ui", "highlighted_text", 4.5),
        ("canvas", "NODE_BODY", "canvas", "NODE_TEXT", 7.0),
        ("canvas", "NODE_BODY", "canvas", "NODE_SUBTEXT", 4.5),
        ("chrome", "bar_bg", "chrome", "fg", 4.5),
        ("editor", "EDITOR_BG", "editor", "EDITOR_FG", 7.0),
        ("editor", "EDITOR_BG", "syntax", "comment", 4.5),
        ("surface", "base", "surface", "text_dim", 4.5),
    ])
    @pytest.mark.parametrize("name", ["light", "light_steel"])
    def test_light_text_is_readable(self, name, bg_section, bg, fg_section,
                                    fg, minimum):
        t = themes.load(name)
        assert _ratio(t.get(bg_section, bg), t.get(fg_section, fg)) >= minimum

    def test_a_white_node_stands_off_the_light_canvas(self):
        t = themes.load("light")
        assert _ratio(t.get("canvas", "NODE_BODY"),
                      t.get("canvas", "CANVAS_BG")) >= 1.2
        assert _ratio(t.get("canvas", "NODE_BODY"),
                      t.get("canvas", "NODE_BORDER")) >= 2.5


class TestUserThemes:
    def test_inherits_what_it_does_not_set(self, tmp_path):
        (tmp_path / "warm.toml").write_text(
            '[meta]\nlabel = "Warm"\nbased_on = "light"\n'
            '[canvas]\nCANVAS_BG = "#ece8e1"\n')
        t = themes.load("warm", tmp_path)
        assert t.label == "Warm" and t.kind == "light"
        assert t.get("canvas", "CANVAS_BG") == "#ece8e1"
        assert t.get("canvas", "NODE_BODY") == themes.load("light").get(
            "canvas", "NODE_BODY")
        assert "warm" in themes.available(tmp_path)

    def test_defaults_to_building_on_dark(self, tmp_path):
        (tmp_path / "plain.toml").write_text('[ui]\nwindow = "#000000"\n')
        t = themes.load("plain", tmp_path)
        assert t.kind == "dark" and t.label == "Plain"
        assert t.get("ui", "window") == "#000000"

    def test_cannot_replace_a_builtin(self, tmp_path):
        (tmp_path / "light.toml").write_text('[ui]\nwindow = "#000000"\n')
        assert themes.load("light", tmp_path).get("ui", "window") != "#000000"

    def test_a_loop_is_an_error(self, tmp_path):
        (tmp_path / "a.toml").write_text('[meta]\nbased_on = "b"\n')
        (tmp_path / "b.toml").write_text('[meta]\nbased_on = "a"\n')
        with pytest.raises(themes.ThemeError):
            themes.load("a", tmp_path)

    def test_bad_toml_is_an_error(self, tmp_path):
        (tmp_path / "bad.toml").write_text("[ui\n")
        with pytest.raises(themes.ThemeError):
            themes.load("bad", tmp_path)

    def test_a_broken_user_theme_falls_back_to_dark(self, qapp, tmp_path,
                                                    monkeypatch):
        from flograph.ui import theme
        (tmp_path / "bad.toml").write_text("[ui\n")
        monkeypatch.setattr(theme, "_user_dir", lambda: tmp_path)
        try:
            theme.apply_theme(qapp, "bad")
            assert theme.current().name == "dark"
        finally:
            theme.apply_theme(qapp, "dark")

    def test_a_user_theme_drives_the_canvas_and_skin(self, qapp, tmp_path,
                                                     monkeypatch):
        from flograph.ui import theme
        (tmp_path / "mint.toml").write_text(
            '[meta]\nbased_on = "light"\n'
            '[canvas]\nCANVAS_BG = "#ddeeee"\n'
            '[surface]\nbase = "#fafffe"\n')
        monkeypatch.setattr(theme, "_user_dir", lambda: tmp_path)
        try:
            assert "mint" in theme.theme_prefs()
            theme.apply_theme(qapp, "mint")
            assert theme.CANVAS_BG.name() == "#ddeeee"
            assert theme.APP_MODE == "light"
            assert theme.skin("background: #1e2024;") == "background: #fafffe;"
        finally:
            theme.apply_theme(qapp, "dark")
