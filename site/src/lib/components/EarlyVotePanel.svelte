<script lang="ts">
  import { signed } from '$lib/format';
  import type { EarlyVote, EvDetail } from '$lib/data/types';

  let { ev, detail, component }: { ev: EarlyVote | null; detail?: EvDetail; component: number | null } = $props();
  const W = 520, H = 220, P = { l: 48, r: 12, t: 10, b: 30 };
  const curves = $derived(Object.entries(ev?.curves ?? {}));
  const xMax = $derived(Math.max(1, ...curves.flatMap(([, c]) => c.map((p) => p[0]))));
  const yMax = $derived(Math.max(1, ...curves.flatMap(([, c]) => c.map((p) => p[1]))));
  const sx = (d: number) => P.l + ((xMax - d) / xMax) * (W - P.l - P.r); // days out runs right-to-left
  const sy = (v: number) => H - P.b - (v / yMax) * (H - P.t - P.b);
  const dash: Record<string, string> = { '2026': '', '2022': '6 3', '2018': '2 3', '2024': '10 3 2 3' };
  const label: Record<EvDetail, string> = { full: 'Party / demographic detail', county_only: 'County totals only', total_only: 'State totals only', none: 'No early-vote data' };
</script>

<section class="panel" aria-labelledby="ev-h">
  <h2 id="ev-h">Early vote <span class="badge" data-detail={detail ?? 'none'}>{label[detail ?? 'none']}</span></h2>
  {#if !ev}
    <p class="muted">No early-vote data for this race yet.</p>
  {:else}
    <p>
      Component: <strong>{signed(component)} pts</strong>{ev.cap_binding ? ' (capped at ±1.5)' : ''}. Ballots cast {ev.as_of_days_out} day(s) before Election Day vs 2022:
      <strong>{ev.vs_2022 ? `${ev.vs_2022.total_ratio.toFixed(2)}×` : 'n/a'}</strong>, 2018: <strong>{ev.vs_2018 ? `${ev.vs_2018.total_ratio.toFixed(2)}×` : 'n/a'}</strong>,
      2024: <strong>{ev.vs_2024 ? `${ev.vs_2024.total_ratio.toFixed(2)}×` : 'n/a'}</strong>.
    </p>
    {#if curves.length}
      <svg viewBox="0 0 {W} {H}" role="img" aria-label="Cumulative early ballots by days before Election Day for {curves.map(([k]) => k).join(', ')}">
        <line x1={P.l} x2={P.l} y1={P.t} y2={H - P.b} stroke="var(--line)" />
        <line x1={P.l} x2={W - P.r} y1={H - P.b} y2={H - P.b} stroke="var(--line)" />
        {#each curves as [k, pts], i}
          <polyline fill="none" stroke={k === '2026' ? 'var(--text)' : ['var(--dem)', 'var(--rep)', '#6a51a3'][i % 3]} stroke-width={k === '2026' ? 3 : 1.6}
                    stroke-dasharray={dash[k] ?? ''} points={pts.map(([d, v]) => `${sx(d)},${sy(v)}`).join(' ')} />
        {/each}
        <text x={W / 2} y={H - 4} text-anchor="middle" font-size="11" fill="var(--muted)">days before Election Day</text>
        <text x={P.l - 6} y={P.t + 8} text-anchor="end" font-size="10" fill="var(--muted)">{Math.round(yMax / 1000)}k</text>
        <text x={P.l - 6} y={H - P.b} text-anchor="end" font-size="10" fill="var(--muted)">0</text>
      </svg>
      <ul class="key">
        {#each curves as [k]}<li><svg width="34" height="8" aria-hidden="true"><line x1="0" x2="34" y1="4" y2="4" stroke="var(--text)" stroke-width="2" stroke-dasharray={dash[k] ?? ''} /></svg> {k}</li>{/each}
      </ul>
    {/if}
    {#if ev.party_share}
      <p class="muted small">Party-registration share of early ballots: {#each Object.entries(ev.party_share) as [yr, s], i}{i ? '; ' : ''}{yr}: D {Math.round((s.D ?? 0) * 100)}% / R {Math.round((s.R ?? 0) * 100)}%{/each}.</p>
    {/if}
  {/if}
</section>

<style>
  .badge { font-size: 0.7rem; font-weight: 600; padding: 0.1rem 0.5rem; border-radius: 999px; background: var(--panel-2); border: 1px solid var(--line); vertical-align: middle; }
  svg { width: 100%; height: auto; max-width: 560px; display: block; }
  .key { display: flex; gap: 1rem; list-style: none; padding: 0; margin: 0.25rem 0; font-size: 0.85rem; }
  .small { font-size: 0.85rem; }
</style>
