"""
Damage-type / skill-tag conflict detection for support gem validation.

Lives in its own light-weight module (no SQLAlchemy / no DatabaseManager
imports) so the rules + helpers can be unit-tested without paying the
gem_synergy_calculator module-load cost. Issue #117.

The flow:
  * SUPPORT_DAMAGE_REQUIREMENTS maps a name-pattern (substring of a support
    gem's display name) to a list of skill tags. The support is "useful"
    on a spell if at least ONE of the listed tags appears in the spell's
    own tag set.
  * support_required_tags(name) does the lookup.
  * lookup_spell_tags(spell_name) reads tags from
    data/game/skill_gems/skill_gems.json.
  * check_semantic_conflicts(...) ties them together and returns a list of
    warning dicts ready to surface in MCP responses.

This is name-pattern-inferred because the canonical .datc64-extracted
support_gems records do not carry damage-type metadata themselves
(compatible_with is uniformly ['spell','attack'] across all 680 records,
tags is empty — verified 2026-06-01). When/if a richer extractor lands,
this module is the single place to swap pattern-matching for data-driven.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Maps lower-case substring pattern -> list of acceptable spell tags.
# When a support's name contains pattern P, the target spell must have at
# least one of the tags from SUPPORT_DAMAGE_REQUIREMENTS[P], or the support
# is wasted.
SUPPORT_DAMAGE_REQUIREMENTS: Dict[str, List[str]] = {
    # Added flat damage supports
    "added fire damage": ["fire", "attack"],
    "added cold damage": ["cold", "attack"],
    "added lightning damage": ["lightning", "attack"],
    "added chaos damage": ["chaos", "attack"],
    "added physical damage": ["physical", "attack"],
    # Element-tagged supports
    "fire mastery": ["fire"],
    "cold mastery": ["cold"],
    "lightning mastery": ["lightning"],
    "pyromaniac": ["fire"],
    "cryomancer": ["cold"],
    "electromancer": ["lightning"],
    # Minion-only supports
    "minion damage": ["minion"],
    "minion speed": ["minion"],
    "minion instability": ["minion"],
    "minion pact": ["minion"],
    "feeding frenzy": ["minion"],
    "meat shield": ["minion"],
    # Skill-shape supports
    "melee damage": ["melee"],
    "melee splash": ["melee"],
    "brutality": ["physical"],
    # Projectile-shape supports
    "fork": ["projectile"],
    "chain": ["projectile"],
    "pierce": ["projectile"],
    "scattershot": ["projectile"],
    "lesser multiple projectiles": ["projectile"],
    "greater multiple projectiles": ["projectile"],
    "additional accuracy": ["projectile", "attack"],
    # Ailment supports
    "ignite proliferation": ["fire"],
    "rapid infusion": ["cold"],
    "swift affliction": ["duration"],
}


def support_required_tags(support_name: str) -> List[str]:
    """Pattern-match a support name against SUPPORT_DAMAGE_REQUIREMENTS.

    Returns the list of acceptable spell tags (any-of) for the support, or
    [] when the support has no registered semantic requirement.
    """
    lower = support_name.lower().replace(" support", "")
    for pattern, tags in SUPPORT_DAMAGE_REQUIREMENTS.items():
        if pattern in lower:
            return list(tags)
    return []


def _skill_gems_path() -> Path:
    """data/game/skill_gems/skill_gems.json — resolves to the in-repo file."""
    # src/optimizer/support_validation.py  ->  <repo root>
    return (
        Path(__file__).resolve().parent.parent.parent
        / "data" / "game" / "skill_gems" / "skill_gems.json"
    )


def lookup_spell_tags(spell_name: str) -> Optional[List[str]]:
    """Read a spell's tags from data/game/skill_gems/skill_gems.json.

    Returns None if the file is missing or the spell can't be resolved —
    callers should treat that as "skip the semantic check" rather than an
    error.
    """
    f = _skill_gems_path()
    if not f.exists():
        return None
    try:
        with open(f, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as e:
        logger.warning(f"Failed to read skill_gems.json: {e}")
        return None

    needle = spell_name.strip().lower()
    for gem in data.get("skill_gems", []):
        name = (gem.get("name") or "").lower()
        gid = (gem.get("gem_id") or "").lower()
        if needle == name or needle == gid or needle in name:
            return list(gem.get("tags") or [])
    return None


def check_semantic_conflicts(
    support_names: List[str],
    spell_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the semantic-conflict check across a list of supports.

    Returns:
        {
            "warnings": [
                {
                    "support": <support name>,
                    "spell": <spell name>,
                    "required_any_of": [<tag>, ...],
                    "spell_tags": [<tag>, ...],
                    "message": <human-readable>,
                },
                ...
            ],
            "spell_tags": [<tag>, ...] | None,  # spell tags resolved
        }

    Empty warnings list when spell_name is None, when the spell can't be
    resolved, or when every support's requirement intersects the spell's tags.
    """
    if not spell_name:
        return {"warnings": [], "spell_tags": None}

    spell_tags = lookup_spell_tags(spell_name)
    if spell_tags is None:
        return {"warnings": [], "spell_tags": None}

    warnings: List[Dict[str, Any]] = []
    for support in support_names:
        needed = support_required_tags(support)
        if needed and not any(tag in spell_tags for tag in needed):
            warnings.append({
                "support": support,
                "spell": spell_name,
                "required_any_of": needed,
                "spell_tags": spell_tags,
                "message": (
                    f"{support} requires the spell to have at least one of "
                    f"{needed}; {spell_name} has tags {spell_tags}. No "
                    f"overlap - support effect is likely wasted unless "
                    f"you're converting damage types via another mechanic."
                ),
            })
    return {"warnings": warnings, "spell_tags": spell_tags}
