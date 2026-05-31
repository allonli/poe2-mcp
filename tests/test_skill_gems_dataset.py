"""
Tests for the data/game/skill_gems/ dataset shipped by PR #91.

Shape + real-data consistency checks against the actual JSON. Mirrors the
pattern of tests/test_game_data.py (datasets-as-fixtures) and catches drift
between data, metadata, and version.json on future re-extractions.

The MCP-handler-side wiring tests (inspect_spell_gem / list_all_spells) live
separately and belong in their own MCP-integration suite.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.game_data import (
    GAME_DATA_DIR,
    SKILL_GEMS_DIR,
    get_version,
)

SKILL_GEMS_JSON = SKILL_GEMS_DIR / "skill_gems.json"
SKILL_GEMS_META = SKILL_GEMS_DIR / "metadata.json"


@pytest.fixture(scope="module")
def dataset():
    """Loaded skill_gems.json payload."""
    assert SKILL_GEMS_JSON.exists(), (
        f"{SKILL_GEMS_JSON} missing — has data/game/skill_gems/ been re-extracted?"
    )
    return json.loads(SKILL_GEMS_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def metadata():
    """Loaded metadata.json payload."""
    assert SKILL_GEMS_META.exists(), f"{SKILL_GEMS_META} missing"
    return json.loads(SKILL_GEMS_META.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gems(dataset):
    """The records list itself."""
    return dataset["skill_gems"]


# ---------------------------------------------------------------------------
# File shape
# ---------------------------------------------------------------------------

def test_dataset_dir_exists():
    assert SKILL_GEMS_DIR.is_dir()


def test_dataset_top_level_shape(dataset):
    assert isinstance(dataset, dict)
    assert dataset.get("schema_version") == 1
    assert isinstance(dataset.get("skill_gems"), list)


def test_metadata_top_level_shape(metadata):
    assert isinstance(metadata, dict)
    for field in (
        "dataset", "filename", "patch_version", "extracted_at",
        "source_repo", "source_commit", "extractor",
        "record_count", "sha256",
    ):
        assert field in metadata, f"metadata.json missing required field '{field}'"
    assert metadata["dataset"] == "skill_gems"
    assert metadata["filename"] == "skill_gems.json"


def test_metadata_record_count_matches_data(gems, metadata):
    """The headline drift check — record_count in metadata.json must match the
    actual list length. If a re-extraction forgets to refresh metadata, this
    fails loudly."""
    assert metadata["record_count"] == len(gems)


def test_version_json_record_count_matches_data(gems):
    """version.json's per-dataset record_count must match the actual data."""
    v = get_version()
    assert v is not None
    assert "skill_gems" in v["datasets"], (
        "skill_gems must be registered in datasets, not datasets_pending_0_5_reextract"
    )
    assert v["datasets"]["skill_gems"]["record_count"] == len(gems)


def test_version_json_skill_gems_no_longer_pending():
    """PR #91 closed the last pending dataset. datasets_pending_0_5_reextract
    should be empty (or absent of skill_gems)."""
    v = get_version()
    pending = v.get("datasets_pending_0_5_reextract") or {}
    assert "skill_gems" not in pending


# ---------------------------------------------------------------------------
# Per-record required fields
# ---------------------------------------------------------------------------

REQUIRED_GEM_FIELDS = {
    "gem_id", "name", "gem_type", "tier", "natural_max_level",
    "requirements", "tags", "additional_stat_sets",
}


def test_every_gem_has_required_fields(gems):
    for gem in gems:
        missing = REQUIRED_GEM_FIELDS - set(gem.keys())
        assert not missing, f"gem {gem.get('gem_id')!r} missing fields: {missing}"


def test_every_gem_id_is_unique(gems):
    """No duplicates — would silently shadow lookups."""
    ids = [g["gem_id"] for g in gems]
    assert len(ids) == len(set(ids)), (
        f"duplicate gem_ids found: {len(ids) - len(set(ids))} duplicates"
    )


def test_every_gem_id_has_metadata_prefix(gems):
    """gem_id format is 'Metadata/Items/Gems/<SkillGemX>' — locks the prefix
    convention from PoB2's Gems.lua."""
    for gem in gems:
        assert gem["gem_id"].startswith("Metadata/Items/Gems/"), (
            f"unexpected gem_id format: {gem['gem_id']!r}"
        )


