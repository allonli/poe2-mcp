"""
Mod-data helpers for MCP handlers.

Lives in its own light-weight module (no heavy imports) so unit tests can
exercise the stat-resolution logic without pulling in mcp_server or
SQLAlchemy. Closes the #118 inline-stat_id audit gap.

The contract: every mod record in data/game/mods/mods.json (and the
identical legacy copy at data/poe2_mods_extracted.json) carries a `stats`
list. Each non-empty entry has a resolved `stat_id` string inline as of
data-v0.5.0-r5. Consumers MUST prefer the inline field; cross-reference
through data/game/stats/ is only a fallback for older extractions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


def resolve_stat_id(
    stat_entry: Dict[str, Any],
    stat_lookup: Optional[Dict[int, str]] = None,
) -> Optional[str]:
    """Return the stat_id for a single mod stat entry, or None when empty.

    Order of preference:
      1. Inline `stat_id` field (post data-v0.5.0-r5).
      2. Cross-reference `stat_lookup[stat_key]` (legacy fallback).
      3. None.

    Returns None for entries marked `is_empty=True` regardless of source.
    """
    if not stat_entry or stat_entry.get("is_empty"):
        return None
    inline = stat_entry.get("stat_id")
    if inline:
        return inline
    if stat_lookup is not None:
        sk = stat_entry.get("stat_key")
        if sk is not None and sk in stat_lookup:
            return stat_lookup[sk]
    return None


def iter_resolved_stats(
    mod: Dict[str, Any],
    stat_lookup: Optional[Dict[int, str]] = None,
) -> List[Dict[str, Any]]:
    """Return a list of {stat_id, min_value, max_value} for a mod's active stats.

    Skips empty entries (is_empty=True) and entries that fail to resolve via
    both inline stat_id and the optional stat_lookup fallback.
    """
    out: List[Dict[str, Any]] = []
    for s in mod.get("stats") or []:
        if not isinstance(s, dict):
            continue
        sid = resolve_stat_id(s, stat_lookup)
        if sid is None:
            continue
        out.append({
            "stat_id": sid,
            "min_value": s.get("min_value", 0),
            "max_value": s.get("max_value", 0),
            "from_inline": bool(s.get("stat_id")),
        })
    return out


def mod_value_range(mod: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """Best-effort single-value range for a mod's primary stat.

    The legacy schema had top-level min_value/max_value. The current schema
    nests those per-stat. This helper returns the first non-empty stat's
    range, falling back to top-level fields when present (handles records
    from older extractions gracefully).

    Returns None when no resolvable stat exists.
    """
    for s in mod.get("stats") or []:
        if isinstance(s, dict) and not s.get("is_empty"):
            return {
                "min": s.get("min_value", 0),
                "max": s.get("max_value", 0),
            }
    # Legacy top-level fields, in case some old record sneaks in
    if "min_value" in mod or "max_value" in mod:
        return {
            "min": mod.get("min_value", 0),
            "max": mod.get("max_value", 0),
        }
    return None


def canonical_mods_path(data_dir: Path) -> Path:
    """The preferred mods file path. Falls back caller-side on missing.

    Args:
        data_dir: The project's DATA_DIR (.../poe2-mcp/data).
    """
    return data_dir / "game" / "mods" / "mods.json"


def legacy_mods_path(data_dir: Path) -> Path:
    """Pre-PR-#69 path. Identical content as of 2026-06-01 — both refer to
    the same extracted dump."""
    return data_dir / "poe2_mods_extracted.json"


def load_stat_lookup(data_dir: Path) -> Dict[int, str]:
    """Read data/game/stats/stats.json into a row_index -> stat_id dict.

    Returns an empty dict on any failure (file missing, parse error). The
    lookup is only used as a fallback — modern extractions have inline
    stat_id on each mod stat, so a missing stats.json is non-fatal.
    """
    stats_file = data_dir / "game" / "stats" / "stats.json"
    if not stats_file.exists():
        return {}
    try:
        with open(stats_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            entry["row_index"]: entry["stat_id"]
            for entry in data.get("stats", [])
            if "row_index" in entry and "stat_id" in entry
        }
    except Exception as e:
        logger.warning(f"load_stat_lookup: {e}")
        return {}
