"""`WikiView` — a folder of Markdown pages as a navigable wiki.

A nav tree on the left (from `_Sidebar.md`, the GitHub-wiki convention), a
breadcrumb and back / forward / nav-toggle over the page on the right. The
Help ▸ Documentation window and the Markdown Wiki canvas card both embed
one; the rendering, history and `[[wikilink]]` handling live in
`DocsBrowser`.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout,
    QInputDialog, QLabel, QMenu, QMessageBox, QPlainTextEdit, QSplitter,
    QStackedWidget, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget)

from flograph.core import docpages
from flograph.core.docpages import breadcrumb, resolve_wiki_dir, sidebar

from .browser import DocsBrowser

_SLUG_ROLE = Qt.UserRole
_SECTION_ROLE = Qt.UserRole + 1


class WikiView(QWidget):
    """Signals so an owner (the card) can persist where the reader is."""

    #: the page changed (slug) — a new destination, not a back/forward step
    page_changed = Signal(str)
    #: the nav panel was shown/hidden
    nav_visibility_changed = Signal(bool)

    def __init__(self, parent=None, *, folder: str | None = None,
                 show_nav: bool = True, editable: bool = False) -> None:
        super().__init__(parent)
        self._dir: Path = resolve_wiki_dir(folder)
        self._editable = bool(editable)
        self._editing = False
        self._loading_editor = False
        self._missing_slug: str | None = None
        self._last_emitted: str | None = None
        self._slug_items: dict[str, QTreeWidgetItem] = {}

        self.browser = DocsBrowser(self, directory=self._dir,
                                   allow_missing=self._can_edit())

        self._nav_toggle = QToolButton(text="☰", toolTip="Show / hide the nav panel")
        self._nav_toggle.setCheckable(True)
        self._nav_toggle.toggled.connect(self.set_nav_visible)
        self._back = QToolButton(text="◀", toolTip="Back")
        self._forward = QToolButton(text="▶", toolTip="Forward")
        self._back.clicked.connect(self._go_back)
        self._forward.clicked.connect(self._go_forward)

        self._edit = QToolButton(text="Edit", toolTip="Edit this Markdown page")
        self._edit.setCheckable(True)
        self._edit.toggled.connect(self._set_editing)
        self._save = QToolButton(text="Save")
        self._save.clicked.connect(self._save_page)
        self._cancel_edit = QToolButton(text="Cancel")
        self._cancel_edit.clicked.connect(self._cancel_editing)
        self._manage_pages = QToolButton(text="Pages")
        self._manage_pages.setPopupMode(QToolButton.InstantPopup)
        page_menu = QMenu(self._manage_pages)
        self._new_page_action = page_menu.addAction("New page…", self._create_page)
        self._rename_page_action = page_menu.addAction(
            "Rename current page…", self._rename_current_page)
        self._delete_page_action = page_menu.addAction(
            "Delete current page…", self._delete_current_page)
        page_menu.addSeparator()
        self._organize_action = page_menu.addAction(
            "Organize navigation…", self._organize_pages)
        self._manage_pages.setMenu(page_menu)
        self._readonly_reason = QLabel()
        self._readonly_reason.setObjectName("wikiReadonlyReason")
        self._missing_action = QToolButton()
        self._missing_action.hide()
        self._missing_action.clicked.connect(self._create_missing_page)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("wikiMarkdownEditor")
        self.editor.textChanged.connect(self._editor_changed)
        self._stack = QStackedWidget()
        self._stack.addWidget(self.browser)
        self._stack.addWidget(self.editor)

        self._crumb = QLabel()
        self._crumb.setTextFormat(Qt.RichText)
        self._crumb.linkActivated.connect(
            lambda slug: self.browser.show_page(slug))

        bar = QHBoxLayout()
        bar.setContentsMargins(2, 2, 2, 2)
        for btn in (self._nav_toggle, self._back, self._forward):
            bar.addWidget(btn)
        self._readonly_reason.hide()
        bar.addWidget(self._readonly_reason)
        bar.addWidget(self._missing_action)
        for btn in (self._edit, self._save, self._cancel_edit,
                    self._manage_pages):
            bar.addWidget(btn)
        bar.addSpacing(6)
        bar.addWidget(self._crumb, 1)

        self.nav = QTreeWidget()
        self.nav.setHeaderHidden(True)
        self.nav.setIndentation(12)
        self.nav.currentItemChanged.connect(self._nav_selected)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addLayout(bar)
        right_layout.addWidget(self._stack, 1)

        self._split = QSplitter(Qt.Horizontal)
        self._split.addWidget(self.nav)
        self._split.addWidget(right)
        self._split.setStretchFactor(0, 0)
        self._split.setStretchFactor(1, 1)
        self._split.setSizes([220, 620])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._split)

        self._build_nav()
        self.browser.navigated.connect(self._sync)
        self.browser.page_missing.connect(self._on_missing_page)
        self._update_edit_controls()
        self.set_nav_visible(show_nav)
        self._sync()

    # ------------------------------------------------------------- public

    def set_folder(self, folder: str | None) -> None:
        new_dir = resolve_wiki_dir(folder)
        if new_dir == self._dir:
            return
        if not self._confirm_leave_editor():
            return
        self._dir = new_dir
        self._last_emitted = None
        self.browser.set_folder(new_dir, allow_missing=self._can_edit())
        self._build_nav()
        self._missing_slug = None
        self._missing_action.hide()
        self._update_edit_controls()
        self._sync()

    def show_page(self, slug: str) -> None:
        if slug and slug != self.browser.current_slug():
            if not self._confirm_leave_editor():
                return
            self.browser.show_page(slug)

    def _can_edit(self) -> bool:
        return (self._editable and not docpages.is_bundled_docs(self._dir)
                and self._dir.is_dir() and os.access(self._dir, os.W_OK))

    def _readonly_message(self) -> str:
        if not self._editable:
            return ""
        if docpages.is_bundled_docs(self._dir):
            return "The bundled handbook is read-only"
        if not self._dir.is_dir() or not os.access(self._dir, os.W_OK):
            return "This folder is not writable"
        return ""

    def _update_edit_controls(self) -> None:
        allowed = self._can_edit()
        current = self._current_page()
        page_writable = bool(current and os.access(current.path, os.W_OK))
        self._edit.setVisible(allowed and page_writable and not self._editing)
        self._manage_pages.setVisible(allowed and not self._editing)
        self._save.setVisible(allowed and self._editing)
        self._cancel_edit.setVisible(allowed and self._editing)
        reason = self._readonly_message()
        if allowed and current is not None and not page_writable:
            reason = "This page is not writable"
        self._readonly_reason.setText(reason)
        self._readonly_reason.setVisible(bool(reason))
        self._rename_page_action.setEnabled(current is not None)
        self._delete_page_action.setEnabled(current is not None)

    def _current_page(self):
        if self._missing_slug:
            return None
        slug = self.browser.current_slug()
        return self.browser._catalog.get(slug) if slug else None

    def _set_editing(self, editing: bool) -> None:
        if not editing:
            if not self._confirm_leave_editor():
                self._edit.blockSignals(True)
                self._edit.setChecked(True)
                self._edit.blockSignals(False)
                return
            self._editing = False
            self._stack.setCurrentWidget(self.browser)
            self._update_edit_controls()
            return
        page = self._current_page()
        if page is None or not self._can_edit():
            self._edit.blockSignals(True)
            self._edit.setChecked(False)
            self._edit.blockSignals(False)
            return
        try:
            self._loading_editor = True
            self.editor.setPlainText(page.path.read_text(encoding="utf-8"))
            self.editor.document().setModified(False)
        except OSError as exc:
            QMessageBox.warning(self, "Can't edit page", str(exc))
            self._edit.blockSignals(True)
            self._edit.setChecked(False)
            self._edit.blockSignals(False)
            return
        finally:
            self._loading_editor = False
        self._editing = True
        self._stack.setCurrentWidget(self.editor)
        self._update_edit_controls()

    def _editor_changed(self) -> None:
        if not self._loading_editor:
            self._sync_edit_label()

    def _sync_edit_label(self) -> None:
        changed = self._editing and self.editor.document().isModified()
        self._edit.setText("Edit*" if changed else "Edit")
        self._save.setEnabled(bool(changed))
        self._cancel_edit.setText("Cancel*" if changed else "Cancel")

    def _save_page(self) -> bool:
        page = self._current_page()
        if page is None:
            return False
        try:
            docpages._atomic_write(page.path, self.editor.toPlainText())
        except OSError as exc:
            QMessageBox.warning(self, "Couldn't save page", str(exc))
            return False
        self.editor.document().setModified(False)
        self.browser.reload_page(page.slug)
        self._build_nav()
        self._leave_editor(discard=False)
        self._sync()
        self._sync_edit_label()
        return True

    def _confirm_leave_editor(self) -> bool:
        if not self._editing:
            return True
        if not self.editor.document().isModified():
            self._leave_editor(discard=False)
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved Wiki page")
        box.setText("Save changes to this page before leaving?")
        save = box.addButton("Save", QMessageBox.AcceptRole)
        discard = box.addButton("Discard", QMessageBox.DestructiveRole)
        cancel = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(save)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save:
            if not self._save_page():
                return False
        elif clicked is discard:
            self._leave_editor(discard=True)
        elif clicked is cancel:
            return False
        else:
            return False
        self._leave_editor(discard=False)
        return True

    def _leave_editor(self, *, discard: bool) -> None:
        if discard:
            self.editor.document().setModified(False)
        self._editing = False
        self._stack.setCurrentWidget(self.browser)
        self._edit.blockSignals(True)
        self._edit.setChecked(False)
        self._edit.blockSignals(False)
        self._update_edit_controls()

    def _cancel_editing(self) -> None:
        if not self._confirm_leave_editor():
            return

    def _go_back(self) -> None:
        if self._confirm_leave_editor():
            self.browser.go_back()

    def _go_forward(self) -> None:
        if self._confirm_leave_editor():
            self.browser.go_forward()

    def _on_missing_page(self, slug: str) -> None:
        if not self._can_edit():
            return
        self._missing_slug = slug
        self._missing_action.setText(f"Create '{slug.replace('-', ' ')}'")
        self._missing_action.show()
        self._update_edit_controls()

    def _create_page(self, title: str | None = None) -> None:
        if not self._can_edit():
            return
        if title is None:
            title, accepted = QInputDialog.getText(self, "New Wiki page",
                                                    "Page title:")
            if not accepted:
                return
        title = title.strip()
        if not title:
            return
        try:
            page = docpages.create_page(self._dir, title)
        except (OSError, ValueError, FileExistsError) as exc:
            QMessageBox.warning(self, "Couldn't create page", str(exc))
            return
        self._refresh_pages(page.slug)
        self._edit.setChecked(True)

    def _create_missing_page(self) -> None:
        slug = self._missing_slug
        if not slug:
            return
        title = slug.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").title()
        self._create_page(title)

    def _rename_current_page(self) -> None:
        page = self._current_page()
        if page is None or not self._can_edit():
            return
        title, accepted = QInputDialog.getText(self, "Rename Wiki page",
                                                "Page title:", text=page.title)
        if not accepted or not title.strip() or title.strip() == page.title:
            return
        try:
            renamed = docpages.rename_page(self._dir, page.slug, title.strip())
        except (OSError, ValueError, FileExistsError) as exc:
            QMessageBox.warning(self, "Couldn't rename page", str(exc))
            return
        self._refresh_pages(renamed.slug)

    def _delete_current_page(self) -> None:
        page = self._current_page()
        if page is None or not self._can_edit():
            return
        answer = QMessageBox.question(
            self, "Delete Wiki page",
            f"Delete '{page.title}'? Its links will remain as unresolved text.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return
        try:
            docpages.delete_page(self._dir, page.slug)
        except OSError as exc:
            QMessageBox.warning(self, "Couldn't delete page", str(exc))
            return
        self._refresh_pages(None)

    def _organize_pages(self) -> None:
        if not self._can_edit():
            return
        dialog = _NavEditor(self._dir, self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            docpages.write_sidebar(self._dir, dialog.entries())
        except OSError as exc:
            QMessageBox.warning(self, "Couldn't save navigation", str(exc))
            return
        self._build_nav()
        self._sync()

    def _refresh_pages(self, slug: str | None) -> None:
        self.browser.reload_catalog()
        self._missing_slug = None
        self._missing_action.hide()
        self._build_nav()
        if slug:
            self.browser.show_page(slug)
        else:
            self.browser.go_home()
        self._update_edit_controls()
        self._sync()

    def current_slug(self) -> str | None:
        return self.browser.current_slug()

    def set_nav_visible(self, visible: bool) -> None:
        visible = bool(visible)
        self.nav.setVisible(visible)
        if self._nav_toggle.isChecked() != visible:
            self._nav_toggle.blockSignals(True)
            self._nav_toggle.setChecked(visible)
            self._nav_toggle.blockSignals(False)
        self.nav_visibility_changed.emit(visible)

    def nav_visible(self) -> bool:
        return self._nav_toggle.isChecked()

    # -------------------------------------------------------------- nav

    def _build_nav(self) -> None:
        self.nav.clear()
        self._slug_items.clear()

        def add(parent, entries) -> None:
            for entry in entries:
                item = QTreeWidgetItem(parent, [entry.title])
                if entry.slug:
                    item.setData(0, _SLUG_ROLE, entry.slug)
                    self._slug_items[entry.slug] = item
                else:  # a section header — shown, not selectable
                    item.setFlags(Qt.ItemIsEnabled)
                    font = item.font(0)
                    font.setBold(True)
                    item.setFont(0, font)
                add(item, entry.children)

        add(self.nav.invisibleRootItem(), sidebar(self._dir))
        self.nav.expandAll()

    def _nav_selected(self, item, _previous) -> None:
        if item is None:
            return
        slug = item.data(0, _SLUG_ROLE)
        if slug and slug != self.browser.current_slug():
            if not self._confirm_leave_editor():
                self._sync()
                return
            self._missing_slug = None
            self._missing_action.hide()
            self.browser.show_page(slug)

    # ------------------------------------------------------------- sync

    def _sync(self) -> None:
        self._back.setEnabled(self.browser.can_go_back())
        self._forward.setEnabled(self.browser.can_go_forward())
        slug = self.browser.current_slug()
        if self._missing_slug and slug and slug != self._last_emitted:
            self._missing_slug = None
            self._missing_action.hide()
        self._update_edit_controls()

        item = self._slug_items.get(slug)
        if item is not None and item is not self.nav.currentItem():
            self.nav.blockSignals(True)
            self.nav.setCurrentItem(item)
            self.nav.blockSignals(False)

        self._crumb.setText(self._crumb_html(slug))

        if slug and slug != self._last_emitted:
            self._last_emitted = slug
            self.page_changed.emit(slug)

    def _crumb_html(self, slug: str | None) -> str:
        if not slug:
            return ""
        trail = breadcrumb(slug, sidebar(self._dir))
        if not trail:
            page = self.browser._catalog.get(slug)
            return f"<b>{page.title if page else slug}</b>"
        parts = []
        for i, entry in enumerate(trail):
            last = i == len(trail) - 1
            if entry.slug and not last:
                parts.append(f'<a href="{entry.slug}">{entry.title}</a>')
            elif last:
                parts.append(f"<b>{entry.title}</b>")
            else:
                parts.append(entry.title)
        return ' <span style="color:#777">›</span> '.join(parts)


class _NavEditor(QDialog):
    """Drag pages between sections and reorder them before saving `_Sidebar`."""

    def __init__(self, directory: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Organize Wiki pages")
        self.resize(420, 520)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setDragDropMode(QTreeWidget.InternalMove)
        self._load_entries(sidebar(directory))
        add = QToolButton(text="Add section")
        add.clicked.connect(self._add_section)
        remove = QToolButton(text="Remove section")
        remove.clicked.connect(self._remove_section)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Drag pages to reorder them or move them into sections."))
        layout.addWidget(self.tree, 1)
        layout.addLayout(row)
        layout.addWidget(buttons)

    def _load_entries(self, entries) -> None:
        def add(parent, children):
            for entry in children:
                item = QTreeWidgetItem(parent, [entry.title])
                item.setData(0, _SLUG_ROLE, entry.slug)
                item.setData(0, _SECTION_ROLE, entry.slug is None)
                if entry.slug is None:
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                add(item, entry.children)
        add(self.tree.invisibleRootItem(), entries)
        self.tree.expandAll()

    def _add_section(self) -> None:
        parent = self.tree.currentItem() or self.tree.invisibleRootItem()
        if parent is not self.tree.invisibleRootItem() and not parent.data(0, _SECTION_ROLE):
            parent = parent.parent() or self.tree.invisibleRootItem()
        item = QTreeWidgetItem(parent, ["New section"])
        item.setData(0, _SLUG_ROLE, None)
        item.setData(0, _SECTION_ROLE, True)
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self.tree.setCurrentItem(item)
        self.tree.editItem(item, 0)

    def _remove_section(self) -> None:
        item = self.tree.currentItem()
        if item is None or not item.data(0, _SECTION_ROLE):
            return
        parent = item.parent() or self.tree.invisibleRootItem()
        index = parent.indexOfChild(item) if parent is not self.tree.invisibleRootItem() else self.tree.indexOfTopLevelItem(item)
        children = [item.takeChild(0) for _ in range(item.childCount())]
        for offset, child in enumerate(children):
            if parent is self.tree.invisibleRootItem():
                self.tree.insertTopLevelItem(index + offset, child)
            else:
                parent.insertChild(index + offset, child)
        if parent is self.tree.invisibleRootItem():
            self.tree.takeTopLevelItem(index + len(children))
        else:
            parent.takeChild(index + len(children))

    def entries(self):
        def walk(parent):
            output = []
            for i in range(parent.childCount()):
                item = parent.child(i)
                slug = item.data(0, _SLUG_ROLE)
                output.append(docpages.NavEntry(
                    item.text(0), slug,
                    tuple(walk(item))))
            return output
        return walk(self.tree.invisibleRootItem())
