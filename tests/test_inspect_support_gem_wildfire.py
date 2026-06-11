"""
End-to-end handler tests for PR #107's Tier-2 fallback wiring on
inspect_support_gem.

PR #107 closes the documented Wildfire gap from HivemindOverlord's
2026-05-31 Claude Desktop session — Wildfire wasn't found because it only
exists in data/game/skill_gems/ (gem_type='Support'), not in the .datc64
support_gems table the handler primarily uses.

What's locked here (parallel to tests/test_explain_mechanic_provenance.py
which covers the PR #101 explain_mechanic two-tier rewire):

  - Tier 1 hit: a support that IS in .datc64 support_gems (Rage) returns
    its existing rich record — fallback path doesn't override.
  - Tier 2 hit: Wildfire (only in skill_gems) returns its gem metadata
    with the Tier-2 source note appended.
  - Both miss: garbage query returns a not-found that names BOTH datasets
    that were searched, so the caller knows we actually looked.

Methodology rule (per fire 28 retraction): every handler test goes through
`await mcp.initialize()`. Module-scoped fixture for the ~5s init cost.
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

# Feature-detect PR #107's Tier-2 fallback. The handler source carries a
# stable marker string when the fallback wiring is in place. Tests that
# require it skip cleanly until #107 merges; the Tier-1 path test still runs.
_MCP_SOURCE = (PROJECT_ROOT / "src" / "mcp_server.py").read_text(encoding="utf-8")
PR107_LANDED = "Tier-2 fallback record from" in _MCP_SOURCE
needs_pr107 = pytest.mark.skipif(
    not PR107_LANDED,
    reason="src/mcp_server.py lacks PR #107 Tier-2 fallback wiring (not yet merged)",
)


@pytest_asyncio.fixture(scope="module")
async def mcp():
    """Initialized MCP server — full async init done once per module."""
    instance = PoE2BuildOptimizerMCP()
    await instance.initialize()
    return instance


async def _call_inspect(mcp_instance, name):
    """Helper: call inspect_support_gem with the given name."""
    result = await mcp_instance._handle_inspect_support_gem({"support_name": name})
    return result[0].text


# ---------------------------------------------------------------------------
# Tier 1 — gem in the .datc64 support_gems table
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tier1_known_support_returns_existing_record(mcp):
    """Rage is in the .datc64 support_gems extract. Tier-1 path takes over;
    PR #107's fallback shouldn't fire. Response should NOT carry the
    Tier-2 source note."""
    text = await _call_inspect(mcp, "Rage")

    # Rage exists — verify we got SOMETHING back, not the not-found message
    assert "not found" not in text.lower()
    # Tier-1 doesn't render the Tier-2 fallback Data Source line
    assert "Tier-2 fallback" not in text


# ---------------------------------------------------------------------------
# Tier 2 — Fire Attunement (only exists in skill_gems, gem_type='Support')
#
# NOTE (2026-06-11): the original probe gem, Wildfire, graduated into the
# 0.5 canonical support_gems extraction (data-v0.5.0-r10) and now resolves
# via Tier 1. The fallback wiring is still load-bearing — ~347 supports
# exist only in skill_gems — so these tests probe with Fire Attunement,
# one of those Tier-2-only gems.
# ---------------------------------------------------------------------------

@needs_pr107
@pytest.mark.asyncio
async def test_tier2_resolves_via_fallback(mcp):
    """A skill_gems-only support resolves through the fallback. Lock the
    Data Source line so any future change that breaks the wiring is
    caught here."""
    text = await _call_inspect(mcp, "Fire Attunement")

    assert "Fire Attunement" in text
    assert "not found" not in text.lower()

    # Tier-2 source line present — the load-bearing provenance signal
    assert "Tier-2 fallback" in text
    assert "data/game/skill_gems" in text


@needs_pr107
@pytest.mark.asyncio
async def test_tier2_carries_v1_schema_gap_note(mcp):
    """The Tier-2 fallback notes field explicitly tells the caller which
    fields aren't extracted in v1 (spirit_cost, effects, compatibility).
    Without this, an LLM might assume the silence on those fields means
    the gem genuinely has no effects — a worse failure mode than a
    bare not-found."""
    text = await _call_inspect(mcp, "Fire Attunement")

    # The note should mention the gap explicitly
    assert "v1" in text.lower()
    # And should reference at least one of the missing field categories
    assert any(field in text.lower() for field in (
        "spirit_cost", "effects", "compatibility"
    ))


@needs_pr107
@pytest.mark.asyncio
async def test_tier2_surfaces_locked_metadata(mcp):
    """The Tier-2 record's gem metadata (tags, tier, attribute
    requirements) must actually surface in the handler output."""
    text = await _call_inspect(mcp, "Fire Attunement")

    # Tags from the canonical skill_gems record
    assert "support" in text.lower()
    assert "fire" in text.lower()
    assert "attack" in text.lower()
    # Tier and the 100 Str requirement from the same record
    assert "**Tier**: 1" in text
    assert "100 Str" in text or "Str: 100" in text or "Str 100" in text


# ---------------------------------------------------------------------------
# Both miss
# ---------------------------------------------------------------------------

@needs_pr107
@pytest.mark.asyncio
async def test_both_tiers_miss_returns_informative_error(mcp):
    """When neither dataset has the queried support, the caller must get
    an actionable error. Originally that meant naming both searched
    datasets; the fuzzy-suggestions rework superseded it with a
    'Did you mean' list + a pointer at inspect_support_gem — assert that
    informative shape rather than the old dataset-name format."""
    text = await _call_inspect(mcp, "TotallyNonexistentSupport_XYZ123")

    # Clear failure framing
    assert "Not Found" in text
    assert "no exact match" in text.lower()
    # Actionable recovery path: suggestions plus how to use them
    assert "Did you mean" in text
    assert "inspect_support_gem" in text
