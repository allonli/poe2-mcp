# PoE2 Game-Data Research Deep-Dive

A field guide to the Path of Exile 2 data files, the formats we
reverse-engineered, and the pipeline that turns them into the JSON this
MCP serves. Written so the next person doesn't have to rediscover any of
it.

**Scope & policy.** Everything here is derived from a *licensed local
PoE2 install* and the open-source PathOfBuilding-PoE2 community repo. No
wikis, no scraping. Game mechanics come from the extracted `.datc64`
tables; player/build data (allowed) comes from poe.ninja's APIs. See
`CLAUDE.md` "Data Source Policy".

---

## 1. The big picture

```
Steam PoE2 install (Bundles2/*.bundle.bin, GGPK)
        │  ooz/bun_extract_file.exe  (scripts/extract_balance_tables_v1.py)
        ▼
data/extracted/data/balance/*.datc64        ← 1,019 canonical tables (raw)
        │  per-table spec parsers (src/parsers/specifications/)
        ▼
data/game/<dataset>/*.json                  ← canonical JSON the MCP loads
        │  fingerprint + version manifest
        ▼
data/game/version.json  +  schema_fingerprints.json   ← drift gate
```

Two independent sources are deliberately kept:

- **`.datc64` tables = canonical.** The only source of truth for game
  mechanics/numbers.
- **PathOfBuilding-PoE2 clone = reconciliation oracle.** We diff our
  extraction against it and investigate deltas, but never feed PoB data
  into the canonical `data/game/` files. (The one historical exception —
  passive/ascendancy *node* data, which the `.datc64` extraction does not
  contain — is sourced from PoB under an explicit "psg+pob" provenance
  marker. See §6.)

This separation exists because mixing the two is exactly how pre-0.5
values once shipped under a 0.5 banner: gem cost/reservation data had
been enriched from a months-stale PoB clone.

---

## 2. The `.datc64` binary format

Every balance table is a `.datc64` file with the same shape:

```
offset 0   ┌─────────────────────────┐
           │ u32  row_count          │   little-endian
offset 4   ├─────────────────────────┤
           │ fixed-width row 0        │
           │ fixed-width row 1        │   row_count rows,
           │ ...                      │   each row_size bytes
           ├─────────────────────────┤
magic_pos  │ 0xBB 0xBB ... (8 bytes)  │   boundary marker
           ├─────────────────────────┤
           │ variable-length section  │   strings, arrays, blobs
           └─────────────────────────┘
```

### Deriving the geometry

`row_size` is never stored — you compute it:

```python
row_count = struct.unpack_from("<I", data, 0)[0]
magic_pos = data.find(b"\xbb" * 8)
row_size, remainder = divmod(magic_pos - 4, row_count)
assert remainder == 0   # if not, it isn't a clean datc64 table
```

A non-zero remainder means you've misidentified the table or the magic
appears in row data by coincidence (rare; the 8-byte run is a strong
signal). This check is the first line of `GrantedEffectsTables._geometry`
and `datc64_fingerprint.fingerprint_table`.

### References into the variable section

Fixed rows don't hold strings/arrays inline — they hold **offsets**.
The convention we confirmed across grantedeffects, stats, and the
gem-stat-set tables:

- A reference is a **`u64` offset relative to `magic_pos`** (the start of
  the 0xBB run), pointing into the variable section.
- Strings are **UTF-16LE**, NUL-terminated (`\x00\x00`).

So to read row `i`'s id string from a table where column 0 is the id ref:

```python
ref = struct.unpack_from("<Q", data, 4 + i*row_size)[0]
start = magic_pos + ref
end = data.find(b"\x00\x00", start)
name = data[start:end].decode("utf-16-le")
```

> **Gotcha that cost a fire:** stat ids in `stats.datc64` are UTF-16LE.
> A verification probe that read them as ASCII (and also checked the
> wrong field name) reported "0 spirit stat ids" when there are 244.
> The extractor was always correct; the probe was wrong. When a table
> "has no X", confirm against the raw bytes before believing it.

---

## 3. Worked example: per-level skill costs (`grantedeffectsperlevel`)

This is the table that drove the deepest dig (`#61`-adjacent campaign
item C1). Spec lives in
`src/parsers/specifications/granted_effects_spec.py`.

`grantedeffectsperlevel.datc64` — 34,169 rows × 116 bytes:

