# `skill_gems` Extractor Port — Audit

Status: **scout-only** (no extractor changes yet). This doc captures what the `data/game/skill_gems/` extractor port needs to do, based on a survey of (1) PoB2 upstream's current 0.5 data on `origin/dev` and (2) the existing pre-0.5 extractor in this repo.

Sets up future-fire deliverables. Not a spec — a working contributor (human or AI) should be able to start coding from this.

---

## 1. Why this port is needed

`data/game/skill_gems/` is the only `data/game/` dataset still pending — see `version.json::datasets_pending_0_5_reextract.skill_gems`. Until it ships, MCP skill-gem tools (`inspect_spell_gem`, `list_all_spells`) read from `data/pob_active_skills.json` (Dec 2025 extraction, pre-0.5).

Was blocked on PoB2 community shipping 0.5 data. **Confirmed unblocked 2026-05-31**:
- `src/Data/Gems.lua` last touched 2026-05-29 04:10 (patch day) — commit `9c93232fb [0.5] Add legacy toggle for gems that are no longer obtainable`
- `src/Data/Skills/*.lua` last touched 2026-05-30 in `8a475b4fe Release 0.16.0`
- Both files have continuous 0.5-era commit history; this is real 0.5 data, not stale leftover.

## 2. PoB2 upstream data shape (what we read FROM)

### `src/Data/Gems.lua`

Single auto-generated Lua file. 18,329 lines, ~459 KB.

```lua
return {
    ["Metadata/Items/Gems/SkillGemIceNova"] = {
        name = "Ice Nova",
        baseTypeName = "Ice Nova",
        gameId = "Metadata/Items/Gems/SkillGemIceNova",
        variantId = "IceNova",
        grantedEffectId = "IceNovaPlayer",           -- <-- joins to Skills/*.lua
        additionalStatSet1 = "IceNovaPlayerOnFrostbolt",
        additionalStatSet2 = "IceNovaColdInfusedPlayer",
        tags = { intelligence = true, grants_active_skill = true, spell = true,
                 area = true, cold = true, duration = true, nova = true, },
        gemType = "Spell",
        tagString = "AoE, Cold, Duration, Nova",
        reqStr = 0, reqDex = 0, reqInt = 100,
        Tier = 1,
        naturalMaxLevel = 20,
    },
    ...
}
```

Per-entry fields: `name`, `baseTypeName`, `gameId`, `variantId`, `grantedEffectId`, optional `additionalStatSet1/2`, `tags` (set as map), `gemType`, `tagString`, optional `weaponRequirements`, `reqStr`/`reqDex`/`reqInt`, `Tier`, `naturalMaxLevel`. Some attack gems also carry `weaponRequirements = "One Hand Mace, Two Hand Mace"` etc.

Approximate entry count: `grep -c SkillGem` returns 1,216 hits — counts references too, so actual entry count is somewhat lower but in the same ballpark. Verified during the actual extraction.

### `src/Data/Skills/*.lua`

9 files, partitioned by skill class:
- `act_dex.lua` / `act_int.lua` / `act_str.lua` — active skill effects by primary attribute
- `sup_dex.lua` / `sup_int.lua` / `sup_str.lua` — support skill effects by primary attribute
- `minion.lua`, `other.lua`, `spectre.lua` — special-case skill tables

Each file starts with `local skills, mod, flag, skill = ...` and assigns into the shared `skills` table:

```lua
skills["ArcPlayer"] = {
    name = "Arc",
    baseTypeName = "Arc",
    icon = "Art/2DArt/SkillIcons/SorceressArc.dds",
    color = 3,
    description = "An arc of Lightning ...",
    skillTypes = { [SkillType.Spell] = true, [SkillType.Projectile] = true, ... },
    castTime = 1.1,
    qualityStats = { { "number_of_chains", 0.1 }, },
    levels = {
        [1] = { PvPDamageMultiplier = -25, critChance = 9, levelRequirement = 0,
                cost = { Mana = 8, }, },
        ...
        [40] = { ... },
    },
    statSets = {
        [1] = {
            label = "Arc",
            baseEffectiveness = 1.75,
            incrementalEffectiveness = 0.12999999523163,
            damageIncrementalEffectiveness = 0.0082000000402331,
            statDescriptionScope = "skill_stat_descriptions",
            statMap = { ["arc_damage_+%_final_for_each_remaining_chain"] = { mod(...), }, },
            baseFlags = { spell = true, chaining = true, projectile = true, },
            constantStats = { { "arc_damage_+%_final_from_infusion_consumption", 200 }, ... },
            stats = { "spell_minimum_base_lightning_damage", "spell_maximum_base_lightning_damage", ... },
        },
    },
}
```

