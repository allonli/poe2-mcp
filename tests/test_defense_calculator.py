"""
Tests for src/calculator/defense_calculator.py.

Pure-math PoE2-specific defense formulas: armor DR, evasion chance, ES
recharge, resistance DR, block chance, plus combined effective-HP and damage-
taken calculations.

These are math + cap tests, no I/O. Headline locks:
  - PoE2 differs from PoE1: BLOCK cap = 50% (not 75%), ES recharge = 12.5%/s
    (not 20%), ES delay = 4s (not 2s). Constants test makes any drift loud.
  - Documented formulas (DR = A/(A+10D), Hit% = Acc*1.25*100/(Acc+Eva*0.3))
    verified at hand-computable values like the docstring example.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calculator.defense_calculator import (
    ArmorResult,
    BlockResult,
    DefenseCalculator,
    DefenseConstants,
    EnergyShieldResult,
    EvasionResult,
    ResistanceResult,
    armor_dr,
    block_effective,
    evasion_chance,
    resistance_dr,
)


@pytest.fixture
def calc():
    return DefenseCalculator()


# ---------------------------------------------------------------------------
# DefenseConstants — PoE2 values that differ from PoE1
# ---------------------------------------------------------------------------

def test_armor_constants():
    assert DefenseConstants.ARMOR_MAX_DR == 90.0
    assert DefenseConstants.ARMOR_MULTIPLIER == 10


def test_evasion_constants():
    assert DefenseConstants.EVASION_MIN_HIT_CHANCE == 5.0
    assert DefenseConstants.EVASION_MAX_HIT_CHANCE == 100.0
    assert DefenseConstants.EVASION_ACCURACY_MULTIPLIER == 1.25
    assert DefenseConstants.EVASION_DIVISOR == 0.3


def test_es_constants_poe2_specific():
    """PoE2 ES recharge differs from PoE1: 12.5%/sec (not 20%), 4s delay (not 2s).
    These values are user-facing — drift breaks every ES build's recovery math."""
    assert DefenseConstants.ES_BASE_RECHARGE_RATE == 12.5
    assert DefenseConstants.ES_BASE_DELAY == 4.0
    assert DefenseConstants.ES_DELAY_BASE_VALUE == 400
    assert DefenseConstants.ES_DELAY_DIVISOR_BASE == 100


def test_resistance_constants():
    assert DefenseConstants.RESISTANCE_DEFAULT_CAP == 75.0
    assert DefenseConstants.RESISTANCE_HARD_CAP == 90.0
    assert DefenseConstants.RESISTANCE_MIN == -200.0


def test_block_constants_poe2_specific():
    """PoE2 block cap is 50% (not 75% like PoE1). Pinning this so a copy-paste
    from a PoE1 calculator doesn't sneak the wrong cap back in."""
    assert DefenseConstants.BLOCK_MAX_CHANCE == 50.0
    assert DefenseConstants.BLOCK_MIN_CHANCE == 0.0


# ---------------------------------------------------------------------------
# calculate_armor_dr — formula: DR% = A / (A + 10 × D_raw)
# ---------------------------------------------------------------------------

def test_armor_dr_docstring_example(calc):
    """Locks in the docstring example: 5000 armor vs 1000 damage = 33.33% DR.
    Hand-check: 5000 / (5000 + 10*1000) = 5000/15000 = 0.3333..."""
    result = calc.calculate_armor_dr(5000, 1000)
    assert math.isclose(result.damage_reduction_percent, 33.3333, abs_tol=0.01)
    assert math.isclose(result.effective_damage, 666.666, abs_tol=0.1)
    assert not result.is_capped


def test_armor_dr_returns_armor_result(calc):
    result = calc.calculate_armor_dr(1000, 100)
    assert isinstance(result, ArmorResult)
    assert result.armor == 1000
    assert result.raw_damage == 100


def test_armor_dr_zero_damage_returns_zero(calc):
    result = calc.calculate_armor_dr(5000, 0)
    assert result.damage_reduction_percent == 0.0
    assert result.effective_damage == 0.0


def test_armor_dr_negative_armor_clamped_to_zero(calc):
    """Negative armor warns but doesn't crash — gear-stat-merge bugs can produce
    negatives; we'd rather degrade than blow up."""
    result = calc.calculate_armor_dr(-100, 1000)
    assert result.armor == 0
    assert result.damage_reduction_percent == 0.0


