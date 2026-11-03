<script lang="ts">
  import { decompose } from '$lib/decompose';
  import { margin, signed } from '$lib/format';
  import type { Race } from '$lib/data/types';

  let { race, weights }: { race: Race; weights: { national: number; state_poll: number } } = $props();
  const d = $derived(decompose(race, weights));
  // cumulative positions for the waterfall
  const rows = $derived.by(() => {
    let acc = race.pres2024_margin;
    const out = [{ label: '2024 presidential baseline', start: 0, end: acc, value: acc, total: true, note: undefined as string | undefined }];
    for (const s of d.steps) {
      out.push({ label: s.label, start: acc, end: acc + s.value, value: s.value, total: false, note: s.note });
      acc += s.value;
    }
    out.push({ label: 'Projection', start: 0, end: acc, value: acc, total: true, note: undefined });
    return out;
  });
  const lo = $derived(Math.min(0, ...rows.flatMap((r) => [r.start, r.end])) - 2);
  const hi = $derived(Math.max(0, ...rows.flatMap((r) => [r.start, r.end])) + 2);
  const x = (v: number) => ((v - lo) / (hi - lo)) * 100;
</script>

<section class="panel" aria-labelledby="sd-h">
  <h2 id="sd-h">How the projection is built</h2>
  <table>
    <caption class="sr-only">Steps from the 2024 baseline to the projected margin, in points (positive = toward Democrats)</caption>
    <thead><tr><th scope="col">Step</th><th scope="col" class="num">Points</th><th scope="col" class="chartcol"><span class="sr-only">Chart</span></th></tr></thead>
    <tbody>
      {#each rows as r}
        <tr class:total={r.total}>
          <th scope="row">{r.label}{#if r.note}<span class="muted note"> · {r.note}</span>{/if}</th>
          <td class="num">{r.total ? margin(r.value) : signed(r.value)}</td>
          <td class="chartcol" aria-hidden="true">
            <svg viewBox="0 0 100 10" preserveAspectRatio="none">
              <line x1={x(0)} x2={x(0)} y1="0" y2="10" stroke="var(--line)" stroke-width="0.5" />
              <rect x={x(Math.min(r.start, r.end))} width={Math.max(0.6, Math.abs(x(r.end) - x(r.start)))} y="2" height="6"
                    fill={r.total ? 'var(--muted)' : r.value >= 0 ? 'var(--dem)' : 'var(--rep)'} />
            </svg>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
  <p class="muted small">Early vote is shown separately and is capped at ±1.5 points. Turnout composition reflects midterm drop-off.</p>
</section>

<style>
  .chartcol { width: 45%; min-width: 120px; }
  svg { width: 100%; height: 18px; display: block; }
  tr.total th, tr.total td { font-weight: 700; }
  .note, .small { font-size: 0.85rem; }
</style>
