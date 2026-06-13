"""
Tests for the ascendancy node dataset (campaign C5, closes #137 row 1b).

The 0.5 .datc64 extraction carries no ascendancy node data (verified on
#137); data/game/ascendancies/nodes.json is generated from the PoB2
community 0.5 tree under the established psg+pob precedent and merged
into the resolver's notable_nodes contract.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.parsers.ascendancy_resolver import AscendancyResolver


@pytest.fixture(scope="module")
def resolver():
    return AscendancyResolver()


def test_dataset_ships_with_provenance():
    data = json.loads(
        (PROJECT_ROOT / "data" / "game" / "ascendancies" / "nodes.json")
        .read_text(encoding="utf-8")
    )
    meta = data["metadata"]
    assert "PathOfBuilding" in meta["source"]
    assert "psg+pob precedent" in meta["provenance"]
    assert meta["ascendancy_count"] >= 20
    assert meta["node_count"] >= 400


def test_new_05_ascendancies_have_nodes(resolver):
    """The #135-class gap: Martial Artist and Spirit Walker were
    class-mapped but had zero node data before this dataset."""
    for name, min_nodes in (("Martial Artist", 10), ("Spirit Walker", 10)):
        info = resolver.get_ascendancy_info(name)
        assert info, f"{name} not resolvable"
        nodes = info.get("notable_nodes") or {}
        assert len(nodes) >= min_nodes, f"{name} has only {len(nodes)} nodes"
        assert any(v.get("kind") == "notable" for v in nodes.values())


def test_eternal_life_text_anchor(resolver):
    """Exact game text for the commander's Lich pivot keystone — locks
    the dataset's stat fidelity."""
    lich = resolver.get_ascendancy_info("Lich")
    nodes = lich.get("notable_nodes") or {}
    eternal = [v for v in nodes.values() if v.get("name") == "Eternal Life"]
    assert eternal, "Eternal Life missing from Lich"
    assert eternal[0]["stats"] == [
        "Your Life cannot change while you have Energy Shield"
    ]


def test_existing_ascendancies_enriched_not_broken(resolver):
    info = resolver.get_ascendancy_info("Infernalist")
    assert info["base_class"] == "Witch"
    nodes = info.get("notable_nodes") or {}
    names = {v.get("name") for v in nodes.values()}
    assert "Loyal Hellhound" in names
    assert info.get("node_source") == "pob_0_5_tree"


def test_node_kinds_classified(resolver):
    info = resolver.get_ascendancy_info("Lich")
    kinds = {v.get("kind") for v in (info.get("notable_nodes") or {}).values()}
    assert "notable" in kinds
    assert "small" in kinds
