"""Bool columns: a tick box in every cell from the moment a column is made
bool, blank meaning unticked — on the grid and down the flow alike."""
import json

import pytest
from PySide6.QtCore import Qt

from flograph.core import NodeRegistry
from flograph.ui.spreadsheet import SheetModel


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def test_a_blank_bool_cell_is_an_unticked_box(qtbot):
    model = SheetModel({"version": 2,
                        "columns": [{"name": "done", "type": "bool"}],
                        "rows": [[""], ["TRUE"]]})
    assert model.index(0, 0).data(Qt.CheckStateRole) == Qt.Unchecked
    assert model.index(1, 0).data(Qt.CheckStateRole) == Qt.Checked
    assert model.flags(model.index(0, 0)) & Qt.ItemIsUserCheckable


def test_switching_to_bool_shows_boxes_and_converts_words(qtbot):
    model = SheetModel({"version": 2,
                        "columns": [{"name": "done", "type": "auto"}],
                        "rows": [[""], ["yes"], ["0"], ["maybe"]]})
    model.set_column_type(0, "bool")
    assert [r[0] for r in model.sheet.rows] == ["", "TRUE", "FALSE",
                                                 "maybe"]
    assert model.index(0, 0).data(Qt.CheckStateRole) == Qt.Unchecked
    assert model.index(3, 0).data(Qt.BackgroundRole) is not None


def test_ticking_a_blank_cell_writes_true(qtbot):
    model = SheetModel({"version": 2,
                        "columns": [{"name": "done", "type": "bool"}],
                        "rows": [[""]]})
    model.setData(model.index(0, 0), Qt.Checked.value, Qt.CheckStateRole)
    assert model.cell_source(0, 0) == "TRUE"


def test_blank_bool_flows_on_as_false(registry):
    from flograph.core import compile_run
    from tests.conftest import FakeContext
    spec = registry.get("flograph.io.table")
    run = compile_run(spec.source, "t")
    params = spec.default_params()
    params["data"] = json.dumps({
        "version": 2, "columns": [{"name": "done", "type": "bool"}],
        "rows": [[""], ["TRUE"]]})
    out = run(FakeContext(params=params))
    assert out["done"].tolist() == [False, True]
