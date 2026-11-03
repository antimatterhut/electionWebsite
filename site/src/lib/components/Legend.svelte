<script lang="ts">
  import { legendStops } from '$lib/color';
  import { viewState } from '$lib/stores.svelte';

  const stops = $derived(legendStops(viewState.view));
  const title = $derived(viewState.view === 'shift' ? 'Shift from 2024 (points)' : 'Projected margin (points)');
  const lo = $derived(stops[0]!.at);
  const hi = $derived(stops[stops.length - 1]!.at);
  const label = (at: number, i: number) => {
    const edge = i === 0 || i === stops.length - 1;
    const n = Math.abs(at);
    if (viewState.view === 'shift') return at === 0 ? '0' : `${edge ? (at > 0 ? '≥' : '≤') : ''}${at > 0 ? '+' : '−'}${n}`;
    return at === 0 ? 'Even' : `${edge ? '≥' : ''}${at > 0 ? 'D' : 'R'}+${n}`;
  };
  // A readable subset of ticks keeps the legend usable on phones.
  const ticks = $derived(stops.filter((_, i) => i % 2 === 0 || i === stops.length - 1));
</script>

<figure class="legend" aria-label={title}>
  <figcaption>{title}</figcaption>
  <ol class="swatches">
    {#each stops as s, i}
      <li style:background={s.hex} class:edge={i === 0 || i === stops.length - 1} title={label(s.at, i)}>
        <span class="sr-only">{label(s.at, i)}</span>
      </li>
    {/each}
  </ol>
  <div class="ticks" aria-hidden="true">
    {#each ticks as s}
      {@const i = stops.indexOf(s)}
      <span style:left="{((s.at - lo) / (hi - lo)) * 100}%">{label(s.at, i)}</span>
    {/each}
  </div>
</figure>

<style>
  .legend { margin: 0; max-width: 520px; }
  figcaption { font-size: 0.85rem; color: var(--muted); margin-bottom: 0.25rem; }
  .swatches { display: flex; list-style: none; margin: 0; padding: 0; height: 14px; border: 1px solid var(--line); }
  .swatches li { flex: 1; }
  /* Pattern hint for the extremes so they are not distinguished by color alone. */
  .swatches li.edge { background-image: repeating-linear-gradient(45deg, rgba(255, 255, 255, 0.45) 0 2px, transparent 2px 5px); background-blend-mode: normal; }
  .ticks { position: relative; height: 1.3rem; font-size: 0.75rem; color: var(--muted); margin-top: 2px; }
  .ticks span { position: absolute; transform: translateX(-50%); white-space: nowrap; }
  .ticks span:first-child { transform: translateX(0); }
  .ticks span:last-child { transform: translateX(-100%); }
</style>
