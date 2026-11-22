"""A fitted column is never narrower than its header. The full editor
fitted its columns before its header stylesheet (and its padding) applied,
so names came out clipped ("regior", "margir"); the view now re-fits once
a style or font change settles, which also covers a live theme switch."""
from flograph.ui.spreadsheet import SheetEditorDialog


def test_editor_columns_fit_their_headers(qtbot):
    dialog = SheetEditorDialog({"columns": ["region", "revenue", "margin"],
                                "rows": [["West", "14600", "5800"]]})
    qtbot.addWidget(dialog)
    dialog.show()
    header = dialog.view.horizontalHeader()

    def fitted():
        return all(dialog.view.columnWidth(c) >= header.sectionSizeHint(c)
                   for c in range(3))

    qtbot.waitUntil(fitted, timeout=3000)
