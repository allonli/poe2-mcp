"""
Tests for the v2 enrichment in inspect_spell_gem.

Follow-up to PR #125 (v2 extractor) and PR #127 (DPS handler v2 coverage).
Verifies that inspect_spell_gem surfaces the rich v2 data — constantStats,
per-level damage scaling stats, qualityStats — when skill_gems_v2.json
carries a record for the requested spell.

Two layers:
  - get_v2_skill_record() helper tests (light, no MCP init needed).
  - inspect_spell_gem handler integration tests via the
    methodology-rule-compliant lazy fixture (per docs/TESTING.md,
    PR #120 lazy-import pattern).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calculator.v2_spell_db import get_v2_skill_record  # noqa: E402

V2_FILE = PROJECT_ROOT / "data" / "game" / "skill_gems" / "skill_gems_v2.json"
needs_v2 = pytest.mark.skipif(
    not V2_FILE.exists(),
    reason="data/game/skill_gems/skill_gems_v2.json absent (PR #125 not yet on this checkout)",
)


# ---------------------------------------------------------------------------
# get_v2_skill_record() — helper layer
# ---------------------------------------------------------------------------

@needs_v2
def test_get_v2_skill_record_ice_nova_by_name():
    r = get_v2_skill_record("Ice Nova")
    assert r is not None
    assert r["name"] == "Ice Nova"
    assert r["_v2_skill_id"] == "IceNovaPlayer"


@needs_v2
def test_get_v2_skill_record_includes_statsets():
    """Headline of the enrichment — v2 carries constantStats and per-level
    damage that v1 does not."""
    r = get_v2_skill_record("Ice Nova")
    assert r is not None
    statsets = r.get("statSets")
    assert isinstance(statsets, list) and statsets
    ss0 = statsets[0]
    assert ss0.get("constantStats"), "Ice Nova statSet[0] must have constantStats"
    assert ss0.get("stats"), "Ice Nova statSet[0] must have stats list"
    assert ss0.get("levels"), "Ice Nova statSet[0] must have per-level damage"


@needs_v2
def test_get_v2_skill_record_includes_quality_stats():
    """Ice Nova has 1 qualityStat in PoB data — verify it surfaces."""
    r = get_v2_skill_record("Ice Nova")
    assert r is not None
    quality = r.get("qualityStats")
    assert isinstance(quality, list) and quality
    # Each entry is [stat_id, per_quality_value]
    entry = quality[0]
    assert isinstance(entry, list) and len(entry) >= 2
    assert isinstance(entry[0], str)


@needs_v2
def test_get_v2_skill_record_by_skill_id():
    r = get_v2_skill_record("IceNovaPlayer")
    assert r is not None
    assert r["_v2_skill_id"] == "IceNovaPlayer"


@needs_v2
def test_get_v2_skill_record_unknown_returns_none():
    assert get_v2_skill_record("DefinitelyNotARealSpell") is None
    assert get_v2_skill_record("") is None


def test_get_v2_skill_record_handles_missing_file(tmp_path, monkeypatch):
    """When v2 file isn't present, returns None gracefully."""
    import src.calculator.v2_spell_db as mod
    fake = tmp_path / "nope.json"
    monkeypatch.setattr(mod, "_skill_gems_v2_path", lambda: fake)
    monkeypatch.setattr(mod, "_CACHE", None)
    assert get_v2_skill_record("Ice Nova") is None


# ---------------------------------------------------------------------------
# inspect_spell_gem handler — v2 enrichment surfaces in response
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module")
async def mcp():
    """Canonical lazy-import fixture per docs/TESTING.md."""
    from src.mcp_server import PoE2BuildOptimizerMCP
    instance = PoE2BuildOptimizerMCP()
    await instance.initialize()
    return instance


@needs_v2
@pytest.mark.asyncio
async def test_inspect_spell_gem_response_includes_v2_enrichment(mcp):
    """Ice Nova response should surface v2 enrichment: built-in modifiers
    AND per-level scaling stats."""
    r = await mcp._handle_inspect_spell_gem({"spell_name": "Ice Nova"})
    text = r[0].text
    assert "Ice Nova" in text
    # v2 enrichment markers
    assert "Built-in Modifiers" in text, (
        "Ice Nova response should include built-in modifiers from v2 constantStats"
    )
    assert "Per-Level Scaling Stats" in text, (
        "Ice Nova response should include per-level scaling stats from v2 levels[]"
    )


@needs_v2
@pytest.mark.asyncio
async def test_inspect_spell_gem_v2_source_in_data_note(mcp):
    """When v2 enrichment fires, the data-source note should reflect it."""
    r = await mcp._handle_inspect_spell_gem({"spell_name": "Ice Nova"})
    text = r[0].text
    assert "skill_gems_v2.json" in text


@needs_v2
@pytest.mark.asyncio
async def test_inspect_spell_gem_per_level_damage_sampled(mcp):
    """The per-level scaling display should sample L1/L10/L20."""
    r = await mcp._handle_inspect_spell_gem({"spell_name": "Ice Nova"})
    text = r[0].text
    # Look for level-sample tags. At least one of L1/L10/L20 should appear.
    assert ("L1=" in text or "L10=" in text or "L20=" in text), (
        "v2 per-level damage sampling should produce L1=/L10=/L20= markers"
    )


@needs_v2
@pytest.mark.asyncio
async def test_inspect_spell_gem_quality_stats_surfaced(mcp):
    """Ice Nova's qualityStats should appear in the response."""
    r = await mcp._handle_inspect_spell_gem({"spell_name": "Ice Nova"})
    text = r[0].text
    assert "Quality Stats" in text


@needs_v2
@pytest.mark.asyncio
async def test_inspect_spell_gem_unknown_spell_still_returns_useful(mcp):
    """A spell not in v2 still returns the v1/legacy response (or a clear
    error) — v2 enrichment is additive, not a hard dependency."""
    r = await mcp._handle_inspect_spell_gem({"spell_name": "NotARealSpellXYZ"})
    text = r[0].text
    # Either resolves via some path or surfaces a 'not found' / suggestion path.
    # We're just verifying it doesn't crash on the v2 enrichment branch.
    assert isinstance(text, str) and len(text) > 0