def test_armor_dr_caps_at_90_percent(calc):
    """Massive armor vs tiny hit naturally exceeds 90% — cap must kick in."""
    result = calc.calculate_armor_dr(1_000_000, 1)
    assert result.damage_reduction_percent == DefenseConstants.ARMOR_MAX_DR
    assert result.is_capped is True


# ---------------------------------------------------------------------------
# calculate_evasion_chance — formula: Hit% = (Acc * 1.25 * 100) / (Acc + Eva * 0.3)
# ---------------------------------------------------------------------------

def test_evasion_returns_evasion_result(calc):
    result = calc.calculate_evasion_chance(1000, 500)
    assert isinstance(result, EvasionResult)


def test_evasion_zero_accuracy_means_zero_hit_100_evade(calc):
    """No accuracy → guaranteed evade. Avoids div-by-zero."""
    result = calc.calculate_evasion_chance(1000, 0)
    assert result.hit_chance_percent == 0.0
    assert result.evade_chance_percent == 100.0


def test_evasion_hit_chance_capped_minimum_5_percent(calc):
    """Massive evasion still leaves a 5% min hit chance — game design."""
    result = calc.calculate_evasion_chance(1_000_000, 100)
    assert result.hit_chance_percent == DefenseConstants.EVASION_MIN_HIT_CHANCE
    assert result.evade_chance_percent == 95.0
    assert result.is_hit_capped is True


def test_evasion_hit_chance_capped_maximum_100_percent(calc):
    """When accuracy hugely dominates evasion, formula could exceed 100% — must cap."""
    result = calc.calculate_evasion_chance(0, 10_000)
    # No evasion, all-accuracy attacker → 100% hit
    assert result.hit_chance_percent == DefenseConstants.EVASION_MAX_HIT_CHANCE
    assert result.evade_chance_percent == 0.0
    assert result.is_hit_capped is True


def test_evasion_known_formula_value(calc):
    """Eva=1000, Acc=1000: Hit = (1000*1.25*100)/(1000 + 1000*0.3) = 125000/1300 ≈ 96.15%."""
    result = calc.calculate_evasion_chance(1000, 1000)
    expected_hit = (1000 * 1.25 * 100) / (1000 + 1000 * 0.3)
    assert math.isclose(result.hit_chance_percent, expected_hit, abs_tol=0.01)


def test_evasion_negative_inputs_clamped_to_zero(calc):
    result = calc.calculate_evasion_chance(-100, -50)
    assert result.evasion == 0
    assert result.accuracy == 0


# ---------------------------------------------------------------------------
# calculate_es_recharge — PoE2 12.5%/s base, 4s delay, delay = 400/(100 + faster%)
# ---------------------------------------------------------------------------

def test_es_recharge_base_values_at_no_modifiers(calc):
    """No modifiers: 12.5% of max ES per second, 4s delay."""
    result = calc.calculate_es_recharge(max_es=1000)
    assert isinstance(result, EnergyShieldResult)
    assert math.isclose(result.recharge_rate_percent, 12.5)
    assert math.isclose(result.recharge_per_second, 125.0)  # 12.5% of 1000
    assert math.isclose(result.delay_seconds, 4.0)  # 400 / (100 + 0)


def test_es_recharge_with_increased_recharge_rate(calc):
    """50% increased recharge rate → 12.5 * 1.5 = 18.75% per second."""
    result = calc.calculate_es_recharge(max_es=1000, increased_recharge_rate_percent=50)
    assert math.isclose(result.recharge_rate_percent, 18.75)
    assert math.isclose(result.recharge_per_second, 187.5)


def test_es_recharge_with_faster_start(calc):
    """100% faster start → delay = 400 / (100 + 100) = 2s."""
    result = calc.calculate_es_recharge(max_es=1000, faster_start_percent=100)
    assert math.isclose(result.delay_seconds, 2.0)


def test_es_recharge_time_to_full_includes_delay(calc):
    """time_to_full = max_es / per_sec + delay. 1000 ES at 125/sec + 4s delay = 12s."""
    result = calc.calculate_es_recharge(max_es=1000)
    assert math.isclose(result.time_to_full_seconds, 12.0)


def test_es_recharge_zero_es_yields_infinite_recharge_time(calc):
    result = calc.calculate_es_recharge(max_es=0)
    assert result.recharge_per_second == 0
    assert math.isinf(result.time_to_full_seconds)


