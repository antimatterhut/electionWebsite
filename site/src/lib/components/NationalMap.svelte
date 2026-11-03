<script lang="ts">
  import { goto } from '$app/navigation';
  import { base } from '$app/paths';
  import { onMount } from 'svelte';
  import type { Topology } from 'topojson-specification';
  import { colorFor, NEUTRAL_GRAY } from '$lib/color';
  import { loadCountiesNational, loadTopo, parseCountiesNational, type CountyRow } from '$lib/data/loaders';
  import { ATLAS_H, ATLAS_W, borders, features, HitTester, toAtlas, toShapes, type Shape } from '$lib/geo';
  import { margin, marginRange, shift as fmtShift } from '$lib/format';
  import { viewState } from '$lib/stores.svelte';
  import CountyTooltip from './CountyTooltip.svelte';
  import type { TooltipContent } from '$lib/tooltip';

  let { runId, fallbackHref }: { runId: string; fallbackHref?: string } = $props();

  let canvas: HTMLCanvasElement;
  let wrap: HTMLDivElement;
  let status = $state<'loading' | 'ready' | 'error'>('loading');
  let errorMsg = $state('');
  let rows = new Map<string, CountyRow>();
  let counties: Shape[] = [];
  let stateShapes: Shape[] = [];
  let stateBorders = '';
  let stateBorderPath: Path2D | undefined;
  let tester: HitTester | null = null;
  let size = $state({ w: 600, h: 375 });
  let hover = $state<{ shape: Shape; x: number; y: number } | null>(null);
  let pinned = $state<{ shape: Shape } | null>(null);
  let live = $state('');
  let colors: string[] = [];
  const reduced = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;

  const value = (r: CountyRow | undefined, v = viewState.view) => (r ? (v === 'shift' ? r.shift : r.proj) : NaN);
  const targetColors = (v = viewState.view) => counties.map((c) => (rows.has(c.geoid) ? colorFor(v, value(rows.get(c.geoid), v)) : NEUTRAL_GRAY));

  const hexRgb = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const mix = (a: string, b: string, t: number) => {
    const ca = hexRgb(a), cb = hexRgb(b);
    return `rgb(${ca.map((x, i) => Math.round(x + (cb[i]! - x) * t)).join(',')})`;
  };

  function draw(from: string[] | null = null, t = 1) {
    const ctx = canvas?.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const s = Math.min(size.w / ATLAS_W, size.h / ATLAS_H);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(dpr * s, 0, 0, dpr * s, dpr * ((size.w - ATLAS_W * s) / 2), dpr * ((size.h - ATLAS_H * s) / 2));
    const css = getComputedStyle(canvas);
    for (const st of stateShapes) {
      if (!st.path) continue;
      ctx.fillStyle = NEUTRAL_GRAY; // non-race states: neutral gray; race states are covered by counties
      ctx.globalAlpha = 0.55;
      ctx.fill(st.path);
    }
    ctx.globalAlpha = 1;
    counties.forEach((c, i) => {
      if (!c.path) return;
      ctx.fillStyle = from ? mix(from[i]!, colors[i]!, t) : colors[i]!;
      ctx.fill(c.path);
    });
    ctx.lineWidth = 0.5 / s;
    ctx.strokeStyle = css.getPropertyValue('--map-line') || '#fff';
    if (stateBorderPath) { ctx.lineWidth = 1.2 / s; ctx.stroke(stateBorderPath); }
    if (pinned?.shape.path) { ctx.lineWidth = 2.5 / s; ctx.strokeStyle = '#000'; ctx.stroke(pinned.shape.path); }
    else if (hover?.shape.path) { ctx.lineWidth = 2 / s; ctx.strokeStyle = '#000'; ctx.stroke(hover.shape.path); }
  }

  let anim = 0;
  function recolor() {
    const next = targetColors();
    if (!counties.length) return;
    const from = colors.length ? colors : next;
    colors = next;
    cancelAnimationFrame(anim);
    if (reduced) return draw();
    const t0 = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - t0) / 200);
      draw(from, t);
      if (t < 1) anim = requestAnimationFrame(step);
    };
    anim = requestAnimationFrame(step);
  }

  function resize() {
    if (!wrap) return;
    const w = wrap.clientWidth;
    size = { w, h: Math.round(w / 1.6) };
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(size.w * dpr);
    canvas.height = Math.round(size.h * dpr);
    draw();
  }

  async function load() {
    status = 'loading';
    try {
      const f = fetch;
      const [ctopo, stopo, cn] = await Promise.all([
        loadTopo<Topology>(f, base, 'counties.topojson', runId),
        loadTopo<Topology>(f, base, 'states.topojson', runId),
        loadCountiesNational(f, base, runId)
      ]);
      rows = parseCountiesNational(cn);
      counties = toShapes(features(ctopo, 'counties'), true);
      stateShapes = toShapes(features(stopo, 'states').filter((s) => !s.properties.race), true);
      stateBorders = borders(stopo, 'states');
      stateBorderPath = new Path2D(stateBorders);
      tester = new HitTester(counties, canvas.getContext('2d'));
      colors = targetColors();
      status = 'ready';
      resize();
    } catch (e) {
      errorMsg = (e as Error).message;
      status = 'error';
    }
  }

  function describe(c: Shape) {
    const r = rows.get(c.geoid);
    return r ? `${c.name}, ${c.state}. Projected ${margin(r.proj)}. Shift ${fmtShift(r.shift)}.` : `${c.name}, ${c.state}`;
  }
  function tipFor(c: Shape): TooltipContent {
    const r = rows.get(c.geoid);
    const rowsOut = r
      ? [
          { label: 'Projected 2026 Senate', value: margin(r.proj) },
          { label: '2024 presidential', value: margin(r.pres2024) },
          { label: 'Shift from 2024', value: fmtShift(r.shift) },
          { label: 'Chance D wins county', value: `${Math.round(r.p * 100)}%` }
        ]
      : [{ label: 'No 2026 Senate race', value: '' }];
    return { title: `${c.name}, ${c.state}`, rows: rowsOut, stateLink: `${base}/state/${c.state}`, text: describe(c) };
  }

  function pointer(e: PointerEvent) {
    if (status !== 'ready' || !tester) return null;
    const r = canvas.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    const [ax, ay] = toAtlas(px, py, size.w, size.h);
    const hit = tester.find(ax, ay);
    return hit ? { shape: hit, x: px, y: py } : null;
  }
  function move(e: PointerEvent) {
    if (e.pointerType === 'touch' || pinned) return;
    const h = pointer(e);
    const changed = h?.shape.geoid !== hover?.shape.geoid;
    hover = h;
    if (changed) { draw(); live = h ? describe(h.shape) : ''; }
  }
  function click(e: PointerEvent) {
    const h = pointer(e);
    if (!h || !rows.has(h.shape.geoid)) { pinned = null; return; }
    if (e.pointerType === 'touch') { pinned = { shape: h.shape }; hover = null; draw(); live = describe(h.shape); return; }
    goto(`${base}/state/${h.shape.state}`);
  }

  $effect(() => { viewState.view; if (status === 'ready') recolor(); });
  $effect(() => { pinned; hover; if (status === 'ready') draw(); });
  onMount(() => {
    load();
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);
    return () => { ro.disconnect(); cancelAnimationFrame(anim); };
  });
