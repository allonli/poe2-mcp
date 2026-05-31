# AI Assistant Guide

How to use the poe2-mcp server effectively from an AI client (Claude, ChatGPT, Cursor, Windsurf, etc.). Targeted at the LLM doing the tool-calling — not at the human end-user.

If you're an LLM with this file in your context: **read top to bottom once**. The rest of the repo's docs are deeper but this one tells you the shape of the surface area and the gotchas that aren't obvious from tool schemas alone.

---

## 1. What this MCP actually gives you

You get **40 tools** (as of 2026-05-31) split into a handful of surfaces:

| Surface | Tools (representative, not exhaustive) | Underlying data |
|---|---|---|
| Character analysis | `analyze_character`, `import_poe_ninja_url`, `compare_to_top_players`, `analyze_passive_tree` | poe.ninja JSON API (live) + local resolvers |
| Passive tree data | `inspect_passive_node`, `inspect_keystone`, `list_all_keystones`, `list_all_notables` | `data/game/passive_tree/` (extracted .datc64) |
| Gem inspection | `inspect_spell_gem`, `inspect_support_gem`, `list_all_spells`, `list_all_supports`, `validate_support_combination` | `data/game/skill_gems/` (PoB2 0.5, since PR #91) + `data/game/support_gems/` (extracted .datc64). Legacy `data/pob_complete_skills.json` used as Tier-2 fallback when a spell isn't yet in the new dataset. |
| Item mods | `inspect_mod`, `list_all_mods`, `search_mods_by_stat`, `get_mod_tiers`, `validate_item_mods`, `get_available_mods`, `list_all_base_items`, `inspect_base_item` | `data/game/mods/` + `data/game/stats/` (extracted) |
| Ascendancy | `get_ascendancy_info` | `data/game/ascendancies/` |
| Knowledge | `explain_mechanic`, `get_formula` | Hardcoded `src/knowledge/poe2_mechanics.py` |
| Path of Building | `import_pob`, `export_pob`, `get_pob_code` (file-based) + 8 `pob_*` tools (live bridge) | PoB XML format / local TCP socket on :49085 |
| Self-diagnostic | `health_check`, `check_tree_freshness`, `clear_cache` | Mixed |

**The MCP is the data layer. You are the intelligence layer.** It doesn't synthesize advice — it returns facts. Build the user-facing reasoning yourself.

## 2. Parameter naming — the alias quirk

Most tools accept the canonical typed-noun parameter name (`keystone_name`, `spell_name`, `support_gems`). After the May 2026 MCP accuracy evaluation, **three tools also accept short aliases** because LLMs frequently guessed those:

| Tool | Canonical | Also accepted |
|---|---|---|
| `inspect_keystone` | `keystone_name` | `name` |
| `inspect_spell_gem` | `spell_name` | `name`, `gem_name` |
| `validate_support_combination` | `support_gems` (array) | `support_gem_names`, `names` |

For all other tools, **use the exact canonical name from the schema**. The MCP layer validates `required` fields before the handler runs, so `name` won't work for tools that haven't been alias-enabled.

When in doubt: check the tool's `inputSchema.properties` keys. The `required` array tells you which ones are mandatory.

## 3. Game data sources — what's authoritative

This MCP enforces a strict data policy (see `CLAUDE.md` "Data Source Policy"):

1. **All game-mechanics data comes from extracted `.datc64` files** — Patch 0.5 fresh data lives in `data/game/{dataset}/`:
   - `data/game/mods/mods.json` — 16,788 item mods (PREFIX/SUFFIX/IMPLICIT/CORRUPTED + 9 monster-mod buckets). Each stat entry includes a resolved `stat_id` inline.
   - `data/game/passive_tree/tree.json` — 9,605 nodes (82 keystones, 2,151 notables, 332 mastery effects).
   - `data/game/support_gems/support_gems.json` — 680 support gems with effect stats.
   - `data/game/ascendancies/ascendancies.json` — 37 classes (23 active, including NEW 0.5 Spirit Walker + Martial Artist), with `base_class` field for filtering.
   - `data/game/stats/stats.json` — 26,943 canonical stat IDs (the `{row_index → stat_id}` lookup that mods/passives/gems all reference).
2. **poe.ninja is allowed ONLY for character/build data** — not for game mechanics. This is what character analysis tools use.
3. **NEVER search wikis, poedb, or third-party scraped sources.** If a tool returns "no data" for a game-mechanics query, it's a real gap to file as a bug — not a cue to fetch from the web.

The `check_tree_freshness` tool tells you whether your local `data/game/` is current with the live patch poe.ninja is serving.

## 4. Known failure modes (don't waste user cycles on these)

### CRITICAL #4: poe.ninja SPA migration (#61)

After Patch 0.5 dropped (2026-05-29), poe.ninja migrated their builds-list and character pages to a client-side rendered Astro SPA. **`compare_to_top_players` and the character HTML-scrape fallback are dead** until the new endpoint shape is reverse-engineered. The per-character JSON API still works for characters present in the current snapshot, but returns 404 for fresh/low-level characters not yet indexed.

If `analyze_character` returns the SPA-migration warning template, **don't troubleshoot the user's profile-privacy or account-format settings** — those aren't the problem. Direct them to either:
- Wait until poe.ninja indexes the character (1-2 hours for fresh chars)
- Use Path of Building import/export tools instead

Tracking: [issue #61](https://github.com/HivemindOverlord/poe2-mcp/issues/61).

### `skill_gems` v1 schema gaps (since PR #91)

`data/game/skill_gems/` is now shipped (872 gems, 0.5-fresh from PoB2 dev). The handlers prefer it over the legacy `data/pob_complete_skills.json` (PR #94). However the v1 extractor deliberately doesn't yet pull:

- `baseMultiplier` (per-level damage scaling)
- `constantStats` / `statMap` (built-in modifiers from PoB2's Skills/*.lua)
- `qualityStats`
- `description` text

These need a structural Lua parser; tracked for v2 in `docs/SKILL_GEMS_PORT_AUDIT.md`. For now, if `inspect_spell_gem` returns a gem from the new dataset, expect the Gem Metadata block + per-level cost/crit/level-requirement to be present and the deeper modifier list to be absent. If a queried spell isn't in the new dataset at all, the handler falls back to the legacy file and notes "pre-0.5; not yet in data/game/skill_gems/" in its Data Source line — that's a signal, not a bug.

`list_all_spells` now uses PoB2's authoritative `gem_type=='Spell'` classification → **83 active spells**. That's narrower than the old "any gem with cast_time" heuristic; if you remember a wider list pre-PR #94, that's why.

### `search_trade_items` is intentionally unimplemented

Requires GGG OAuth which they've gated against AI tooling. Won't be enabled until that policy changes. Don't recommend its use to users.

## 5. Common failure modes (your fault if you keep hitting these)

- **Guessing parameter names**: see §2 above. When unsure, read the schema.
- **Calling tools that don't exist**: 40 registered tools. The README and `src/mcp_server.py`'s `_register_tools()` are the source of truth.
- **Assuming MCP synthesizes opinions**: it returns facts. You do the analysis.
- **Re-asking the user for data the MCP already gave you**: read your own prior tool results before asking follow-ups.

## 6. Useful workflow patterns

### "Analyze my character X"

```
1. analyze_character(account=..., character=..., league=...)
   - If SPA-migration error: explain CRITICAL #4, suggest PoB import/export instead
   - If success: feed the returned passives into analyze_passive_tree
2. analyze_passive_tree(node_ids=[...from step 1])
   - Reports allocated keystones, notables, unresolved (ascendancy) nodes
3. For each notable mentioned in the report, optionally inspect_passive_node
   for full stat text
4. compare_to_top_players → CURRENTLY DEAD per CRITICAL #4
```

### "Find mods that grant X"

```
1. search_mods_by_stat(stat_keyword="...")   ← tokenized multi-field search
   Searches mod_id + display_name + resolved stat_ids. "life regeneration"
   returns 173 mods spanning both LifeRegeneration* mod IDs and mods whose
   underlying stat_id contains those tokens.
2. For specific tier inspection: get_mod_tiers(mod_id="LifeRegeneration")
3. To check what can roll on a given item: get_available_mods(...)
```

### "What does keystone X do? Is it good for build Y?"

```
1. inspect_keystone(name="Resolute Technique")   ← uses alias!
   Returns: Stats + position + connection count
2. Synthesize the build-fit answer YOURSELF based on the stats + the user's
   build context. The MCP returns facts; you do the recommendation.
```

### "Which ascendancies are available for class X?"

```
Programmatic (when src/data/game_data.py PR #80 lands):
  from src.data.game_data import find_ascendancies_by_base_class
  find_ascendancies_by_base_class("Witch")
  → [Infernalist, Blood Mage, Lich, Abyssal Lich]

Via MCP tool:
  get_ascendancy_info(ascendancy_name="Witch")
```

## 7. When something looks wrong

If a tool returns a result that contradicts what you know:
1. **Don't fabricate corrections.** The MCP's data is authoritative for PoE2 0.5 game mechanics.
2. **Check `check_tree_freshness`** to confirm local data is current.
3. **If still wrong, log it.** The `tests/mcp_accuracy_evaluation_2026-05-30.md` doc tracks known gaps. Add your finding there or file a GitHub issue if it's substantive.

If a tool errors out (Python TypeError, etc.) — that's a real bug. File an issue with the exact tool call and error message; the maintainer (HivemindOverlord) reviews issues regularly and HivemindMinion's cron triages new ones.

## 8. Quick reference: file → what's in it

| Path | Content |
|---|---|
| `CLAUDE.md` | Project rules (read first for context) |
| `data/game/README.md` | Game-data layout reference |
| `data/game/version.json` | Current data revision + dataset summary |
| `data/game/*/metadata.json` | Per-dataset provenance + schema notes + caveats |
| `src/data/game_data.py` | Path constants + load helpers (Python API) |
| `tests/mcp_accuracy_evaluation_2026-05-30.md` | Known gaps + workarounds |
| `CHANGELOG.md` | What changed in each release |

## 9. Versioning

The MCP is at code version 1.0.x; game data has its own revision number in `data/game/version.json` (currently `data-v0.5.0-r6` as of 2026-05-31). Data revisions don't necessarily map to code releases — data can land independently when a patch drops or new datasets are added.

---

Maintained by HivemindMinion. Update this doc when adding new tools, finding new failure modes, or otherwise changing the AI-facing surface in a way that LLMs need to know.
