<script lang="ts">
  import { base } from '$app/paths';
  import { select } from 'd3-selection';
  import { zoom, zoomIdentity } from 'd3-zoom';
  import { onMount } from 'svelte';
  import type { Topology } from 'topojson-specification';
  import { colorFor } from '$lib/color';
  import { loadTopo } from '$lib/data/loaders';
  import { bounds, features, toShapes, type Shape } from '$lib/geo';
  import { viewState } from '$lib/stores.svelte';
  import { countyTooltip } from '$lib/tooltip';
  import CountyTooltip from './CountyTooltip.svelte';
  import type { County } from '$lib/data/types';

  let { abbr, counties, runId }: { abbr: string; counties: County[]; runId: string } = $props();

  let svg: SVGSVGElement;
  let g: SVGGElement;
  let shapes = $state<Shape[]>([]);
  let status = $state<'loading' | 'ready' | 'error'>('loading');
  let viewBox = $state('0 0 600 400');
  let focusIdx = $state(0);
  let hover = $state<{ geoid: string; x: number; y: number } | null>(null);
  let pinned = $state<string | null>(null);
  let live = $state('');
  let width = $state(600);
  let height = $state(400);

  const by = $derived(new Map(counties.map((c) => [c.geoid, c])));
  const sorted = $derived([...shapes].sort((a, b) => a.name.localeCompare(b.name)));
  const val = (c: County | undefined) => (c ? (viewState.view === 'shift' ? c.shift : c.proj_margin) : NaN);

  onMount(async () => {
    try {
      const topo = await loadTopo<Topology>(fetch, base, `states/${abbr}.topojson`, runId);
      const feats = features(topo, 'counties');
      shapes = toShapes(feats);
      const [[x0, y0], [x1, y1]] = bounds(feats);
      const pad = 8;
      viewBox = `${x0 - pad} ${y0 - pad} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`;
      status = 'ready';
      const z = zoom<SVGSVGElement, unknown>().scaleExtent([1, 8]).on('zoom', (e) => g.setAttribute('transform', e.transform.toString()));
      select(svg).call(z).on('dblclick.zoom', null);
      select(svg).call(z.transform, zoomIdentity);
    } catch {
      status = 'error';
    }
  });

  function show(s: Shape, x = 0, y = 0, announce = true) {
    hover = { geoid: s.geoid, x, y };
    const c = by.get(s.geoid);
    if (announce && c) live = countyTooltip(c, abbr, base).text;
  }
  function key(e: KeyboardEvent, i: number) {
    let n = i;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') n = Math.min(sorted.length - 1, i + 1);
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') n = Math.max(0, i - 1);
    else if (e.key === 'Home') n = 0;
    else if (e.key === 'End') n = sorted.length - 1;
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pinned = sorted[i]!.geoid; return; }
    else if (e.key === 'Escape') { pinned = null; return; }
    else return;
    e.preventDefault();
    focusIdx = n;
    (svg.querySelector(`[data-i="${n}"]`) as SVGElement | null)?.focus();
  }
  const tipFor = (geoid: string | null) => {
    const c = geoid ? by.get(geoid) : undefined;
    return c ? countyTooltip(c, abbr, base) : null;
  };
</script>

<div class="statemap" bind:clientWidth={width} bind:clientHeight={height}>
  <svg bind:this={svg} {viewBox} role="group" aria-label="County map for {abbr}. Use arrow keys to move between counties; the county table below has the same data." onpointerleave={() => (hover = null)}>
    <g bind:this={g}>
      {#each sorted as s, i (s.geoid)}
        {@const c = by.get(s.geoid)}
        <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
        <path
          d={s.d} data-i={i} data-geoid={s.geoid}
          fill={c ? colorFor(viewState.view, val(c)) : '#d4d4d4'}
          stroke="var(--map-line)" stroke-width={pinned === s.geoid ? 2.2 : 0.6} vector-effect="non-scaling-stroke"
          tabindex={i === focusIdx ? 0 : -1} role="img" aria-label={c ? countyTooltip(c, abbr, base).text : s.name}
          onpointermove={(e) => { const r = svg.getBoundingClientRect(); show(s, e.clientX - r.left, e.clientY - r.top, false); }}
          onfocus={(e) => { focusIdx = i; show(s, 12, 12); }}
          onblur={() => (hover = null)}
          onclick={() => (pinned = pinned === s.geoid ? null : s.geoid)}
          onkeydown={(e) => key(e, i)}
        />
      {/each}
    </g>
  </svg>
  {#if status === 'loading'}<div class="overlay"><span class="skeleton" style="width: 60%; height: 60%"></span></div>{/if}
  {#if status === 'error'}<div class="overlay" role="alert">County map unavailable. The table below has all values.</div>{/if}
  {#if hover && !pinned}<CountyTooltip content={tipFor(hover.geoid)} x={hover.x} y={hover.y} containerWidth={width} containerHeight={height} />{/if}
  {#if pinned}<CountyTooltip content={tipFor(pinned)} pinned onclose={() => (pinned = null)} />{/if}
  <p class="sr-only" aria-live="polite">{live}</p>
</div>

<style>
  .statemap { position: relative; background: var(--map-bg); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; }
  svg { width: 100%; height: auto; max-height: 560px; display: block; touch-action: pan-y; }
  path { cursor: pointer; transition: fill 200ms; }
  path:focus-visible { outline: none; stroke: #000; stroke-width: 3px; }
  .overlay { position: absolute; inset: 0; display: grid; place-content: center; text-align: center; padding: 1rem; }
</style>
