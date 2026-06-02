"""
Tests for #132 - charModel.pathOfBuildingExport as primary parse route.

When poe.ninja returns a character with a non-empty pathOfBuildingExport,
the normaliser routes it through the PoB importer first and merges
poe.ninja-only metadata on top. This sidesteps CLAUDE.md CRITICAL #1
(stale local passive tree) for all poe.ninja-sourced characters.

Tests:
  - sync helper ``import_build_sync`` is present + callable + matches the
    async wrapper's output on the same input
  - normaliser picks ``pob_export`` route when export looks valid
  - normaliser falls back to field-based normalize when export missing or
    fails to decode
  - poe.ninja-only metadata (account, league, defensiveStats) is preserved
    when PoB takes the primary route
"""
from __future__ import annotations

import asyncio
import base64
import sys
import zlib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# Minimal-but-valid PoB XML: enough for the importer's parsers to walk
# without crashing. Items/Skills are empty; the importer's defaults handle
# that gracefully (returns empty lists / "0" / "Unknown").
_MINIMAL_POB_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<PathOfBuilding version="2.0">'
    '<Build level="55" className="Witch" ascendClassName="Infernalist">'
    '<PlayerStat stat="AverageHit" value="1234.5"/>'
    '</Build>'
    '<Notes>Test build notes</Notes>'
    '<Tree activeSpec="1">'
    '<Spec masteryEffects="">'
    '<URL>https://www.pathofexile.com/passive-skill-tree/AAAAAA</URL>'
    '</Spec>'
    '</Tree>'
    '<Items/>'
    '<Skills/>'
    '<Config/>'
    '</PathOfBuilding>'
)


def _make_pob_code(xml: str = _MINIMAL_POB_XML) -> str:
    """Encode XML the way PoB exports it (zlib-compressed + base64)."""
    return base64.b64encode(zlib.compress(xml.encode("utf-8"))).decode("ascii")


# ---------------------------------------------------------------------------
# Sync helper present + matches async wrapper
# ---------------------------------------------------------------------------

def test_import_build_sync_callable():
    """Sync entry point exists and produces a dict from a minimal PoB blob."""
    from src.pob.importer import PoBImporter
    importer = PoBImporter()
    code = _make_pob_code()
    result = importer.import_build_sync(code)
    assert isinstance(result, dict)
    assert result["level"] == 55
    assert result["class"] == "Witch"
    assert result["ascendancy"] == "Infernalist"


def test_sync_matches_async_output():
    """The async wrapper returns the same dict as the sync helper."""
    from src.pob.importer import PoBImporter
    importer = PoBImporter()
    code = _make_pob_code()
    sync_result = importer.import_build_sync(code)
    async_result = asyncio.run(importer.import_build(code))
    assert sync_result == async_result


# ---------------------------------------------------------------------------
# Normaliser routing
# ---------------------------------------------------------------------------

def _bare_fetcher():
    """Build a CharacterFetcher without running __init__ (no httpx client)."""
    from src.api.character_fetcher import CharacterFetcher
    return CharacterFetcher.__new__(CharacterFetcher)


def test_normalise_uses_pob_export_when_present():
    """A charModel with valid pathOfBuildingExport must take the PoB route."""
    f = _bare_fetcher()
    char_model = {
        "name": "TestChar",
        "level": 55,
        "class": "Witch",
        "league": "Runes of Aldur",
        "defensiveStats": {"life": 5000, "es": 2000},
        "pathOfBuildingExport": _make_pob_code(),
    }
    result = f._normalize_character_data(
        {"charModel": char_model}, "TestAcct", "TestChar"
    )
    assert result["parse_source"] == "pob_export"
    assert result["ascendancy"] == "Infernalist"
    assert result["pob_version"] == "2.0"
    # poe.ninja-only metadata preserved
    assert result["account"] == "TestAcct"
    assert result["league"] == "Runes of Aldur"
    assert result["stats"] == {"life": 5000, "es": 2000}


def test_normalise_falls_back_when_export_missing():
    """No export -> normaliser uses field-based path (pre-#132 behaviour)."""
    f = _bare_fetcher()
    char_model = {
        "name": "TestChar",
        "level": 55,
        "class": "Witch",
        "league": "Runes of Aldur",
        "defensiveStats": {"life": 5000},
        "passiveSelection": [4, 16, 30],
    }
    result = f._normalize_character_data(
        {"charModel": char_model}, "TestAcct", "TestChar"
    )
    assert result["parse_source"] == "field_normalize"
    assert "ascendancy" not in result  # PoB-only field absent
    assert result["passive_tree"] == [4, 16, 30]
    assert result["level"] == 55
    assert result["class"] == "Witch"


def test_normalise_falls_back_on_bad_export():
    """A corrupted/bogus export must not crash; fall back to field path."""
    f = _bare_fetcher()
    char_model = {
        "name": "TestChar",
        "level": 55,
        "class": "Witch",
        # Looks like a PoB header but isn't actually valid base64+zlib+XML.
        "pathOfBuildingExport": "eNrTotallyBogusGarbage===",
        "passiveSelection": [4, 16],
    }
    result = f._normalize_character_data(
        {"charModel": char_model}, "TestAcct", "TestChar"
    )
    assert result["parse_source"] == "field_normalize"
    assert result["passive_tree"] == [4, 16]


def test_normalise_ignores_non_pob_prefix():
    """Export that doesn't start with a known PoB zlib-header prefix is
    treated as absent (avoids burning the importer on obvious junk)."""
    f = _bare_fetcher()
    char_model = {
        "name": "X",
        "level": 1,
        "class": "Witch",
        "pathOfBuildingExport": "{this is not a pob code, it's json}",
    }
    result = f._normalize_character_data(
        {"charModel": char_model}, "Acc", "X"
    )
    assert result["parse_source"] == "field_normalize"


def test_normalise_preserves_pob_export_string():
    """``pob_export`` field on the output still carries the raw string for
    downstream callers (e.g. PoB-code re-export tools)."""
    f = _bare_fetcher()
    code = _make_pob_code()
    result = f._normalize_character_data(
        {"charModel": {"name": "X", "level": 1, "class": "Witch",
                       "pathOfBuildingExport": code}},
        "Acc", "X",
    )
    assert result["pob_export"] == code
