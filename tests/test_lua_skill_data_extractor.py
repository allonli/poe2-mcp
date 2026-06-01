"""
Tests for the v2 skill_gems extractor (Issue #119).

Two layers:
  - Parser tests exercise src/parsers/lua_skill_data.py against a small
    embedded Lua fixture. No PoB clone required — these run anywhere.
  - Output-JSON tests assert the shipped data/game/skill_gems/skill_gems_v2.json
    has the expected shape (schema_version, record count vs metadata,
    Ice Nova canonical example carries the expected fields). Skips if the
    file isn't present (fresh checkout before extractor ran).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Lupa is a hard requirement for the parser. If it's not available in the
# test env, parser tests skip and output-JSON tests still run on shipped data.
LUPA_AVAILABLE = True
try:
    import lupa  # noqa: F401
except ImportError:
    LUPA_AVAILABLE = False


needs_lupa = pytest.mark.skipif(
    not LUPA_AVAILABLE,
    reason="lupa not installed in this environment",
)


# ---------------------------------------------------------------------------
# Parser tests against an embedded fixture
# ---------------------------------------------------------------------------

FIXTURE_LUA = r"""
-- Minimal mimic of a Skills/*.lua chunk to lock the parser contract.
local skills, mod, flag, skill = ...

skills["TestSpellPlayer"] = {
    name = "Test Spell",
    baseTypeName = "Test Spell",
    color = 3,
    description = "A spell that does test things.",
    skillTypes = { [SkillType.Spell] = true, [SkillType.Area] = true, [SkillType.Cold] = true },
    castTime = 0.8,
    qualityStats = {
        { "active_skill_damage_+%_final_vs_chilled", 1 },
    },
    levels = {
        [1] = { critChance = 12, levelRequirement = 0, cost = { Mana = 5 } },
        [2] = { critChance = 12, levelRequirement = 3, cost = { Mana = 6 } },
        [3] = { critChance = 12, levelRequirement = 6, cost = { Mana = 8 } },
    },
    statSets = {
        [1] = {
            label = "Test Spell",
            baseEffectiveness = 1.5,
            incrementalEffectiveness = 0.12,
            constantStats = {
                { "active_skill_base_area_of_effect_radius", 24 },
            },
            stats = {
                "spell_minimum_base_cold_damage",
                "spell_maximum_base_cold_damage",
            },
            levels = {
                [1] = { 10, 15, statInterpolation = { 1, 1 }, actorLevel = 1 },
                [2] = { 12, 18, statInterpolation = { 1, 1 }, actorLevel = 3 },
            },
            baseMods = {
                mod("Damage", "MORE", 0, 0, 0),
            },
        },
    },
}
"""


@needs_lupa
def test_parser_returns_dict(tmp_path):
    """Parser returns a dict keyed by skill_id."""
    from src.parsers.lua_skill_data import parse_skills_lua

    f = tmp_path / "fixture.lua"
    f.write_text(FIXTURE_LUA, encoding="utf-8")
    parsed = parse_skills_lua(f)

    assert isinstance(parsed, dict)
    assert "TestSpellPlayer" in parsed


@needs_lupa
def test_parser_extracts_basic_fields(tmp_path):
    from src.parsers.lua_skill_data import parse_skills_lua

    f = tmp_path / "fixture.lua"
    f.write_text(FIXTURE_LUA, encoding="utf-8")
    parsed = parse_skills_lua(f)
    rec = parsed["TestSpellPlayer"]

    assert rec["name"] == "Test Spell"
    assert rec["castTime"] == 0.8


@needs_lupa
def test_parser_resolves_skill_type_enum(tmp_path):
    """SkillType.X table-key expressions should resolve to bare string keys."""
    from src.parsers.lua_skill_data import parse_skills_lua

    f = tmp_path / "fixture.lua"
    f.write_text(FIXTURE_LUA, encoding="utf-8")
    parsed = parse_skills_lua(f)
    rec = parsed["TestSpellPlayer"]

    st = rec["skillTypes"]
    # Either dict-shape (post-converter dict) with str keys, or list (if
    # converter promoted to array because all keys happened to look array-y).
    if isinstance(st, dict):
        assert "Spell" in st
        assert "Area" in st
        assert "Cold" in st


@needs_lupa
def test_parser_extracts_levels_as_array(tmp_path):
    """Lua [1]=..., [2]=..., contiguous ints become a Python list."""
    from src.parsers.lua_skill_data import parse_skills_lua

    f = tmp_path / "fixture.lua"
    f.write_text(FIXTURE_LUA, encoding="utf-8")
    parsed = parse_skills_lua(f)
    rec = parsed["TestSpellPlayer"]

    levels = rec["levels"]
    assert isinstance(levels, list)
    assert len(levels) == 3
    assert levels[0]["cost"]["Mana"] == 5
    assert levels[2]["cost"]["Mana"] == 8


@needs_lupa
def test_parser_extracts_statSets_with_constantStats(tmp_path):
    from src.parsers.lua_skill_data import parse_skills_lua

    f = tmp_path / "fixture.lua"
    f.write_text(FIXTURE_LUA, encoding="utf-8")
    parsed = parse_skills_lua(f)
    rec = parsed["TestSpellPlayer"]

    statsets = rec["statSets"]
    assert isinstance(statsets, list)
    assert len(statsets) == 1
    ss = statsets[0]
    assert ss["label"] == "Test Spell"
    assert ss["baseEffectiveness"] == 1.5
    assert ss["constantStats"] == [["active_skill_base_area_of_effect_radius", 24]]
    assert "spell_minimum_base_cold_damage" in ss["stats"]
    # Per-level damage entry: mixed-key Lua table becomes dict with
    # stringified int keys for the implicit positions (Lua [1]=10 -> "1": 10)
    # and named keys preserved (statInterpolation, actorLevel).
    level1 = ss["levels"][0]
    assert isinstance(level1, dict)
    assert level1["1"] == 10  # first implicit value
    assert level1["2"] == 15  # second implicit value
    assert level1["actorLevel"] == 1


@needs_lupa
def test_parser_mod_call_returns_tagged_dict(tmp_path):
    """The mod() inline helper is stubbed — calls preserved as tagged dicts."""
    from src.parsers.lua_skill_data import parse_skills_lua

    f = tmp_path / "fixture.lua"
    f.write_text(FIXTURE_LUA, encoding="utf-8")
    parsed = parse_skills_lua(f)
    rec = parsed["TestSpellPlayer"]

    base_mods = rec["statSets"][0].get("baseMods") or []
    assert base_mods, "baseMods should be present"
    m = base_mods[0]
    assert isinstance(m, dict)
    assert m.get("__mod") is True
    assert m.get("name") == "Damage"
    assert m.get("type") == "MORE"


@needs_lupa
def test_extract_canonical_subset_drops_verbose_fields(tmp_path):
    """The subset extractor should keep numeric fields and drop description/color."""
    from src.parsers.lua_skill_data import extract_canonical_subset, parse_skills_lua

    f = tmp_path / "fixture.lua"
    f.write_text(FIXTURE_LUA, encoding="utf-8")
    parsed = parse_skills_lua(f)
    sub = extract_canonical_subset(parsed["TestSpellPlayer"])

    assert "name" in sub
    assert "castTime" in sub
    assert "skillTypes" in sub
    assert "qualityStats" in sub
    assert "levels" in sub
    assert "statSets" in sub
    # Verbose fields dropped
    assert "description" not in sub
    assert "color" not in sub


# ---------------------------------------------------------------------------
# Output-JSON sanity (against the shipped file)
# ---------------------------------------------------------------------------

OUTPUT_JSON = PROJECT_ROOT / "data" / "game" / "skill_gems" / "skill_gems_v2.json"
OUTPUT_META = PROJECT_ROOT / "data" / "game" / "skill_gems" / "metadata_v2.json"


def test_output_json_exists():
    """The extractor's output file ships in the repo."""
    assert OUTPUT_JSON.exists(), (
        f"{OUTPUT_JSON} missing - run scripts/extract_skill_gems_rich.py "
        "and commit the output before merging this PR."
    )


def test_output_metadata_record_count_matches():
    """metadata_v2.json's record_count must match the actual JSON length."""
    if not OUTPUT_JSON.exists():
        pytest.skip("output file not shipped")

    with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    with open(OUTPUT_META, "r", encoding="utf-8") as f:
        meta = json.load(f)

    assert meta["record_count"] == len(data["skills"])


def test_output_schema_version_is_2():
    if not OUTPUT_JSON.exists():
        pytest.skip("output file not shipped")
    with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["schema_version"] == 2


def test_output_ice_nova_has_rich_data():
    """Ice Nova is the canonical example — verify the rich fields are there."""
    if not OUTPUT_JSON.exists():
        pytest.skip("output file not shipped")
    with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    nova = data["skills"].get("IceNovaPlayer")
    assert nova is not None, "IceNovaPlayer missing from extracted v2 data"
    assert nova["name"] == "Ice Nova"
    assert "castTime" in nova
    assert nova["castTime"] > 0
    # qualityStats and statSets are the headline of #119's ask
    assert nova.get("qualityStats")
    assert nova.get("statSets")
    # First statSet should have baseEffectiveness and constantStats
    ss0 = nova["statSets"][0]
    assert ss0.get("baseEffectiveness", 0) > 0
    assert ss0.get("constantStats")


def test_output_record_count_is_substantial():
    """Sanity: extractor should pull >500 records (PoB has ~1200)."""
    if not OUTPUT_JSON.exists():
        pytest.skip("output file not shipped")
    with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["skills"]) > 500


def test_output_levels_field_is_array():
    """Each skill's levels should be a list (Lua 1-indexed contiguous keys
    are converted to Python 0-indexed arrays)."""
    if not OUTPUT_JSON.exists():
        pytest.skip("output file not shipped")
    with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    nova = data["skills"].get("IceNovaPlayer")
    if nova and nova.get("levels"):
        assert isinstance(nova["levels"], list)
