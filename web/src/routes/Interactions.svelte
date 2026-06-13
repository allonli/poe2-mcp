<script>
  import { onMount } from 'svelte';

  // Skill + support interaction explorer (commander directive 2026-06-13:
  // "view the various combinations of a particular interaction"). Pick a
  // skill, see every support that can socket with it, build a setup, and
  // get live conflict warnings — all from the canonical extraction.

  let data = $state(null);
  let error = $state(null);
  let query = $state('');
  let selectedSkill = $state(null);
  let chosen = $state([]);          // chosen support names
  let supportFilter = $state('');

  onMount(async () => {
    try {
      const r = await fetch('./data/skill_support_interactions.json');
      if (!r.ok) throw new Error('Failed to load interaction data');
      data = await r.json();
    } catch (e) {
      error = e.message;
    }
  });

  // incompatibility lookup: normalized-name -> set of conflicting normalized names
  function norm(name) {
    let n = name.toLowerCase().replace(/_/g, ' ').trim();
    if (n.endsWith(' support')) n = n.slice(0, -' support'.length).trim();
    return n;
  }
  const incompatMap = $derived.by(() => {
    const m = new Map();
    if (!data) return m;
    for (const [a, b] of data.incompatibilities) {
      if (!m.has(a)) m.set(a, new Set());
      if (!m.has(b)) m.set(b, new Set());
      m.get(a).add(b);
      m.get(b).add(a);
    }
    return m;
  });

  const filteredSkills = $derived.by(() => {
    if (!data) return [];
    const q = query.toLowerCase();
    return data.skills
      .filter(s => !q || s.name.toLowerCase().includes(q))
      .slice(0, 60);
  });

  // supports compatible with the selected skill's category
  const compatibleSupports = $derived.by(() => {
    if (!data || !selectedSkill) return [];
    const cat = selectedSkill.category;
    const f = supportFilter.toLowerCase();
    return data.supports
      .filter(s => s.compatible_with.includes(cat))
      .filter(s => !f || s.name.toLowerCase().includes(f));
  });

  // conflicts among the currently chosen supports
  const conflicts = $derived.by(() => {
    const out = [];
    for (let i = 0; i < chosen.length; i++) {
      for (let j = i + 1; j < chosen.length; j++) {
        const a = norm(chosen[i]), b = norm(chosen[j]);
        if (incompatMap.get(a)?.has(b)) out.push([chosen[i], chosen[j]]);
      }
    }
    return out;
  });

  function pickSkill(s) {
    selectedSkill = s;
    chosen = [];
    supportFilter = '';
  }
  function toggleSupport(name) {
    chosen = chosen.includes(name)
      ? chosen.filter(n => n !== name)
      : [...chosen, name];
  }
  function conflictsWith(name) {
    const n = norm(name);
    return chosen.some(c => c !== name && incompatMap.get(norm(c))?.has(n));
  }
</script>

