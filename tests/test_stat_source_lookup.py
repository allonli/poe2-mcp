"""
Tests for the reverse stat-source lookup + explain_mechanic cluster mode
(field-feedback wishes, 2026-06-11) and the issue #155 fuzzy-matcher fixes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.stat_source_index import StatSourceIndex, get_stat_source_index


# ---------------------------------------------------------------------------
# StatSourceIndex unit tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def index():
    idx = StatSourceIndex()
    idx._ensure_built()
    return idx


def test_index_builds_from_local_data(index):
    """Skill and mod indices populate from tracked game data."""
    assert len(index._skill_index) > 100
    assert len(index._mod_index) > 100
    assert len(index._passive_nodes) > 1000


def test_wither_skills_found(index):
    """The headline feedback case: wither sources are enumerable."""
    sources = index.find_sources("wither")
    assert sources["skills"], "wither stat_ids should map to skills"
    all_skills = {s for skills in sources["skills"].values() for s in skills}
    assert "Withering Touch" in all_skills


def test_passive_text_match(index):
    """Passive nodes match on stat TEXT, not just ids."""
    sources = index.find_sources("chance to Shock")
    assert sources["passive_nodes"]
    assert any(
        "shock" in s.lower()
        for n in sources["passive_nodes"]
        for s in n["stats"]
    )


def test_mod_stat_id_match(index):
    sources = index.find_sources("withered_magnitude")
    assert sources["mods"]
    mods = next(iter(sources["mods"].values()))
    assert any(m.get("display_name") for m in mods)


def test_exact_stat_id_skill_lookup(index):
    skills = index.skills_granting_stat("spell_minimum_base_fire_damage")
    assert "Fireball" in skills


def test_empty_query_returns_empty(index):
    sources = index.find_sources("")
    assert sources["skills"] == {}
    assert sources["passive_nodes"] == []


def test_limit_respected(index):
    sources = index.find_sources("damage", limit_per_source=3)
    assert len(sources["skills"]) <= 3
    assert len(sources["passive_nodes"]) <= 3
    assert len(sources["mods"]) <= 3


def test_missing_data_dir_degrades_gracefully(tmp_path):
    idx = StatSourceIndex(data_dir=tmp_path)
    sources = idx.find_sources("wither")
    assert sources["skills"] == {}
    assert sources["ascendancy_data_available"] is False


def test_singleton_accessor():
    assert get_stat_source_index() is get_stat_source_index()


# ---------------------------------------------------------------------------
# Issue #155 — knowledge-base entries + matcher ranking
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def kb():
    from src.knowledge.poe2_mechanics import PoE2MechanicsKnowledgeBase
    return PoE2MechanicsKnowledgeBase()


def test_chaos_damage_entry_exists(kb):
    m = kb.get_mechanic("chaos damage")
    assert m is not None
    assert m.name == "Chaos Damage"


def test_wither_entry_exists(kb):
    m = kb.get_mechanic("wither")
    assert m is not None
    assert m.name == "Wither"


def test_search_ranks_name_matches_first(kb):
    """'chaos damage' must surface Chaos Damage, not Poison (#155)."""
    results = kb.search_mechanics("chaos damage")
    assert results
    assert results[0].name == "Chaos Damage"


def test_search_body_matches_still_found(kb):
    """Description-text matches remain reachable, just ranked lower."""
    results = kb.search_mechanics("chaos damage")
    names = [m.name for m in results]
    assert "Poison" in names
    assert names.index("Chaos Damage") < names.index("Poison")


# ---------------------------------------------------------------------------
# Handler integration
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module")
async def mcp():
    from src.mcp_server import PoE2BuildOptimizerMCP
    instance = PoE2BuildOptimizerMCP()
    await instance.initialize()
    return instance


@pytest.mark.asyncio
async def test_find_stat_sources_handler(mcp):
    r = await mcp._handle_find_stat_sources({"query": "wither"})
    text = r[0].text
    assert "Withering Touch" in text
    assert "## Skills" in text
    assert "## Passive tree nodes" in text


@pytest.mark.asyncio
async def test_find_stat_sources_requires_query(mcp):
    r = await mcp._handle_find_stat_sources({})
    assert "Error" in r[0].text


@pytest.mark.asyncio
async def test_find_stat_sources_no_match(mcp):
    r = await mcp._handle_find_stat_sources({"query": "zzz_no_such_stat_xyz"})
    text = r[0].text
    assert "No skills" in text


@pytest.mark.asyncio
async def test_cluster_dump_mode(mcp):
    """The one-call cluster dump the feedback asked for."""
    r = await mcp._handle_explain_mechanic({
        "mechanic_name": "infusion", "cluster": True,
    })
    text = r[0].text
    assert "Cluster dump" in text
    assert "Canonical stat_ids" in text
    assert "Granted by skills:" in text


@pytest.mark.asyncio
async def test_explain_chaos_damage_returns_chaos_entry(mcp):
    """#155 acceptance: 'chaos damage' returns the chaos entry, not Poison."""
    r = await mcp._handle_explain_mechanic({"mechanic_name": "chaos damage"})
    text = r[0].text
    assert "CHAOS DAMAGE" in text.upper()
    assert "stack limit" not in text.lower()[:500]  # not the Poison entry


@pytest.mark.asyncio
async def test_explain_wither_returns_summary(mcp):
    """#155 acceptance: 'wither' returns a top-level summary."""
    r = await mcp._handle_explain_mechanic({"mechanic_name": "wither"})
    text = r[0].text
    assert "WITHER" in text.upper()
    assert "chaos damage" in text.lower()
