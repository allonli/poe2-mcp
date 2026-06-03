#!/usr/bin/env python3
"""
Full ``Data/balance/*.datc64`` extractor (issue #138).

Replaces the partial-extraction path in ``scripts/extract_poe2_data.py``,
which uses pythonnet + LibBundle3 v2.7.x and silently produces an
incomplete result (279 of 1,017 canonical tables as of 2026-06-02).

This script uses ``ooz/build/Release/bun_extract_file.exe`` directly,
which the maintainer (#138) verified gets all 1,017 canonical English
tables on a single pass. The tool is fast (~5-10 seconds end-to-end on
a Steam install) and ships in-tree, so no extra deps required.

Behaviour:
  1. Locate the live PoE2 Steam install (or honor ``$POE2_PATH``).
  2. Locate ``bun_extract_file.exe`` at the canonical in-tree path.
  3. Run ``bun_extract_file extract-files --regex <install> <output>
     "^Data/balance/[^/]+\\.datc64$"`` to pull every canonical English
     ``.datc64`` table from the bundles.
  4. Verify the extracted count matches the index manifest count via a
     ``list-files`` cross-check. Print a delta if they diverge.

Usage:
    python scripts/extract_balance_tables_v1.py
    python scripts/extract_balance_tables_v1.py --output data/extracted_fresh
    python scripts/extract_balance_tables_v1.py --check  # verify-only

Output is gitignored (``data/extracted/``). The PR-shippable consequence
of running this script is regenerated ``data/game/*`` derived datasets
(handled in follow-up PRs per the issue's acceptance criteria).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BUN_EXTRACT = BASE_DIR / "ooz" / "build" / "Release" / "bun_extract_file.exe"
DEFAULT_OUTPUT = BASE_DIR / "data" / "extracted"

# Regex matches every canonical English .datc64 directly in data/balance/
# (no language subfolders, no other directories). poe.ninja and the
# downstream parsers in this repo all consume canonical English tables.
# Note: bun_extract_file emits paths lowercased with forward slashes,
# so this regex is intentionally lowercase.
CANONICAL_BALANCE_RE = r"^data/balance/[^/]+\.datc64$"


def find_poe2_install() -> Path | None:
    """Return the live PoE2 Steam install root, or None."""
    candidates = [
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Path of Exile 2"),
        Path(r"C:\Program Files\Steam\steamapps\common\Path of Exile 2"),
        Path(r"D:\Steam\steamapps\common\Path of Exile 2"),
        Path(r"D:\SteamLibrary\steamapps\common\Path of Exile 2"),
    ]
    env_path = os.environ.get("POE2_PATH")
    if env_path:
        candidates.insert(0, Path(env_path))
    for p in candidates:
        if (p / "Bundles2" / "_.index.bin").exists():
            return p
    return None


def count_index_balance_tables(install: Path) -> int:
    """Count canonical balance .datc64 entries in the live index."""
    proc = subprocess.run(
        [str(BUN_EXTRACT), "list-files", str(install)],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    )
    pattern = re.compile(CANONICAL_BALANCE_RE)
    return sum(1 for line in proc.stdout.splitlines() if pattern.match(line))


def count_extracted_balance_tables(output_root: Path) -> int:
    """Count canonical balance .datc64 files actually on disk."""
    balance_dir = output_root / "Data" / "balance"
    if not balance_dir.is_dir():
        return 0
    return sum(1 for p in balance_dir.iterdir() if p.suffix == ".datc64")


def run_extraction(install: Path, output_root: Path) -> int:
    """Invoke bun_extract_file. Returns its exit code."""
    output_root.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(BUN_EXTRACT),
        "extract-files",
        "--regex",
        str(install),
        str(output_root),
        CANONICAL_BALANCE_RE,
    ]
    print(f"  $ {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.stdout:
        # bun emits a "Done, X/Y extracted, Z missed" line we want to surface
        for line in proc.stdout.splitlines():
            if line.strip():
                print(f"  | {line}")
    if proc.returncode != 0 and proc.stderr:
        print(f"  STDERR:\n{proc.stderr}", file=sys.stderr)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output root (default: data/extracted)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify-only mode: report counts, don't run extraction",
    )
    args = parser.parse_args()

    if not BUN_EXTRACT.exists():
        print(f"ERROR: bun_extract_file not found at {BUN_EXTRACT}", file=sys.stderr)
        print("Expected in-tree at ooz/build/Release/. Build the ooz "
              "submodule first?", file=sys.stderr)
        return 2

    install = find_poe2_install()
    if not install:
        print("ERROR: PoE2 install not found. Set $POE2_PATH if Steam is "
              "in a non-standard location.", file=sys.stderr)
        return 2

    print(f"PoE2 install: {install}")
    print(f"Output root:  {args.output}")

    print("Counting canonical balance tables in live index...")
    index_count = count_index_balance_tables(install)
    print(f"  Index reports: {index_count} canonical balance .datc64 tables")

    if args.check:
        on_disk = count_extracted_balance_tables(args.output)
        print(f"  On disk:       {on_disk}")
        if on_disk == index_count:
            print(f"OK: extraction complete ({on_disk}/{index_count})")
            return 0
        missing = index_count - on_disk
        print(f"GAP: {missing} table(s) missing from extraction")
        return 1

    print("Running extraction...")
    rc = run_extraction(install, args.output)
    if rc != 0:
        print(f"ERROR: bun_extract_file exited {rc}", file=sys.stderr)
        return rc

    on_disk = count_extracted_balance_tables(args.output)
    print(f"\nVerification: {on_disk}/{index_count} canonical tables on disk")
    if on_disk != index_count:
        print("WARNING: extraction count does not match index count",
              file=sys.stderr)
        return 1
    print("OK: full extraction successful")
    return 0


if __name__ == "__main__":
    sys.exit(main())
