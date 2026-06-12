"""
Campaign C1b: spirit reservations surface in inspect_spell_gem.

The canonical dataset gained per-level spirit_reservation_flat in
data-v0.5.0-r11 (PR #169); this locks the handler-side display so the
"what does this meta gem reserve" question is answerable in-tool.
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


@pytest.mark.asyncio
async def test_cast_on_minion_death_shows_reservation(mcp):
    r = await mcp._handle_inspect_spell_gem({"spell_name": "Cast on Minion Death"})
    text = r[0].text
    assert "Spirit Reservation: 30" in text


@pytest.mark.asyncio
async def test_cast_on_elemental_ailment_shows_reservation(mcp):
    r = await mcp._handle_inspect_spell_gem({"spell_name": "Cast on Elemental Ailment"})
    text = r[0].text
    assert "Spirit Reservation: 100" in text


@pytest.mark.asyncio
async def test_non_reserving_spell_has_no_reservation_line(mcp):
    r = await mcp._handle_inspect_spell_gem({"spell_name": "Essence Drain"})
    text = r[0].text
    assert "Spirit Reservation" not in text
    assert "Cost: Mana: 5" in text  # mana costs still render
