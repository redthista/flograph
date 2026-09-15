from flograph.ui.report.css_snippets import list_snippets, read_snippet, save_snippet


def test_css_snippets_are_saved_in_the_user_data_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path))
    path = save_snippet("Quarterly / Blue", "body { color: blue; }")
    assert path == tmp_path / "css" / "Quarterly-Blue.css"
    assert list_snippets() == [path]
    assert read_snippet(path) == "body { color: blue; }"


def test_css_snippet_names_are_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path))
    path = save_snippet("  ", "body {}")
    assert path.name == "snippet.css"