| offset | type | meaning |
|--------|------|---------|
| 0      | u32  | `grantedeffects` row index (foreign key) |
| 16     | u32  | gem level (1..40) |
| 100    | u64  | **cost pointer** into the variable section |
| 108    | f32  | per-level effectiveness multiplier (1.0 at L1) |

Each effect's 40 levels are contiguous rows sharing FK@0. To find a
skill's block: resolve its `grantedeffects` row by id string (§2), then
gather GEPL rows whose FK matches.

### The deduplicated cost pool — the part that wasn't obvious

The cost @100 isn't a value, it's a pointer — and the pool it points
into is **deduplicated across all skills**. Essence Drain L5 and Fireball
L1 both cost 10 mana, and **both rows carry the same pointer (12)**. ED
L12 and Fireball L7 both cost 24 → same pointer (188). The first `u32`
at `magic_pos + ptr` is the cost amount.

That dedup property is what cracked it: flat per-offset value scans
failed for fires because the "value" column is a pointer, but plotting
pointer-vs-known-cost across skills revealed identical pointers for
identical costs.

### Reconciliation result

Decoding all effects and diffing every per-level Mana cost against the
PoB oracle: **12,061 / 12,061 comparisons match (100.00%)**. The diff
ships as a permanent test (`tests/test_granted_effects_spec.py`) so any
future column move fails loudly.

**Known limits:** cost *type* (Mana vs Life vs …) isn't decoded here
(the cost-types linkage lives in `costtypes.datc64`, 18 rows, dumped:
Mana/Life/ES/Rage/Ward families). **Spirit reservations are NOT in this
table** — meta-gem cost pointers are degenerate; reservations currently
come from the PoB-derived dataset with provenance noted. Sibling tables
`grantedeffectstatsets` (8,274×101B) and `grantedeffectstatsetsperlevel`
(41,428×185B) share the same FK@0/level@16 skeleton and hold the
per-level stat *values* (including DoT bases — an open extraction item).

---

## 4. Extraction: getting all 1,019 tables out

`scripts/extract_balance_tables_v1.py` shells out to the in-tree
`ooz/build/Release/bun_extract_file.exe`:

```
bun_extract_file extract-files --regex <install> <out> "^data/balance/[^/]+\.datc64$"
```

It then **verifies the extracted count against the live bundle index**
(reported 1,019 on 2026-06-13). That count check is not cosmetic: it
caught a mid-0.5 GGG hotfix (1,017 → 1,019 tables, and
`grantedeffectsperlevel` 34,153 → 34,169 rows) that the previous
LibBundle-based path had silently under-extracted (it pulled only 279 of
the 1,019 tables — the original motivation for the whole data-correctness
campaign).

Four high-value tables were missing entirely from the old bundle list
and only appeared after switching extractors: `costtypes`, `soulcores`
(295 rows — 0.5 Runeforging), `itemspirit`, plus corrected `buffdefinitions`.

---

## 5. Drift protection (futureproofing)

`src/parsers/datc64_fingerprint.py` + `data/game/schema_fingerprints.json`:

- **Fingerprint** = per-table `{row_count, row_size, bytes, sha256}` over
  all 1,019 tables.
- **Diff classes**, loudest first:
  - `layout_changed` — `row_size` differs → **columns moved/added; every
    spec touching the table needs review.**
  - `added` / `removed` — tables GGG introduced or cut.
  - `rows_changed` — balance edits (same layout).
  - `content_changed` — value edits (same geometry, different hash).
- A test (`test_shipped_baseline_is_current`) fails if the repo baseline
  and the on-disk extraction drift apart — i.e. if someone re-extracts
  without regenerating the baseline.

Per-patch workflow: re-extract → regenerate baseline → the diff report
names exactly which tables changed and which specs need eyes. Combined
with the live-index count check (§4), both the "GGG added/removed a
table" and "GGG moved a column" cases now fail loudly instead of
producing silently-wrong data.

`data/game/version.json` carries the human-facing revision
(`data-v0.5.0-r12`) and per-dataset record counts + provenance.

---

## 6. Passive tree & ascendancy nodes

- **Passive tree** (`data/psg_passive_nodes.json`, 4,975 nodes) is the
  canonical node source — it carries the adjacency graph AND uses the
  poe.ninja node-id space, both of which the MCP's resolver needs.
  Validated at **732/732 (100%)** allocation resolution across 6 real
  end-game characters.
