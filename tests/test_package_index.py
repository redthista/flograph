"""Installing from a configured package index (AC1).

pip reads pip.conf and PIP_INDEX_URL; the `uv pip` fallback reads neither,
and nothing in flograph could set an index at all. Settings ▸ Packages now
can, pip is given it over its own settings, and uv is handed what pip would
have used when nothing is set. The update check asks the same index.
"""
import os
import sys
from types import SimpleNamespace

import pytest

from flograph import packages
from flograph.packages import PackageIndex

MIRROR = "https://mirror.example.com/simple"


class TestPackageIndex:

    def test_empty_means_the_installers_own(self):
        assert not PackageIndex()
        assert PackageIndex().pip_args() == []
        assert PackageIndex().uv_args() == []

    def test_pip_and_uv_each_get_their_own_spelling(self):
        index = PackageIndex(MIRROR, "mirror.example.com, other.example.com")
        assert index.pip_args() == [
            "--index-url", MIRROR,
            "--trusted-host", "mirror.example.com",
            "--trusted-host", "other.example.com"]
        assert index.uv_args() == [
            "--index-url", MIRROR,
            "--allow-insecure-host", "mirror.example.com",
            "--allow-insecure-host", "other.example.com"]

    def test_what_is_wrong_with_one(self):
        assert packages.index_problem(MIRROR) == ""
        assert packages.index_problem("") == ""
        assert packages.index_problem("file:///srv/wheels") == ""
        assert "https://" in packages.index_problem("mirror.example.com/simple")
        assert "spaces" in packages.index_problem("https://a b/simple")
        assert "host" in packages.index_problem(MIRROR, "-evil")

    def test_saying_where_installs_come_from(self):
        assert packages.describe_index(PackageIndex()).startswith("PyPI")
        text = packages.describe_index(
            PackageIndex(MIRROR, "mirror.example.com", source="PIP_INDEX_URL"))
        assert MIRROR in text and "mirror.example.com" in text
        assert "PIP_INDEX_URL" in text


class TestReadingPipsOwnSettings:

    def test_the_environment_first(self):
        index = packages.pip_config_index(
            {"PIP_INDEX_URL": MIRROR, "PIP_TRUSTED_HOST": "mirror.example.com"},
            files=[])
        assert index.url == MIRROR
        assert index.hosts() == ["mirror.example.com"]
        assert index.source == "PIP_INDEX_URL"

    def test_a_later_file_wins_and_install_beats_global(self, tmp_path):
        first = tmp_path / "first.conf"
        first.write_text("[global]\nindex-url = https://a/simple\n"
                         "trusted-host = a\n")
        second = tmp_path / "second.conf"
        second.write_text("[global]\nindex-url = https://b/simple\n")
        index = packages.pip_config_index({}, files=[str(first), str(second)])
        assert index.url == "https://b/simple"
        assert index.hosts() == ["a"]
        assert str(second) in index.source
        install = tmp_path / "install.conf"
        install.write_text("[install]\nindex_url = https://c/simple\n")
        index = packages.pip_config_index(
            {}, files=[str(install), str(first), str(second)])
        assert index.url == "https://c/simple"

    def test_several_hosts_over_several_lines(self, tmp_path):
        conf = tmp_path / "pip.conf"
        conf.write_text("[global]\ntrusted-host =\n    a.example\n"
                        "    b.example\n")
        assert packages.pip_config_index({}, files=[str(conf)]).hosts() == [
            "a.example", "b.example"]

    def test_a_missing_or_unreadable_file_is_passed_over(self, tmp_path):
        broken = tmp_path / "broken.conf"
        broken.write_text("this is not ini at all")
        index = packages.pip_config_index(
            {}, files=[str(tmp_path / "absent.conf"), str(broken)])
        assert not index

    def test_devnull_turns_pips_config_off(self):
        assert packages._pip_config_files({"PIP_CONFIG_FILE": os.devnull}) == []

    def test_pip_config_file_is_read_last(self):
        files = packages._pip_config_files({"PIP_CONFIG_FILE": "/x/pip.conf"})
        assert files[-1] == "/x/pip.conf"


@pytest.fixture
def uv(monkeypatch):
    monkeypatch.setattr(packages, "installer_kind", lambda: "uv")
    monkeypatch.setattr(packages.shutil, "which", lambda _: "/usr/bin/uv")


@pytest.fixture
def pip(monkeypatch):
    monkeypatch.setattr(packages, "installer_kind", lambda: "pip")


