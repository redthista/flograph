"""flograph.core must stay Qt-free and import-light.

Run the import in a subprocess so this test is immune to whatever the rest of
the suite already imported.
"""
import subprocess
import sys

CHECK = """
import sys
import flograph.core
import flograph.core.serialization

heavy = [name for name in sys.modules
         if name.split(".")[0] in ("PySide6", "pandas", "matplotlib", "shiboken6")]
assert not heavy, f"flograph.core import pulled in: {heavy}"
"""


def test_core_imports_without_qt_or_heavy_deps():
    result = subprocess.run(
        [sys.executable, "-c", CHECK], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