- **`data/game/passive_tree/tree.json`** (9,605 nodes, from the 0.5
  extraction) is a *name/stat reference only* — it has **no adjacency**
  and its `graph_id` is a 7-value which-graph enum, NOT node ids. Do not
  try to drive pathfinding from it.
- **Ascendancy nodes** (`data/game/ascendancies/nodes.json`, 22
  ascendancies / 429 nodes) come from the **PoB 0.5 tree** under the
  psg+pob precedent: the `.datc64` extraction contains *no* ascendancy
  node data (`ascendancies.datc64` is a 37-row class registry;
  `tree.json`'s per-node `ascendancyName`/stats live only in the PoB
  data). This is the one place PoB is canonical, and it's marked
  `node_source: pob_0_5_tree` in the dataset.

---

## 7. poe.ninja APIs (player/build data — allowed source)

The 0.5 Astro migration was widely read as "poe.ninja killed its APIs".
It didn't — it changed encodings and shapes. Two families, both
recovered by mining the live `_astro/*.mjs` bundles for endpoint strings.

### 7a. Profile API (single character) — JSON

```
GET /poe2/api/events/character/{account}/{leagueSlug}/{char}   → SSE: data: {"version": N}
GET /poe2/api/profile/characters/{account}/{leagueSlug}/{char}/model/{N}  → JSON {type, charModel}
```

No auth. `charModel.pathOfBuildingExport` carries a full PoB export — the
basis for `analyze_character` and the revived `get_pob_code`. Account
enumeration: `GET /poe2/api/profile/characters/{account}/{listVersion}`
(list version from the account-level events SSE) returns every public
character with its `leagueUrl` slug.

### 7b. Builds-list / ladder API — **protobuf** (this is why it "died")

```
GET /poe2/api/data/index-state                  → JSON; snapshotVersions[] (version + snapshotName)
GET /poe2/api/builds/{version}/search?overview=<snapshotName>  → application/x-protobuf
     filters pass through as query params: name=, class=, sort=
GET /poe2/api/builds/dictionary                 → string tables
```

Every post-0.5 probe failed because it expected JSON and got protobuf.
`src/api/poe_ninja_ladder.py` decodes it with a schema-less wire walker
(no `.proto`, no protobuf dependency). The search response is
**columnar**:

```
envelope (field 1) {
    1:  total result count            e.g. 124,242 builds
    5 (repeated): column block { 1: column name; 2 (×100): cells }
    11 (repeated): column catalog (incl. per-skill 'dps-*' columns)
}
```

Cells carry a display string (field 1), a numeric value (field 2), or
packed dictionary indices (field 3). The decoder pivots columns to row
dicts (`name/account/class/level/life/energyshield/ehp/dps`). A recorded
payload lives at `tests/fixtures/ninja_builds_search_roa.pb` for offline
tests. This powers the revived `compare_to_top_players`.

---

## 8. Reusable building blocks

| What | Where |
|------|-------|
| datc64 geometry + string-ref reader | `src/parsers/specifications/granted_effects_spec.py` |
| Schema-less protobuf wire walker | `src/api/poe_ninja_ladder.py` (`parse_message`) |
| Per-table fingerprint + drift diff | `src/parsers/datc64_fingerprint.py` |
| Full-table extraction + count gate | `scripts/extract_balance_tables_v1.py` |
| Reverse stat-source index | `src/data/stat_source_index.py` |
| BM25 lexical search over stat text | `src/data/lexical_search.py` |

---

## 9. Open threads (for whoever's next)

- **Spirit reservations from `.datc64`** — not in GEPL; likely
  `skillgems.datc64` or a buff table. Currently PoB-sourced.
- **DoT base values** — in `grantedeffectstatsetsperlevel` per-level stat
  arrays; would let `calculate_character_dps` auto-resolve skill-DoT
  bases instead of taking them from the caller.
- **`buffdefinitions`** (3,211×351B) — Withered per-stack magnitude and
  other ailment/buff constants.
- **`monstervarieties`** (2,722×1,030B) — "monster power", which drives
  Cast-on-Critical energy generation scaling.
- **`soulcores`** (295 rows) — 0.5 Runeforging; un-parsed dataset.
- **`costtypes` linkage** — wire the cost-type enum to GEPL costs so the
  cost amount carries its type.
