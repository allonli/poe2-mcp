"""
Tests for the calc reconciliation harness (issue #139).

Verifies:
  - Harness consumes a ``charModel`` dict (or its embedded
    ``defensiveStats`` sub-dict) and emits one ``StatDelta`` per
    reconcilable stat.
  - DefensiveStats adapter handles both poe.ninja camelCase ("armour",
    "energyShield", "fireResistance") and our snake_case names.
  - The synthetic fixture lands inside the default tolerance band (a
    regression guard: if a future calc change moves any default stat
    >15% off the fixture's oracle values, this test trips first).
  - Missing oracle fields are skipped, not crashed.
  - Bad oracle values (intentionally far off) correctly flip
    ``all_within_tolerance`` to False.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "poe_ninja" / "synthetic_lvl90.json"


def _load_fixture() -> dict:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_fixture_loads_and_has_required_keys():
    """Sanity: the fixture exists and exposes the oracle fields the harness
    looks for. If this trips, the fixture got shape-broken accidentally."""
    char = _load_fixture()
    ds = char["defensiveStats"]
    for key in [
        "life", "energyShield", "armour", "evasion",
        "fireResistance", "coldResistance", "lightningResistance", "chaosResistance",
        "effectiveHealthPool",
        "physicalMaximumHitTaken", "fireMaximumHitTaken",
        "coldMaximumHitTaken", "lightningMaximumHitTaken", "chaosMaximumHitTaken",
    ]:
        assert key in ds, f"fixture missing required oracle key {key!r}"


def test_adapter_maps_poe_ninja_field_names():
    """``build_defensive_stats_from_charmodel`` must read British camelCase
    keys from a poe.ninja payload."""
    from src.calculator.reconcile_poe_ninja import build_defensive_stats_from_charmodel
    char = _load_fixture()
    stats = build_defensive_stats_from_charmodel(char)
    ds = char["defensiveStats"]
    assert stats.life == ds["life"]
    assert stats.energy_shield == ds["energyShield"]
    assert stats.armor == ds["armour"]
    assert stats.fire_res == ds["fireResistance"]
    assert stats.chaos_res == ds["chaosResistance"]


def test_adapter_accepts_inner_dict_shape():
    """If a caller already extracted ``defensiveStats``, the adapter should
    accept that sub-dict directly without barfing."""
    from src.calculator.reconcile_poe_ninja import build_defensive_stats_from_charmodel
    char = _load_fixture()
    stats = build_defensive_stats_from_charmodel(char["defensiveStats"])
    assert stats.life == 5500
    assert stats.armor == 8000


def test_reconcile_produces_one_delta_per_oracle_stat():
    """A clean fixture should yield 6 deltas (effective_hp + 5 per-type maxes)."""
    from src.calculator.reconcile_poe_ninja import reconcile_defensive_stats
    char = _load_fixture()
    report = reconcile_defensive_stats(char)
    stat_names = {d.stat for d in report.deltas}
    expected = {
        "effective_hp", "physical_max_hit", "fire_max_hit",
        "cold_max_hit", "lightning_max_hit", "chaos_max_hit",
    }
    assert stat_names == expected
    assert report.char_name == "ReconcileTestChar_Synthetic"


def test_synthetic_fixture_passes_default_tolerance():
    """Regression guard: the synthetic fixture's oracle values are
    constructed so our calc lands inside the default 15% band on every
    reconciled stat. A breaking calc change will trip this first."""
    from src.calculator.reconcile_poe_ninja import reconcile_defensive_stats
    char = _load_fixture()
    report = reconcile_defensive_stats(char)
    failing = [(d.stat, d.pct_delta, d.tolerance_pct) for d in report.deltas
               if not d.within_tolerance]
    assert not failing, (
        f"calc drifted outside synthetic fixture's tolerance: {failing}"
    )
    assert report.all_within_tolerance


def test_missing_oracle_field_is_skipped_not_crashed():
    """If poe.ninja omits a field, the harness skips it instead of crashing."""
    from src.calculator.reconcile_poe_ninja import reconcile_defensive_stats
    char = _load_fixture()
    trimmed = copy.deepcopy(char)
    del trimmed["defensiveStats"]["chaosMaximumHitTaken"]
    report = reconcile_defensive_stats(trimmed)
    stat_names = {d.stat for d in report.deltas}
    assert "chaos_max_hit" not in stat_names
    assert "chaos_max_hit" in report.skipped


def test_bad_oracle_trips_all_within_tolerance():
    """Move the oracle's effectiveHealthPool to a value we can't reach
    (1.0) - the report must flip to FAIL."""
    from src.calculator.reconcile_poe_ninja import reconcile_defensive_stats
    char = _load_fixture()
    sabotaged = copy.deepcopy(char)
    sabotaged["defensiveStats"]["effectiveHealthPool"] = 1.0
    report = reconcile_defensive_stats(sabotaged)
    assert not report.all_within_tolerance
    ehp_row = next(d for d in report.deltas if d.stat == "effective_hp")
    assert not ehp_row.within_tolerance


def test_format_report_renders_a_table():
    """The text formatter should not crash on a real report and should
    surface the PASS/FAIL footer."""
    from src.calculator.reconcile_poe_ninja import (
        format_report,
        reconcile_defensive_stats,
    )
    char = _load_fixture()
    report = reconcile_defensive_stats(char)
    text = format_report(report)
    assert "ReconcileTestChar_Synthetic" in text
    assert "Overall:" in text


def test_format_report_handles_empty():
    """No deltas (e.g. all oracle keys absent) should not crash."""
    from src.calculator.reconcile_poe_ninja import (
        ReconciliationReport,
        format_report,
    )
    r = ReconciliationReport(char_name="empty", skipped=["effective_hp"])
    text = format_report(r)
    assert "no deltas computed" in text
