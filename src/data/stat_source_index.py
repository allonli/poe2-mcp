"""
Reverse stat-source index (field-feedback wishes, 2026-06-11).

Answers "which skill / passive node / ascendancy node / item mod grants
stat X" — the lookup the explain_mechanic substring search cannot do
(it finds stat_ids, but not what GRANTS them).

Sources (all local game data):
  - Skills: data/game/skill_gems/skill_gems_v2.json — statSets[].stats
    carry the stat_ids each skill's effect applies (1,249 skills).
  - Passive tree: data/psg_passive_nodes.json — node stat TEXT lines
    plus keystone/notable flags.
  - Ascendancy notables: data/complete_models/all_ascendancies.json —
    node name + stat TEXT. This file is a local-only legacy artifact
    (not tracked); the index degrades gracefully when absent.
  - Item mods: data/game/mods/mods.json — explicit stat_id per mod stat.

Index is built lazily on first query and cached for the process.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class StatSourceIndex:
    """Lazily-built reverse index from stat ids / stat text to sources."""

    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir is None:
            data_dir = Path(__file__).parent.parent.parent / "data"
        self.data_dir = Path(data_dir)
        self._built = False
        # stat_id -> sorted list of skill display names
        self._skill_index: Dict[str, List[str]] = {}
        # stat_id -> list of {mod_id, display_name, generation_type}
        self._mod_index: Dict[str, List[Dict[str, Any]]] = {}
        # passive nodes: {name, kind, stats(list of text lines)}
        self._passive_nodes: List[Dict[str, Any]] = []
        # ascendancy notables: {ascendancy, base_class, name, stats}
        self._ascendancy_nodes: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _ensure_built(self):
        if self._built:
            return
        self._built = True
        self._build_skill_index()
        self._build_mod_index()
        self._build_passive_nodes()
        self._build_ascendancy_nodes()
        logger.info(
            f"StatSourceIndex built: {len(self._skill_index)} skill stat_ids, "
            f"{len(self._mod_index)} mod stat_ids, "
            f"{len(self._passive_nodes)} passive nodes, "
            f"{len(self._ascendancy_nodes)} ascendancy notables"
        )

    def _build_skill_index(self):
        path = self.data_dir / "game" / "skill_gems" / "skill_gems_v2.json"
        if not path.exists():
            logger.warning(f"StatSourceIndex: {path} missing — no skill sources")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"StatSourceIndex: failed to read {path}: {e}")
            return
        index: Dict[str, set] = {}
        for skill_id, skill in (data.get("skills") or {}).items():
            if not isinstance(skill, dict):
                continue
            name = skill.get("name") or skill_id
            for stat_set in (skill.get("statSets") or []):
                if not isinstance(stat_set, dict):
                    continue
                for stat_id in (stat_set.get("stats") or []):
                    index.setdefault(stat_id, set()).add(name)
        self._skill_index = {k: sorted(v) for k, v in index.items()}

    def _build_mod_index(self):
        path = self.data_dir / "game" / "mods" / "mods.json"
        if not path.exists():
            logger.warning(f"StatSourceIndex: {path} missing — no mod sources")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"StatSourceIndex: failed to read {path}: {e}")
            return
        mods = data.get("mods") or []
        if isinstance(mods, dict):
            mods = list(mods.values())
        for mod in mods:
            if not isinstance(mod, dict):
                continue
            entry = {
                "mod_id": mod.get("mod_id"),
                "display_name": mod.get("display_name"),
                "generation_type": mod.get("generation_type_name"),
            }
            for stat in (mod.get("stats") or []):
                stat_id = stat.get("stat_id") if isinstance(stat, dict) else None
                if stat_id:
                    self._mod_index.setdefault(stat_id, []).append(entry)

    def _build_passive_nodes(self):
        path = self.data_dir / "psg_passive_nodes.json"
        if not path.exists():
            logger.warning(f"StatSourceIndex: {path} missing — no passive sources")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"StatSourceIndex: failed to read {path}: {e}")
            return
        for node in data.values():
            if not isinstance(node, dict):
                continue
            stats = node.get("stats") or []
            name = node.get("name")
            if not stats or not name:
                continue
            if node.get("is_keystone"):
                kind = "keystone"
            elif node.get("is_notable"):
                kind = "notable"
            elif node.get("is_ascendancy"):
                kind = "ascendancy"
            else:
                kind = "small"
            self._passive_nodes.append(
                {"name": name, "kind": kind, "stats": stats}
            )

    def _build_ascendancy_nodes(self):
        # Legacy local-only artifact — see module docstring. Optional.
        path = self.data_dir / "complete_models" / "all_ascendancies.json"
        if not path.exists():
            logger.info(
                f"StatSourceIndex: {path} missing (untracked legacy file) — "
                f"ascendancy sources unavailable in this checkout"
            )
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"StatSourceIndex: failed to read {path}: {e}")
            return
        for asc_name, rec in (data.get("ascendancies") or {}).items():
            if not isinstance(rec, dict):
                continue
            nodes = rec.get("notable_nodes") or {}
            if isinstance(nodes, dict):
                nodes = list(nodes.values())
            for node in nodes:
                if not isinstance(node, dict) or not node.get("name"):
                    continue
                self._ascendancy_nodes.append({
                    "ascendancy": asc_name,
                    "base_class": rec.get("base_class"),
                    "name": node["name"],
                    "stats": node.get("stats") or [],
                })

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def find_sources(self, query: str, limit_per_source: int = 15) -> Dict[str, Any]:
        """
        Find everything that grants/references a stat.

        Args:
            query: A stat_id, stat_id substring, or stat text fragment
                (e.g. "withered", "spell_minimum_base_fire_damage",
                "chance to Shock").
            limit_per_source: Cap per source category.

        Returns:
            {
              "query": ...,
              "skills": {stat_id: [skill names]},         # id-substring match
              "mods": {stat_id: [mod entries]},           # id-substring match
              "passive_nodes": [node entries],            # text/name match
              "ascendancy_nodes": [node entries],         # text/name match
              "ascendancy_data_available": bool,
            }
        """
        self._ensure_built()
        q = (query or "").lower().strip()
        result: Dict[str, Any] = {
            "query": query,
            "skills": {},
            "mods": {},
            "passive_nodes": [],
            "ascendancy_nodes": [],
            "ascendancy_data_available": bool(self._ascendancy_nodes),
        }
        if not q:
            return result

        skill_hits = 0
        for stat_id, skills in self._skill_index.items():
            if q in stat_id.lower():
                result["skills"][stat_id] = skills[:limit_per_source]
                skill_hits += 1
                if skill_hits >= limit_per_source:
                    break

        mod_hits = 0
        for stat_id, mods in self._mod_index.items():
            if q in stat_id.lower():
                # Dedupe by display name, keep first occurrence
                seen = set()
                unique = []
                for m in mods:
                    key = (m.get("display_name"), m.get("generation_type"))
                    if key not in seen:
                        seen.add(key)
                        unique.append(m)
                result["mods"][stat_id] = unique[:limit_per_source]
                mod_hits += 1
                if mod_hits >= limit_per_source:
                    break

        for node in self._passive_nodes:
            if q in node["name"].lower() or any(
                q in s.lower() for s in node["stats"]
            ):
                result["passive_nodes"].append(node)
                if len(result["passive_nodes"]) >= limit_per_source:
                    break

        for node in self._ascendancy_nodes:
            if q in node["name"].lower() or any(
                q in s.lower() for s in node["stats"]
            ):
                result["ascendancy_nodes"].append(node)
                if len(result["ascendancy_nodes"]) >= limit_per_source:
                    break

        return result

    def skills_granting_stat(self, stat_id: str) -> List[str]:
        """Exact stat_id -> skill names (empty when none)."""
        self._ensure_built()
        return self._skill_index.get(stat_id, [])


_INSTANCE: Optional[StatSourceIndex] = None


def get_stat_source_index() -> StatSourceIndex:
    """Process-wide singleton accessor (index build is lazy)."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = StatSourceIndex()
    return _INSTANCE
