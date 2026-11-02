"""`scripts/run_tests.py` — how many workers the suite asks for.

The suite is happiest at `-n12`, but twelve workers peg every core for
minutes, which is not something to do to a machine somebody is using. The
script decides from current load and CPU temperature instead; this pins the
decision, which is the only part with any judgement in it.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_tests.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("run_tests", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDecide:

    def test_an_idle_machine_gets_the_cap(self, script):
        workers, _ = script.decide(cores=16, load=0.0, temp=40.0)
        assert workers == script.MAX_WORKERS

    def test_workers_come_from_the_spare_cores_not_all_of_them(self, script):
        """Load average is what somebody else is already using."""
        workers, why = script.decide(cores=16, load=12.0, temp=40.0)
        assert workers == 3           # 4 spare, 75% of that
        assert "spare" in why

    def test_a_fully_loaded_machine_still_gets_one(self, script):
        workers, _ = script.decide(cores=16, load=64.0, temp=40.0)
        assert workers == 1

    def test_a_warm_cpu_halves_it(self, script):
        cool, _ = script.decide(cores=16, load=0.0, temp=40.0)
        warm, why = script.decide(cores=16, load=0.0,
                                  temp=script.WARM_C + 1)
        assert warm == max(1, cool // 2)
        assert "halved" in why

    def test_a_hot_cpu_goes_serial(self, script):
        """A hot chip throttles under a parallel run anyway, so backing off
        costs less wall-clock than it looks like it should."""
        workers, why = script.decide(cores=16, load=0.0,
                                     temp=script.HOT_C + 1)
        assert workers == 1
        assert "serial" in why

    def test_temperature_wins_over_an_idle_machine(self, script):
        """The case this exists for: nothing running, chip already hot."""
        workers, _ = script.decide(cores=16, load=0.2,
                                   temp=script.HOT_C + 5)
        assert workers == 1

    def test_no_reading_falls_back_to_load_alone(self, script):
        workers, why = script.decide(cores=16, load=0.0, temp=None)
        assert workers == script.MAX_WORKERS
        assert "no CPU temperature" in why

    def test_the_cap_is_respected(self, script):
        workers, _ = script.decide(cores=64, load=0.0, temp=40.0, cap=4)
        assert workers == 4

    def test_it_always_says_why(self, script):
        for temp in (40.0, script.WARM_C + 1, script.HOT_C + 1, None):
            _, why = script.decide(cores=16, load=2.0, temp=temp)
            assert why.strip()


class TestTemperature:

    def test_acpitz_is_not_trusted(self, script):
        """It exists on this machine and reads 16°C while the CPU is at
        80°C — worse than having no reading at all."""
        assert "acpitz" not in script.CPU_SENSORS

    def test_it_reads_the_hottest_probe_on_the_chip(self, script, tmp_path,
                                                    monkeypatch):
        chip = tmp_path / "hwmon0"
        chip.mkdir()
        (chip / "name").write_text("k10temp\n")
        (chip / "temp1_input").write_text("71250\n")
        (chip / "temp3_input").write_text("80000\n")
        monkeypatch.setattr(script, "Path", lambda p: tmp_path
                            if str(p) == "/sys/class/hwmon" else Path(p))
        assert script.cpu_temperature() == pytest.approx(80.0)

    def test_no_sensors_is_none_not_a_guess(self, script, tmp_path,
                                            monkeypatch):
        monkeypatch.setattr(script, "Path", lambda p: tmp_path
                            if str(p) == "/sys/class/hwmon" else Path(p))
        assert script.cpu_temperature() is None

    def test_an_unreadable_chip_is_skipped(self, script, tmp_path,
                                           monkeypatch):
        chip = tmp_path / "hwmon0"
        chip.mkdir()
        (chip / "name").write_text("k10temp\n")
        (chip / "temp1_input").write_text("not a number\n")
        monkeypatch.setattr(script, "Path", lambda p: tmp_path
                            if str(p) == "/sys/class/hwmon" else Path(p))
        assert script.cpu_temperature() is None


class TestMemory:
    def test_busy_machine_limits_even_explicit_worker_count(self, script):
        workers, budget = script.memory_plan(32 * script.GIB, 8 * script.GIB, 12)
        assert budget == int(8 * script.GIB * 0.6)
        assert workers == 1

    def test_idle_machine_keeps_half_total_for_other_apps(self, script):
        workers, budget = script.memory_plan(32 * script.GIB, 30 * script.GIB, 12)
        assert budget == 16 * script.GIB
        assert workers == 5

    def test_serial_request_stays_serial(self, script):
        assert script.memory_plan(32 * script.GIB, 30 * script.GIB, 0)[0] == 0

    def test_low_memory_still_has_a_finite_budget(self, script):
        workers, budget = script.memory_plan(8 * script.GIB, script.GIB, 12)
        assert workers == 1
        assert 0 < budget < script.GIB

    def test_scope_probe_failure_does_not_claim_enforcement(self, script, monkeypatch):
        import subprocess
        monkeypatch.setattr(script.sys, 'platform', 'linux')
        monkeypatch.setattr(script.shutil, 'which', lambda _: '/usr/bin/systemd-run')
        monkeypatch.setattr(script.subprocess, 'run',
                            lambda *a, **k: subprocess.CompletedProcess(a, 1))
        assert script.memory_scope(script.GIB) == []

    def test_scope_limits_all_children_and_disables_swap(self, script, monkeypatch):
        import subprocess
        monkeypatch.setattr(script.sys, 'platform', 'linux')
        monkeypatch.setattr(script.shutil, 'which', lambda _: '/usr/bin/systemd-run')
        monkeypatch.setattr(script.subprocess, 'run',
                            lambda *a, **k: subprocess.CompletedProcess(a, 0))
        command = script.memory_scope(script.GIB)
        assert f'MemoryMax={script.GIB}' in command
        assert 'MemorySwapMax=0' in command
