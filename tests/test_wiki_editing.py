"""Editing pages and navigation in the Markdown Wiki card."""

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QMessageBox

from flograph.ui.wiki.view import WikiView, _NavEditor, _SLUG_ROLE


@pytest.fixture
def wiki(qtbot, tmp_path):
    (tmp_path / "Home.md").write_text(
        "# Home\n\nSee [[Setup]] and [[New Page]].\n", encoding="utf-8")
    (tmp_path / "Setup.md").write_text("# Setup\n\nOriginal text.\n",
                                        encoding="utf-8")
    (tmp_path / "_Sidebar.md").write_text(
        "- [[Home]]\n- [[Setup]]\n", encoding="utf-8")
    view = WikiView(folder=str(tmp_path), editable=True)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.show()
    return view


class TestWikiEditing:
    def test_writable_wiki_opens_in_read_mode(self, wiki):
        assert not wiki._editing
        assert wiki._stack.currentWidget() is wiki.browser
        assert not wiki._edit.isHidden()
        assert not wiki._manage_pages.isHidden()

    def test_page_operations_live_in_one_compact_menu(self, wiki):
        labels = [action.text() for action in wiki._manage_pages.menu().actions()
                  if not action.isSeparator()]
        assert labels == ["New page…", "Rename current page…",
                          "Delete current page…", "Organize navigation…"]

    def test_edit_save_writes_and_renders_the_current_page(self, wiki):
        page = wiki.browser._catalog["home"]
        wiki._edit.click()
        assert wiki._editing
        wiki.editor.setPlainText("# Home\n\nEdited from the Wiki card.\n")
        wiki.editor.document().setModified(True)
        assert wiki._save.isEnabled()

        assert wiki._save_page()

        assert page.path.read_text(encoding="utf-8").endswith(
            "Edited from the Wiki card.\n")
        assert "Edited from the Wiki card." in wiki.browser.toPlainText()
        assert not wiki.editor.document().isModified()
        assert wiki._stack.currentWidget() is wiki.browser
        assert not wiki._editing

    def test_missing_wikilink_offers_to_create_a_page(self, wiki, tmp_path):
        wiki.browser._on_anchor(QUrl("newpage:new-page"))
        assert not wiki._missing_action.isHidden()
        wiki._missing_action.click()

        assert (tmp_path / "New-Page.md").exists()
        assert wiki.current_slug() == "new-page"
        assert wiki._editing

    def test_missing_link_in_a_rendered_page_is_clickable(self, wiki):
        html = wiki.browser.document().toHtml()
        assert 'href="newpage:new-page"' in html
        wiki.browser._on_anchor(QUrl("newpage:new-page"))
        assert not wiki._missing_action.isHidden()
        assert not wiki._rename_page_action.isEnabled()
        wiki.show_page("setup")
        assert wiki._missing_action.isHidden()
        assert wiki._rename_page_action.isEnabled()

    def test_rename_rewrites_links_and_updates_the_current_page(
            self, wiki, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "flograph.ui.wiki.view.QInputDialog.getText",
            lambda *args, **kwargs: ("Installation", True))
        wiki.show_page("setup")

        wiki._rename_current_page()

        assert not (tmp_path / "Setup.md").exists()
        assert (tmp_path / "Installation.md").exists()
        assert "[[installation|Installation]]" in (tmp_path / "Home.md").read_text(
            encoding="utf-8")
        assert wiki.current_slug() == "installation"
        assert not wiki.browser.can_go_back()

    def test_delete_removes_current_page_and_selects_home(
            self, wiki, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "flograph.ui.wiki.view.QMessageBox.question",
            lambda *args, **kwargs: QMessageBox.Yes)
        wiki.show_page("setup")

        wiki._delete_current_page()

        assert not (tmp_path / "Setup.md").exists()
        assert wiki.current_slug() == "home"
        assert not wiki.browser.can_go_back()
        assert "setup" not in (tmp_path / "_Sidebar.md").read_text(
            encoding="utf-8").lower()

    @pytest.mark.parametrize("choice,expected_slug,expected_text", [
        ("Save", "setup", "Unsaved edit."),
        ("Discard", "setup", "See [[Setup]]"),
    ])
    def test_navigation_prompts_before_leaving_modified_page(
            self, wiki, tmp_path, monkeypatch, choice, expected_slug,
            expected_text):
        def choose(box):
            box._test_choice = next(button for button in box.buttons()
                                     if button.text() == choice)
            return 0

        monkeypatch.setattr(QMessageBox, "exec", choose)
        monkeypatch.setattr(QMessageBox, "clickedButton",
                            lambda box: box._test_choice)
        wiki._edit.click()
        wiki.editor.setPlainText("# Home\n\nUnsaved edit.\n")
        wiki.editor.document().setModified(True)

        wiki.nav.setCurrentItem(wiki._slug_items["setup"])

        assert wiki.current_slug() == expected_slug
        assert not wiki._editing
        home_text = (tmp_path / "Home.md").read_text(encoding="utf-8")
        assert expected_text in home_text

    def test_cancel_keeps_the_editor_and_current_page(self, wiki, monkeypatch):
        def choose(box):
            box._test_choice = next(button for button in box.buttons()
                                     if button.text() == "Cancel")
            return 0

        monkeypatch.setattr(QMessageBox, "exec", choose)
        monkeypatch.setattr(QMessageBox, "clickedButton",
                            lambda box: box._test_choice)
        wiki._edit.click()
        wiki.editor.setPlainText("# Home\n\nUnsaved.\n")
        wiki.editor.document().setModified(True)

        wiki.nav.setCurrentItem(wiki._slug_items["setup"])

        assert wiki.current_slug() == "home"
        assert wiki._editing
        assert wiki.editor.document().isModified()

    def test_refreshing_the_same_folder_does_not_prompt_or_leave_editor(
            self, wiki, tmp_path):
        wiki._edit.click()
        wiki.editor.setPlainText("# Home\n\nUnsaved.\n")
        wiki.editor.document().setModified(True)

        wiki.set_folder(str(tmp_path))

        assert wiki._editing
        assert wiki.editor.document().isModified()

    def test_bundled_handbook_explains_why_editing_is_hidden(self, qtbot):
        view = WikiView(editable=True)
        qtbot.addWidget(view)

        assert view._edit.isHidden()
        assert view._readonly_reason.text() == "The bundled handbook is read-only"

    def test_help_view_stays_read_only_without_an_explanation_label(self, qtbot):
        view = WikiView()
        qtbot.addWidget(view)

        assert view._edit.isHidden()
        assert view._readonly_reason.isHidden()

    def test_unwritable_folder_explains_why_controls_are_hidden(
            self, qtbot, tmp_path, monkeypatch):
        (tmp_path / "Home.md").write_text("# Home\n", encoding="utf-8")
        monkeypatch.setattr("flograph.ui.wiki.view.os.access",
                            lambda path, mode: False)
        view = WikiView(folder=str(tmp_path), editable=True)
        qtbot.addWidget(view)

        assert view._edit.isHidden()
        assert view._readonly_reason.text() == "This folder is not writable"

    def test_navigation_editor_saves_reordered_pages_and_sections(
            self, qtbot, tmp_path):
        (tmp_path / "Home.md").write_text("# Home\n", encoding="utf-8")
        (tmp_path / "Setup.md").write_text("# Setup\n", encoding="utf-8")
        dialog = _NavEditor(tmp_path)
        qtbot.addWidget(dialog)
        setup = next(item for i in range(dialog.tree.topLevelItemCount())
                     if (item := dialog.tree.topLevelItem(i)).data(
                         0, _SLUG_ROLE) == "setup")

        dialog._add_section()
        section = dialog.tree.currentItem()
        section.setText(0, "Guides")
        dialog.tree.takeTopLevelItem(dialog.tree.indexOfTopLevelItem(setup))
        section.addChild(setup)

        entries = dialog.entries()
        assert entries[-1].title == "Guides"
        assert entries[-1].children[0].slug == "setup"