`act_int.lua` alone is 22,316 lines. `levels` typically goes to `[40]`; `statSets` may have `[2]`, `[3]`, ... for skills with multiple stat sets (referenced by Gems.lua's `additionalStatSet1/2`).

**Join key**: `Gems.lua[<gemMetadata>].grantedEffectId` matches `Skills/*.lua[<grantedEffectId>]`.

## 3. Existing extractor — `scripts/extract_complete_pob_skills.py`

Status: present locally, gitignored under `.gitignore`'s `scripts/extract_*.py` rule.

What it currently does:
- Reads `src/Data/Skills/*.lua` (NOT `Gems.lua`)
- Regex-parses Lua tables (`parse_lua_value`, `extract_levels_table`, etc.)
- Outputs `data/pob_complete_skills.json` (tracked):

  ```json
  {
    "metadata": {
      "source": "Path of Building",
      "extraction_date": "2025-12-13",
      "total_skills": 1066,
      "skills_with_levels": 1066,
      "skills_with_statsets": 1064
    },
    "skills": {
      "ArcPlayer": {
        "id": "ArcPlayer",
        "name": "Arc",
        "description": "...",
        "color": 3, "castTime": 1.1,
        "skillTypes": [...], "weaponTypes": [...],
        "qualityStats": [...],
        "levels": {...},
        "statSets": [...]
      },
      ...
    }
  }
  ```

- 1,066 skills extracted as of 2025-12-13 (pre-0.5).

## 4. Gap analysis — what the port has to add

| Gap | Current state | Port deliverable |
|---|---|---|
| **Missing gem-metadata layer** | Extractor reads only `Skills/*.lua` (effect data). Misses `Gems.lua` (tags, Tier, requirements, naturalMaxLevel, weaponRequirements). | Read `Gems.lua` too. Join via `grantedEffectId`. Output one record per gem (not per effect). |
| **Output location** | Writes `data/pob_complete_skills.json` (legacy path). | Write `data/game/skill_gems/skill_gems.json` per the canonical layout. |
| **Missing `metadata.json`** | Inline `metadata` envelope inside the data file. | Separate `data/game/skill_gems/metadata.json` matching the convention used by mods/ascendancies/stats (dataset, filename, patch_version, extracted_at, source_file, source_bytes, source_row_count, extractor, record_count, sha256, schema_notes). |
| **`version.json` registration** | Listed only under `datasets_pending_0_5_reextract`. | Move into `datasets`, drop the pending entry, bump `data_revision`, set new `released_as`. |
| **Pre-0.5 data** | Extraction date 2025-12-13. | Re-run against PoB2 `origin/dev` HEAD post-2026-05-29. |
| **No 0.5 Gems.lua awareness** | Doesn't know about 0.5 additions (e.g. the "legacy toggle for gems no longer obtainable" from PoB2 commit `9c93232fb`). | Decide whether to surface `legacy=true` field or filter legacy gems entirely. Recommend surface-with-flag so consumers can decide. |

## 5. Recommended output schema

```json
{
  "schema_version": 1,
  "skill_gems": [
    {
      "gem_id": "Metadata/Items/Gems/SkillGemIceNova",
      "variant_id": "IceNova",
      "name": "Ice Nova",
      "base_type_name": "Ice Nova",
      "gem_type": "Spell",
      "tier": 1,
      "natural_max_level": 20,
      "requirements": { "str": 0, "dex": 0, "int": 100 },
      "weapon_requirements": null,
      "tags": ["intelligence", "grants_active_skill", "spell", "area", "cold", "duration", "nova"],
      "tag_string": "AoE, Cold, Duration, Nova",
      "granted_effect": {
        "effect_id": "IceNovaPlayer",
        "skill_types": [...],
        "cast_time": 0.6,
        "quality_stats": [...],
        "levels": { "1": {...}, ..., "40": {...} },
        "stat_sets": [ {...}, {...} ]
      },
      "additional_stat_sets": ["IceNovaPlayerOnFrostbolt", "IceNovaColdInfusedPlayer"],
      "legacy": false
    },
    ...
  ]
}
```

- Snake_case keys throughout (consistent with other `data/game/` datasets).
- One record per gem (joined view), not per effect.
- `granted_effect` embeds the joined `Skills/*.lua` payload — consumers don't need a second file.
- `additional_stat_sets` lists effect IDs (not embedded data) — those would each have their own gem record with the same effect, so embedding would balloon the file.
- `legacy: bool` based on whatever flag the 0.5 PoB2 toggle exposes.

## 6. Open questions for the port

1. **How does the 0.5 "legacy toggle" surface in Lua?** Need to read `9c93232fb` to find whether it's a per-gem field, a separate file, or a runtime config. Drives schema decision on the `legacy` field.
2. **Do `additional_stat_sets` correspond to alternative-quality variants?** If yes, they need their own first-class representation. If no (just stat aliasing), the current "list of IDs" approach is fine.
3. **Stat-set value cleanup.** PoB2 floats like `0.12999999523163` are clearly de-IEEE'd values — round to a sane number of decimals (4? 6?) before serializing or carry verbatim?
4. **MCP-side migration.** Once `skill_gems.json` ships, `inspect_spell_gem` / `list_all_spells` need rewiring. That's a `src/mcp_server.py` change — currently in the WIP bucket, so will need stash-isolation discipline when the time comes.

## 7. Port size estimate

- Extractor changes: ~150-300 lines (add `Gems.lua` parser, join logic, output reshape, metadata.json emission). Bulk of the existing regex-based Lua parser is reusable.
- Data file size: rough projection from current `pob_complete_skills.json` (~few MB) + gem metadata overhead ≈ 5-10 MB.
- `version.json` update: trivial.
- README/eval-doc updates: small.

Realistic single-fire deliverable if no surprises. Could land in 2-3 stacked PRs (extractor port → ship data → MCP rewiring) since the MCP rewiring touches files currently in queue/WIP.

---

## See also

- `docs/EXTRACTION_PIPELINE.md` — general pipeline shape (PR #84)
- `data/game/version.json` — `datasets_pending_0_5_reextract.skill_gems` block
- `data/game/README.md` — current 0.5 status table
- `scripts/extract_complete_pob_skills.py` — existing extractor (gitignored)
- PoB2 upstream: `src/Data/Gems.lua`, `src/Data/Skills/*.lua`