class TestInstallingFromIt:

    def test_pip_gets_flogrophs_setting(self, pip):
        argv = packages.build_command(
            "install", ["requests"],
            index=PackageIndex(MIRROR, "mirror.example.com"),
            environ={}, files=[])
        assert argv[3:] == ["install", "--index-url", MIRROR,
                            "--trusted-host", "mirror.example.com", "requests"]
        upgrade = packages.build_command("upgrade", ["requests"],
                                         index=PackageIndex(MIRROR),
                                         environ={}, files=[])
        assert upgrade[3:] == ["install", "--upgrade", "--index-url", MIRROR,
                               "requests"]

    def test_pip_without_a_setting_reads_its_own(self, pip):
        """pip reads its own config; nothing is added to its command."""
        argv = packages.build_command("install", ["requests"],
                                      environ={"PIP_INDEX_URL": MIRROR},
                                      files=[])
        assert argv[3:] == ["install", "requests"]

    def test_uv_is_handed_what_pip_would_use(self, uv):
        argv = packages.build_command("install", ["requests"],
                                      environ={"PIP_INDEX_URL": MIRROR},
                                      files=[])
        assert argv[:3] == ["/usr/bin/uv", "pip", "install"]
        assert argv[argv.index("--index-url") + 1] == MIRROR
        assert argv[-1] == "requests"
        assert sys.executable in argv

    def test_uv_told_an_index_of_its_own_is_left_alone(self, uv):
        argv = packages.build_command(
            "install", ["requests"],
            environ={"PIP_INDEX_URL": MIRROR,
                     "UV_INDEX_URL": "https://uv.example/simple"},
            files=[])
        assert "--index-url" not in argv

    def test_the_setting_beats_both(self, uv):
        argv = packages.build_command(
            "install", ["requests"],
            index=PackageIndex("https://flo.example/simple", "flo.example"),
            environ={"PIP_INDEX_URL": MIRROR,
                     "UV_INDEX_URL": "https://uv.example/simple"},
            files=[])
        assert argv[argv.index("--index-url") + 1] == \
            "https://flo.example/simple"
        assert argv[argv.index("--allow-insecure-host") + 1] == "flo.example"

    def test_uninstalling_takes_no_index(self, uv, pip):
        for kind in ("pip", "uv"):
            packages.installer_kind = (lambda k=kind: k)
            argv = packages.build_command("uninstall", ["requests"],
                                          index=PackageIndex(MIRROR),
                                          environ={"PIP_INDEX_URL": MIRROR},
                                          files=[])
            assert "--index-url" not in argv, kind


class TestTheUpdateCheckAsksTheSameIndex:

    def _with_pip(self, monkeypatch, present: bool):
        real = packages.importlib.util.find_spec

        def find_spec(name, *args, **kwargs):
            if name == "pip":
                return object() if present else None
            return real(name, *args, **kwargs)
        monkeypatch.setattr(packages.importlib.util, "find_spec", find_spec)

    def test_pip_is_asked_with_the_setting(self, monkeypatch):
        self._with_pip(monkeypatch, True)
        seen = []

        def run(argv, **kwargs):
            seen.append(argv)
            return SimpleNamespace(stdout="Available versions: 0.2.0, 0.1.14")
        monkeypatch.setattr(packages.subprocess, "run", run)
        versions = packages._pip_index_versions(index=PackageIndex(MIRROR))
        assert versions == ["0.2.0", "0.1.14"]
        argv = seen[0]
        assert argv[argv.index("--index-url") + 1] == MIRROR
        assert argv[-1] == "flograph"

    def test_with_no_pip_the_index_is_asked_directly(self, monkeypatch):
        self._with_pip(monkeypatch, False)
        asked = []
        monkeypatch.setattr(
            packages, "_simple_index_versions",
            lambda index, *a, **k: asked.append(index) or ["0.1.14", "0.2.0"])
        monkeypatch.setattr(packages, "_pypi_latest_version", lambda **k: None)
        assert packages.latest_available_version(PackageIndex(MIRROR)) == "0.2.0"
        assert asked[0].url == MIRROR

    def test_a_simple_page_as_json(self):
        body = '{"versions": ["0.1.13", "0.1.14"], "files": []}'
        assert packages._versions_from_simple_page(body, "flograph") == [
            "0.1.13", "0.1.14"]
        files = ('{"files": [{"filename": "flograph-0.1.14-py3-none-any.whl"},'
                 ' {"filename": "flograph-0.1.14.tar.gz"},'
                 ' {"filename": "flograph-0.2.0.tar.gz"},'
                 ' {"filename": "other-9.0.tar.gz"}]}')
        assert packages._versions_from_simple_page(files, "flograph") == [
            "0.1.14", "0.2.0"]

    def test_a_simple_page_as_html(self):
        body = ('<html><body>'
                '<a href="../flograph-0.1.13.tar.gz#sha256=x">'
                'flograph-0.1.13.tar.gz</a><br/>'
                '<a href="x">flograph-0.1.14-py3-none-any.whl</a>'
                '</body></html>')
        assert packages._versions_from_simple_page(body, "flograph") == [
            "0.1.13", "0.1.14"]

    def test_no_index_no_question(self):
        assert packages._simple_index_versions(PackageIndex()) == []
