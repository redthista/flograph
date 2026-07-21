"""Guards scripts/build_onefile.py: the generated single-file bundle must
actually work in a fresh interpreter that never installed flograph — the
whole point of the one-file script is to hand someone a file that needs
no `pip install`."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_onefile_bundle_runs_standalone(tmp_path):
    onefile = tmp_path / "flograph_onefile.py"
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "build_onefile.py"), str(onefile)],
        check=True, cwd=REPO_ROOT,
    )
    assert onefile.exists()

    # Runs the bundle's top-level bootstrap (unpack + sys.path insert) under
    # a non-"__main__" run_name so it doesn't also launch the Qt event loop,
    # then exercises the two things that depend on resources actually being
    # present: node discovery and template files being real files on disk
    # (not zip members — MainWindow's "Open Example" needs a real Path).
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import runpy, sys\n"
        "runpy.run_path(sys.argv[1], run_name='onefile_under_test')\n"
        "import flograph\n"
        "assert 'flograph_onefile_' in flograph.__file__, ("
        "'imported flograph from ' + flograph.__file__ + ' instead of the "
        "bundle extraction dir — bootstrap is broken and a stale/editable "
        "install is masking it')\n"
        "from flograph.core import NodeRegistry\n"
        "import importlib.resources\n"
        "reg = NodeRegistry()\n"
        "loaded = reg.load_builtins()\n"
        "assert len(loaded) > 0, 'no builtin nodes loaded from bundle'\n"
        "templates = [p for p in importlib.resources.files('flograph.templates').iterdir() "
        "if p.name.endswith('.flograph')]\n"
        "assert templates, 'no example templates found in bundle'\n"
        "assert all(p.is_file() for p in templates), "
        "'templates must resolve to real files on disk for Open Example to work'\n"
        "print('OK', len(loaded), len(templates))\n"
    )
    result = subprocess.run(
        [sys.executable, str(probe), str(onefile)],
        cwd=tmp_path, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().startswith("OK")
