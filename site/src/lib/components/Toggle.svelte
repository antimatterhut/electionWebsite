<script lang="ts">
  import { viewState } from '$lib/stores.svelte';
  import { nextView, VIEWS } from '$lib/view';
  import type { View } from '$lib/data/types';

  const label: Record<View, string> = { projection: 'Projection', shift: 'Shift from 2024' };
  let refs: Record<string, HTMLButtonElement | undefined> = {};

  function key(e: KeyboardEvent) {
    const n = nextView(viewState.view, e.key);
    if (!n) return;
    e.preventDefault();
    viewState.set(n);
    refs[n]?.focus();
  }
</script>

<div class="toggle" role="radiogroup" aria-label="Map view" tabindex="-1">
  {#each VIEWS as v}
    <button
      bind:this={refs[v]}
      type="button"
      role="radio"
      aria-checked={viewState.view === v}
      tabindex={viewState.view === v ? 0 : -1}
      class:on={viewState.view === v}
      data-view={v}
      onclick={() => viewState.set(v)}
      onkeydown={key}
    >{label[v]}</button>
  {/each}
</div>

<style>
  .toggle { display: inline-flex; border: 1px solid var(--line); border-radius: 999px; overflow: hidden; background: var(--panel); }
  button { border: 0; background: transparent; padding: 0.45rem 1rem; cursor: pointer; min-height: 44px; }
  button.on { background: var(--accent); color: var(--accent-text); font-weight: 600; }
</style>
