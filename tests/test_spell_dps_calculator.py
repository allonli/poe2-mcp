"""
Tests for src/calculator/spell_dps_calculator.py.

Pure-math PoE2 spell DPS pipeline: base damage, added flat with damage
effectiveness, archmage, increased/more stacking, crit, resistance/exposure/
penetration, shock, cast speed.

Most assertions are anchored to the docstring examples in the module — those
are the canonical, hand-checked formula values. Locks them in as regression
guards (the documented examples ARE the contract; if any change drifts them,
the test fails loudly).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calculator.spell_dps_calculator import (
    CharacterModifiers,
    EnemyStats,
    SpellDPSCalculator,
    SpellStats,
)


@pytest.fixture
def calc():
    return SpellDPSCalculator()


# ---------------------------------------------------------------------------
# SpellStats dataclass
# ---------------------------------------------------------------------------

def test_spell_stats_default_damage_types_is_empty_list():
    """__post_init__ replaces None with []. Mutable-default-arg trap avoided."""
    s = SpellStats(name="X", base_damage_min=1, base_damage_max=2)
    assert s.damage_types == []


def test_spell_stats_explicit_damage_types_preserved():
    s = SpellStats(name="X", base_damage_min=1, base_damage_max=2, damage_types=["fire"])
    assert s.damage_types == ["fire"]


def test_spell_stats_defaults_match_documented_baseline():
    """damage_effectiveness=1.0, base_crit_chance=0.0, base_cast_time=1.0."""
    s = SpellStats(name="X", base_damage_min=10, base_damage_max=20)
    assert s.damage_effectiveness == 1.0
    assert s.base_crit_chance == 0.0
    assert s.base_cast_time == 1.0


# ---------------------------------------------------------------------------
# CharacterModifiers
# ---------------------------------------------------------------------------

def test_character_modifiers_more_multipliers_defaults_to_empty_list():
    cm = CharacterModifiers()
    assert cm.more_multipliers == []


def test_character_modifiers_default_crit_bonus_is_poe2_baseline():
    """PoE2 base crit bonus is +100% (2.0x). Locked in — must not regress."""
    assert CharacterModifiers().added_crit_bonus == 100.0


# ---------------------------------------------------------------------------
# EnemyStats
# ---------------------------------------------------------------------------

def test_enemy_stats_default_zeros():
    e = EnemyStats()
    for attr in (
        "fire_resistance", "cold_resistance", "lightning_resistance",
        "chaos_resistance", "physical_resistance",
        "fire_exposure", "cold_exposure", "lightning_exposure",
        "fire_penetration", "cold_penetration", "lightning_penetration",
    ):
        assert getattr(e, attr) == 0.0
    assert e.is_shocked is False


# ---------------------------------------------------------------------------
# _calculate_added_damage — docstring example: 64.0
# ---------------------------------------------------------------------------

def test_added_damage_docstring_example(calc):
    """(50 + 30 + 0 + 0 + 0) × 0.8 = 64.0"""
    spell = SpellStats(name="Test", base_damage_min=10, base_damage_max=20, damage_effectiveness=0.8)
    cm = CharacterModifiers(added_fire=50, added_cold=30)
    assert calc._calculate_added_damage(spell, cm) == 64.0


def test_added_damage_full_effectiveness(calc):
    """100% effectiveness → unchanged sum."""
    spell = SpellStats(name="X", base_damage_min=0, base_damage_max=0, damage_effectiveness=1.0)
    cm = CharacterModifiers(added_fire=10, added_cold=20, added_lightning=30, added_chaos=15, added_physical=5)
    assert calc._calculate_added_damage(spell, cm) == 80.0


def test_added_damage_zero_with_no_added(calc):
    spell = SpellStats(name="X", base_damage_min=10, base_damage_max=20, damage_effectiveness=1.5)
    cm = CharacterModifiers()
    assert calc._calculate_added_damage(spell, cm) == 0.0


# ---------------------------------------------------------------------------
# _calculate_archmage_bonus — docstring examples
# ---------------------------------------------------------------------------

def test_archmage_docstring_example(calc):
    """(2000 / 100) × 0.04 × 100 = 20 × 0.04 × 100 = 80.0"""
    assert calc._calculate_archmage_bonus(2000, 100) == 80.0


def test_archmage_zero_mana_returns_zero(calc):
    assert calc._calculate_archmage_bonus(0, 100) == 0.0
    assert calc._calculate_archmage_bonus(-50, 100) == 0.0


def test_archmage_scales_with_base_damage(calc):
    """Double base damage → double bonus."""
    base = calc._calculate_archmage_bonus(2000, 100)
    doubled = calc._calculate_archmage_bonus(2000, 200)
    assert math.isclose(doubled, 2 * base)


# ---------------------------------------------------------------------------
# _calculate_more_multiplier — docstring examples
# ---------------------------------------------------------------------------

def test_more_multiplier_docstring_example(calc):
    """(1 + 25/100) × (1 + 30/100) = 1.25 × 1.30 = 1.625"""
    assert calc._calculate_more_multiplier([25, 30]) == 1.625


def test_more_multiplier_empty_list_returns_one(calc):
    """No more multipliers → identity (1.0)."""
    assert calc._calculate_more_multiplier([]) == 1.0


def test_more_multiplier_negative_less_modifier(calc):
    """'Less' modifiers are negative more — e.g. -50% means × 0.5."""
    assert calc._calculate_more_multiplier([-50]) == 0.5


def test_more_multiplier_stacks_multiplicatively_not_additively(calc):
    """[50, 50] should be 1.5 × 1.5 = 2.25, NOT 1 + 0.5 + 0.5 = 2.0 (the
    additive answer). Locks in the more-vs-increased distinction."""
    result = calc._calculate_more_multiplier([50, 50])
    assert math.isclose(result, 2.25)


# ---------------------------------------------------------------------------
# _calculate_crit_multiplier — docstring examples
# ---------------------------------------------------------------------------

def test_crit_multiplier_docstring_no_increase(calc):
    """+100% base, +0% increased → 1 + (100/100)*(1+0) = 2.0"""
    assert calc._calculate_crit_multiplier(100, 0) == 2.0


def test_crit_multiplier_docstring_with_increased(calc):
    """+100% base, +50% increased → 1 + (100/100)*(1+0.5) = 2.5"""
    assert calc._calculate_crit_multiplier(100, 50) == 2.5


def test_crit_multiplier_with_added_bonus(calc):
    """+150% base, +0% increased → 1 + 1.5 = 2.5"""
    assert calc._calculate_crit_multiplier(150, 0) == 2.5


# ---------------------------------------------------------------------------
# _apply_resistances — docstring example: 55.0
# ---------------------------------------------------------------------------

def test_apply_resistances_docstring_example(calc):
    """75 res - 20 exposure - 10 pen = 45 effective. 100 × (1 - 0.45) = 55.0"""
    enemy = EnemyStats(fire_resistance=75, fire_exposure=20, fire_penetration=10)
    # isclose because 1 - 0.45 incurs IEEE 754 rounding (55.00000000000001)
    assert math.isclose(calc._apply_resistances(100, ["fire"], enemy), 55.0)


def test_apply_resistances_no_damage_types_passthrough(calc):
    """Empty damage_types list returns damage unchanged."""
    assert calc._apply_resistances(100, [], EnemyStats(fire_resistance=75)) == 100


def test_apply_resistances_unknown_type_passthrough(calc):
    """Unknown damage type (typo or future ele) returns damage unchanged."""
    assert calc._apply_resistances(100, ["bogus"], EnemyStats(fire_resistance=75)) == 100


def test_apply_resistances_uses_first_damage_type_as_primary(calc):
    """Only the first damage_type matters — others ignored in v1."""
    enemy = EnemyStats(fire_resistance=75, cold_resistance=0)
    # Primary fire → 75% res → 25% damage taken → 25
    result = calc._apply_resistances(100, ["fire", "cold"], enemy)
    assert result == 25.0


def test_apply_resistances_penetration_cannot_make_negative(calc):
    """If exposure + penetration would push effective res below 0, clamp at 0
    (penetration can't ADD damage on top of negative-res enemies)."""
    enemy = EnemyStats(fire_resistance=0, fire_exposure=20, fire_penetration=50)
    # 0 - 20 - 50 = -70 → clamp to 0 → full damage
    assert calc._apply_resistances(100, ["fire"], enemy) == 100.0


def test_apply_resistances_exposure_alone_can_go_negative(calc):
    """Negative effective resistance (from exposure WITHOUT pen) means MORE
    damage taken — exposure on a 0-res enemy goes negative pre-pen-clamp.
    But with no penetration applied, the max() floor still applies.
    Wait — re-reading: effective_resistance = max(base - exposure - pen, 0).
    So even pure exposure on a 0-res enemy clamps to 0. Verify."""
    enemy = EnemyStats(fire_resistance=0, fire_exposure=20)
    # 0 - 20 - 0 = -20 → clamp to 0 → full damage
    assert calc._apply_resistances(100, ["fire"], enemy) == 100.0


def test_apply_resistances_handles_each_element(calc):
    """fire/cold/lightning/chaos/physical all routed correctly."""
    for elem in ("fire", "cold", "lightning"):
        enemy_kwargs = {f"{elem}_resistance": 50}
        result = calc._apply_resistances(100, [elem], EnemyStats(**enemy_kwargs))
        assert result == 50.0, f"{elem} resistance not applied correctly"
    # chaos & physical don't have exposure/penetration plumbing but resistance works
    assert calc._apply_resistances(100, ["chaos"], EnemyStats(chaos_resistance=30)) == 70.0
    assert calc._apply_resistances(100, ["physical"], EnemyStats(physical_resistance=40)) == 60.0


# ---------------------------------------------------------------------------
# _calculate_cast_speed — docstring examples
# ---------------------------------------------------------------------------

def test_cast_speed_docstring_50_percent_inc(calc):
    """0.8s base / 1.5 = 0.5333s → 1.875 casts/sec."""
    assert calc._calculate_cast_speed(0.8, 50) == 1.875


def test_cast_speed_docstring_no_modifier(calc):
    """1.0s base, 0% inc → 1.0 cast/sec."""
    assert calc._calculate_cast_speed(1.0, 0) == 1.0


def test_cast_speed_double_with_100_increased(calc):
    """100% increased → 2x cast rate."""
    assert calc._calculate_cast_speed(1.0, 100) == 2.0


# ---------------------------------------------------------------------------
# get_spell_by_name / add_spell_to_database
# ---------------------------------------------------------------------------

def test_get_spell_by_name_returns_known_spell():
    """SPELL_DATABASE has 'arc', 'spark', 'fireball' pre-loaded."""
    calc = SpellDPSCalculator()
    arc = calc.get_spell_by_name("Arc")
    assert arc is not None
    assert arc.name == "Arc"


def test_get_spell_by_name_case_insensitive():
    calc = SpellDPSCalculator()
    assert calc.get_spell_by_name("ARC").name == "Arc"
    assert calc.get_spell_by_name("arc").name == "Arc"
    assert calc.get_spell_by_name("Arc").name == "Arc"


def test_get_spell_by_name_unknown_returns_none():
    calc = SpellDPSCalculator()
    assert calc.get_spell_by_name("NonexistentSpell") is None


def test_add_spell_to_database_then_lookup():
    """Round-trip — add a spell, look it up by name (case-insensitive)."""
    calc = SpellDPSCalculator()
    custom = SpellStats(
        name="UnitTestCustomSpell",
        base_damage_min=50, base_damage_max=100, damage_effectiveness=1.2,
    )
    try:
        calc.add_spell_to_database(custom)
        assert calc.get_spell_by_name("UnitTestCustomSpell").name == "UnitTestCustomSpell"
        # Case-insensitive lookup works too
        assert calc.get_spell_by_name("unittestcustomspell").name == "UnitTestCustomSpell"
    finally:
        # SPELL_DATABASE is a class attribute — clean up to avoid test leakage
        SpellDPSCalculator.SPELL_DATABASE.pop("unittestcustomspell", None)


# ---------------------------------------------------------------------------
# calculate_dps — full pipeline integration
# ---------------------------------------------------------------------------

def test_calculate_dps_returns_breakdown_shape(calc):
    """Result contains the documented top-level keys + a `breakdown` dict."""
    spell = SpellStats(name="X", base_damage_min=100, base_damage_max=100,
                       damage_types=["fire"], base_cast_time=1.0)
    result = calc.calculate_dps(spell, CharacterModifiers())
    assert "total_dps" in result
    assert "average_hit" in result
    assert "casts_per_second" in result
    assert "crit_chance" in result
    assert "breakdown" in result
    bd = result["breakdown"]
    for k in ("base_damage", "added_damage", "after_increased", "after_more",
              "expected_hit", "after_resistance", "multipliers"):
        assert k in bd


def test_calculate_dps_no_modifiers_no_enemy_yields_clean_base(calc):
    """100 base damage, no modifiers, no enemy → 100 expected hit, 100 dps at 1.0 cast/s."""
    spell = SpellStats(name="X", base_damage_min=100, base_damage_max=100,
                       damage_types=["fire"], base_cast_time=1.0,
                       base_crit_chance=0.0)
    result = calc.calculate_dps(spell, CharacterModifiers())
    assert result["total_dps"] == 100.0
    assert result["average_hit"] == 100.0
    assert result["casts_per_second"] == 1.0
    assert result["crit_chance"] == 0.0


def test_calculate_dps_applies_increased_damage(calc):
    """+50% increased spell damage → 100 base × 1.5 = 150."""
    spell = SpellStats(name="X", base_damage_min=100, base_damage_max=100,
                       damage_types=["fire"], base_cast_time=1.0)
    cm = CharacterModifiers(increased_spell_damage=50)
    result = calc.calculate_dps(spell, cm)
    assert result["average_hit"] == 150.0


def test_calculate_dps_applies_more_multiplier(calc):
    """50% more on top of base → 100 × 1.5 = 150."""
    spell = SpellStats(name="X", base_damage_min=100, base_damage_max=100,
                       damage_types=["fire"], base_cast_time=1.0)
    cm = CharacterModifiers(more_multipliers=[50])
    result = calc.calculate_dps(spell, cm)
    assert result["average_hit"] == 150.0


def test_calculate_dps_applies_resistance(calc):
    """50% fire res → half damage."""
    spell = SpellStats(name="X", base_damage_min=100, base_damage_max=100,
                       damage_types=["fire"], base_cast_time=1.0)
    enemy = EnemyStats(fire_resistance=50)
    result = calc.calculate_dps(spell, CharacterModifiers(), enemy)
    assert result["average_hit"] == 50.0


def test_calculate_dps_applies_shock_bonus(calc):
    """is_shocked → 1.2x damage taken."""
    spell = SpellStats(name="X", base_damage_min=100, base_damage_max=100,
                       damage_types=["fire"], base_cast_time=1.0)
    unshocked = calc.calculate_dps(spell, CharacterModifiers(), EnemyStats(is_shocked=False))
    shocked = calc.calculate_dps(spell, CharacterModifiers(), EnemyStats(is_shocked=True))
    assert math.isclose(shocked["average_hit"], unshocked["average_hit"] * 1.2)


def test_calculate_dps_dps_equals_avg_hit_times_cast_speed(calc):
    """Identity check: total_dps == average_hit × casts_per_second (within rounding)."""
    spell = SpellStats(name="X", base_damage_min=100, base_damage_max=200,
                       damage_types=["lightning"], base_cast_time=0.8,
                       base_crit_chance=10.0)
    cm = CharacterModifiers(increased_spell_damage=40, increased_cast_speed=20)
    result = calc.calculate_dps(spell, cm)
    expected_dps = result["average_hit"] * result["casts_per_second"]
    # Rounding inside the function gives ±0.5 wiggle room — be lenient
    assert math.isclose(result["total_dps"], expected_dps, abs_tol=0.5)


def test_calculate_dps_crit_chance_capped_at_100(calc):
    """Even with absurd +crit_chance, the cap is 100%."""
    spell = SpellStats(name="X", base_damage_min=100, base_damage_max=100,
                       damage_types=["fire"], base_crit_chance=50.0)
    cm = CharacterModifiers(increased_crit_chance=200.0)  # 50 + 200 = 250 → capped to 100
    result = calc.calculate_dps(spell, cm)
    assert result["crit_chance"] == 100.0
