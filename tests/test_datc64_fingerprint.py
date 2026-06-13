"""
Tests for .datc64 schema fingerprinting (campaign C3).

Diff-classification tests run everywhere (synthetic inputs); the
baseline-generation tests skip when the gitignored raw extraction
is absent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.parsers.datc64_fingerprint import (
    diff_fingerprints,
    fingerprint_balance_dir,
    format_diff_report,
)

BALANCE = PROJECT_ROOT / "data" / "extracted" / "data" / "balance"
needs_tables = pytest.mark.skipif(
    not (BALANCE / "stats.datc64").exists(),
    reason="raw .datc64 extraction not present (gitignored)",
)


def _fp(tables):
    return {"generated_at": "t", "table_count": len(tables), "tables": tables}


def test_diff_clean():
    a = _fp({"x": {"row_count": 5, "row_size": 8, "sha256": "aa", "bytes": 1}})
    d = diff_fingerprints(a, a)
    assert d["clean"] is True
    assert "CLEAN" in format_diff_report(d)


def test_diff_layout_change_is_loudest():
    old = _fp({"x": {"row_count": 5, "row_size": 8, "sha256": "aa", "bytes": 1}})
    new = _fp({"x": {"row_count": 5, "row_size": 12, "sha256": "bb", "bytes": 1}})
    d = diff_fingerprints(old, new)
    assert d["layout_changed"][0]["table"] == "x"
    assert d["clean"] is False
    assert "LAYOUT CHANGED" in format_diff_report(d)


def test_diff_rows_and_content_and_membership():
    old = _fp({
        "a": {"row_count": 5, "row_size": 8, "sha256": "aa"},
        "b": {"row_count": 5, "row_size": 8, "sha256": "bb"},
        "gone": {"row_count": 1, "row_size": 4, "sha256": "cc"},
    })
    new = _fp({
        "a": {"row_count": 9, "row_size": 8, "sha256": "xx"},   # rows changed
        "b": {"row_count": 5, "row_size": 8, "sha256": "yy"},   # content only
        "fresh": {"row_count": 1, "row_size": 4, "sha256": "zz"},
    })
    d = diff_fingerprints(old, new)
    assert d["added"] == ["fresh"]
    assert d["removed"] == ["gone"]
    assert d["rows_changed"][0]["table"] == "a"
    assert d["content_changed"] == ["b"]


@needs_tables
def test_baseline_generation_matches_disk():
    fp = fingerprint_balance_dir(BALANCE)
    assert fp["table_count"] >= 1000
    gepl = fp["tables"]["grantedeffectsperlevel"]
    assert gepl["row_size"] == 116          # the C1 spec's layout anchor
    assert gepl["row_count"] >= 34000


@needs_tables
def test_shipped_baseline_is_current():
    """The tracked baseline must match the on-disk extraction — if this
    fails, someone re-extracted without regenerating the baseline."""
    shipped = json.loads(
        (PROJECT_ROOT / "data" / "game" / "schema_fingerprints.json")
        .read_text(encoding="utf-8")
    )
    live = fingerprint_balance_dir(BALANCE)
    d = diff_fingerprints(shipped, live)
    assert d["clean"], format_diff_report(d)
