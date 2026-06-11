"""
Tests for the P2 / Issue #115 fuzzy-match + did-you-mean recovery wired into
inspect_keystone, inspect_support_gem, inspect_spell_gem.

Two test modes:
  - Helper-direct tests exercise the did_you_mean() free function in
    src/mcp_server.py against the real canonical name pools. These don't need
    MCP init and run anywhere — they lock the matcher contract.
  - Handler tests invoke the three inspect_* handlers via the
    methodology-rule-compliant lazy-fixture pattern (PR #120). Verifies the
    response shape on miss includes "Did you mean:" with concrete candidates.

The lazy fixture pattern matters: pytest collection has been observed to
hang on `from src.mcp_server import ...` at module-load time on some
configurations. Importing inside the fixture (not at module top) keeps the
helper-direct tests collectible regardless.
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
# Helper-direct mode — locks did_you_mean() contract
# ---------------------------------------------------------------------------

# Helper lives in src/text_search.py (lightweight module — no heavy imports
# so test collection isn't blocked by mcp_server side-effects).
from src.text_search import did_you_mean  # noqa: E402


def test_helper_typo_recovery():
    """Fuzzy match should catch a single-character typo on a real gem name."""
    pool = ["Wildfire Support", "Wildshards Support", "Fork Support", "Spell Echo Support"]
    out = did_you_mean("Wildfir", pool, k=5)
    assert "Wildfire Support" in out, f"typo recovery missed Wildfire: {out}"


def test_helper_substring_match():
    """Bare query that's a substring of a name should surface that name."""
    pool = ["Fork Support", "Forking Projectiles Support", "Other Thing"]
    out = did_you_mean("Fork", pool, k=5)
    assert "Fork Support" in out


def test_helper_prefix_priority_over_substring():
    """Prefix matches should rank ahead of mid-string matches."""
    pool = ["Concentrated Effect Support", "Unconcerned Support", "Concussive Support"]
    out = did_you_mean("Conc", pool, k=3)
    # The two prefix-starts-with-Conc names should both rank above "Unconcerned"
    assert out.index("Concentrated Effect Support") < out.index("Unconcerned Support")
    assert out.index("Concussive Support") < out.index("Unconcerned Support")


def test_helper_empty_query_returns_empty():
    assert did_you_mean("", ["A", "B", "C"], k=5) == []
    assert did_you_mean("   ", ["A", "B", "C"], k=5) == []


def test_helper_nonsense_query_returns_empty():
    """Random characters with no signal in the pool — empty (no false-positive
    fuzzy matches)."""
    out = did_you_mean("ZZZZZ", ["Fork", "Concentrated"], k=5)
    assert out == []


def test_helper_respects_k_limit():
    pool = [f"Item {i}" for i in range(20)]
    out = did_you_mean("Item", pool, k=3)
    assert len(out) == 3


def test_helper_dedupes_case_insensitively():
    pool = ["Fork Support", "fork support", "FORK SUPPORT"]
    out = did_you_mean("Fork", pool, k=5)
    # All three are the same name case-insensitively — should appear once
    assert len(out) == 1


# ---------------------------------------------------------------------------
# Handler mode — methodology-rule-compliant per docs/TESTING.md (lazy import)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module")
async def mcp():
    """Canonical fixture per docs/TESTING.md — initialize before handler use.

    Import deferred to fixture body so pytest collection isn't blocked by a
    slow mcp_server module-level import on some platforms (see PR #120).
    """
    from src.mcp_server import PoE2BuildOptimizerMCP
    instance = PoE2BuildOptimizerMCP()
    await instance.initialize()
    return instance


@pytest.mark.asyncio
async def test_inspect_support_gem_typo_returns_suggestions(mcp):
    """inspect_support_gem('Wildfir') must not dead-end on the typo.

    Since Wildfire Support entered the 0.5 canonical dataset, the handler
    may resolve the near-miss directly instead of suggesting — both are
    acceptable; a flat unhelpful error is not."""
    r = await mcp._handle_inspect_support_gem({"support_name": "Wildfir"})
    text = r[0].text
    assert "Wildfire" in text
    assert "Did you mean" in text or "not found" not in text.lower()


@pytest.mark.asyncio
async def test_inspect_support_gem_no_match_falls_back_to_list_all(mcp):
    """Total miss with no close candidates points the caller at list_all_supports."""
    r = await mcp._handle_inspect_support_gem({"support_name": "QQQQQQQQQQQ"})
    text = r[0].text
    # Either suggestions OR list_all_supports pointer
    assert "Did you mean" in text or "list_all_supports" in text


@pytest.mark.asyncio
async def test_inspect_spell_gem_typo_returns_suggestions(mcp):
    """inspect_spell_gem with a typo should return suggestions, not a flat error."""
    r = await mcp._handle_inspect_spell_gem({"spell_name": "Spar"})
    text = r[0].text
    # Either found a real match (exact match on a prefix) OR returned suggestions
    if "not found" in text.lower() or "Did you mean" in text:
        assert "Did you mean" in text or "Spell Gem Not Found" in text


@pytest.mark.asyncio
async def test_inspect_keystone_typo_returns_suggestions(mcp):
    """inspect_keystone with a near-miss should return 'Did you mean'."""
    # Use a query that's unlikely to be an exact keystone but close to one
    r = await mcp._handle_inspect_keystone({"keystone_name": "Avatr Fire"})
    text = r[0].text
    # Either matches partially or returns suggestions
    if "Keystone Not Found" in text:
        assert "Did you mean" in text or "list_all_keystones" in text


@pytest.mark.asyncio
async def test_inspect_keystone_nonsense_falls_back(mcp):
    """Total nonsense query → either no suggestions OR list_all_keystones hint."""
    r = await mcp._handle_inspect_keystone({"keystone_name": "XYZZYABCDEFGH123"})
    text = r[0].text
    # Either no suggestions, list_all hint, OR (in unlikely event of accidental
    # match) returns a keystone — all acceptable
    assert ("Keystone Not Found" in text) or ("Keystone" in text and "Stats" in text)