def test_es_recharge_negative_es_clamped(calc):
    result = calc.calculate_es_recharge(max_es=-100)
    assert result.max_es == 0


# ---------------------------------------------------------------------------
# calculate_resistance_dr — Damage = (100 - Res%) / 100
# ---------------------------------------------------------------------------

def test_resistance_under_cap(calc):
    """50% resistance → takes 50% damage."""
    result = calc.calculate_resistance_dr(50)
    assert isinstance(result, ResistanceResult)
    assert math.isclose(result.damage_taken_multiplier, 0.5)
    assert math.isclose(result.damage_reduction_percent, 50.0)
    assert not result.is_capped
    assert not result.is_over_cap


def test_resistance_at_default_cap(calc):
    """75% resistance at 75% cap — exactly at cap, not over."""
    result = calc.calculate_resistance_dr(75)
    assert math.isclose(result.damage_taken_multiplier, 0.25)
    assert not result.is_capped


def test_resistance_over_cap_truncated(calc):
    """80% resistance with default 75% cap → effective 75%, flags is_over_cap."""
    result = calc.calculate_resistance_dr(80)
    assert math.isclose(result.damage_taken_multiplier, 0.25)
    assert result.is_capped
    assert result.is_over_cap


def test_resistance_negative_takes_more_damage(calc):
    """-30% resistance → takes 130% damage."""
    result = calc.calculate_resistance_dr(-30)
    assert math.isclose(result.damage_taken_multiplier, 1.3)
    assert math.isclose(result.damage_reduction_percent, -30.0)


def test_resistance_below_minimum_clamped(calc):
    """-500% resistance clamped to -200% per RESISTANCE_MIN."""
    result = calc.calculate_resistance_dr(-500)
    assert result.resistance_percent == DefenseConstants.RESISTANCE_MIN


def test_resistance_cap_exceeding_hard_cap_warned_and_clamped(calc):
    """User passes cap=95, gets clamped to RESISTANCE_HARD_CAP=90."""
    result = calc.calculate_resistance_dr(100, cap=95)
    # Effective cap should be 90, so 100% res becomes 90%
    assert result.resistance_percent == DefenseConstants.RESISTANCE_HARD_CAP
    assert result.is_capped


# ---------------------------------------------------------------------------
# calculate_block_chance — PoE2 50% cap
# ---------------------------------------------------------------------------

def test_block_under_cap(calc):
    result = calc.calculate_block_chance(40)
    assert isinstance(result, BlockResult)
    assert result.block_chance_percent == 40
    assert not result.is_capped


def test_block_at_cap(calc):
    result = calc.calculate_block_chance(50)
    assert result.block_chance_percent == 50
    assert not result.is_capped


def test_block_over_cap_truncated_to_50_not_75(calc):
    """Headline regression guard: 60% input must cap at 50%, NOT 75% (PoE1 value).
    Copy-pasting from a PoE1 calculator would silently raise this to 75."""
    result = calc.calculate_block_chance(60)
    assert result.block_chance_percent == 50
    assert result.is_capped


def test_block_negative_clamped_to_zero(calc):
    result = calc.calculate_block_chance(-10)
    assert result.block_chance_percent == 0.0


# ---------------------------------------------------------------------------
# Module-level convenience wrappers
# ---------------------------------------------------------------------------

def test_armor_dr_helper_wraps_method():
    """Wrapper returns the .damage_reduction_percent field of the method result."""
    assert math.isclose(armor_dr(5000, 1000), 33.3333, abs_tol=0.01)


def test_evasion_chance_helper_returns_evade_not_hit():
    """Note: module-level helper returns EVADE chance, not hit chance —
    documented in the docstring. Catches misuse."""
    val = evasion_chance(1_000_000, 100)
    # Massive evasion → ~95% evade (5% min hit)
    assert math.isclose(val, 95.0)


def test_resistance_dr_helper_uses_default_cap():
    """Default cap is 75% — passing 80% caps to 75%, DR = 75%."""
    assert math.isclose(resistance_dr(80), 75.0)


def test_resistance_dr_helper_explicit_cap():
    """Passing a lower cap takes effect."""
    assert math.isclose(resistance_dr(60, cap=50), 50.0)


def test_block_effective_helper_caps_at_50():
    assert block_effective(75) == 50.0
    assert block_effective(40) == 40.0
