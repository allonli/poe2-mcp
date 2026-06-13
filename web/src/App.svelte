<script>
  import { onMount } from 'svelte';
  import {
    currentRoute,
    passiveTree,
    spawnWeights,
    isLoading,
    loadError,
    navigate,
    initRouteListener
  } from './lib/stores.js';

  import Home from './routes/Home.svelte';
  import Calculator from './routes/Calculator.svelte';
  import Interactions from './routes/Interactions.svelte';

  // Load data on mount
  onMount(async () => {
    // Initialize route listener (must be in component lifecycle for Svelte 5)
    initRouteListener();

    try {
      // Load passive tree data
      const treeResponse = await fetch('./data/passive_tree.json');
      if (!treeResponse.ok) throw new Error('Failed to load passive tree');
      const treeData = await treeResponse.json();
      passiveTree.set(treeData);

      // Load spawn weights
      const weightsResponse = await fetch('./data/abyss_spawn_weights.json');
      if (!weightsResponse.ok) throw new Error('Failed to load spawn weights');
      const weightsData = await weightsResponse.json();
      spawnWeights.set(weightsData);

      isLoading.set(false);
    } catch (err) {
      console.error('Failed to load data:', err);
      loadError.set(err.message);
      isLoading.set(false);
    }
  });

  // Simple hash router
  $: route = $currentRoute.replace('#', '') || '/';
</script>

<div class="app">
  <header>
    <nav>
      <a href="#/" class:active={route === '/'}>Home</a>
      <a href="#/calculator" class:active={route === '/calculator'}>Undying Hate Calculator</a>
      <a href="#/interactions" class:active={route === '/interactions'}>Interaction Explorer</a>
    </nav>
    <h1>PoE2 Tools</h1>
  </header>

  <main>
    {#if $isLoading}
      <div class="loading">
        <div class="spinner"></div>
        <p>Loading game data...</p>
      </div>
    {:else if $loadError}
      <div class="error">
        <h2>Error Loading Data</h2>
        <p>{$loadError}</p>
        <p>Make sure the data files exist in the static/data/ folder.</p>
      </div>
    {:else}
      {#if route === '/'}
        <Home />
      {:else if route === '/calculator'}
        <Calculator />
      {:else if route === '/interactions'}
        <Interactions />
      {:else}
        <div class="not-found">
          <h2>404 - Page Not Found</h2>
          <p><a href="#/">Go Home</a></p>
        </div>
      {/if}
    {/if}
  </main>

  <footer>
    <p>
      PoE2 Undying Hate Calculator |
      <a href="https://github.com/HivemindOverlord/poe2-mcp" target="_blank">GitHub</a>
    </p>
  </footer>
</div>

<style>
  .app {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  header {
    background: var(--bg-secondary);
    padding: 1rem 2rem;
    border-bottom: 1px solid var(--border);
  }

  nav {
    display: flex;
    gap: 1.5rem;
    margin-bottom: 0.5rem;
  }

  nav a {
    color: var(--text-secondary);
    text-decoration: none;
    padding: 0.5rem 1rem;
    border-radius: 4px;
    transition: all 0.2s;
  }

  nav a:hover {
    color: var(--text-primary);
    background: rgba(175, 96, 37, 0.2);
  }

  nav a.active {
    color: var(--accent);
    background: rgba(175, 96, 37, 0.15);
  }

  h1 {
    font-size: 1.5rem;
    color: var(--accent);
    margin: 0;
  }

  main {
    flex: 1;
    padding: 2rem;
    max-width: 1400px;
    margin: 0 auto;
    width: 100%;
  }

  footer {
    background: var(--bg-secondary);
    padding: 1rem 2rem;
    text-align: center;
    border-top: 1px solid var(--border);
    color: var(--text-secondary);
    font-size: 0.9rem;
  }

  footer a {
    color: var(--accent);
  }

  .loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 400px;
    gap: 1rem;
  }

  .spinner {
    width: 50px;
    height: 50px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  .error {
    background: rgba(220, 53, 69, 0.1);
    border: 1px solid rgba(220, 53, 69, 0.3);
    padding: 2rem;
    border-radius: 8px;
    text-align: center;
  }

  .error h2 {
    color: #dc3545;
  }

  .not-found {
    text-align: center;
    padding: 4rem;
  }

  .not-found a {
    color: var(--accent);
  }
</style>
