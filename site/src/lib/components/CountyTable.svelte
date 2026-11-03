<script lang="ts">
  import { int, margin, marginRange, pct, shift as fmtShift } from '$lib/format';
  import { csvEscape } from '$lib/csv';
  import { viewState } from '$lib/stores.svelte';
  import type { County } from '$lib/data/types';

  let { counties, abbr }: { counties: County[]; abbr: string } = $props();

  type Key = 'name' | 'pres' | 'proj' | 'shift' | 'p' | 'votes';
  let q = $state('');
  let sortKey = $state<Key>('votes');
  let dir = $state<1 | -1>(-1);
  const get: Record<Key, (c: County) => number | string> = {
    name: (c) => c.name, pres: (c) => c.pres2024_margin, proj: (c) => c.proj_margin, shift: (c) => c.shift,
    p: (c) => c.p_dside_win, votes: (c) => c.votes_proj
  };
  const rows = $derived.by(() => {
    const t = q.trim().toLowerCase();
    return counties
      .filter((c) => !t || c.name.toLowerCase().includes(t))
      .sort((a, b) => {
        const x = get[sortKey](a), y = get[sortKey](b);
        return (typeof x === 'string' ? x.localeCompare(y as string) : (x as number) - (y as number)) * dir || a.geoid.localeCompare(b.geoid);
      });
  });
  function sort(k: Key) {
    if (sortKey === k) dir = dir === 1 ? -1 : 1;
    else { sortKey = k; dir = k === 'name' ? 1 : -1; }
  }
  const aria = (k: Key) => (sortKey === k ? (dir === 1 ? 'ascending' : 'descending') : 'none');
  const heads: Array<[Key, string, boolean]> = [['name', 'County', false], ['pres', '2024 president', true], ['proj', 'Projected', true], ['shift', 'Shift', true], ['p', 'Chance D', true], ['votes', 'Expected votes', true]];

  function download() {
    const cols = ['geoid', 'name', 'pres2024_margin', 'proj_margin', 'shift', 'interval80_lo', 'interval80_hi', 'p_dside_win', 'votes_2024', 'votes_proj'];
    const lines = [cols.join(',')];
    for (const c of rows) {
      lines.push([c.geoid, c.name, c.pres2024_margin, c.proj_margin, c.shift, c.interval80[0], c.interval80[1], c.p_dside_win, c.votes_2024, c.votes_proj].map(csvEscape).join(','));
    }
    const url = URL.createObjectURL(new Blob([lines.join('\n') + '\n'], { type: 'text/csv;charset=utf-8' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: `${abbr}_counties.csv` });
    document.body.append(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }
</script>

<section aria-labelledby="ct-h">
  <div class="top">
    <h2 id="ct-h">Counties</h2>
    <label>Search <input type="search" bind:value={q} placeholder="County name" /></label>
    <button type="button" class="btn" onclick={download}>Download CSV</button>
  </div>
  <div class="scroll">
    <table>
      <caption class="sr-only">County projections for {abbr}; same values as the map</caption>
      <thead>
        <tr>
          {#each heads as [k, label, num]}
            <th scope="col" class:num aria-sort={aria(k)}>
              <button type="button" class="link sortbtn" onclick={() => sort(k)}>{label}{sortKey === k ? (dir === 1 ? ' ▲' : ' ▼') : ''}</button>
            </th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each rows as c (c.geoid)}
          <tr>
            <th scope="row">{c.name}</th>
            <td class="num">{margin(c.pres2024_margin)}</td>
            <td class="num" title="80%: {marginRange(c.interval80)}">{viewState.view === 'projection' ? '' : ''}<strong>{margin(c.proj_margin)}</strong></td>
            <td class="num">{fmtShift(c.shift)}</td>
            <td class="num">{pct(c.p_dside_win)}</td>
            <td class="num">{int(c.votes_proj)}</td>
          </tr>
        {:else}
          <tr><td colspan="6">No counties match.</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</section>

<style>
  .top { display: flex; flex-wrap: wrap; gap: 0.75rem 1.25rem; align-items: end; justify-content: space-between; }
  .top h2 { margin: 0; }
  input { padding: 0.35rem 0.5rem; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; }
  .scroll { overflow-x: auto; max-height: 520px; overflow-y: auto; margin-top: 0.5rem; border: 1px solid var(--line); border-radius: var(--radius); }
  thead th { position: sticky; top: 0; background: var(--panel); }
  .sortbtn { text-decoration: none; font-weight: 600; color: var(--muted); font-size: 0.85rem; }
</style>
