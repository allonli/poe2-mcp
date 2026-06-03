"""
Tests for ascendancy_resolver migration to data/game/ (issues #137, #135).

Locks in:
  - Fresh data load (4 ascendancies the legacy file misses): Spirit Walker,
    Martial Artist, Abyssal Lich, Disciple of Varashta.
  - Schema adapter correctly converts the flat-list shape into the
    resolver's dict-keyed-by-display-name shape.
  - Legacy fallback still works when data/game/ is absent.
  - Hardcoded ASCENDANCY_TO_CLASS gets augmented from fresh data so
    ``get_base_class`` is correct for the new ascendancies.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def resolver():
    """Construct a resolver pointed at the repo's real data/ dir."""
    from src.parsers.ascendancy_resolver import AscendancyResolver
    return AscendancyResolver(data_dir=PROJECT_ROOT / "data")


def test_loads_fresh_data_with_new_ascendancies(resolver):
    """Fresh dataset should expose the 4 ascendancies the legacy file lacks."""
    resolver._ensure_loaded()
    asc_dict = resolver._all_ascendancies.get("ascendancies", {})
    # The four 0.5 ascendancies the legacy all_ascendancies.json was missing.
    for name in ["Spirit Walker", "Martial Artist", "Abyssal Lich", "Disciple of Varashta"]:
        assert name in asc_dict, (
            f"missing {name!r} — migration to data/game/ascendancies/ didn't take effect"
        )


def test_active_count_matches_fresh_extraction(resolver):
    """Should expose exactly the 23 active ascendancies from the fresh extraction."""
    resolver._ensure_loaded()
    asc_dict = resolver._all_ascendancies.get("ascendancies", {})
    assert len(asc_dict) == 23, (
        f"expected 23 active ascendancies, got {len(asc_dict)}. "
        f"Did the fresh dataset get re-extracted with a different active count?"
    )


def test_get_base_class_works_for_new_ascendancies(resolver):
    """get_base_class must return correct base class for new 0.5 ascendancies."""
    expected = {
        "Spirit Walker": "Huntress",
        "Martial Artist": "Monk",
        "Abyssal Lich": "Witch",
        "Disciple of Varashta": "Sorceress",
    }
    resolver._ensure_loaded()
    for asc, base in expected.items():
        got = resolver.get_base_class(asc)
        assert got == base, f"{asc}: expected base {base!r}, got {got!r}"


def test_existing_ascendancies_still_resolve(resolver):
    """Regression: pre-0.5 ascendancies must still load correctly."""
    resolver._ensure_loaded()
    for name in ["Stormweaver", "Titan", "Deadeye", "Shaman"]:
        assert name in resolver._all_ascendancies.get("ascendancies", {})
        assert resolver.get_base_class(name) is not None


def test_unused_placeholder_rows_excluded(resolver):
    """The 14 ``[DNT-UNUSED]`` placeholder rows from the source datc64 must
    NOT appear in the resolver's exposed dataset."""
    resolver._ensure_loaded()
    asc_dict = resolver._all_ascendancies.get("ascendancies", {})
    unused_markers = [name for name in asc_dict if "DNT-UNUSED" in name]
    assert not unused_markers, f"placeholder rows leaked into resolver: {unused_markers}"


def test_schema_adapter_is_static_and_pure(tmp_path):
    """The adapter should work on synthetic input without touching disk."""
    from src.parsers.ascendancy_resolver import AscendancyResolver
    synthetic = {
        "metadata": {"source": "test"},
        "ascendancies": [
            {"row_index": 0, "id": "X1", "display_name": "[DNT-UNUSED] foo",
             "base_class": "Warrior", "is_unused": True},
            {"row_index": 1, "id": "X2", "display_name": "Real Asc",
             "base_class": "Warrior", "is_unused": False},
            {"row_index": 2, "id": "X3", "display_name": "Other",
             "base_class": "Witch"},  # no is_unused → treated as active
        ],
    }
    result = AscendancyResolver._adapt_fresh_schema(synthetic)
    asc = result["ascendancies"]
    assert "[DNT-UNUSED] foo" not in asc
    assert asc["Real Asc"]["base_class"] == "Warrior"
    assert asc["Other"]["base_class"] == "Witch"
    assert asc["Real Asc"]["notable_nodes"] == {}


def test_legacy_fallback_when_fresh_missing(tmp_path):
    """If data/game/ascendancies/ doesn't exist, resolver must fall back to
    data/complete_models/ — graceful degradation, not a crash."""
    from src.parsers.ascendancy_resolver import AscendancyResolver
    # Stub data tree: no game/ascendancies, just legacy complete_models
    (tmp_path / "complete_models").mkdir()
    (tmp_path / "complete_models" / "all_ascendancies.json").write_text(json.dumps({
        "ascendancies": {
            "Titan": {"base_class": "Warrior", "notable_nodes": {}},
        }
    }))
    r = AscendancyResolver(data_dir=tmp_path)
    r._ensure_loaded()
    assert "Titan" in r._all_ascendancies.get("ascendancies", {})


def test_no_data_at_all_does_not_crash(tmp_path):
    """If neither dataset is available, resolver loads empty without raising."""
    from src.parsers.ascendancy_resolver import AscendancyResolver
    r = AscendancyResolver(data_dir=tmp_path)
    r._ensure_loaded()
    # Hardcoded ASCENDANCY_TO_CLASS still answers for known names
    assert r.get_base_class("Stormweaver") == "Sorceress"
