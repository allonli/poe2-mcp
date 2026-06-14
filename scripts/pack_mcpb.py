#!/usr/bin/env python3
"""Pack mcpb_bundle/ into a distributable .mcpb file for Claude Desktop.

An .mcpb (MCP Bundle) is a plain ZIP archive whose root contains a spec-conformant
manifest.json (manifest_version + server.entry_point + server.mcp_config). Claude
Desktop's extension installer reads manifest.json from the archive root; if the
manifest is missing manifest_version or the server block, the install silently
does nothing (issue #185).

This script validates the manifest against the required MCPB fields before packing,
so a broken bundle can never be shipped again.

Usage:
    python scripts/pack_mcpb.py                 # -> poe2-mcp-<version>.mcpb
    python scripts/pack_mcpb.py --out dist.mcpb # custom output path

Data flow:
    mcpb_bundle/manifest.json (validated) + mcpb_bundle/** -> <name>-<version>.mcpb
"""

import argparse
import json
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_DIR = REPO_ROOT / "mcpb_bundle"

# Fields the Claude Desktop / MCPB loader requires. Missing any of these is the
# difference between "installs" and "nothing happens".
REQUIRED_TOP_LEVEL = ("manifest_version", "name", "version", "description", "author", "server")
REQUIRED_SERVER = ("type", "entry_point", "mcp_config")
VALID_SERVER_TYPES = ("node", "python", "binary", "uv")


def validate_manifest(manifest: dict) -> list[str]:
    """Return a list of human-readable problems; empty list means valid."""
    problems: list[str] = []

    for field in REQUIRED_TOP_LEVEL:
        if field not in manifest:
            problems.append(f"missing required top-level field: {field!r}")

    server = manifest.get("server")
    if not isinstance(server, dict):
        problems.append("'server' must be an object")
        return problems

    for field in REQUIRED_SERVER:
        if field not in server:
            problems.append(f"missing required server field: server.{field!r}")

    stype = server.get("type")
    if stype is not None and stype not in VALID_SERVER_TYPES:
        problems.append(f"server.type {stype!r} not one of {VALID_SERVER_TYPES}")

    entry = server.get("entry_point")
    if isinstance(entry, str):
        if not (BUNDLE_DIR / entry).exists():
            problems.append(f"server.entry_point {entry!r} does not exist in bundle")

    mcp_config = server.get("mcp_config")
    if mcp_config is not None and not isinstance(mcp_config, dict):
        problems.append("server.mcp_config must be an object")

    return problems


def pack(out_path: Path) -> Path:
    manifest_path = BUNDLE_DIR / "manifest.json"
    if not manifest_path.exists():
        sys.exit(f"ERROR: {manifest_path} not found")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems = validate_manifest(manifest)
    if problems:
        print("ERROR: manifest.json is not MCPB-conformant:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)

    files = sorted(p for p in BUNDLE_DIR.rglob("*") if p.is_file())
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            # arcname is relative to bundle root so manifest.json sits at archive root
            zf.write(f, f.relative_to(BUNDLE_DIR).as_posix())

    print(f"Packed {len(files)} files -> {out_path} ({out_path.stat().st_size:,} bytes)")
    print(f"manifest_version={manifest['manifest_version']} "
          f"entry_point={manifest['server']['entry_point']}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Pack mcpb_bundle/ into a .mcpb file")
    parser.add_argument("--out", type=Path, default=None,
                        help="output path (default: <name>-<version>.mcpb in repo root)")
    args = parser.parse_args()

    manifest = json.loads((BUNDLE_DIR / "manifest.json").read_text(encoding="utf-8"))
    out = args.out or REPO_ROOT / f"{manifest['name']}-{manifest['version']}.mcpb"
    pack(out)


if __name__ == "__main__":
    main()
