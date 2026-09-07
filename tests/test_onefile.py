"""Guards scripts/build_onefile.py: the generated single-file bundle must
actually work in a fresh interpreter that never installed flograph — the
whole point of the one-file script is to hand someone a file that needs
no `pip install`."""
from __future__ import annotations

import os
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
        "docs = [p for p in importlib.resources.files('flograph.docs').iterdir() "
        "if p.name.endswith('.md')]\n"
        "assert docs, 'no handbook pages found in bundle'\n"
        "assert all(p.is_file() for p in docs), "
        "'docs pages must resolve to real files on disk for the Documentation window'\n"
        "print('OK', len(loaded), len(templates), len(docs))\n"
    )
    result = subprocess.run(
        [sys.executable, str(probe), str(onefile)],
        cwd=tmp_path, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().startswith("OK")


def _build(tmp_path) -> Path:
    onefile = tmp_path / "flograph_onefile.py"
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "build_onefile.py"), str(onefile)],
        check=True, cwd=REPO_ROOT,
    )
    return onefile


def _pyproject_version() -> str:
    import re
    text = (REPO_ROOT / "pyproject.toml").read_text()
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE).group(1)


def test_the_bundle_reports_its_own_version_not_a_pip_install_s(tmp_path):
    """The reported bug: a 0.1.14 bundle announcing 0.1.12 in Settings.

    A bundle carries no distribution metadata, so the metadata lookup found
    the *other* flograph pip-installed in the interpreter that started it and
    reported that instead — while running the bundle's code throughout. Set
    up exactly that: a bundle beside a distribution claiming another version.
    """
    onefile = _build(tmp_path)
    expected = _pyproject_version()

    # a dist-info with no package beside it: importlib.metadata reads it,
    # imports still come from the bundle, which is the real machine's shape
    shadow = tmp_path / "shadow"
    dist_info = shadow / "flograph-0.1.12.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: flograph\nVersion: 0.1.12\n")

    probe = tmp_path / "version_probe.py"
    probe.write_text(
        "import runpy, sys\n"
        "runpy.run_path(sys.argv[1], run_name='onefile_under_test')\n"
        "from flograph import version as v\n"
        "print(v.bundled_version(), v.installed_version(), v.running_version())\n"
    )
    env = dict(os.environ, PYTHONPATH=str(shadow))
    result = subprocess.run(
        [sys.executable, str(probe), str(onefile)],
        cwd=tmp_path, capture_output=True, text=True, timeout=60, env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    bundled, installed, running = result.stdout.split()

    assert installed == "0.1.12", "the shadowing install didn't take effect"
    assert bundled == expected
    # the whole point: the metadata is there, says something else, and loses
    assert running == expected


def test_the_generated_version_module_stays_out_of_the_source_tree():
    """It must exist only inside the zip. In `src/` it would be picked up by
    a build and shipped in the wheel, and a pip install would then report the
    version of whichever bundle was built last rather than its own."""
    assert not (REPO_ROOT / "src" / "flograph" / "_bundle_version.py").exists()
