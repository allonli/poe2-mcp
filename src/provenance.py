"""
Provenance banner helper for MCP responses.

Every numeric or fact-claim response from the MCP should carry a small
trailing block telling the caller:
  1. WHICH data version produced the number (data_revision from
     data/game/version.json).
  2. WHEN it was extracted (so a caller can detect "this is from before
     last patch").
  3. WHAT TIER it has — was it pulled from canonical game files, derived
     via a formula, hand-authored from community sources, or fetched from
     an external service like poe.ninja?

The goal: AI assistants stop quoting wiki numbers as if they came from
the game. Whether the assistant cites a number with confidence depends
on the tier the MCP attached to it.

Lives in its own light-weight module so test files and any handler can
import it without triggering full mcp_server initialization.
"""

from __future__ import annotations

from typing import Optional

# Tier vocabulary — keep stable; downstream tooling reads these.
CANONICAL = "canonical"       # Extracted directly from .datc64 / .csd game files.
COMPUTED = "computed"         # Derived via a documented formula from canonical inputs.
INTERPRETED = "interpreted"   # Hand-authored / wiki-derived summary.
EXTERNAL = "external"         # Live data from poe.ninja / trade API / similar.

_TIER_NOTES = {
    INTERPRETED: (
        "Warning: Hand-authored summary - verify against the in-game tooltip "
        "for balance-sensitive numbers."
    ),
    EXTERNAL: (
        "Note: Live external source - depends on its uptime + indexer recency. "
        "Numbers may shift between calls."
    ),
}


def _load_version_metadata() -> dict:
    """Read data/game/version.json. Returns {} on failure (e.g. import or
    file errors) so callers never crash on banner construction."""
    try:
        try:
            from .data.game_data import get_version
        except ImportError:
            from src.data.game_data import get_version
        return get_version() or {}
    except Exception:
        return {}


def format_banner(
    tier: str,
    source: Optional[str] = None,
    version: Optional[str] = None,
    extracted_at: Optional[str] = None,
) -> str:
    """Return a formatted footer block for an MCP response.

    Args:
        tier: One of CANONICAL / COMPUTED / INTERPRETED / EXTERNAL. Free-form
            strings are accepted (printed verbatim) but tooling expects the
            canonical vocabulary above.
        source: Optional path or URL identifying where this number lives
            (e.g. "data/game/passive_tree/tree.json", "poe.ninja/api/...").
            Surfaces in the banner so a future audit knows what to re-check.
        version: Override the version string. Defaults to the
            released_as field from data/game/version.json.
        extracted_at: Override the extraction timestamp. Defaults to the
            extracted_at field from data/game/version.json.

    Returns:
        A multi-line string ready to append (with a leading newline) to any
        response. Format:

            ---
            **Data**: data-v0.5.0-r8 (extracted 2026-05-31T20:30:00Z) | **Tier**: canonical
            **Source**: data/game/passive_tree/tree.json

        Tier-specific warning lines added automatically for INTERPRETED and
        EXTERNAL. All characters are ASCII-safe (no Unicode separators or
        emojis) so the banner round-trips through Windows cp1252 terminals
        and log files without encoding errors.
    """
    if version is None or extracted_at is None:
        meta = _load_version_metadata()
        if version is None:
            version = meta.get("released_as", "unknown")
        if extracted_at is None:
            extracted_at = meta.get("extracted_at", "?")

    lines = [
        "---",
        f"**Data**: {version} (extracted {extracted_at}) | **Tier**: {tier}",
    ]
    if source:
        lines.append(f"**Source**: {source}")
    note = _TIER_NOTES.get(tier)
    if note:
        lines.append(note)
    return "\n".join(lines)
