"""
Tests for the GrantedEffects/GEPL .datc64 spec (campaign C1, fires 7-12).

The reconciliation test IS the acceptance criterion the campaign
mandates: pure-game-file extraction vs the PoB2 oracle. At spec-landing
time the full corpus matched 12,061/12,061 per-level costs (100.00%).

All tests skip when the raw extraction isn't on disk (data/extracted/
is gitignored pipeline state - fresh clones don't carry 4MB tables).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.parsers.specifications.granted_effects_spec import load_granted_effects

EXTRACTED = PROJECT_ROOT / "data" / "extracted"
HAVE_TABLES = (
    (EXTRACTED / "data" / "balance" / "grantedeffectsperlevel.datc64").exists()
    or (EXTRACTED / "Data" / "balance" / "grantedeffectsperlevel.datc64").exists()
)
needs_tables = pytest.mark.skipif(
    not HAVE_TABLES, reason="raw .datc64 extraction not present (gitignored)"
)


@pytest.fixture(scope="module")
def tables():
    return load_granted_effects(EXTRACTED)


@needs_tables
def test_effect_rows_resolve_known_ids(tables):
    rows = tables.effect_rows()
    assert "EssenceDrainPlayer" in rows
    assert "FireballPlayer" in rows
    assert "MetaCastOnMinionDeathPlayer" in rows
    assert len(rows) > 8000


@needs_tables
def test_known_cost_anchors(tables):
    costs = tables.costs_by_effect_id()
    ed = costs["EssenceDrainPlayer"]
    assert ed[1] == 5 and ed[5] == 10 and ed[10] == 19
    fb = costs["FireballPlayer"]
    assert fb[1] == 10 and fb[10] == 35


@needs_tables
def test_dedup_pool_property(tables):
    """Same cost value across skills can share a pool entry - the property
    that cracked the encoding. Cost VALUES must agree regardless."""
    costs = tables.costs_by_effect_id()
    assert costs["EssenceDrainPlayer"][5] == costs["FireballPlayer"][1] == 10


@needs_tables
def test_full_corpus_reconciliation_vs_pob_oracle(tables):
    """Every per-level Mana cost in the PoB-derived v2 dataset must match
    the pure-.datc64 extraction. 100% at landing; any future patch that
    moves the column or pool encoding fails here loudly."""
    v2_path = PROJECT_ROOT / "data" / "game" / "skill_gems" / "skill_gems_v2.json"
    v2 = json.loads(v2_path.read_text(encoding="utf-8"))["skills"]
    datc = tables.costs_by_effect_id()

    compared = mismatched = 0
    for sid, skill in v2.items():
        if not isinstance(skill, dict):
            continue
        levels = [lv for lv in (skill.get("levels") or []) if isinstance(lv, dict)]
        d = datc.get(sid)
        if d is None:
            continue
        for n, lv in enumerate(levels):
            pob_cost = (lv.get("cost") or {}).get("Mana")
            if pob_cost is None or (n + 1) not in d:
                continue
            compared += 1
            if d[n + 1] != pob_cost:
                mismatched += 1
    assert compared > 10000, f"reconciliation corpus too small: {compared}"
    assert mismatched == 0, f"{mismatched}/{compared} cost mismatches vs PoB oracle"


@needs_tables
def test_geometry_validates(tables):
    """The spec's geometry check rejects malformed input."""
    with pytest.raises(ValueError):
        tables._geometry(b"\x05\x00\x00\x00" + b"\x00" * 7)  # no magic
