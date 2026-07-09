import pytest

from flopy.core import NodeScriptError, PortType, compile_run, parse_spec
from tests.conftest import FakeContext

GOOD = """
\"\"\"Doc line.\"\"\"
NODE = {
    "label": "Adder",
    "category": "Math",
    "inputs": [("a", "number"), ("b", "number", {"optional": True})],
    "outputs": [("total", "number")],
}
PARAMS = [
    {"name": "offset", "type": "float", "default": 0.5, "label": "Offset"},
]
def run(ctx, a, b):
    return a + (b or 0) + ctx.params["offset"]
"""


class TestParseSpec:
    def test_good_spec(self):
        spec = parse_spec(GOOD, "test.adder", builtin=True)
        assert spec.label == "Adder"
        assert spec.category == "Math"
        assert spec.doc == "Doc line."
        assert spec.builtin
        assert [p.name for p in spec.inputs] == ["a", "b"]
        assert spec.inputs[1].optional and not spec.inputs[0].optional
        assert spec.outputs[0].type == PortType.NUMBER
        assert spec.params[0].default == 0.5
        assert spec.default_params() == {"offset": 0.5}

    @pytest.mark.parametrize("source, message", [
        ("x = 1", "must define a NODE dict"),
        ("NODE = {'label': 'X'}", "NODE\\['category'\\]"),
        ("NODE = {'category': 'X'}", "NODE\\['label'\\]"),
        ("NODE = {'label': 'X', 'category': 'Y', 'inputs': [('a',)]}",
         "must be \\(name, type\\)"),
        ("NODE = {'label': 'X', 'category': 'Y', 'inputs': [('a', 'dframe')]}",
         "unknown port type 'dframe'"),
        ("NODE = {'label': 'X', 'category': 'Y', "
         "'inputs': [('a', 'any'), ('a', 'any')]}", "duplicate port name"),
        ("NODE = {'label': 'X', 'category': 'Y', 'inputs': [('2bad', 'any')]}",
         "valid identifier"),
        ("NODE = {'label': 'X', 'category': 'Y', 'outputs': [('o', 'any')]}",
         "must define a run"),
    ])
    def test_bad_specs(self, source, message):
        with pytest.raises(NodeScriptError, match=message):
            parse_spec(source, "test.bad")

    def test_bad_param(self):
        source = GOOD.replace('"type": "float"', '"type": "flt"')
        with pytest.raises(NodeScriptError, match="unknown type 'flt'"):
            parse_spec(source, "test.bad")

    def test_syntax_error_reports_line(self):
        with pytest.raises(NodeScriptError, match="syntax error on line 2"):
            parse_spec("x = 1\ndef broken(:\n", "test.bad")

    def test_top_level_crash_reported(self):
        with pytest.raises(NodeScriptError, match="error while loading"):
            parse_spec("raise RuntimeError('nope')", "test.bad")

    def test_portless_display_node_allowed(self):
        spec = parse_spec(
            "NODE = {'label': 'X', 'category': 'Y'}\n"
            "def run(ctx):\n    return {}\n", "test.portless")
        assert spec.inputs == [] and spec.outputs == []


class TestCompileRun:
    def test_run_executes(self):
        run = compile_run(GOOD, "node-123")
        result = run(FakeContext(params={"offset": 0.5}), a=1, b=2)
        assert result == 3.5

    def test_traceback_carries_virtual_filename(self):
        source = GOOD.replace("a + (b or 0)", "a + undefined_name")
        run = compile_run(source, "node-123")
        try:
            run(FakeContext(params={"offset": 0.0}), a=1, b=None)
            raise AssertionError("should have raised")
        except NameError as exc:
            tb = exc.__traceback__
            frames = []
            while tb is not None:
                frames.append(tb.tb_frame.f_code.co_filename)
                tb = tb.tb_next
            assert "<node:node-123>" in frames
