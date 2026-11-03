<script lang="ts">
  import { margin, marginRange, pct } from '$lib/format';
  import type { Race } from '$lib/data/types';

  let { race }: { race: Race } = $props();
  const iv = $derived(race.interval80);
  const lo = $derived(Math.min(-20, iv?.[0] ?? -20));
  const hi = $derived(Math.max(20, iv?.[1] ?? 20));
  const pos = (v: number) => ((v - lo) / (hi - lo)) * 100;
  // D-side label rules (plan §2.2): an independent standing in as D-side is shown with a diamond and its own party.
  const dLabel = $derived(race.dside.party === 'D' ? 'Democratic nominee' : race.dside.party === 'I' ? 'Independent (D-side)' : 'D-side candidate');
</script>

<header class="sh">
  <h1>{race.name ?? race.state} U.S. Senate{race.special ? ' (special election)' : ''}</h1>
  <p class="muted">
    Class {race.class}{race.incumbent ? ` · incumbent ${race.incumbent} (${race.incumbent_party})` : ''}{race.rcv ? ' · ranked-choice general election' : ''}
  </p>
  <div class="cands">
    <div class="cand d"><span class="role">{dLabel}{race.dside.party === 'I' ? ' ◆' : ''}</span><strong>{race.dside.name ?? 'To be determined'}</strong></div>
    <div class="cand r"><span class="role">Republican nominee</span><strong>{race.rside.name ?? 'To be determined'}</strong></div>
  </div>
  <div class="stats">
    <div><span class="muted">Projected margin</span><strong>{margin(race.proj_margin)}</strong></div>
    <div><span class="muted">Chance D-side wins</span><strong>{pct(race.p_dside_win)}</strong></div>
    <div><span class="muted">80% interval</span><strong>{marginRange(iv)}</strong></div>
  </div>
  {#if iv}
    <svg viewBox="0 0 100 14" class="range" role="img" aria-label="80% interval {marginRange(iv)}, projection {margin(race.proj_margin)}" preserveAspectRatio="none">
      <rect x="0" y="5" width="100" height="4" fill="var(--panel-2)" />
      <rect x={pos(iv[0])} y="3" width={pos(iv[1]) - pos(iv[0])} height="8" fill="var(--accent)" opacity="0.55" />
      <line x1={pos(0)} x2={pos(0)} y1="0" y2="14" stroke="var(--text)" stroke-width="1" vector-effect="non-scaling-stroke" />
      <line x1={pos(race.proj_margin)} x2={pos(race.proj_margin)} y1="1" y2="13" stroke="var(--text)" stroke-width="2.5" vector-effect="non-scaling-stroke" />
    </svg>
    <div class="axis muted"><span>R+{Math.abs(Math.round(lo))}</span><span class="even" style:left="{pos(0)}%">Even</span><span>D+{Math.round(hi)}</span></div>
  {/if}
  {#if race.swing_source === 'national_fallback'}
    <p class="notice" role="note">No recent state polling; this projection uses the national environment, adjusted for the state's demographic mix.</p>
  {/if}
</header>

<style>
  .cands { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.75rem; margin: 0.75rem 0; }
  .cand { border-left: 5px solid var(--dem); padding: 0.4rem 0.75rem; background: var(--panel); border-radius: 0 var(--radius) var(--radius) 0; display: grid; }
  .cand.r { border-left-color: var(--rep); }
  .role { font-size: 0.8rem; color: var(--muted); }
  .stats { display: flex; flex-wrap: wrap; gap: 0.5rem 2rem; }
  .stats div { display: grid; }
  .stats strong { font-size: 1.4rem; }
  .range { width: 100%; max-width: 560px; height: 22px; display: block; margin-top: 0.5rem; }
  .axis { position: relative; display: flex; justify-content: space-between; max-width: 560px; font-size: 0.75rem; }
  .axis .even { position: absolute; transform: translateX(-50%); }
  .notice { margin-top: 0.75rem; padding: 0.5rem 0.75rem; background: var(--warn-bg); color: var(--warn-text); border-radius: 6px; }
</style>
