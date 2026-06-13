"""
Tests for weapon-set-aware gear rendering in analyze_character (#183 follow-up).

Items tagged weapon_set==2 must render in a separate "Weapon Set 2 (swap)"
section, never flattened into the active gear — the fix for the build-
analysis bug where a swap staff's stats read as active during set-1 play.
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
    s = PoE2BuildOptimizerMCP()
    await s.initialize()
    return s


def _char():
    # Mirrors the real TomawarTheSeventh two-set layout
    return {
        "name": "SwapTest", "class": "Witch", "level": 90,
        "passive_tree": [], "skills": [],
        "items": [
            {"slot": "Weapon", "weapon_set": 1, "name": "Torment Song",
             "type_line": "Wand", "rarity": 2, "mods": ["+6 to Level of all Fire Spell Skills"]},
            {"slot": "Offhand", "weapon_set": 1, "name": "The Dark Defiler",
             "type_line": "Rattling Sceptre", "rarity": 3, "mods": ["15% increased Spirit"]},
            {"slot": "Weapon 1 Swap", "weapon_set": 2, "name": "The Unborn Lich",
             "type_line": "Staff", "rarity": 3, "mods": ["195% increased Chaos Damage", "+86 to Spirit"]},
            {"slot": "BodyArmour", "weapon_set": None, "name": "Necromantle",
             "type_line": "Conjurer Mantle", "rarity": 2, "mods": ["+55 to maximum Life"]},
        ],
    }


def test_swap_weapon_in_separate_section(mcp):
    text = mcp._format_character_analysis(_char(), analysis={}, recommendations="", passive_analysis=None)
    assert "## Weapon Set 2 (swap)" in text
    # The chaos staff appears under the swap section, not the active Equipment block
    eq, swap = text.split("## Weapon Set 2 (swap)")
    assert "The Unborn Lich" in swap
    assert "The Unborn Lich" not in eq           # NOT flattened into active gear
    assert "195% increased Chaos Damage" in swap


def test_active_set_intact(mcp):
    text = mcp._format_character_analysis(_char(), analysis={}, recommendations="", passive_analysis=None)
    eq = text.split("## Weapon Set 2 (swap)")[0]
    assert "Torment Song" in eq                  # set-1 weapon stays in active gear
    assert "The Dark Defiler" in eq
    assert "Necromantle" in eq                   # body armour (set-independent)
    assert "swap" in text.lower()                # the caveat note is present


def test_no_swap_section_for_single_set(mcp):
    """A build with no weapon_set==2 items renders no swap section."""
    char = _char()
    char["items"] = [i for i in char["items"] if i.get("weapon_set") != 2]
    text = mcp._format_character_analysis(char, analysis={}, recommendations="", passive_analysis=None)
    assert "Weapon Set 2 (swap)" not in text
    assert "Torment Song" in text
