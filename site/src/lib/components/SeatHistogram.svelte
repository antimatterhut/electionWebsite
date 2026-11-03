<script lang="ts">
  import { pct } from '$lib/format';
  import type { Summary } from '$lib/data/types';

  let { summary }: { summary: Summary | null } = $props();
  const s = $derived(summary?.national.senate);
  const W = 560, H = 190, PAD = { l: 8, r: 8, t: 14, b: 26 };
  const bars = $derived.by(() => {
    if (!s) return [];
    const e = Object.entries(s.distribution).map(([k, v]) => [Number(k), v] as const).sort((a, b) => a[0] - b[0]);
    return e;
  });
  const max = $derived(Math.max(0.0001, ...bars.map((b) => b[1])));
  const x = (k: number) => {
    const lo = bars[0]?.[0] ?? 0, hi = bars[bars.length - 1]?.[0] ?? 1;
    return PAD.l + ((k - lo + 0.5) / (hi - lo + 1)) * (W - PAD.l - PAD.r);
  };
  const bw = $derived(bars.length ? (W - PAD.l - PAD.r) / (bars[bars.length - 1]![0] - bars[0]![0] + 1) - 2 : 10);
  let active = $state<number | null>(null);
  const thr = $derived(s?.threshold ?? 51);
</script>

{#if s && bars.length}
  <section class="panel" aria-labelledby="seat-h">
    <h2 id="seat-h">Democratic-caucus seats after 2026</h2>
    <svg viewBox="0 0 {W} {H}" role="group" aria-label="Seat distribution histogram" width="100%">
      {#each bars as [k, v]}
        <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
        <rect
          x={x(k) - bw / 2} width={bw} y={H - PAD.b - (v / max) * (H - PAD.b - PAD.t)} height={(v / max) * (H - PAD.b - PAD.t)}
          fill={k >= thr ? 'var(--dem)' : 'var(--rep)'} opacity={active === null || active === k ? 1 : 0.55}
          role="img" tabindex="0" aria-label="{k} seats: {pct(v, 1)}"
          onmouseenter={() => (active = k)} onmouseleave={() => (active = null)}
          onfocus={() => (active = k)} onblur={() => (active = null)}
        />
        {#if k % 2 === 0 || bars.length < 12}
          <text x={x(k)} y={H - 8} text-anchor="middle" font-size="11" fill="var(--muted)">{k}</text>
        {/if}
      {/each}
      <line x1={x(thr) - bw / 2 - 1} x2={x(thr) - bw / 2 - 1} y1={PAD.t - 6} y2={H - PAD.b} stroke="var(--text)" stroke-dasharray="4 3" />
      <text x={x(thr) - bw / 2 + 3} y={PAD.t} font-size="11" fill="var(--text)">{thr} = control</text>
    </svg>
    <p class="readout" aria-live="polite">
      {#if active !== null}P(exactly {active} seats) = {pct(s.distribution[String(active)], 1)}{:else}Hover or focus a bar for P(exactly k seats).{/if}
    </p>
  </section>
{/if}

<style>
  .readout { margin: 0.25rem 0 0; font-size: 0.9rem; color: var(--muted); min-height: 1.4em; }
  rect:focus-visible { outline: 3px solid var(--focus); }
</style>
