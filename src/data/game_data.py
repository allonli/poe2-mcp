"""
Canonical paths for extracted PoE2 game data tracked in this repo.

Use these constants instead of hardcoding strings — the layout can move and
callers won't notice:

    from src.data.game_data import MODS_JSON, PASSIVE_TREE_JSON, load_mods
    mods = load_mods()

See `data/game/README.md` for the layout, lifecycle, and data policy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
GAME_DATA_DIR = _BASE_DIR / "data" / "game"

# Global version manifest
VERSION_JSON = GAME_DATA_DIR / "version.json"

# Datasets — each is its own folder with `<name>.json` + `metadata.json`
MODS_DIR = GAME_DATA_DIR / "mods"
MODS_JSON = MODS_DIR / "mods.json"
MODS_META = MODS_DIR / "metadata.json"

PASSIVE_TREE_DIR = GAME_DATA_DIR / "passive_tree"
PASSIVE_TREE_JSON = PASSIVE_TREE_DIR / "tree.json"
PASSIVE_TREE_META = PASSIVE_TREE_DIR / "metadata.json"

SUPPORT_GEMS_DIR = GAME_DATA_DIR / "support_gems"
SUPPORT_GEMS_JSON = SUPPORT_GEMS_DIR / "support_gems.json"
SUPPORT_GEMS_META = SUPPORT_GEMS_DIR / "metadata.json"

ASCENDANCIES_DIR = GAME_DATA_DIR / "ascendancies"
ASCENDANCIES_JSON = ASCENDANCIES_DIR / "ascendancies.json"
ASCENDANCIES_META = ASCENDANCIES_DIR / "metadata.json"

STATS_DIR = GAME_DATA_DIR / "stats"
STATS_JSON = STATS_DIR / "stats.json"
STATS_META = STATS_DIR / "metadata.json"

SKILL_GEMS_DIR = GAME_DATA_DIR / "skill_gems"
SKILL_GEMS_JSON = SKILL_GEMS_DIR / "skill_gems.json"
SKILL_GEMS_META = SKILL_GEMS_DIR / "metadata.json"

STAT_DESCRIPTIONS_DIR = GAME_DATA_DIR / "stat_descriptions"
STAT_DESCRIPTIONS_INDEX = STAT_DESCRIPTIONS_DIR / "index.json"
STAT_DESCRIPTIONS_META = STAT_DESCRIPTIONS_DIR / "metadata.json"


def get_version() -> Optional[Dict[str, Any]]:
    """Return the parsed contents of data/game/version.json, or None if missing."""
    if not VERSION_JSON.exists():
        return None
    try:
        return json.loads(VERSION_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_mods() -> Optional[Dict[str, Any]]:
    """Load and return the canonical mods dataset, or None if missing."""
    if not MODS_JSON.exists():
        return None
    return json.loads(MODS_JSON.read_text(encoding="utf-8"))


def load_passive_tree() -> Optional[Dict[str, Any]]:
    """Load and return the canonical passive tree dataset, or None if missing."""
    if not PASSIVE_TREE_JSON.exists():
        return None
    return json.loads(PASSIVE_TREE_JSON.read_text(encoding="utf-8"))


def load_support_gems() -> Optional[Dict[str, Any]]:
    """Load and return the canonical support gems dataset, or None if missing."""
    if not SUPPORT_GEMS_JSON.exists():
        return None
    return json.loads(SUPPORT_GEMS_JSON.read_text(encoding="utf-8"))


def load_ascendancies() -> Optional[Dict[str, Any]]:
    """Load and return the canonical ascendancies dataset, or None if missing."""
    if not ASCENDANCIES_JSON.exists():
        return None
    return json.loads(ASCENDANCIES_JSON.read_text(encoding="utf-8"))


def load_stats() -> Optional[Dict[int, str]]:
    """Load and return the canonical stats table as a {row_index: stat_id} dict.

    Returns the dict form (not the raw JSON envelope) because that's the shape
    every caller wants — for resolving stat_key references from mods, passives,
    and gems. Returns None if stats.json is missing.
    """
    if not STATS_JSON.exists():
        return None
    payload = json.loads(STATS_JSON.read_text(encoding="utf-8"))
    return {entry["row_index"]: entry["stat_id"] for entry in payload.get("stats", [])}


# ============================================================================
# Convenience lookup helpers — saved scrolls so callers (especially AIs) don't
# have to know the internal JSON shape to do common filters.
#
# These are pure functions over the loaded data — no caching, no IO beyond the
# one load_*() call. Callers that need many lookups should load once and use
# the structures directly; these helpers are for one-shot use from MCP handlers
# and ad-hoc scripts.
# ============================================================================


def find_ascendancies_by_base_class(
    base_class: str,
    include_unused: bool = False,
) -> list:
    """Return all ascendancy entries whose base_class matches.

    Example:
        >>> find_ascendancies_by_base_class("Witch")
        [{"id": "Witch1", "display_name": "Infernalist", ...},
         {"id": "Witch2", "display_name": "Blood Mage", ...},
         {"id": "Witch3", "display_name": "Lich", ...},
         {"id": "Witch3b", "display_name": "Abyssal Lich", ...}]

    Args:
        base_class: Case-insensitive class name ("Witch", "monk", etc.).
        include_unused: If True, include [DNT-UNUSED] placeholder rows.
                        Default False — only PoE2-active ascendancies.

    Returns empty list if dataset isn't loaded yet or no matches.
    Relies on PR #78's base_class field; older revisions without that
    field will return empty.
    """
    payload = load_ascendancies()
    if not payload:
        return []
    target = base_class.lower()
    out = []
    for a in payload.get("ascendancies", []):
        if (a.get("base_class") or "").lower() != target:
            continue
        if not include_unused and a.get("is_unused"):
            continue
        out.append(a)
    return out


def find_mods_by_stat_id(
    stat_id: str,
    generation_type: Optional[str] = None,
    limit: int = 50,
) -> list:
    """Return mods whose stats include the given stat_id.

    Relies on PR #75's inline stat_id enrichment. Falls back to empty if the
    mods dataset doesn't have that field yet (older data revisions).

    Args:
        stat_id: Canonical stat identifier (e.g. 'additional_strength',
                 'base_life_regeneration_rate_per_second').
        generation_type: Optional filter — 'PREFIX', 'SUFFIX', 'IMPLICIT',
                         'CORRUPTED'. None = all types.
        limit: Cap on returned mods (sorted by level_requirement asc).
    """
    payload = load_mods()
    if not payload:
        return []
    target = stat_id.lower()
    out = []
    for mod in payload.get("mods", []):
        if generation_type and mod.get("generation_type_name") != generation_type:
            continue
        for s in mod.get("stats", []):
            if s.get("is_empty"):
                continue
            sid = s.get("stat_id")
            if sid and sid.lower() == target:
                out.append(mod)
                break
    out.sort(key=lambda m: m.get("level_requirement", 0))
    return out[:limit]


def find_mods_by_display_name(display_name_fragment: str, limit: int = 50) -> list:
    """Substring search across mod display_name (case-insensitive).

    Useful for "find the mod that grants X" queries when the user knows the
    suffix/prefix name (e.g. 'of the Newt') but not the stat_id.
    """
    payload = load_mods()
    if not payload:
        return []
    needle = display_name_fragment.lower()
    out = [m for m in payload.get("mods", []) if needle in (m.get("display_name") or "").lower()]
    out.sort(key=lambda m: m.get("level_requirement", 0))
    return out[:limit]


def get_keystones() -> list:
    """Return all keystone nodes from the passive tree.

    Each entry includes id, name, stats, and other passive-tree-node fields.
    Empty list if passive_tree dataset isn't loaded.
    """
    payload = load_passive_tree()
    if not payload:
        return []
    return [n for n in payload.get("nodes", {}).values() if n.get("is_keystone")]


def get_notables() -> list:
    """Return all notable nodes from the passive tree (excluding keystones)."""
    payload = load_passive_tree()
    if not payload:
        return []
    return [n for n in payload.get("nodes", {}).values() if n.get("is_notable") and not n.get("is_keystone")]


def find_keystone_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Look up a keystone by display name (case-insensitive exact match).

    Example:
        >>> find_keystone_by_name("Resolute Technique")
        {"id": "passive_keystone_resolute_technique", "name": "Resolute Technique", ...}
    """
    target = name.lower().strip()
    for k in get_keystones():
        if (k.get("name") or "").lower().strip() == target:
            return k
    return None


