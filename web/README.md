# PoE2 Timeless Jewel Seed Calculator

Standalone web frontend for searching Timeless Jewel seeds in Path of Exile 2. Independent of the MCP server in the parent repo — different language, different lifecycle, different deployment target.

Live at **https://hivemindoverlord.github.io/poe2-mcp/** (GitHub Pages, auto-deployed from `main`).

---

## What it does

Given a chosen passive node radius on the PoE2 tree, enumerates Timeless Jewel seeds and reports which seeds transform which nearby passives into which Undying Hate / other timeless-jewel keystones. Lets you scan for a seed that gives you the exact set of conversions you want before you commit gold to rerolling jewels in-game.

The underlying TinyMT32 PRNG, the radius math, and the seed→keystone mapping live in the **parent repo's Python** (`src/calculator/timeless_seed_mapper.py`, `src/calculator/jewel_radius.py`, `src/calculator/tinymt32.py`) and are re-implemented in JS here (`src/lib/tinymt32.js`, `src/lib/seedMapper.js`) so the calculator can run fully client-side without a backend.

## Tech

- **Svelte 5** with the new runes-style stores (see PR #38 — module-level side effects were the bug)
- **Vite 7** for dev / build
- **svg-pan-zoom** for the passive tree interactive view
- **No router framework** — hand-rolled hash routing in `src/lib/stores.js` (`Home` and `Calculator` routes)
- **No backend** — static data files in `static/data/` are loaded with `fetch()` on mount

## Layout

```
web/
├── package.json                 # name: poe2-undying-hate-calculator
├── vite.config.js               # base: '/poe2-mcp/' for GitHub Pages
├── svelte.config.js
├── index.html
├── src/
│   ├── App.svelte               # Loads data on mount, dispatches by route
│   ├── main.js                  # Entry point
│   ├── app.css
│   ├── routes/
│   │   ├── Home.svelte          # Landing page
│   │   └── Calculator.svelte    # Main calculator UI
│   ├── components/
│   │   ├── PassiveTreeView.svelte    # SVG tree visualization
│   │   ├── SeedInput.svelte          # Seed range entry
│   │   └── ResultsPanel.svelte       # Match output
│   └── lib/
│       ├── stores.js            # Svelte stores + route listener
│       ├── seedMapper.js        # Seed → keystone mapping (port of Python)
│       └── tinymt32.js          # TinyMT32 PRNG (port of Python)
├── static/
│   └── data/
│       ├── passive_tree.json    # Node positions + IDs
│       └── abyss_spawn_weights.json
└── dist/                        # Build output (gitignored)
```

## Develop

Prereqs: Node 20+ (matches CI), npm.

```bash
cd web
npm install
npm run dev       # Vite dev server on http://localhost:3000
```

The dev server auto-opens the browser (`server.open: true` in `vite.config.js`). Hash routing means `/calculator` lives at `http://localhost:3000/#/calculator`.

## Build

```bash
npm run build     # Output: web/dist/
npm run preview   # Serves the built bundle for sanity check
```

`vite.config.js` sets `base: '/poe2-mcp/'` so all asset URLs are GitHub Pages compatible. If you ever fork to a differently-named repo, change that base.

## Deploy

Fully automated. `.github/workflows/deploy-web.yml` triggers on any push to `main` that touches `web/**` (or on manual `workflow_dispatch`):

1. Checkout
2. Setup Node 20 with `web/package-lock.json` cache
3. `npm ci` in `web/`
4. `npm run build` in `web/`
5. Upload `web/dist/` as a Pages artifact
6. Deploy to the `github-pages` environment

Concurrency group `"pages"` with `cancel-in-progress: true` so only one deploy runs at a time. Standard PR workflow — merge to main and Pages updates on its own.

## Data files

`static/data/passive_tree.json` and `static/data/abyss_spawn_weights.json` are extracted upstream by the parent repo's Python pipeline. To refresh them:

- `passive_tree.json` — see `docs/EXTRACTION_PIPELINE.md` in the parent repo, plus `data/game/passive_tree/tree.json` as the canonical source.
- `abyss_spawn_weights.json` — produced by `scripts/extract_abyss_spawn_weights.py` (gitignored extractor scripts) against the local `.datc64` blobs.

Don't edit these by hand — re-extract and commit the refreshed file.

## Relation to the parent MCP server

| | This subproject | Parent (`poe2-mcp`) |
|---|---|---|
| Language | JavaScript / Svelte | Python |
| Purpose | Interactive timeless-jewel search | MCP server for AI clients |
| Deployment | GitHub Pages | pip install / local launch |
| Data source | `static/data/*.json` (bundled) | `data/game/*` + live poe.ninja |
| CI workflow | `deploy-web.yml` | `python-app.yml` (tests) |
| Shared code | None — JS reimplements the Python seed logic | (same) |

The two subprojects are intentionally decoupled. If you want the calculator embedded in an MCP tool (e.g. "find me a seed that gives X"), that's a future feature that would call the Python implementation directly rather than reaching into this web app.

## Known recent fixes

- **Svelte 5 module-level side effects** (PR #38) — stores were being initialized at module load and triggering `setInterval` / DOM listeners before any component mounted. `initRouteListener()` now runs inside `App.svelte`'s `onMount`.
- **Equipment slot display + charm extraction from poe.ninja** (PR #39)
- **Lineage support gem lookup** (commit `cb26285`) — switched lookup key to `display_name`.

## License

MIT (matches parent repo).
