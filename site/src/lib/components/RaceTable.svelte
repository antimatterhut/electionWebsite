<script lang="ts">
  import { base } from '$app/paths';
  import { margin, pct, primary, shift as fmtShift } from '$lib/format';
  import { viewState } from '$lib/stores.svelte';
  import type { Race } from '$lib/data/types';

  let { races }: { races: Race[] } = $props();

  type Key = 'state' | 'proj' | 'shift' | 'p' | 'polls';
  let sortKey = $state<Key>('p');
  let dir = $state<1 | -1>(-1);
  let filter = $state<'all' | 'competitive' | 'lean'>('all');

  const p = (r: Race) => r.p_dside_win ?? 0.5;
  const val: Record<Key, (r: Race) => number | string> = {
    state: (r) => r.name ?? r.state, proj: (r) => r.proj_margin, shift: (r) => r.shift, p, polls: (r) => r.polls.n
  };
  const rows = $derived.by(() => {
    const f = races.filter((r) => filter === 'all' || (filter === 'competitive' ? p(r) > 0.1 && p(r) < 0.9 : p(r) > 0.02 && p(r) < 0.98));
    return [...f].sort((a, b) => {
      const x = val[sortKey](a), y = val[sortKey](b);
      return (typeof x === 'string' ? x.localeCompare(y as string) : (x as number) - (y as number)) * dir || a.state.localeCompare(b.state);
    });
  });
  function sort(k: Key) {
    if (sortKey === k) dir = dir === 1 ? -1 : 1;
    else { sortKey = k; dir = k === 'state' ? 1 : -1; }
  }
  const aria = (k: Key) => (sortKey === k ? (dir === 1 ? 'ascending' : 'descending') : 'none');
  const heads: Array<[Key, string, boolean]> = [['state', 'State', false], ['proj', 'Projected margin', true], ['shift', 'Shift from 2024', true], ['p', 'Chance D wins', true], ['polls', 'Polls', true]];
  const dside = (r: Race) => `${r.dside.name ?? 'D-side TBD'}${r.dside.party !== 'D' ? ' (' + r.dside.party + ')' : ''}`;
</script>

<section aria-labelledby="race-h">
  <div class="top">
    <h2 id="race-h">All 35 races</h2>
    <label>Show
      <select bind:value={filter}>
        <option value="all">All races</option>
        <option value="competitive">Competitive (10–90%)</option>
        <option value="lean">Not safe (2–98%)</option>
      </select>
    </label>
  </div>
  <p class="muted note">This table has the same values as the map. Primary column follows the selected view ({viewState.view === 'shift' ? 'shift' : 'projection'}).</p>
  {#if rows.length === 0}
    <p class="panel">No races match.</p>
  {:else}
    <table class="desktop">
      <caption class="sr-only">Races by projected margin, shift, win probability and polls</caption>
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
        {#each rows as r (r.state)}
          <tr>
            <th scope="row">
              <a href="{base}/state/{r.state}">{r.name ?? r.state}</a>{r.special ? ' (special)' : ''}
              {#if r.dside.party === 'I'}<span title="Independent standing in as the D-side candidate" aria-label="independent D-side candidate"> ◆</span>{/if}
            </th>
            <td class="num"><strong>{primary(viewState.view, r.proj_margin, r.shift)}</strong>{viewState.view === 'shift' ? ` (${margin(r.proj_margin)})` : ''}</td>
            <td class="num">{viewState.view === 'shift' ? margin(r.shift) : fmtShift(r.shift)}</td>
            <td class="num">{pct(r.p_dside_win)}</td>
            <td class="num">{r.polls.n}</td>
          </tr>
        {/each}
      </tbody>
    </table>
    <ul class="cards" aria-label="Races">
      {#each rows as r (r.state)}
        <li class="panel">
          <a href="{base}/state/{r.state}"><strong>{r.name ?? r.state}</strong></a>{r.special ? ' (special)' : ''}
          <div class="muted">{dside(r)}</div>
          <div>{primary(viewState.view, r.proj_margin, r.shift)} · {pct(r.p_dside_win)} D win · {r.polls.n} polls</div>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .top { display: flex; justify-content: space-between; align-items: end; flex-wrap: wrap; gap: 0.5rem; }
  select { padding: 0.3rem; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; }
  .note { font-size: 0.85rem; }
  .sortbtn { text-decoration: none; font-weight: 600; color: var(--muted); font-size: 0.85rem; }
  .cards { display: none; list-style: none; padding: 0; margin: 0; gap: 0.6rem; }
  @media (max-width: 720px) {
    .desktop { display: none; }
    .cards { display: grid; }
  }
</style>
