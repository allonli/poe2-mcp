"""
Tests for the post-#164 issue batch:
  #152 — validate_build_constraints silently ignored resistances under
         both common schemas (flat + nested); now all three shapes parse
         and absent fields are reported as SKIPPED, never zeroed
  #153 — explicit nulls crashed with TypeError; now treated as absent
  #154 — reconcile_defensive_stats handler was never registered
  #149 — analyze_character response exposes raw passive_node_ids
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.mcp_server import PoE2BuildOptimizerMCP


@pytest_asyncio.fixture(scope="module")
async def mcp():
    instance = PoE2BuildOptimizerMCP()
    await instance.initialize()
    return instance


async def _validate(mcp_instance, character_data):
    r = await mcp_instance._handle_validate_build_constraints(
        {"character_data": character_data}
    )
    return r[0].text


# ---------------------------------------------------------------------------
# #152 — resistance schema shapes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flat_resistance_shape_parsed(mcp):
    """The exact flat shape from the #152 repro must be read, not zeroed."""
    text = await _validate(mcp, {
        "fire_resistance": -24,
        "cold_resistance": -38,
        "lightning_resistance": 0,
        "chaos_resistance": 19,
        "life_plus_es": 1199,
        "level": 59,
    })
    assert "-24%" in text            # the actual value, not 0
    assert "-38%" in text
    assert "Fire Res (not provided)" not in text
    assert "Skipped" not in text or "Res (not provided)" not in text


@pytest.mark.asyncio
async def test_nested_resistance_shape_parsed(mcp):
    """The nested shape from the #152 repro must also be read."""
    text = await _validate(mcp, {
        "resistances": {"fire": -24, "cold": 80, "lightning": 95},
        "level": 59,
    })
    assert "-24%" in text            # fire below cap, real value shown
    assert "95%" in text             # lightning over 90 hard cap
    assert "exceeds hard cap" in text


@pytest.mark.asyncio
async def test_legacy_res_keys_still_work(mcp):
    text = await _validate(mcp, {"fire_res": -70, "level": 10})
    assert "below minimum (-60%)" in text
    assert "-70%" in text


@pytest.mark.asyncio
async def test_absent_resistances_skipped_not_zeroed(mcp):
    """No resistance keys at all -> SKIPPED notes, no bogus 0% violations."""
    text = await _validate(mcp, {"life": 2000, "level": 30})
    assert "Fire Res (not provided)" in text
    assert "Cold Res (not provided)" in text
    assert "0%" not in text          # nothing validated as zero


@pytest.mark.asyncio
async def test_chaos_res_only_floor_checked(mcp):
    """Chaos res below 75 is NOT flagged (deliberate in PoE2); below -60 is."""
    ok = await _validate(mcp, {"chaos_resistance": -40, "level": 10})
    assert "Chaos Res is below minimum" not in ok
    bad = await _validate(mcp, {"chaos_resistance": -75, "level": 10})
    assert "Chaos Res is below minimum" in bad


# ---------------------------------------------------------------------------
# #153 — null tolerance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_explicit_nulls_do_not_crash(mcp):
    """The exact failure shape from the #153 repro: explicit nulls."""
    text = await _validate(mcp, {
        "level": 59,
        "spirit": None,
        "mana_reservation": None,
        "fire_resistance": None,
        "life": None,
    })
    assert "TypeError" not in text
    assert "Error:" not in text
    assert "Spirit allocation" in text       # reported skipped
    assert "(not provided)" in text


@pytest.mark.asyncio
async def test_spirit_overflow_still_detected(mcp):
    text = await _validate(mcp, {
        "spirit": 100, "spirit_reserved": 130, "level": 50,
    })
    assert "Spirit overflow" in text


@pytest.mark.asyncio
async def test_life_plus_es_combined_field(mcp):
    """#152 repro used life_plus_es — must feed the survivability check."""
    low = await _validate(mcp, {"life_plus_es": 500, "level": 59})
    assert "below recommended" in low
    fine = await _validate(mcp, {"life_plus_es": 5000, "level": 59})
    assert "below recommended" not in fine


@pytest.mark.asyncio
async def test_numeric_strings_accepted(mcp):
    text = await _validate(mcp, {"fire_resistance": "75", "level": "59"})
    assert "Fire Res (not provided)" not in text
    assert "Error" not in text


