"""
Tests for the BM25 lexical retrieval tier (#177, amended no-model design).

Locks the morphological-recall property that motivated the issue:
substring search misses wither->Withered; stemmed BM25 catches it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.lexical_search import (
    BM25Index,
    search_stat_descriptions_ranked,
    stem,
    tokenize,
)


def test_stem_handles_inflection():
    assert stem("withered") == "wither"
    assert stem("withering") == "wither"
    assert stem("slows") == "slow"
    assert stem("igniting") == "ignit" and stem("ignited") == "ignit"
    assert stem("hits") == "hit" and stem("stacks") == "stack"
    assert stem("dps") == "dps"          # short tokens untouched
    assert stem("chaos") == "chaos"     # vowel-before-s is not a plural
    assert stem("status") == "status"


def test_tokenize_strips_markup():
    toks = tokenize("[Withered|Wither] increased [Chaos] Damage")
    assert "wither" in toks            # both markup halves stem together
    assert "chao" in toks or "chaos" in toks
    assert "damag" in toks or "damage" in toks


def test_bm25_ranks_relevant_doc_first():
    idx = BM25Index()
    idx.add("a", "increased chaos damage")
    idx.add("b", "poison deals chaos damage over time and bypasses energy shield")
    idx.add("c", "increased fire damage")
    idx.finalize()
    hits = idx.search("chaos damage", k=3)
    assert hits[0][1]["id"] in ("a", "b")   # a chaos doc, not fire
    assert hits[0][1]["id"] != "c"


def test_bm25_empty_query_and_corpus():
    idx = BM25Index()
    idx.finalize()
    assert idx.search("anything") == []
    idx2 = BM25Index()
    idx2.add("a", "some text")
    idx2.finalize()
    assert idx2.search("") == []


# --- real-corpus tests (skip if dataset absent) ---

CORPUS = PROJECT_ROOT / "data" / "game" / "stat_descriptions" / "stat_descriptions.json"
needs_corpus = pytest.mark.skipif(not CORPUS.exists(), reason="stat descriptions not present")


@needs_corpus
def test_wither_morphological_recall():
    """The headline #177 case: 'wither' must surface Withered stat ids."""
    hits = search_stat_descriptions_ranked("wither", k=5)
    assert hits
    assert any("wither" in h["stat_id"].lower() for h in hits)


@needs_corpus
def test_chaos_damage_ranks_chaos_not_poison():
    hits = search_stat_descriptions_ranked("chaos damage", k=5)
    assert hits
    assert "chaos" in hits[0]["stat_id"].lower()


@needs_corpus
def test_results_carry_score_and_template():
    hits = search_stat_descriptions_ranked("ignite", k=3)
    assert hits
    for h in hits:
        assert "stat_id" in h and "score" in h
        assert h["score"] > 0
