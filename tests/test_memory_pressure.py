"""Warning when the project is the reason the machine is filling up.

Nothing here evicts anything: the cache invariant is "a node is clean iff
its outputs are cached", so dropping an entry behind the user's back marks
the node dirty and it re-runs later with no explanation. These tests pin the
warning, and pin that it stays a warning.
"""
import pytest

from flograph.engine.cache import OutputCache
from flograph.ui.resource_monitor import (CACHE_SHARE, SYSTEM_PRESSURE,
                                          memory_pressure)

GB = 1024 ** 3


class TestMemoryPressure:
    def test_quiet_when_the_machine_has_room(self):
        assert not memory_pressure(cache=2 * GB, used=8 * GB, total=32 * GB)

    def test_quiet_when_the_machine_is_full_but_not_because_of_us(self):
        """Something else is eating the box. Blaming the flow would be
        wrong and would train the user to ignore the warning."""
        assert not memory_pressure(cache=100 * 1024 ** 2, used=31 * GB,
                                   total=32 * GB)

    def test_quiet_when_we_hold_a_lot_but_the_machine_is_huge(self):
        assert not memory_pressure(cache=12 * GB, used=20 * GB, total=128 * GB)

    def test_warns_when_both_hold(self):
        assert memory_pressure(cache=12 * GB, used=29 * GB, total=32 * GB)

    def test_thresholds_are_the_boundary(self):
        total = 100 * GB
        used = int(total * SYSTEM_PRESSURE)
        cache = int(total * CACHE_SHARE)
        assert memory_pressure(cache=cache, used=used, total=total)
        assert not memory_pressure(cache=cache - GB, used=used, total=total)
        assert not memory_pressure(cache=cache, used=used - 2 * GB, total=total)

    def test_no_total_is_not_a_crash(self):
        """psutil can report nothing on an odd platform; a division by zero
        in a status bar refresh would take the window down every 2 s."""
        assert not memory_pressure(cache=0, used=0, total=0)


class TestHysteresis:
    """Memory in use wanders by a point or two from moment to moment. On a
    bare threshold that flickers the bar and re-announces itself every
    refresh, which is exactly the nagging the warning is meant to avoid."""

    def total(self):
        return 100 * GB

    def test_a_dip_below_the_line_does_not_clear_the_warning(self):
        total = self.total()
        cache = 20 * GB
        assert memory_pressure(cache, used=int(total * 0.84), total=total,
                               already_warning=True)

    def test_it_clears_once_it_falls_clear_of_the_line(self):
        total = self.total()
        cache = 20 * GB
        assert not memory_pressure(cache, used=int(total * 0.79), total=total,
                                   already_warning=True)

    def test_the_cache_share_has_relief_too(self):
        """Releasing one node's output should not immediately un-warn while
        the machine is still full."""
        total = self.total()
        used = int(total * 0.90)
        assert memory_pressure(cache=int(total * 0.09), used=used, total=total,
                               already_warning=True)
        assert not memory_pressure(cache=int(total * 0.09), used=used,
                                   total=total, already_warning=False)

    def test_wobbling_across_the_threshold_settles(self):
        """The regression this exists for: usage oscillating around 85%
        used to fire the warning once per upward crossing."""
        total = self.total()
        cache = 20 * GB
        warning = False
        crossings = 0
        for frac in (0.849, 0.851, 0.848, 0.852, 0.850, 0.847, 0.853):
            now = memory_pressure(cache, int(total * frac), total,
                                  already_warning=warning)
            if now and not warning:
                crossings += 1
            warning = now
        assert crossings == 1


class TestHeaviest:
    def entry(self, cache, node_id, size, alias_of=None):
        cache.set(node_id, {"v": object()}, 0.0, alias_of=alias_of)
        cache.get(node_id).memory_bytes = size

    def test_largest_first_and_limited(self):
        cache = OutputCache()
        for nid, size in (("a", 10), ("b", 300), ("c", 200), ("d", 1)):
            self.entry(cache, nid, size)
        assert cache.heaviest(2) == [("b", 300), ("c", 200)]

    def test_a_shared_value_is_credited_once(self):
        """A Goto chain serves one object from several entries; counting it
        per entry would send the user chasing a node that holds nothing."""
        cache = OutputCache()
        self.entry(cache, "src", 500)
        self.entry(cache, "goto", 500, alias_of="src")
        assert cache.heaviest() == [("src", 500)]
        assert cache.total_bytes() == 500

    def test_an_orphaned_alias_is_counted(self):
        """Once the entry it shared with is gone, the alias is the only
        thing holding the object, so it is the one that has to be counted."""
        cache = OutputCache()
        self.entry(cache, "src", 500)
        self.entry(cache, "goto", 500, alias_of="src")
        cache.evict("src")
        assert cache.heaviest() == [("goto", 500)]

    def test_empty_cache_has_no_heaviest(self):
        assert OutputCache().heaviest() == []

    def test_zero_sized_entries_are_skipped(self):
        cache = OutputCache()
        self.entry(cache, "a", 0)
        assert cache.heaviest() == []