</script>

<div class="mapwrap" bind:this={wrap}>
  <canvas
    bind:this={canvas}
    style:height="{size.h}px"
    aria-label="Map of projected 2026 Senate county results. A data table with the same values follows the map."
    onpointermove={move}
    onpointerleave={() => { if (!pinned) { hover = null; live = ''; } }}
    onpointerup={click}
  >Map of projected 2026 Senate county results. The race table below the map has the same values.</canvas>
  {#if status === 'loading'}
    <div class="overlay" aria-live="polite"><span class="spinner" aria-hidden="true"></span> Loading map…</div>
  {:else if status === 'error'}
    <div class="overlay err" role="alert">
      <p>The map could not be loaded ({errorMsg}).</p>
      <img src="{base}/og/national.png" alt="Static national projection map" width="600" height="315" />
      <p><button type="button" class="btn" onclick={load}>Retry</button></p>
    </div>
  {/if}
  {#if hover && !pinned}
    <CountyTooltip content={tipFor(hover.shape)} x={hover.x} y={hover.y} containerWidth={size.w} containerHeight={size.h} />
  {/if}
  {#if pinned}
    <CountyTooltip content={tipFor(pinned.shape)} pinned onclose={() => { pinned = null; draw(); }} />
  {/if}
  <p class="sr-only" aria-live="polite">{live}</p>
</div>

<style>
  .mapwrap { position: relative; width: 100%; background: var(--map-bg); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; }
  canvas { display: block; width: 100%; touch-action: manipulation; cursor: pointer; }
  .overlay { position: absolute; inset: 0; display: grid; place-content: center; justify-items: center; background: color-mix(in srgb, var(--map-bg) 85%, transparent); text-align: center; gap: 0.5rem; padding: 1rem; overflow: auto; }
  .overlay img { max-width: 100%; height: auto; }
  .spinner { display: inline-block; width: 1em; height: 1em; border: 2px solid var(--line); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; vertical-align: -2px; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
