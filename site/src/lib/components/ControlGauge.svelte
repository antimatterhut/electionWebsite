<script lang="ts">
  import { pct } from '$lib/format';
  import type { Summary } from '$lib/data/types';

  let { summary }: { summary: Summary | null } = $props();
  const s = $derived(summary?.national.senate);
</script>

<section class="panel gauge" aria-labelledby="gauge-h">
  <h2 id="gauge-h">Chance Democrats control the Senate</h2>
  {#if !summary}
    <div class="skeleton" style="height: 4rem"></div>
  {:else if !s}
    <p class="muted">Simulation results are not available for this run.</p>
  {:else}
    <p class="big"><strong>{pct(s.p_d_control)}</strong></p>
    <div class="bar" role="img" aria-label="Democratic control probability {pct(s.p_d_control)}">
      <span style:width="{s.p_d_control * 100}%"></span>
    </div>
    <p class="muted">
      Median {s.d_seats_median} Democratic-caucus seats (80% range {s.d_seats_p10}–{s.d_seats_p90}); {s.threshold ?? 51} needed for control.
      Probabilities are not forecasts of margins.
    </p>
  {/if}
</section>

<style>
  .big { font-size: 2.4rem; margin: 0; line-height: 1.1; }
  .bar { height: 10px; background: var(--panel-2); border-radius: 5px; overflow: hidden; margin: 0.5rem 0; border: 1px solid var(--line); }
  .bar span { display: block; height: 100%; background: var(--dem); }
</style>
