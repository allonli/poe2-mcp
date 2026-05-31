"""
Tests for the data/game/stat_descriptions/ dataset (PR #98) and the lookup
helpers in src/data/game_data.py (PR #99).

Combined into one file because the helpers' contract is tightly coupled to
the dataset shape. Mirrors the pattern of tests/test_skill_gems_dataset.py
plus tests/test_game_data_helpers.py.

If either PR #98 or PR #99 is not yet merged when this test file is invoked
against `main`, the helper tests skip rather than fail (the helpers
explicitly graceful-degrade to None / empty list when the dataset is
missing). Once both land, full coverage activates automatically.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.game_data import GAME_DATA_DIR

# Helpers live in PR #99. When this test file is run against `main` before
# #99 merges, skip everything that touches them rather than fail at collect.
try:
    from src.data.game_data import (
        STAT_DESCRIPTIONS_DIR,
        STAT_DESCRIPTIONS_INDEX,
        STAT_DESCRIPTIONS_META,
        find_stat_description,
        load_stat_descriptions_file,
        load_stat_descriptions_index,
        search_stat_descriptions,
    )
    HELPERS_PRESENT = True
except ImportError:
    HELPERS_PRESENT = False
    STAT_DESCRIPTIONS_DIR = GAME_DATA_DIR / "stat_descriptions"
    STAT_DESCRIPTIONS_INDEX = STAT_DESCRIPTIONS_DIR / "index.json"
    STAT_DESCRIPTIONS_META = STAT_DESCRIPTIONS_DIR / "metadata.json"

DATASET_PRESENT = STAT_DESCRIPTIONS_INDEX.exists()

needs_helpers = pytest.mark.skipif(
    not HELPERS_PRESENT,
    reason="src.data.game_data stat_descriptions helpers not present (PR #99 not merged yet)",
)
needs_dataset = pytest.mark.skipif(
    not (HELPERS_PRESENT and DATASET_PRESENT),
    reason="data/game/stat_descriptions/ + helpers required (PR #98 + #99 must both be merged)",
)


# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

def test_stat_descriptions_dir_constant_correct():
    assert STAT_DESCRIPTIONS_DIR == GAME_DATA_DIR / "stat_descriptions"


def test_stat_descriptions_index_path_constant_correct():
    assert STAT_DESCRIPTIONS_INDEX == STAT_DESCRIPTIONS_DIR / "index.json"


def test_stat_descriptions_meta_path_constant_correct():
    assert STAT_DESCRIPTIONS_META == STAT_DESCRIPTIONS_DIR / "metadata.json"


# ---------------------------------------------------------------------------
# Graceful degradation when dataset absent
# ---------------------------------------------------------------------------

@needs_helpers
def test_load_index_returns_none_when_missing(monkeypatch, tmp_path):
    """If the index file isn't present, loader returns None — not raises."""
    monkeypatch.setattr(
        "src.data.game_data.STAT_DESCRIPTIONS_INDEX",
        tmp_path / "definitely_does_not_exist.json",
    )
    # Clear the module cache so the monkeypatched path takes effect
    from src.data import game_data
    game_data._STAT_DESCRIPTIONS_CACHE.clear()
    try:
        assert load_stat_descriptions_index() is None
    finally:
        game_data._STAT_DESCRIPTIONS_CACHE.clear()


@needs_helpers
def test_find_stat_description_returns_none_for_empty_input():
    assert find_stat_description("") is None
    assert find_stat_description("   ") is None


@needs_helpers
def test_search_stat_descriptions_returns_empty_for_empty_input():
    assert search_stat_descriptions("") == []
    assert search_stat_descriptions("   ") == []


# ---------------------------------------------------------------------------
# Dataset shape (when present)
# ---------------------------------------------------------------------------

@needs_dataset
def test_dataset_index_shape():
    idx = load_stat_descriptions_index()
    assert isinstance(idx, dict)
    assert idx.get("schema_version") == 1
    assert isinstance(idx.get("files"), dict)
    assert isinstance(idx.get("totals"), dict)
    totals = idx["totals"]
    for k in ("files", "descriptions", "no_descriptions"):
        assert k in totals
        assert isinstance(totals[k], int)


@needs_dataset
def test_metadata_required_fields():
    meta = json.loads(STAT_DESCRIPTIONS_META.read_text(encoding="utf-8"))
    for field in (
        "dataset", "filename", "patch_version", "extracted_at",
        "source_dir", "source_format", "extractor",
        "file_count", "description_count", "no_description_count",
        "schema_notes", "data_policy",
    ):
        assert field in meta, f"metadata.json missing required field '{field}'"
    assert meta["dataset"] == "stat_descriptions"


@needs_dataset
def test_metadata_total_matches_index_total():
    """Drift check between metadata.json totals and index.json totals."""
    idx = load_stat_descriptions_index()
    meta = json.loads(STAT_DESCRIPTIONS_META.read_text(encoding="utf-8"))
    assert meta["description_count"] == idx["totals"]["descriptions"]
    assert meta["no_description_count"] == idx["totals"]["no_descriptions"]
    assert meta["file_count"] == idx["totals"]["files"]


