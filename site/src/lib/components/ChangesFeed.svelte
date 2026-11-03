<script lang="ts">
  import { base } from '$app/paths';
  import { loadChanges } from '$lib/data/loaders';
  import type { Changes } from '$lib/data/types';

  let { runId }: { runId: string } = $props();
  let changes = $state<Changes | null>(null);
  let failed = $state(false);
  $effect(() => {
    loadChanges(fetch, base, runId).then((c) => (changes = c)).catch(() => (failed = true));
  });
</script>

<section class="panel" aria-labelledby="chg-h">
  <h2 id="chg-h">Changes since the last run</h2>
  {#if failed}
    <p class="muted">Change log unavailable.</p>
  {:else if !changes}
    <div class="skeleton" style="height: 3rem"></div>
  {:else if changes.items.length === 0}
    <p class="muted">No notable changes.</p>
  {:else}
    <ul>
      {#each changes.items as c}
        <li>{#if c.state}<a href="{base}/state/{c.state}">{c.state}</a>: {/if}{c.text}</li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  ul { margin: 0; padding-left: 1.1rem; }
</style>
