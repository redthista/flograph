"""The one place that answers "what version is running?".

Two sources disagree by design — a bundle's stamped module and a pip
install's distribution metadata — and which one wins is the whole point.
"""
from __future__ import annotations

import sys
import types

import pytest

from flograph import version as v


@pytest.fixture
def _no_bundle(monkeypatch):
    """A plain pip install / source checkout: no stamped module anywhere."""
    monkeypatch.delitem(sys.modules, "flograph._bundle_version", raising=False)
    monkeypatch.setattr(v, "bundled_version", lambda: None)


def _stamped(monkeypatch, value):
    module = types.ModuleType("flograph._bundle_version")
    module.VERSION = value
    monkeypatch.setitem(sys.modules, "flograph._bundle_version", module)


class TestBundledVersion:
    def test_it_reads_the_module_the_builder_stamps_in(self, monkeypatch):
        _stamped(monkeypatch, "1.2.3")

        assert v.bundled_version() == "1.2.3"

    def test_outside_a_bundle_there_is_no_such_module(self, _no_bundle):
        # the import has to fail quietly: this is the normal case for every
        # pip install and every source checkout
        assert v.bundled_version() is None

    def test_an_empty_stamp_counts_as_absent(self, monkeypatch):
        _stamped(monkeypatch, "")

        assert v.bundled_version() is None


class TestRunningVersion:
    def test_the_bundle_outranks_the_metadata(self, monkeypatch):
        _stamped(monkeypatch, "0.1.14")
        monkeypatch.setattr(v, "installed_version", lambda: "0.1.12")

        # the reported bug: the bundle's code is what is executing, so its
        # version is the true one however loudly the metadata disagrees
        assert v.running_version() == "0.1.14"

    def test_a_pip_install_reports_its_own_version(self, _no_bundle, monkeypatch):
        monkeypatch.setattr(v, "installed_version", lambda: "0.1.13")

        # and the fix must not swing the other way: running 0.1.13 from pip
        # reports 0.1.13, whatever bundles are sitting on the same disk
        assert v.running_version() == "0.1.13"

    def test_with_neither_it_falls_back_to_what_the_caller_asked_for(
            self, _no_bundle, monkeypatch):
        monkeypatch.setattr(v, "installed_version", lambda: None)

        assert v.running_version("unknown") == "unknown"
        assert v.running_version() is None


class TestCallers:
    def test_the_update_check_compares_the_running_version(self, monkeypatch):
        from flograph import packages

        _stamped(monkeypatch, "0.1.14")
        monkeypatch.setattr(v, "installed_version", lambda: "0.1.12")

        # comparing an old pip install against PyPI would offer an update to
        # something already running
        assert packages.installed_version() == "0.1.14"

    def test_an_unidentifiable_build_is_never_told_it_is_behind(
            self, _no_bundle, monkeypatch):
        from flograph import packages

        monkeypatch.setattr(v, "installed_version", lambda: None)

        assert packages.installed_version() == "0"
