<script lang="ts">
  import { relativeTime } from '$lib/format';
  import type { Summary } from '$lib/data/types';

  let { summary }: { summary: Summary | null } = $props();
  let now = $state<number | null>(null);
  $effect(() => { now = Date.now(); });
  // run_id looks like 20261102T120000Z[-suffix]; show the absolute time and a relative hint once hydrated.
  const iso = $derived.by(() => {
    const m = summary?.run_id.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z/);
    return m ? `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}Z` : null;
  });
</script>

<div class="head">
  <h1>2026 U.S. Senate: county-level projection</h1>
  {#if summary}
    <p class="muted">
      Data as of <time datetime={summary.as_of}>{summary.as_of}</time>
      · updated {#if iso}<time datetime={iso}>{iso.replace('T', ' ').replace('Z', ' UTC')}</time>{#if now} ({relativeTime(iso, now)}){/if}{/if}
      · run <code>{summary.run_id}</code>
    </p>
  {:else}
    <p class="skeleton" style="width: 22rem; max-width: 100%">&nbsp;</p>
  {/if}
</div>

<style>
  .head p { margin: 0; font-size: 0.9rem; }
  code { font-size: 0.85em; }
</style>
