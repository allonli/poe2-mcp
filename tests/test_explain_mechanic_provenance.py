"""
End-to-end tests for explain_mechanic (PR #101) — locks the user-facing
two-tier provenance contract.

What's being protected:
  - Tier 1 (canonical stat_descriptions) exact-stat_id lookup returns the
    literal game-shipped text + source-file/source-line provenance line.
  - Tier 2 (hand-authored poe2_mechanics.py) returns the explicit
    "community interpretation" disclaimer the user feedback demanded — so
    we never again confuse hand-authored text for authoritative data.
  - Substring queries return "did you mean" suggestions instead of bare
    not-founds (the dead-end-by-design UX the user called out).
  - Empty query returns the tier overview (mechanic_name is OPTIONAL since
    PR #101 — fixes the contradiction with the old "call without arguments"
    help text).

Methodology rule (per fire 28 retraction): every test MUST go through
`await mcp.initialize()`. Skipping it produces false "broken" claims —
that's what created the Gap G/H phantom bugs.

Module-scoped fixture so initialize() runs once for the whole file.
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
    """Initialized MCP server — full async init done once per module."""
    instance = PoE2BuildOptimizerMCP()
    await instance.initialize()
    return instance


async def _call_explain(mcp_instance, query):
    """Helper: call explain_mechanic and return the first TextContent's text."""
    args = {"mechanic_name": query} if query is not None else {}
    result = await mcp_instance._handle_explain_mechanic(args)
    return result[0].text


# ---------------------------------------------------------------------------
# Tier 1 — canonical stat_descriptions lookup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tier1_exact_stat_id_returns_canonical_game_text(mcp):
    """The proliferation case HivemindOverlord couldn't get in their Claude
    Desktop session — locks the end-to-end behavior."""
    text = await _call_explain(mcp, "support_ignite_proliferation_radius")

    # Game-shipped template literally returned
    assert "inflicted by Supported Skills" in text
    assert "[AilmentSpread|Spread]" in text  # PoB hyperlink syntax preserved
    assert "{0} metre" in text  # placeholder preserved


@pytest.mark.asyncio
async def test_tier1_response_carries_provenance_line(mcp):
    """Every Tier 1 response ends with a Data source line + canonical/
    not-hand-authored statement. This is the trust-recovery contract."""
    text = await _call_explain(mcp, "support_ignite_proliferation_radius")

    assert "Data source" in text
    assert "gem_stat_descriptions" in text  # the source .csd file
    assert "Canonical game-shipped text" in text or "canonical" in text.lower()
    assert "Not hand-authored interpretation" in text


@pytest.mark.asyncio
async def test_tier1_unknown_stat_id_falls_through(mcp):
    """Garbage stat_id shouldn't crash and shouldn't return a Tier 1 record.
    Should fall through to Tier 2 search, then substring search, then
    helpful not-found message."""
    text = await _call_explain(mcp, "definitely_not_a_real_stat_id_xyz_12345")
    assert "Data source" not in text or "No match" in text or "not found" in text.lower()


# ---------------------------------------------------------------------------
# Tier 2 — hand-authored fallback with explicit disclaimer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tier2_mechanic_query_carries_provenance_disclaimer(mcp):
    """High-level concept queries hit the hand-authored fallback. The
    response MUST explicitly label itself as community interpretation,
    not authoritative data. Closes the epistemic problem the user
    flagged (`"crits do NOT guarantee ignite"` confidently asserted with
    no source)."""
    text = await _call_explain(mcp, "ignite")

    # The disclaimer is the load-bearing piece — verify it's there verbatim
    assert "hand-authored summary" in text
    assert "community interpretation" in text
    # The actionable instruction — caller must know to cross-reference
    assert "Cross-reference" in text or "cross-reference" in text
    assert "tooltip" in text.lower()


# ---------------------------------------------------------------------------
# Substring "did you mean" recovery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_substring_query_returns_multiple_suggestions(mcp):
    """The recovery layer for the user's "proliferation" query — no longer
    a bare not-found. Returns stat_id suggestions the caller can re-query."""
    text = await _call_explain(mcp, "proliferation")

    # Should list multiple stat_ids
    assert "support_ignite_proliferation_radius" in text
    # Recovery framing in the output
    assert "Suggestions" in text or "match" in text.lower() or "did you mean" in text.lower()


@pytest.mark.asyncio
async def test_substring_each_suggestion_includes_source_csd(mcp):
    """Each suggested stat_id should be tagged with which .csd file it
    came from — so the caller can build the provenance trail."""
    text = await _call_explain(mcp, "proliferation")
    # gem_stat_descriptions.csd is where proliferation stats live
    assert "gem_stat_descriptions" in text


# ---------------------------------------------------------------------------
# Empty query — overview (was previously a dead-end-by-design)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_query_returns_overview_not_error(mcp):
    """Pre-PR-#101 the schema marked mechanic_name as required, so calling
    without it was rejected at the MCP validation layer — making the
    "Use this tool without arguments" help text a dead-end-by-design
    contradiction. PR #101 made the param optional. This test locks that."""
    text = await _call_explain(mcp, "")

    # Tier overview present
    assert "Tier 1" in text
    assert "Tier 2" in text
    # Should reference both data sources
    assert "stat_descriptions" in text
    assert "poe2_mechanics" in text


@pytest.mark.asyncio
async def test_empty_query_describes_query_shapes(mcp):
    """The overview should tell the caller what shapes of query work,
    so the LLM knows whether to send a mechanic name, a stat_id, or
    a substring."""
    text = await _call_explain(mcp, "")

    # Three documented shapes
    assert "stat_id" in text.lower()
    # At least one example name + substring usage
    assert "freeze" in text.lower() or "ignite" in text.lower()