# ---------------------------------------------------------------------------
# #154 — reconcile_defensive_stats registration
# ---------------------------------------------------------------------------

def test_reconcile_tool_registered():
    """Registration + dispatch wiring exist in the server source (#154's
    whole complaint was the handler existing without either). Same
    feature-detection pattern as the PR #107 marker tests."""
    src = (PROJECT_ROOT / "src" / "mcp_server.py").read_text(encoding="utf-8")
    assert 'name="reconcile_defensive_stats"' in src, "Tool not registered"
    assert 'elif name == "reconcile_defensive_stats":' in src, "Dispatch missing"


@pytest.mark.asyncio
async def test_reconcile_handler_runs(mcp):
    """Handler wires to the #139 harness and renders the delta table."""
    r = await mcp._handle_reconcile_defensive_stats({
        "char_model": {
            "name": "FixtureChar",
            "defensiveStats": {
                "life": 3000, "energyShield": 0, "armour": 10000,
                "evasion": 0, "fireResistance": 75, "coldResistance": 75,
                "lightningResistance": 75, "chaosResistance": 0,
                "effectiveHealthPool": 9000,
            },
        }
    })
    text = r[0].text
    assert "Defensive Stats Reconciliation" in text
    assert "Verdict" in text
    assert "Error" not in text.split("Verdict")[0]


@pytest.mark.asyncio
async def test_reconcile_requires_char_model(mcp):
    r = await mcp._handle_reconcile_defensive_stats({})
    assert "char_model" in r[0].text
    assert "required" in r[0].text


# ---------------------------------------------------------------------------
# #149 — passive_node_ids in the analyze_character response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_passive_node_ids_rendered(mcp):
    """The response formatter surfaces the raw id array + unresolved list."""
    character_data = {
        "name": "TestChar",
        "class": "Witch",
        "level": 90,
        "passive_tree": [4, 11578, 999999999],  # last id won't resolve
        "items": [],
        "skills": [],
    }
    text = mcp._format_character_analysis(
        character_data, analysis={}, recommendations="", passive_analysis=None
    )
    assert "Passive Node IDs (3)" in text
    assert "`passive_node_ids`: [4, 11578, 999999999]" in text
    assert "`unresolved_node_ids`" in text
    assert "999999999" in text.split("unresolved_node_ids")[1].splitlines()[0]
    assert "analyze_passive_tree" in text


@pytest.mark.asyncio
async def test_passive_node_ids_handles_pob_tree_dict(mcp):
    """PoB-route characters carry the tree as {allocated_nodes: [...]}."""
    character_data = {
        "name": "PoBChar",
        "class": "Monk",
        "level": 50,
        "passive_tree": {"allocated_nodes": [4, 11578], "total_points": 2},
        "items": [],
        "skills": [],
    }
    text = mcp._format_character_analysis(
        character_data, analysis={}, recommendations="", passive_analysis=None
    )
    assert "Passive Node IDs (2)" in text
    assert "[4, 11578]" in text


@pytest.mark.asyncio
async def test_no_node_ids_no_section(mcp):
    character_data = {
        "name": "Bare", "class": "Witch", "level": 1,
        "passive_tree": [], "items": [], "skills": [],
    }
    text = mcp._format_character_analysis(
        character_data, analysis={}, recommendations="", passive_analysis=None
    )
    assert "Passive Node IDs" not in text


# ---------------------------------------------------------------------------
# Regression: items with explicit slot: null (cached/older records) must not
# crash the equipment formatter — .get('slot', default) does not cover None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_equipment_formatter_tolerates_null_slot(mcp):
    character_data = {
        "name": "NullSlotChar",
        "class": "Witch",
        "level": 87,
        "passive_tree": [],
        "skills": [{"name": None, "slot": None, "allGems": [], "gems": [], "dps": []}],
        "items": [
            {"slot": None, "name": "Mystery Item", "type_line": "Wand", "rarity": 2, "mods": {}},
            {"slot": "Weapon", "name": "Real Wand", "type_line": "Wand", "rarity": 3, "mods": {}},
        ],
    }
    text = mcp._format_character_analysis(
        character_data, analysis={}, recommendations="", passive_analysis=None
    )
    assert "Real Wand" in text
    assert "Mystery Item" in text   # rendered under Unknown, not crashed
