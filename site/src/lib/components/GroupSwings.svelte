<script lang="ts">
  import { groupLabel, signed } from '$lib/format';
  import type { GroupSwing } from '$lib/data/types';

  let { groups }: { groups: GroupSwing[] } = $props();
  const Z80 = 1.2816;
  const lo = $derived(Math.min(0, ...groups.map((g) => g.swing - Z80 * g.sd)) - 1);
  const hi = $derived(Math.max(0, ...groups.map((g) => g.swing + Z80 * g.sd)) + 1);
  const x = (v: number) => ((v - lo) / (hi - lo)) * 100;
</script>

<section class="panel" aria-labelledby="gs-h">
  <h2 id="gs-h">Swing by group</h2>
  <p class="muted small">Points toward Democrats since 2024, with 80% intervals. Shrinkage is the share of each estimate pulled toward the overall swing; higher means less group-specific information.</p>
  <table>
    <caption class="sr-only">Estimated group swings with 80% intervals</caption>
    <thead><tr><th scope="col">Group</th><th scope="col" class="num">Swing</th><th scope="col" class="num">Shrinkage</th><th scope="col" class="chartcol"><span class="sr-only">Chart</span></th></tr></thead>
    <tbody>
      {#each groups as g}
        <tr>
          <th scope="row">{groupLabel(g.group)}</th>
          <td class="num">{signed(g.swing)} ± {(Z80 * g.sd).toFixed(1)}</td>
          <td class="num" title="{g.n_polls} crosstab polls">{Math.round(g.shrinkage * 100)}%</td>
          <td class="chartcol" aria-hidden="true">
            <svg viewBox="0 0 100 10" preserveAspectRatio="none">
              <line x1={x(0)} x2={x(0)} y1="0" y2="10" stroke="var(--muted)" stroke-width="0.5" />
              <line x1={x(g.swing - Z80 * g.sd)} x2={x(g.swing + Z80 * g.sd)} y1="5" y2="5" stroke="var(--text)" stroke-width="1" />
              <circle cx={x(g.swing)} cy="5" r="2.2" fill="var(--accent)" stroke="var(--bg)" stroke-width="0.6" opacity={1 - 0.5 * g.shrinkage} />
            </svg>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</section>

<style>
  .chartcol { width: 45%; min-width: 120px; }
  svg { width: 100%; height: 20px; display: block; }
  .small { font-size: 0.85rem; }
</style>
