"""
Tests for the bun-based balance-table extraction helper (issue #138).

The script ``scripts/extract_balance_tables_v1.py`` exists to FIX the
partial extraction produced by ``scripts/extract_poe2_data.py`` (pythonnet +
LibBundle3 v2.7.x got 279 of 1,017 canonical tables on 2026-06-02).

Unit-testable surfaces:
  - ``CANONICAL_BALANCE_RE`` correctly matches what bun_extract_file emits
    (lowercase forward-slash paths under ``data/balance/``).
  - The same regex correctly rejects localization variants, sub-directories,
    and non-.datc64 entries.

The subprocess paths (``run_extraction``, ``count_index_balance_tables``)
are smoke-tested by ``--check`` mode in the field; not pinned here to keep
the test suite hermetic (no Steam install / no bun binary required).
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "extract_balance_tables_v1.py"


def _load_script_module():
    """Load the script as a module without running its __main__."""
    spec = importlib.util.spec_from_file_location(
        "extract_balance_tables_v1", SCRIPT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["extract_balance_tables_v1"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_canonical_regex_matches_balance_tables():
    """Direct children of data/balance/ ending in .datc64 must match."""
    mod = _load_script_module()
    pattern = re.compile(mod.CANONICAL_BALANCE_RE)
    # Real samples from bun_extract_file's `list-files` output (2026-06-02)
    samples = [
        "data/balance/flasks.datc64",
        "data/balance/passivejewelradii.datc64",
        "data/balance/modfamily.datc64",
        "data/balance/words.datc64",
        "data/balance/skillgems.datc64",
    ]
    for s in samples:
        assert pattern.match(s) is not None, f"expected to match: {s}"


def test_canonical_regex_rejects_localization_variants():
    """Per-language copies live in subdirectories — must NOT match."""
    mod = _load_script_module()
    pattern = re.compile(mod.CANONICAL_BALANCE_RE)
    rejects = [
        "data/balance/french/flasks.datc64",
        "data/balance/german/flasks.datc64",
        "data/balance/japanese/skillgems.datc64",
        "data/balance/koreana/words.datc64",
    ]
    for s in rejects:
        assert pattern.match(s) is None, f"expected to reject (lang subdir): {s}"


def test_canonical_regex_rejects_non_datc64():
    """Non-.datc64 entries must NOT match."""
    mod = _load_script_module()
    pattern = re.compile(mod.CANONICAL_BALANCE_RE)
    rejects = [
        "data/balance/readme.txt",
        "data/balance/words.dat",
        "data/balance/words.datc",
        "data/balance/words.datc64.bak",
    ]
    for s in rejects:
        assert pattern.match(s) is None, f"expected to reject (wrong ext): {s}"


def test_canonical_regex_rejects_other_directories():
    """Files in other top-level dirs must NOT match."""
    mod = _load_script_module()
    pattern = re.compile(mod.CANONICAL_BALANCE_RE)
    rejects = [
        "data/effects/some.datc64",
        "data/uistate/some.datc64",
        "metadata/balance/something.datc64",
        "balance/something.datc64",
    ]
    for s in rejects:
        assert pattern.match(s) is None, f"expected to reject (wrong dir): {s}"


def test_count_extracted_returns_zero_for_missing_dir(tmp_path):
    """If the output root has no Data/balance/, count is 0 (not crash)."""
    mod = _load_script_module()
    empty = tmp_path / "nothing-here"
    assert mod.count_extracted_balance_tables(empty) == 0


def test_count_extracted_counts_datc64_only(tmp_path):
    """Count includes .datc64 files only, ignores siblings."""
    mod = _load_script_module()
    balance = tmp_path / "Data" / "balance"
    balance.mkdir(parents=True)
    (balance / "flasks.datc64").write_bytes(b"")
    (balance / "skillgems.datc64").write_bytes(b"")
    (balance / "readme.txt").write_bytes(b"")
    (balance / "subdir").mkdir()
    (balance / "subdir" / "ignored.datc64").write_bytes(b"")
    assert mod.count_extracted_balance_tables(tmp_path) == 2
