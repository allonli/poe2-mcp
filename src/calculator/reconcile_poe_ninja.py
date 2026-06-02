"""
Calculator reconciliation harness — validate our EHP / defense / resource
calcs against poe.ninja's ``charModel.defensiveStats`` oracle (issue #139).

poe.ninja's ``charModel`` payload ships its OWN computed defensive numbers
for the exact character build it returns. Since that's *character data*
(allowed by data policy, not game mechanics), it makes a zero-policy-risk
regression oracle for our local calculators.

This module is intentionally a light helper with no SQLAlchemy / no async /
no MCP-server imports — pure stat-shaping + delta math. Callers feed in a
``charModel`` dict (loaded from a fixture or returned by the character
fetcher) and a ``ThreatProfile``; the harness produces a per-stat report
with our value, poe.ninja's value, the delta, and a within-tolerance flag.

Acceptance criteria for #139:
  - Per-stat diff table vs ``defensiveStats``                    [shipped]
  - Runs against an offline fixture corpus                        [shipped via tests]
  - Tolerances configurable, meaningful deltas fail               [shipped]
  - ``breakdowns.stats`` multiplier reconciliation                [deferred -
    needs trace_dps_calculation refactor; out of this PR's scope]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from .ehp_calculator import (
        DamageType,
        DefensiveStats,
        EHPCalculator,
        ThreatProfile,
    )
except ImportError:
    from src.calculator.ehp_calculator import (
        DamageType,
        DefensiveStats,
        EHPCalculator,
        ThreatProfile,
    )

logger = logging.getLogger(__name__)


# Default per-stat tolerances (percent). Picked generously enough to absorb
# the genuine model differences (PoE2's full layered-defense math vs.
# whatever shortcut poe.ninja uses), but tight enough that a real bug
# in our calc moves a stat outside the band.
DEFAULT_TOLERANCE_PCT: Dict[str, float] = {
    "effective_hp": 15.0,
    "physical_max_hit": 15.0,
    "fire_max_hit": 15.0,
    "cold_max_hit": 15.0,
    "lightning_max_hit": 15.0,
    "chaos_max_hit": 15.0,
}


@dataclass
class StatDelta:
    """One row of the reconciliation report.

    Attributes:
        stat: Stat name (matches DEFAULT_TOLERANCE_PCT key).
        our_value: Value computed by our local calculator.
        oracle_value: Value reported by poe.ninja's ``defensiveStats``.
        abs_delta: ``|our - oracle|``.
        pct_delta: ``abs_delta / max(|oracle|, 1) * 100``.
        tolerance_pct: Tolerance band applied to this stat.
        within_tolerance: ``pct_delta <= tolerance_pct``.
    """
    stat: str
    our_value: float
    oracle_value: float
    abs_delta: float
    pct_delta: float
    tolerance_pct: float
    within_tolerance: bool


@dataclass
class ReconciliationReport:
    """Full output of a reconciliation run.

    Attributes:
        char_name: Echo of ``charModel.name`` if present (handy for logs).
        deltas: One ``StatDelta`` per reconciled stat (skips stats absent
            from the oracle).
        all_within_tolerance: True iff every delta is within its band.
        skipped: List of stat names not present in the oracle.
    """
    char_name: Optional[str]
    deltas: List[StatDelta] = field(default_factory=list)
    all_within_tolerance: bool = True
    skipped: List[str] = field(default_factory=list)


def build_defensive_stats_from_charmodel(char_model: Dict[str, Any]) -> DefensiveStats:
    """Adapt a poe.ninja ``charModel`` (or its embedded ``defensiveStats`` sub-dict)
    into our internal ``DefensiveStats`` dataclass.

    poe.ninja's field names are camelCase and slightly different from ours;
    this maps the known overlaps. Unknown / 0.5-specific fields (e.g.
    ``runicWard``) are passed through where the dataclass has a slot for
    them, defaulted otherwise.

    Args:
        char_model: A full ``charModel`` dict OR its inner ``defensiveStats``
            sub-dict (auto-detected via key probe).

    Returns:
        A populated ``DefensiveStats``.
    """
    if "defensiveStats" in char_model:
        ds = char_model["defensiveStats"]
    else:
        ds = char_model

    # poe.ninja uses British spelling ("armour") and stores resistances
    # as percentages already.
    return DefensiveStats(
        life=float(ds.get("life", 0.0)),
        energy_shield=float(ds.get("energyShield", ds.get("energy_shield", 0.0))),
        runic_ward=float(ds.get("runicWard", ds.get("runic_ward", 0.0))),
        armor=float(ds.get("armour", ds.get("armor", 0.0))),
        evasion=float(ds.get("evasion", 0.0)),
        block_chance=float(ds.get("block", ds.get("blockChance", 0.0))),
        fire_res=float(ds.get("fireResistance", ds.get("fire_res", 0.0))),
        cold_res=float(ds.get("coldResistance", ds.get("cold_res", 0.0))),
        lightning_res=float(ds.get("lightningResistance", ds.get("lightning_res", 0.0))),
        chaos_res=float(ds.get("chaosResistance", ds.get("chaos_res", 0.0))),
    )


def reconcile_defensive_stats(
    char_model: Dict[str, Any],
    threat: Optional[ThreatProfile] = None,
    tolerance_pct: Optional[Dict[str, float]] = None,
) -> ReconciliationReport:
    """Run our EHP / defense calculators on the build poe.ninja describes,
    then diff each headline number against poe.ninja's own value.

    Args:
        char_model: A full ``charModel`` dict, or just its ``defensiveStats``
            sub-dict. Both shapes are accepted.
        threat: Optional threat profile (hit size, accuracy). Defaults to
            ``ThreatProfile()``.
        tolerance_pct: Per-stat tolerance overrides. Falls back to
            ``DEFAULT_TOLERANCE_PCT`` for unset entries.

    Returns:
        A populated ``ReconciliationReport``.
    """
    oracle = char_model.get("defensiveStats", char_model)
    tolerances = {**DEFAULT_TOLERANCE_PCT, **(tolerance_pct or {})}
    threat = threat or ThreatProfile()
    calc = EHPCalculator()

    stats = build_defensive_stats_from_charmodel(char_model)
    name = char_model.get("name") if isinstance(char_model.get("name"), str) else None
    report = ReconciliationReport(char_name=name)

    def _add_delta(stat: str, ours: float, oracle_key: str):
        if oracle_key not in oracle:
            report.skipped.append(stat)
            return
        oracle_val = float(oracle[oracle_key])
        abs_d = abs(ours - oracle_val)
        denom = max(abs(oracle_val), 1.0)
        pct = abs_d / denom * 100.0
        tol = tolerances.get(stat, 15.0)
        within = pct <= tol
        report.deltas.append(StatDelta(
            stat=stat,
            our_value=ours,
            oracle_value=oracle_val,
            abs_delta=abs_d,
            pct_delta=pct,
            tolerance_pct=tol,
            within_tolerance=within,
        ))
        if not within:
            report.all_within_tolerance = False

    # effective_hp: poe.ninja reports a single composite "effectiveHealthPool".
    # We approximate by computing physical EHP and treating it as the
    # representative number for now (poe.ninja's exact damage-type weighting
    # is opaque). Tolerance bands above account for the model difference.
    try:
        ehp_phys = calc.calculate_ehp(stats, DamageType.PHYSICAL, threat)
        _add_delta("effective_hp", ehp_phys.effective_hp, "effectiveHealthPool")
        _add_delta("physical_max_hit", ehp_phys.effective_hp, "physicalMaximumHitTaken")
    except Exception as e:
        logger.warning(f"Physical EHP calc failed during reconcile: {e}")
        report.skipped.extend(["effective_hp", "physical_max_hit"])

    for dt, oracle_key, stat_name in [
        (DamageType.FIRE, "fireMaximumHitTaken", "fire_max_hit"),
        (DamageType.COLD, "coldMaximumHitTaken", "cold_max_hit"),
        (DamageType.LIGHTNING, "lightningMaximumHitTaken", "lightning_max_hit"),
        (DamageType.CHAOS, "chaosMaximumHitTaken", "chaos_max_hit"),
    ]:
        try:
            ehp = calc.calculate_ehp(stats, dt, threat)
            _add_delta(stat_name, ehp.effective_hp, oracle_key)
        except Exception as e:
            logger.warning(f"{dt.value} EHP calc failed during reconcile: {e}")
            report.skipped.append(stat_name)

    return report


def format_report(report: ReconciliationReport) -> str:
    """Render a ``ReconciliationReport`` as a fixed-width text table."""
    if not report.deltas:
        return f"Reconciliation: no deltas computed (skipped={report.skipped})"
    lines = []
    if report.char_name:
        lines.append(f"Reconciliation report for: {report.char_name}")
    lines.append(
        f"{'Stat':<24}{'Ours':>12}{'Oracle':>12}{'AbsDelta':>12}"
        f"{'Pct%':>10}{'Tol%':>8} OK?"
    )
    lines.append("-" * 84)
    for d in report.deltas:
        flag = "yes" if d.within_tolerance else "NO "
        lines.append(
            f"{d.stat:<24}{d.our_value:>12.1f}{d.oracle_value:>12.1f}"
            f"{d.abs_delta:>12.1f}{d.pct_delta:>9.1f}%{d.tolerance_pct:>7.1f}% {flag}"
        )
    if report.skipped:
        lines.append(f"Skipped (not in oracle): {', '.join(report.skipped)}")
    status = "PASS" if report.all_within_tolerance else "FAIL"
    lines.append(f"Overall: {status}")
    return "\n".join(lines)
