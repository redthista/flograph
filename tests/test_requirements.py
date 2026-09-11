"""What a flow needs installed (AC2): read from the nodes' own code."""
from types import SimpleNamespace

from flograph import requirements as req

SOURCE = '''
import os, json
import pandas as pd
from sklearn.cluster import KMeans
from . import sibling
from flograph.core import Graph
try:
    import polars
except ImportError:
    polars = None


def run(ctx):
    import requests
    try:
        import pyarrow
    except Exception:
        pass
    import pyarrow.parquet
'''


class TestImports:

    def test_third_party_imports_and_nothing_else(self):
        found = req.imports_in(SOURCE)
        assert set(found) == {"pandas", "sklearn", "polars", "requests",
                              "pyarrow"}

    def test_one_with_a_fallback_is_optional(self):
        found = req.imports_in(SOURCE)
        assert found["polars"] is True
        assert found["requests"] is False
        # guarded once, needed outright once: it is needed
        assert found["pyarrow"] is False

    def test_a_try_for_something_else_is_no_fallback(self):
        source = "try:\n    import thing\nexcept KeyError:\n    pass\n"
        assert req.imports_in(source) == {"thing": False}

    def test_code_that_does_not_parse_needs_nothing(self):
        assert req.imports_in("def (:") == {}


class TestWebLibraries:

    def test_markup_inside_an_f_string(self):
        source = ('from flograph.weblibs import markup\n'
                  'def run(ctx):\n'
                  '    return f"<head>{markup(\'d3\')}'
                  '{markup(\'echarts\', mode=\'inline\')}</head>"\n')
        assert req.web_libraries_in(source) == ["d3", "echarts"]

    def test_through_the_module(self):
        source = ('from flograph import weblibs\n'
                  'weblibs.require("leaflet")\n'
                  'import flograph.weblibs as w\n'
                  'w.markup("mermaid", "leaflet")\n')
        assert req.web_libraries_in(source) == ["leaflet", "mermaid"]

    def test_an_example_in_a_docstring_or_comment_is_not_a_use(self):
        source = ('"""\n    from flograph.weblibs import markup\n'
                  '    head = markup("echarts")\n"""\n'
                  '# markup("d3")\n')
        assert req.web_libraries_in(source) == []

    def test_a_markup_of_somebody_elses_is_not_ours(self):
        assert req.web_libraries_in('def markup(x):\n    pass\n'
                                    'markup("d3")\n') == []


class TestNamingThePackage:

    def test_an_installed_module_names_its_own(self):
        assert req.package_for("yaml", {"yaml": ["PyYAML"]}) == ("PyYAML", True)

    def test_a_known_mismatch(self):
        assert req.package_for("sklearn", {}) == ("scikit-learn", True)

    def test_otherwise_it_is_a_guess(self):
        assert req.package_for("zzq_nowhere", {}) == ("zzq_nowhere", False)


def _node(label, source, broken=False):
    return SimpleNamespace(label=label, source=source,
                           spec=SimpleNamespace(label=label, broken=broken))


class TestAFlow:

    def test_one_row_per_thing_naming_every_node(self):
        nodes = [
            _node("Cluster", "import sklearn\nimport zzq_nowhere\n"),
            _node("Score", "from sklearn import metrics\nimport pandas\n"),
            _node("Fast path",
                  "try:\n    import polars\nexcept ImportError:\n    pass\n"),
            _node("Circles", "from flograph.weblibs import markup\n"
                             "markup('d3')\nmarkup('echarts')\n"),
            _node("Gone", "import broken_thing\n", broken=True),
        ]
        needs = req.requirements_of(
            nodes, weblib_installed=lambda name: name == "d3",
            importable=lambda module: False, skip={"pandas"})
        by_name = {n.name: n for n in needs}
        assert "pandas" not in by_name, "flograph's own are skipped"
        assert "broken_thing" not in by_name, "a broken node has no code"
        sklearn = by_name["scikit-learn"]
        assert sklearn.nodes == ["Cluster", "Score"]
        assert sklearn.module == "sklearn" and sklearn.missing
        assert by_name["zzq_nowhere"].certain is False
        assert by_name["polars"].optional
        assert by_name["d3"].installed and by_name["d3"].kind == req.WEBLIB
        assert by_name["echarts"].missing

    def test_missing_things_come_first_and_optional_ones_wait(self):
        nodes = [_node("A", "import aaa_there\nimport zzz_gone\n"
                            "try:\n    import mmm_maybe\n"
                            "except ImportError:\n    pass\n")]
        needs = req.requirements_of(
            nodes, weblib_installed=lambda name: True,
            importable=lambda module: module == "aaa_there")
        assert [n.name for n in needs] == ["zzz_gone", "mmm_maybe", "aaa_there"]
        assert [n.name for n in req.missing(needs)] == ["zzz_gone"]
        assert [n.name for n in req.missing(needs, include_optional=True)] == [
            "zzz_gone", "mmm_maybe"]

    def test_a_real_visual_names_its_library(self, registry):
        """A library node's own script is read, not just forked code."""
        node = registry.instantiate("flograph.viz.mermaid")
        needs = req.requirements_of([node], weblib_installed=lambda n: False)
        assert any(n.kind == req.WEBLIB and n.name == "mermaid" for n in needs)
