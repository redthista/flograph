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


def test_off_mode_with_no_text_emits_an_empty_payload(registry):
    out, _ = _run(registry, {"cf_mode": "off"})
    assert out == {"style": {"rules": [], "errors": []}}


def test_structured_colour_scale_emits_a_rule_dict(registry):
    out, _ = _run(registry, {"cf_mode": "colour scale", "cf_columns": "revenue",
                             "cf_scale": "blue"})
    (rule,) = out["style"]["rules"]
    assert rule["mode"] == "color_scale" and rule["columns"] == ["revenue"]


def test_structured_and_text_rules_combine(registry):
    out, ctx = _run(registry, {"cf_mode": "data bars", "cf_columns": "units",
                               "format_rules": "revenue scale green"})
    assert [r["mode"] for r in out["style"]["rules"]] == ["data_bar", "color_scale"]
    assert any("2 rule" in m for m in ctx.logs)


def test_malformed_text_rule_is_carried_not_raised(registry):
    out, ctx = _run(registry, {"format_rules": "revenue scale nonsense"})
    assert out["style"]["rules"] == []
    assert len(out["style"]["errors"]) == 1
    assert any("not understood" in m for m in ctx.logs)


def test_style_payload_is_json_plain(registry):
    import json
    out, _ = _run(registry, {"format_rules": "a >= 1 => bg red, bold\n"
                                             "b scale green\nc icons traffic"})
    json.dumps(out["style"])  # must not raise
