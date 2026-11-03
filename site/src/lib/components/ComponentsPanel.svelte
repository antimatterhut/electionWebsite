<script lang="ts">
  import { margin, signed } from '$lib/format';
  import type { Summary } from '$lib/data/types';

  let { summary }: { summary: Summary | null } = $props();
</script>

<section class="panel" aria-labelledby="comp-h">
  <h2 id="comp-h">National environment</h2>
  {#if !summary}
    <div class="skeleton" style="height: 5rem"></div>
  {:else}
    {@const n = summary.national}
    <dl>
      <div><dt>Generic ballot</dt><dd>{margin(n.generic_ballot.margin)} ({n.generic_ballot.n_polls} polls)</dd></div>
      <div><dt>2024 national vote</dt><dd>{margin(n.npv2024)}</dd></div>
      <div><dt>National swing</dt><dd>{signed(n.s_nat)} pts toward Democrats</dd></div>
      <div><dt>Combination weights</dt><dd>{summary.weights.national}:{summary.weights.state_poll} (national : race polls)</dd></div>
    </dl>
  {/if}
</section>

<style>
  dl { margin: 0; }
  dl div { display: flex; justify-content: space-between; gap: 1rem; padding: 0.2rem 0; border-bottom: 1px solid var(--line); }
  dt { color: var(--muted); }
  dd { margin: 0; text-align: right; }
</style>