<div class="explorer">
  <h1>Skill &amp; Support Interaction Explorer</h1>
  <p class="sub">
    Pick a skill to see every support gem that can socket with it, build a
    setup, and get live conflict warnings. Sourced from the extracted
    game data ({data ? `${data.skills.length} skills, ${data.supports.length} supports` : '…'}).
  </p>

  {#if error}
    <div class="error">Error: {error}</div>
  {:else if !data}
    <div class="loading">Loading interaction data…</div>
  {:else}
    <div class="grid">
      <!-- left: skill picker -->
      <div class="panel">
        <h2>1. Pick a skill</h2>
        <input class="search" placeholder="Search skills…" bind:value={query} />
        <ul class="list">
          {#each filteredSkills as s}
            <li>
              <button
                class:selected={selectedSkill?.name === s.name}
                onclick={() => pickSkill(s)}>
                <span class="name">{s.name}</span>
                <span class="cat {s.category}">{s.category}</span>
              </button>
            </li>
          {/each}
          {#if filteredSkills.length === 0}
            <li class="empty">No skills match “{query}”.</li>
          {/if}
        </ul>
      </div>

      <!-- middle: compatible supports -->
      <div class="panel">
        <h2>2. Compatible supports</h2>
        {#if !selectedSkill}
          <p class="hint">Select a skill on the left.</p>
        {:else}
          <p class="ctx">
            <strong>{selectedSkill.name}</strong>
            <span class="cat {selectedSkill.category}">{selectedSkill.category}</span>
            — {compatibleSupports.length} compatible supports
          </p>
          <input class="search" placeholder="Filter supports…" bind:value={supportFilter} />
          <ul class="list supports">
            {#each compatibleSupports as s}
              <li>
                <button
                  class:chosen={chosen.includes(s.name)}
                  class:conflict={conflictsWith(s.name)}
                  onclick={() => toggleSupport(s.name)}>
                  {s.name}
                  {#if conflictsWith(s.name)}<span class="warn">conflict</span>{/if}
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      </div>

      <!-- right: your setup -->
      <div class="panel">
        <h2>3. Your setup</h2>
        {#if chosen.length === 0}
          <p class="hint">Click supports to add them.</p>
        {:else}
          <ul class="chosen-list">
            {#each chosen as c}
              <li>
                <span>{c}</span>
                <button class="x" onclick={() => toggleSupport(c)}>×</button>
              </li>
            {/each}
          </ul>
          {#if conflicts.length > 0}
            <div class="conflicts">
              <h3>⚠ Incompatible pairs</h3>
              <ul>
                {#each conflicts as [a, b]}
                  <li>{a} + {b}</li>
                {/each}
              </ul>
            </div>
          {:else}
            <div class="ok">✓ No hard conflicts in this setup</div>
          {/if}
        {/if}
      </div>
    </div>

    <p class="note">
      Compatibility is by gem category (spell/attack). Conflict detection
      uses the canonical hard-incompatibility rules
      ({data.incompatibilities.length} pairs, e.g. Projectile
      Acceleration + Deceleration). Semantic mismatches (e.g. a fire
      support on a cold skill) are not flagged here — use the MCP
      <code>validate_support_combination</code> tool for that depth.
    </p>
  {/if}
</div>

<style>
  .explorer { max-width: 1300px; margin: 0 auto; }
  h1 { color: var(--accent); margin-bottom: 0.25rem; }
  .sub { color: var(--text-secondary); margin-bottom: 1.5rem; }
  .grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; }
  .panel {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem;
    min-height: 300px;
  }
  .panel h2 { font-size: 1.1rem; color: var(--text-primary); margin-top: 0; }
  .search {
    width: 100%; padding: 0.5rem; margin-bottom: 0.75rem;
    background: var(--bg-primary); border: 1px solid var(--border);
    border-radius: 4px; color: var(--text-primary); box-sizing: border-box;
  }
  .list { list-style: none; padding: 0; margin: 0; max-height: 460px; overflow-y: auto; }
  .list button {
    width: 100%; text-align: left; padding: 0.45rem 0.6rem; margin-bottom: 2px;
    background: var(--bg-primary); border: 1px solid transparent;
    border-radius: 4px; color: var(--text-primary); cursor: pointer;
    display: flex; justify-content: space-between; align-items: center; gap: 0.5rem;
  }
  .list button:hover { border-color: var(--accent); }
  .list button.selected { background: rgba(175,96,37,0.25); border-color: var(--accent); }
  .list button.chosen { background: rgba(40,120,60,0.3); border-color: #3a8; }
  .list button.conflict { border-color: #dc3545; }
  .cat { font-size: 0.7rem; padding: 0.1rem 0.4rem; border-radius: 3px; text-transform: uppercase; }
  .cat.spell { background: rgba(80,130,220,0.3); color: #9bf; }
  .cat.attack { background: rgba(200,120,40,0.3); color: #fc9; }
  .warn { font-size: 0.7rem; color: #f88; margin-left: 0.4rem; }
  .ctx { color: var(--text-secondary); margin-bottom: 0.5rem; }
  .hint, .empty { color: var(--text-secondary); font-style: italic; }
  .chosen-list { list-style: none; padding: 0; margin: 0; }
  .chosen-list li {
    display: flex; justify-content: space-between; align-items: center;
    padding: 0.4rem 0.6rem; background: var(--bg-primary);
    border-radius: 4px; margin-bottom: 3px;
  }
  .x { background: none; border: none; color: #f88; cursor: pointer; font-size: 1.1rem; }
  .conflicts { margin-top: 1rem; background: rgba(220,53,69,0.12);
    border: 1px solid rgba(220,53,69,0.4); border-radius: 6px; padding: 0.75rem; }
  .conflicts h3 { margin: 0 0 0.4rem; color: #f66; font-size: 0.95rem; }
  .ok { margin-top: 1rem; color: #5c9; }
  .note { margin-top: 1.5rem; color: var(--text-secondary); font-size: 0.85rem; }
  .note code { background: var(--bg-secondary); padding: 0.1rem 0.3rem; border-radius: 3px; }
  .error { background: rgba(220,53,69,0.1); border: 1px solid rgba(220,53,69,0.3);
    padding: 1rem; border-radius: 6px; color: #f66; }
  @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
</style>
