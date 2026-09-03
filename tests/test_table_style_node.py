"""The Table Style node — turns params into a list of rule dicts on `style`."""
import pandas as pd
import pytest

from flograph.core import NodeRegistry, compile_run
from flograph.core.datatypes import PortType
from tests.conftest import FakeContext


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def _run(registry, params, **inputs):
    spec = registry.get("flograph.viz.table_style")
    defaults = spec.default_params()
    defaults.update(params)
    run = compile_run(spec.source, "test-table-style")
    ctx = FakeContext(params=defaults)
    return run(ctx, **inputs), ctx


def test_registered_with_optional_table_in_and_style_out(registry):
    spec = registry.get("flograph.viz.table_style")
    assert [p.name for p in spec.inputs] == ["table"]
    assert spec.inputs[0].optional is True
    assert [p.name for p in spec.outputs] == ["style"]
    assert spec.outputs[0].type == PortType.OBJECT


def test_off_mode_with_no_text_emits_empty_style(registry):
    out, _ = _run(registry, {"cf_mode": "off"})
    assert out == {"style": []}


def test_structured_colour_scale_emits_a_rule_dict(registry):
    out, _ = _run(registry, {"cf_mode": "colour scale", "cf_columns": "revenue",
                             "cf_scale": "blue"})
    (rule,) = out["style"]
    assert rule["mode"] == "color_scale" and rule["columns"] == ["revenue"]


def test_structured_and_text_rules_combine(registry):
    out, ctx = _run(registry, {"cf_mode": "data bars", "cf_columns": "units",
                               "format_rules": "revenue scale green"})
    assert [r["mode"] for r in out["style"]] == ["data_bar", "color_scale"]
    assert any("2 rule" in m for m in ctx.logs)


def test_malformed_text_rule_raises(registry):
    with pytest.raises(ValueError, match="line 1"):
        _run(registry, {"format_rules": "revenue scale nonsense"})


def test_unknown_column_logs_but_does_not_raise(registry):
    df = pd.DataFrame({"a": [1, 2]})
    out, ctx = _run(registry, {"format_rules": "missing scale green"}, table=df)
    assert out["style"] and any("not in the table" in m for m in ctx.logs)


def test_style_payload_is_json_plain(registry):
    import json
    out, _ = _run(registry, {"format_rules": "a >= 1 => bg red, bold\n"
                                             "b scale green\nc icons traffic"})
    json.dumps(out["style"])  # must not raise
