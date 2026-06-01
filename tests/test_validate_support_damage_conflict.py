"""
Tests for the damage-type-conflict enrichment in validate_support_combination
(Issue #117).

Two test modes:
  - Calculator-direct tests instantiate GemSynergyCalculator and exercise
    validate_combination + its new helpers in isolation. These verify the
    name-pattern requirement mapping, the spell-tag lookup, and the
    valid/warnings contract. No MCP init.
  - Handler tests cover the MCP wiring: the spell_name argument is forwarded
    and warnings surface in the formatted response.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helper-direct mode — imports the light support_validation module so
# unit tests don't pay SQLAlchemy import cost on the gem_synergy_calculator
# module load.
# ---------------------------------------------------------------------------

from src.optimizer.support_validation import (  # noqa: E402
    SUPPORT_DAMAGE_REQUIREMENTS,
    check_semantic_conflicts,
    lookup_spell_tags,
    support_required_tags,
)


def test_required_tags_known_patterns():
    """Pattern dictionary returns the right tag lists."""
    assert "fire" in support_required_tags("Added Fire Damage Support")
    assert "cold" in support_required_tags("Added Cold Damage Support")
    assert "minion" in support_required_tags("Minion Damage Support")
    # Pattern works even without trailing 'Support'
    assert "fire" in support_required_tags("Added Fire Damage")


def test_required_tags_unknown_returns_empty():
    """Supports with no registered requirement (most of them) return []."""
    assert support_required_tags("Rage Support") == []
    assert support_required_tags("Random Made Up Name") == []


def test_spell_tag_lookup_ice_nova():
    """Spell-tag lookup resolves a canonical spell from skill_gems data."""
    tags = lookup_spell_tags("Ice Nova")
    assert tags is not None
    assert "cold" in tags
    assert "spell" in tags


def test_spell_tag_lookup_unknown_returns_none():
    """Unknown spell -> None (not [])."""
    assert lookup_spell_tags("NotARealSpellAtAll") is None


def test_check_semantic_conflicts_added_fire_on_ice_nova_warns():
    """Headline #117 case: Added Fire Damage Support on Ice Nova (cold)."""
    result = check_semantic_conflicts(
        ["Added Fire Damage Support"], spell_name="Ice Nova"
    )
    assert result["warnings"], "expected a semantic warning"
    w = result["warnings"][0]
    assert "Added Fire Damage Support" in w["support"]
    assert "Ice Nova" in w["spell"]
    assert "fire" in w["required_any_of"]
    assert "cold" in (result["spell_tags"] or [])


def test_check_semantic_conflicts_fire_on_fire_no_warning():
    """Counter-case: Added Fire Damage Support on Fireball is fine."""
    result = check_semantic_conflicts(
        ["Added Fire Damage Support"], spell_name="Fireball"
    )
    assert result["warnings"] == [], (
        f"unexpected warning on fire support + fire spell: {result['warnings']}"
    )


def test_check_semantic_conflicts_minion_support_on_non_minion_warns():
    result = check_semantic_conflicts(
        ["Minion Damage Support"], spell_name="Ice Nova"
    )
    assert result["warnings"]
    assert "minion" in result["warnings"][0]["required_any_of"]


def test_check_semantic_conflicts_mixed_only_warns_offenders():
    """A support fine for the spell shouldn't be flagged."""
    result = check_semantic_conflicts(
        ["Added Fire Damage Support", "Concentrated Effect Support"],
        spell_name="Ice Nova",
    )
    warned = {w["support"] for w in result["warnings"]}
    assert "Added Fire Damage Support" in warned
    assert "Concentrated Effect Support" not in warned


def test_check_semantic_conflicts_no_spell_name_returns_empty():
    """Backward compat path: no spell_name -> no warnings."""
    result = check_semantic_conflicts(["Added Fire Damage Support"])
    assert result["warnings"] == []
    assert result["spell_tags"] is None


def test_check_semantic_conflicts_unknown_spell_returns_empty():
    """Unknown spell -> can't resolve tags -> no warnings (graceful)."""
    result = check_semantic_conflicts(
        ["Added Fire Damage Support"], spell_name="UnknownSpellXYZ"
    )
    assert result["warnings"] == []
    assert result["spell_tags"] is None


def test_requirements_dict_has_expected_coverage():
    """Sanity check: the requirements map covers each major axis."""
    keys = SUPPORT_DAMAGE_REQUIREMENTS.keys()
    assert any("added fire" in k for k in keys)
    assert any("minion" in k for k in keys)
    assert any("melee" in k for k in keys)
    assert any("projectile" in k for k in keys) or any("fork" in k for k in keys)


# ---------------------------------------------------------------------------
# Handler mode — methodology-rule lazy fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module")
async def mcp():
    from src.mcp_server import PoE2BuildOptimizerMCP
    instance = PoE2BuildOptimizerMCP()
    await instance.initialize()
    return instance


@pytest.mark.asyncio
async def test_handler_forwards_spell_name(mcp):
    """The MCP handler accepts spell_name and surfaces semantic warnings."""
    r = await mcp._handle_validate_support_combination({
        "support_gems": ["Added Fire Damage Support"],
        "spell_name": "Ice Nova",
    })
    text = r[0].text
    assert "Warnings" in text or "warning" in text.lower()
    assert "Ice Nova" in text


@pytest.mark.asyncio
async def test_handler_no_spell_name_works_unchanged(mcp):
    """Backward compat: no spell_name still produces a valid/invalid line."""
    r = await mcp._handle_validate_support_combination({
        "support_gems": ["Rage Support"],
    })
    text = r[0].text
    assert "Valid combination" in text or "Invalid combination" in text


@pytest.mark.asyncio
async def test_handler_includes_provenance_banner(mcp):
    """Per #116 pattern, the response carries the COMPUTED tier banner."""
    r = await mcp._handle_validate_support_combination({
        "support_gems": ["Rage Support"],
        "spell_name": "Fireball",
    })
    text = r[0].text
    assert "**Data**:" in text and "**Tier**: computed" in text
