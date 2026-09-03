"""The Table Style node — a no-input node that emits a rule payload."""
import pytest

from flograph.core import NodeRegistry, compile_run
from flograph.core.datatypes import PortType
from tests.conftest import FakeContext


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def _run(registry, params):
    spec = registry.get("flograph.viz.table_style")
    defaults = spec.default_params()
    defaults.update(params)
    run = compile_run(spec.source, "test-table-style")
    ctx = FakeContext(params=defaults)
    return run(ctx), ctx


def test_registered_with_no_input_and_a_style_output(registry):
    spec = registry.get("flograph.viz.table_style")
    assert list(spec.inputs) == []
    assert [p.name for p in spec.outputs] == ["style"]
    assert spec.outputs[0].type == PortType.OBJECT
    assert [p.name for p in spec.params] == ["format_rules", "hide"]
    assert spec.param("format_rules").rule_wizard is True


def test_empty_rules_emit_an_empty_payload(registry):
    out, _ = _run(registry, {})
    assert out == {"style": {"rules": [], "hide": [], "errors": []}}


def test_rules_box_becomes_rule_dicts(registry):
    out, _ = _run(registry, {"format_rules": "revenue scale blue\nunits bar green"})
    assert [r["mode"] for r in out["style"]["rules"]] == ["color_scale", "data_bar"]


def test_hide_from_the_box_and_the_param(registry):
    out, _ = _run(registry, {"format_rules": "sla iconmap x: a=b\nhide sla",
                             "hide": "secret"})
    assert set(out["style"]["hide"]) == {"sla", "secret"}


def test_malformed_line_is_carried_not_raised(registry):
    out, ctx = _run(registry, {"format_rules": "revenue scale nonsense"})
    assert out["style"]["rules"] == [] and len(out["style"]["errors"]) == 1
    assert any("not understood" in m for m in ctx.logs)


def test_style_payload_is_json_plain(registry):
    import json
    out, _ = _run(registry, {"format_rules": "a >= 1 => bg red, bold\n"
                                             "b scale green\nc icons traffic"})
    json.dumps(out["style"])  # must not raise
