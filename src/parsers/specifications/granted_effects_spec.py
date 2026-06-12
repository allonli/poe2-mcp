"""
GrantedEffects / GrantedEffectsPerLevel .datc64 spec (campaign C1, fires 7-12).

Reverse-engineered layout, verified against the 0.5 extraction
(grantedeffects: 8,339 x 297B; grantedeffectsperlevel: 34,169 x 116B):

grantedeffects.datc64 row:
    @0   u64  id-string ref (offset into variable section, relative to
               the 0xBB-magic position; string is UTF-16LE)

grantedeffectsperlevel.datc64 row (116 bytes):
    @0   u32  GrantedEffects row index (foreign key)
    @16  u32  gem level (1..40)
    @100 u64  cost pointer: byte offset into the variable section
               (relative to the 0xBB-magic position) of this level's
               cost-amount array. The pool is DEDUPLICATED across
               effects: levels sharing a cost value share a pointer
               (verified cross-skill: ptr 12 -> 10 mana for both
               Essence Drain L5 and Fireball L1). The first u32 at the
               target is the level's primary cost amount.
    @108 f32  per-level effectiveness multiplier (1.0 at L1)

Known limitations (documented, by design):
  - Cost TYPE is not decoded here (the cost-types linkage lives
    elsewhere); callers should treat the amount as the skill's primary
    cost in its native type (Mana for the overwhelming majority).
  - Spirit reservations are NOT in this table (verified: meta gems'
    cost pointers are degenerate) - reservation values remain sourced
    from the PoB-derived dataset with provenance noted.

The PoB2 clone serves as reconciliation ORACLE for this spec - see
tests/test_granted_effects_spec.py for the full-corpus delta check.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Dict, Optional

MAGIC = b"\xbb" * 8

GEPL_FK_OFFSET = 0
GEPL_LEVEL_OFFSET = 16
GEPL_COST_PTR_OFFSET = 100
GEPL_EFFECTIVENESS_OFFSET = 108


class GrantedEffectsTables:
    """Parsed view over grantedeffects + grantedeffectsperlevel."""

    def __init__(self, balance_dir: Path):
        self.balance_dir = Path(balance_dir)
        self._ge: Optional[bytes] = None
        self._gepl: Optional[bytes] = None
        self._effect_rows: Optional[Dict[str, int]] = None
        self._loaded = False

    # -- table plumbing ----------------------------------------------------

    @staticmethod
    def _geometry(data: bytes):
        row_count = struct.unpack_from("<I", data, 0)[0]
        magic_pos = data.find(MAGIC)
        if magic_pos < 4 or row_count == 0:
            raise ValueError("not a datc64 table (no magic / zero rows)")
        row_size, rem = divmod(magic_pos - 4, row_count)
        if rem:
            raise ValueError(
                f"irregular geometry: {magic_pos - 4} fixed bytes / "
                f"{row_count} rows leaves remainder {rem}"
            )
        return row_count, row_size, magic_pos

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._ge = (self.balance_dir / "grantedeffects.datc64").read_bytes()
        self._gepl = (self.balance_dir / "grantedeffectsperlevel.datc64").read_bytes()
        self._loaded = True

    # -- grantedeffects: id -> row index ------------------------------------

    def effect_rows(self) -> Dict[str, int]:
        """Map every effect id string to its grantedeffects row index.

        Row column 0 is a u64 ref to the id string (UTF-16LE), relative
        to the magic position. Built once by walking all rows and
        reading each id - O(rows), no scanning.
        """
        self._ensure_loaded()
        if self._effect_rows is not None:
            return self._effect_rows
        ge = self._ge
        row_count, row_size, magic_pos = self._geometry(ge)
        out: Dict[str, int] = {}
        for i in range(row_count):
            ref = struct.unpack_from("<Q", ge, 4 + i * row_size)[0]
            start = magic_pos + ref
            end = ge.find(b"\x00\x00", start)
            # UTF-16LE terminator alignment: ensure even length
            if (end - start) % 2:
                end += 1
            try:
                effect_id = ge[start:end].decode("utf-16-le", errors="strict")
            except (UnicodeDecodeError, ValueError):
                continue
            if effect_id:
                out[effect_id] = i
        self._effect_rows = out
        return out

    # -- grantedeffectsperlevel: per-level cost extraction -------------------

    def per_level_costs(self) -> Dict[int, Dict[int, int]]:
        """{effect_row_index: {level: cost_amount}} for every GEPL row.

        Cost amount is the first u32 of the deduplicated cost array the
        row's @100 pointer targets. Rows whose pointer is 0 or out of
        bounds are skipped (no-cost levels).
        """
        self._ensure_loaded()
        g = self._gepl
        row_count, row_size, magic_pos = self._geometry(g)
        var_size = len(g) - magic_pos
        out: Dict[int, Dict[int, int]] = {}
        for i in range(row_count):
            base = 4 + i * row_size
            fk = struct.unpack_from("<I", g, base + GEPL_FK_OFFSET)[0]
            level = struct.unpack_from("<I", g, base + GEPL_LEVEL_OFFSET)[0]
            ptr = struct.unpack_from("<Q", g, base + GEPL_COST_PTR_OFFSET)[0]
            if not (0 < ptr < var_size - 4) or not (1 <= level <= 60):
                continue
            cost = struct.unpack_from("<I", g, magic_pos + ptr)[0]
            out.setdefault(fk, {})[level] = cost
        return out

    def costs_by_effect_id(self) -> Dict[str, Dict[int, int]]:
        """{effect_id_string: {level: cost_amount}} - the joined view."""
        rows = self.effect_rows()
        costs = self.per_level_costs()
        return {
            effect_id: costs[row]
            for effect_id, row in rows.items()
            if row in costs
        }


def load_granted_effects(extracted_root: Path | str) -> GrantedEffectsTables:
    """Convenience constructor from the extraction root
    (e.g. data/extracted -> data/extracted/data/balance)."""
    root = Path(extracted_root)
    balance = root / "data" / "balance"
    if not balance.exists():
        balance = root / "Data" / "balance"
    return GrantedEffectsTables(balance)
