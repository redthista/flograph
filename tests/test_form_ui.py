"""The User Form widget holds edits until Submit and is safe to sync."""
import json

from PySide6.QtTest import QSignalSpy

from flograph.ui.controls import FormControl, connect_control


def _widget(qtbot, fields=("name|text*|Name|\nage|int|Age|0")):
    widget = FormControl()
    qtbot.addWidget(widget)
    widget.sync({"caption": "New person", "fields": fields, "value": ""})
    return widget


class TestFormControl:
    def test_builds_fields_and_holds_edits_until_submit(self, qtbot):
        widget = _widget(qtbot)
        submitted = QSignalSpy(widget.value_committed)
        name = widget._editors["name"]
        name.setText("Ada")
        widget._edited()

        assert submitted.count() == 0
        assert not widget._pending.isHidden()
        widget._submit_button.click()

        assert submitted.count() == 1
        assert widget._pending.isHidden()
        assert json.loads(submitted.at(0)[0]) == {"name": "Ada", "age": 0}

    def test_required_fields_block_submit_and_show_a_hint(self, qtbot):
        widget = _widget(qtbot, "email|text*|Email|")
        submitted = QSignalSpy(widget.value_committed)

        widget._submit_button.click()

        assert submitted.count() == 0
        assert "Email is required" in widget._problem.text()
        assert "#ef4444" in widget._field_labels["email"].styleSheet()

    def test_reset_restores_defaults_locally_without_submitting(self, qtbot):
        widget = _widget(qtbot, "name|text|Name|Guest")
        submitted = QSignalSpy(widget.value_committed)
        widget._editors["name"].setText("Ada")
        widget._edited()

        widget._reset_form_button.click()

        assert widget._editors["name"].text() == "Guest"
        assert submitted.count() == 0

    def test_sync_does_not_clobber_unsubmitted_typing(self, qtbot):
        widget = _widget(qtbot, "name|text|Name|")
        widget._editors["name"].setText("Draft")
        widget._edited()

        widget.sync({"caption": "Changed caption", "fields":
                     "name|text|Name|", "value": '{"name":"Saved"}'})

        assert widget._editors["name"].text() == "Draft"

    def test_sync_preserves_a_blank_required_value(self, qtbot):
        widget = _widget(qtbot, "name|text*|Name|Guest")
        widget._editors["name"].clear()
        widget._edited()

        widget.sync({"caption": "Changed caption", "fields":
                     "name|text*|Name|Guest", "value": ""})

        assert widget._editors["name"].text() == ""

    def test_schema_rebuild_preserves_matching_dirty_values(self, qtbot):
        widget = _widget(qtbot, "name|text|Name|")
        widget._editors["name"].setText("Draft")
        widget._edited()

        widget.set_upstream({"fields": [
            {"name": "name", "type": "text", "label": "Person"},
            {"name": "years", "type": "int", "label": "Years"},
        ]})

        assert widget._editors["name"].text() == "Draft"
        assert "years" in widget._editors

    def test_submit_uses_the_undoable_control_binding(self, qtbot, registry):
        from PySide6.QtGui import QUndoStack

        from flograph.core import Graph

        graph = Graph()
        node = graph.add_node(registry.instantiate("flograph.input.user_form"))
        graph.set_param(node.id, "fields", "name|text|Name|")
        stack = QUndoStack()
        widget = _widget(qtbot, "name|text|Name|")
        changed = []
        connect_control(widget, lambda: graph, lambda: stack,
                        lambda: node.id, changed.append)
        widget._editors["name"].setText("Ada")
        widget._edited()

        widget._submit_button.click()

        assert json.loads(graph.nodes[node.id].params["value"]) == {
            "name": "Ada"}
        assert stack.count() == 1
        assert changed == [node.id]
        stack.undo()
        assert graph.nodes[node.id].params["value"] == ""


def test_user_form_is_a_dashboard_tile(registry):
    from flograph.core import Graph
    from flograph.ui.dashboard.tile_item import default_tile_size, is_tile_able

    node = Graph().add_node(registry.instantiate("flograph.input.user_form"))
    assert is_tile_able(node)
    assert default_tile_size(node) == (360.0, 344.0)


def test_user_form_builds_as_a_canvas_card(qtbot, registry):
    from PySide6.QtGui import QUndoStack

    from flograph.core import Graph
    from flograph.ui.canvas import NodeGraphScene

    graph = Graph()
    scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
    node = graph.add_node(registry.instantiate("flograph.input.user_form"))

    item = scene.node_items[node.id]
    assert item.form and item.control
    assert isinstance(item._control_widget, FormControl)