def test_requirements_shape(gems):
    """requirements is always {str, dex, int} with int values."""
    for gem in gems:
        r = gem["requirements"]
        assert isinstance(r, dict)
        assert set(r.keys()) == {"str", "dex", "int"}, (
            f"gem {gem['gem_id']!r} requirements keys: {set(r.keys())}"
        )
        for k, v in r.items():
            assert isinstance(v, int) and v >= 0, (
                f"gem {gem['gem_id']!r} requirements[{k}] = {v!r}"
            )


def test_tags_is_string_list(gems):
    for gem in gems:
        assert isinstance(gem["tags"], list)
        for t in gem["tags"]:
            assert isinstance(t, str) and t, f"non-string/empty tag in {gem['gem_id']}"


# ---------------------------------------------------------------------------
# Join health — granted_effect coverage
# ---------------------------------------------------------------------------

def test_join_rate_high(gems, metadata):
    """metadata claims a join rate; verify against actual data."""
    matched = sum(1 for g in gems if g.get("granted_effect") is not None)
    assert matched == metadata["matched_effect_count"], (
        f"actual matched count {matched} != metadata claim {metadata['matched_effect_count']}"
    )


def test_join_rate_is_total(gems):
    """PR #91 reported 100% join. Lock that as a regression — if a future
    extraction misses joins, surface it loudly."""
    matched = sum(1 for g in gems if g.get("granted_effect") is not None)
    assert matched == len(gems), (
        f"join rate dropped: {matched}/{len(gems)} ({100*matched/len(gems):.1f}%)"
    )


def test_granted_effect_shape_when_present(gems):
    """When granted_effect is non-null, it has the documented schema fields."""
    for gem in gems:
        ge = gem.get("granted_effect")
        if ge is None:
            continue
        assert "effect_id" in ge
        assert "skill_types" in ge and isinstance(ge["skill_types"], list)
        # levels is a dict keyed by stringified level numbers
        assert isinstance(ge.get("levels", {}), dict)
        # stat_sets is a list
        assert isinstance(ge.get("stat_sets", []), list)


# ---------------------------------------------------------------------------
# Gem type distribution — sanity vs PR #91 description
# ---------------------------------------------------------------------------

def test_gem_type_distribution_contains_core_categories(gems):
    """PR #91 reported these categories: Support, Attack, Spell, Buff,
    Minion, Warcry, Mark, Banner, Shapeshift, Totem. Verify all appear."""
    types = {g.get("gem_type") for g in gems}
    expected_min = {"Support", "Spell", "Attack", "Buff", "Minion"}
    assert expected_min.issubset(types), (
        f"missing core gem_types: {expected_min - types}"
    )


def test_spell_count_matches_handler_expectation(gems):
    """list_all_spells (PR #94) uses gem_type=='Spell' as its filter and
    reports 83 active spells. Lock that count."""
    spells = [g for g in gems if g.get("gem_type") == "Spell"]
    assert len(spells) == 83, (
        f"gem_type=='Spell' count is {len(spells)}, not 83 — PR #94 handler "
        "expectation broken"
    )


# ---------------------------------------------------------------------------
# Spot-check: Ice Nova (the canonical docstring/audit example)
# ---------------------------------------------------------------------------

def test_ice_nova_present_and_canonical(gems):
    """Ice Nova is the canonical example used in the audit (#85), the
    extractor's docstring, and the MCP handler smoke test. Spot-check it."""
    ice_nova = next((g for g in gems if g.get("name") == "Ice Nova"), None)
    assert ice_nova is not None, "Ice Nova missing — was Gems.lua truncated?"

    assert ice_nova["gem_id"] == "Metadata/Items/Gems/SkillGemIceNova"
    assert ice_nova["gem_type"] == "Spell"
    assert ice_nova["tier"] == 1
    assert ice_nova["natural_max_level"] == 20
    assert ice_nova["requirements"] == {"str": 0, "dex": 0, "int": 100}

    # Tags must include the cold/spell signature
    for required_tag in ("spell", "cold", "area"):
        assert required_tag in ice_nova["tags"], (
            f"Ice Nova missing required tag {required_tag!r}: tags={ice_nova['tags']}"
        )

    # Has additional_stat_sets per audit (#85)
    assert "IceNovaPlayerOnFrostbolt" in ice_nova["additional_stat_sets"]
    assert "IceNovaColdInfusedPlayer" in ice_nova["additional_stat_sets"]

    # Has a granted_effect with cast_time
    ge = ice_nova["granted_effect"]
    assert ge is not None
    assert ge["effect_id"] == "IceNovaPlayer"
    assert ge["cast_time"] is not None