@needs_dataset
def test_per_file_counts_sum_to_index_total():
    """Sum of individual file description_counts == index totals (no orphans)."""
    idx = load_stat_descriptions_index()
    files = idx.get("files") or {}
    summed_desc = sum(info["description_count"] for info in files.values())
    summed_no = sum(info["no_description_count"] for info in files.values())
    assert summed_desc == idx["totals"]["descriptions"]
    assert summed_no == idx["totals"]["no_descriptions"]


@needs_dataset
def test_each_index_file_exists_on_disk():
    """Every file the index references must actually exist."""
    idx = load_stat_descriptions_index()
    for csd_name, info in (idx.get("files") or {}).items():
        path = STAT_DESCRIPTIONS_DIR / info["json_file"]
        assert path.exists(), f"index references missing file: {info['json_file']}"


@needs_dataset
def test_each_file_loads_and_has_expected_shape():
    """Every per-file payload has schema_version, source_file, descriptions list."""
    idx = load_stat_descriptions_index()
    for csd_name, info in (idx.get("files") or {}).items():
        payload = load_stat_descriptions_file(info["json_file"])
        assert payload is not None, f"failed to load {info['json_file']}"
        assert payload.get("schema_version") == 1
        assert "source_file" in payload
        assert isinstance(payload.get("descriptions"), list)
        # description_count claim matches actual
        assert payload["description_count"] == len(payload["descriptions"])


@needs_dataset
def test_descriptions_have_required_keys():
    """Sample a few records per file — check shape consistency."""
    idx = load_stat_descriptions_index()
    for csd_name, info in (idx.get("files") or {}).items():
        payload = load_stat_descriptions_file(info["json_file"])
        if not payload["descriptions"]:
            continue
        # Sample up to 3 records per file
        for record in payload["descriptions"][:3]:
            assert "stat_ids" in record and isinstance(record["stat_ids"], list)
            assert "primary_stat_id" in record
            assert "variants" in record and isinstance(record["variants"], list)
            assert "languages_available" in record
            assert "source_line" in record
            # primary_stat_id should match first of stat_ids list
            assert record["primary_stat_id"] == record["stat_ids"][0]


# ---------------------------------------------------------------------------
# find_stat_description (when dataset present)
# ---------------------------------------------------------------------------

@needs_dataset
def test_find_stat_description_returns_proliferation_canonical_text():
    """The proliferation example HivemindOverlord's Claude Desktop session
    couldn't find — verify the dataset surfaces the literal game string."""
    r = find_stat_description("support_ignite_proliferation_radius")
    assert r is not None
    # Source provenance fields added by helper
    assert r.get("source_file") == "gem_stat_descriptions.json"
    assert "source_csd" in r
    # The actual game text — locked verbatim. Templates use PoB-style
    # [InternalName|DisplayText] hyperlink syntax; preserved as-is so the
    # consumer can choose to display the bracketed form or strip it.
    assert "inflicted by Supported Skills" in r["primary_template"]
    assert "[AilmentSpread|Spread]" in r["primary_template"]
    assert "{0} metre" in r["primary_template"]


@needs_dataset
def test_find_stat_description_returns_none_for_unknown_stat():
    assert find_stat_description("definitely_not_a_real_stat_id_xyz_12345") is None


@needs_dataset
def test_find_stat_description_other_known_stat():
    """Pick an unrelated stat that's definitely in the dataset."""
    r = find_stat_description("support_elemental_proliferation_damage_+%_final")
    assert r is not None
    assert "more Damage" in r["primary_template"]


# ---------------------------------------------------------------------------
# search_stat_descriptions
# ---------------------------------------------------------------------------

@needs_dataset
def test_search_proliferation_returns_multiple_hits():
    """Generic 'proliferation' query should surface multiple stat_ids."""
    hits = search_stat_descriptions("proliferation", limit=10)
    assert len(hits) >= 2  # at least the two we documented in #98
    for h in hits:
        # Every hit tagged with provenance + match info
        assert "source_file" in h
        assert "match_field" in h
        assert h["match_field"] in ("stat_id", "template")


@needs_dataset
def test_search_respects_limit():
    hits = search_stat_descriptions("life", limit=5)
    assert len(hits) <= 5


@needs_dataset
def test_search_unknown_query_returns_empty():
    assert search_stat_descriptions("zzzzz_definitely_no_match_zzzzz") == []


@needs_dataset
def test_search_template_only_mode():
    """Searching only templates should miss stat_id-only matches."""
    # Proliferation is in stat_id ("support_ignite_proliferation_radius") but
    # the word "proliferation" doesn't appear in the template text itself
    # (which says "Spread"). Verify template-only mode reflects this.
    template_only = search_stat_descriptions(
        "proliferation", limit=10, fields=("template",)
    )
    # Stat_id-only would include the proliferation_radius entry
    stat_id_only = search_stat_descriptions(
        "proliferation", limit=10, fields=("stat_id",)
    )
    # Stat-id search must find more than template search for this query
    assert len(stat_id_only) > len(template_only)


@needs_dataset
def test_search_case_insensitive():
    upper = search_stat_descriptions("PROLIFERATION", limit=5)
    lower = search_stat_descriptions("proliferation", limit=5)
    assert {h["primary_stat_id"] for h in upper} == {h["primary_stat_id"] for h in lower}