# ---------------------------------------------------------------------------
# stat_descriptions helpers (PR #98 dataset — 16,533 game-shipped stat texts)
# ---------------------------------------------------------------------------

# Cached single-load of the index + each per-file dataset on first lookup,
# because callers will often hit several stat_ids in one request and re-reading
# the 9 MB tree each time is wasteful. Cleared automatically when the underlying
# files change is NOT supported — assume process restart between data revisions.
_STAT_DESCRIPTIONS_CACHE: Dict[str, Any] = {}


def load_stat_descriptions_index() -> Optional[Dict[str, Any]]:
    """Load data/game/stat_descriptions/index.json.

    Returns the index dict with `files` (per-source-file metadata) and `totals`
    keys, or None if the dataset isn't installed yet. Lightweight (~5 KB) so
    safe to call repeatedly.
    """
    if not STAT_DESCRIPTIONS_INDEX.exists():
        return None
    if "_index" not in _STAT_DESCRIPTIONS_CACHE:
        _STAT_DESCRIPTIONS_CACHE["_index"] = json.loads(
            STAT_DESCRIPTIONS_INDEX.read_text(encoding="utf-8")
        )
    return _STAT_DESCRIPTIONS_CACHE["_index"]


def load_stat_descriptions_file(json_filename: str) -> Optional[Dict[str, Any]]:
    """Load one per-source stat_descriptions file by its JSON filename.

    `json_filename` is the value from the index's `files[<csd_name>].json_file`
    field (e.g. 'gem_stat_descriptions.json'). Cached per filename.
    """
    if not STAT_DESCRIPTIONS_DIR.exists():
        return None
    path = STAT_DESCRIPTIONS_DIR / json_filename
    if not path.exists():
        return None
    cache_key = f"file:{json_filename}"
    if cache_key not in _STAT_DESCRIPTIONS_CACHE:
        _STAT_DESCRIPTIONS_CACHE[cache_key] = json.loads(path.read_text(encoding="utf-8"))
    return _STAT_DESCRIPTIONS_CACHE[cache_key]


def find_stat_description(stat_id: str) -> Optional[Dict[str, Any]]:
    """Look up the canonical game-shipped description for a stat_id.

    Searches across all stat_descriptions files. Returns the matching description
    record (with stat_ids, primary_template, variants, source_line) plus a
    `source_file` field naming which .csd the entry came from. Useful for
    provenance display.

    Example:
        >>> r = find_stat_description("support_ignite_proliferation_radius")
        >>> r["primary_template"]
        'Ignites inflicted by Supported Skills Spread to other enemies...'
        >>> r["source_file"]
        'gem_stat_descriptions.json'

    Returns None if the dataset isn't installed OR the stat_id isn't documented
    (note: missing-in-dataset != missing-in-game — see `no_descriptions` on each
    file payload for stats GGG explicitly ships without display text).
    """
    target = stat_id.strip()
    if not target:
        return None
    index = load_stat_descriptions_index()
    if not index:
        return None
    for csd_name, info in (index.get("files") or {}).items():
        payload = load_stat_descriptions_file(info["json_file"])
        if not payload:
            continue
        for record in payload.get("descriptions") or []:
            if target in (record.get("stat_ids") or []):
                # Shallow-copy + tag with source so caller can display provenance
                out = dict(record)
                out["source_file"] = info["json_file"]
                out["source_csd"] = csd_name
                return out
    return None


def search_stat_descriptions(
    query: str,
    limit: int = 20,
    fields: tuple = ("stat_id", "template"),
) -> list:
    """Substring search across stat IDs and/or templates (case-insensitive).

    Returns a list of matching description records, each tagged with `source_file`
    and `match_field` indicating where the substring hit. Useful as the lookup
    layer for explain_mechanic("proliferation") — the user query doesn't have
    to be an exact stat_id.

    Args:
        query: substring to match against
        limit: cap on returned hits (default 20)
        fields: which sub-fields to search. Default both stat_id and template;
                pass ("stat_id",) for stat-id-only, ("template",) for prose-only.

    Returns empty list if dataset missing or no matches.
    """
    target = query.lower().strip()
    if not target:
        return []
    index = load_stat_descriptions_index()
    if not index:
        return []
    results: list = []
    for csd_name, info in (index.get("files") or {}).items():
        payload = load_stat_descriptions_file(info["json_file"])
        if not payload:
            continue
        for record in payload.get("descriptions") or []:
            match_field = None
            if "stat_id" in fields:
                for sid in record.get("stat_ids") or []:
                    if target in sid.lower():
                        match_field = "stat_id"
                        break
            if not match_field and "template" in fields:
                primary = record.get("primary_template") or ""
                if target in primary.lower():
                    match_field = "template"
            if match_field:
                out = dict(record)
                out["source_file"] = info["json_file"]
                out["source_csd"] = csd_name
                out["match_field"] = match_field
                results.append(out)
                if len(results) >= limit:
                    return results
    return results


def load_metadata(dataset_dir: Path) -> Optional[Dict[str, Any]]:
    """Load `metadata.json` from a dataset directory."""
    meta = dataset_dir / "metadata.json"
    if not meta.exists():
        return None
    try:
        return json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def describe() -> str:
    """Human-readable summary of what data is currently installed. Useful for
    health_check / diagnostic output."""
    v = get_version()
    if not v:
        return "data/game/ not populated yet — see README.md"
    lines = [
        f"PoE2 Patch {v.get('patch_version', '?')} "
        f"({v.get('patch_name', '?')}, released {v.get('patch_released', '?')})",
        f"Released as: {v.get('released_as', '?')}; data revision {v.get('data_revision', '?')}",
        f"Extracted: {v.get('extracted_at', '?')}",
    ]
    for ds, info in (v.get("datasets") or {}).items():
        lines.append(f"  - {ds}: {info.get('record_count', '?')} records at {info.get('path', '?')}")
    pending = v.get("datasets_pending_0_5_reextract") or {}
    if pending:
        lines.append(f"  pending re-extract: {', '.join(pending.keys())}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
