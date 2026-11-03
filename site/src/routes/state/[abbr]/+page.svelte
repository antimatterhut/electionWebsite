<script lang="ts">
  import { base } from '$app/paths';
  import { page } from '$app/state';
  import Toggle from '$lib/components/Toggle.svelte';
  import Legend from '$lib/components/Legend.svelte';
  import StateHeader from '$lib/components/StateHeader.svelte';
  import SwingDecomposition from '$lib/components/SwingDecomposition.svelte';
  import StateMap from '$lib/components/StateMap.svelte';
  import CountyTable from '$lib/components/CountyTable.svelte';
  import GroupSwings from '$lib/components/GroupSwings.svelte';
  import EarlyVotePanel from '$lib/components/EarlyVotePanel.svelte';
  import PollList from '$lib/components/PollList.svelte';
  import { useSummary } from '$lib/context';
  import { margin } from '$lib/format';
  import { siteUrl } from '$lib/seo';

  let { data } = $props();
  const get = useSummary();
  const summary = $derived(get());
  const race = $derived(summary?.races.find((r) => r.state === data.abbr) ?? null);
  const detail = $derived(data.detail && data.detail.counties.length ? data.detail : null);  // no counties (e.g. Alaska) => no county panels
  const runId = $derived(summary?.run_id ?? '');
  const title = $derived(race ? `${race.name ?? race.state} Senate 2026 projection by county` : `${data.abbr} Senate 2026`);
  const desc = $derived(race ? `${race.name} U.S. Senate 2026: projected ${margin(race.proj_margin)}${race.p_dside_win != null ? `, ${Math.round(race.p_dside_win * 100)}% chance the D-side candidate wins` : ''}, with county-level results.` : '');
  const canonical = $derived(`${siteUrl}${base}/state/${data.abbr}`);
</script>

<svelte:head>
  <title>{title}</title>
  <meta name="description" content={desc} />
  <link rel="canonical" href={canonical} />
  <meta property="og:title" content={title} />
  <meta property="og:description" content={desc} />
  <meta property="og:type" content="website" />
  <meta property="og:url" content={canonical} />
  <meta property="og:image" content="{siteUrl}{base}/og/{data.abbr}.png" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:updated_time" content={summary?.as_of ?? ''} />
  <meta name="twitter:card" content="summary_large_image" />
</svelte:head>

<div class="wrap grid">
  <nav aria-label="Breadcrumb"><a href="{base}/">← All races</a></nav>
  {#if race}
    <StateHeader {race} />
    {#if detail}
      <div class="sticky"><Toggle /> <Legend /></div>
      <StateMap abbr={data.abbr} counties={detail.counties} {runId} />
      <SwingDecomposition {race} weights={summary!.weights} />
      <CountyTable counties={detail.counties} abbr={data.abbr} />
      <div class="grid two">
        <GroupSwings groups={detail.groups} />
        <EarlyVotePanel ev={detail.early_vote} detail={race.ev_detail} component={race.components.early_vote} />
      </div>
      <PollList polls={detail.polls_recent} />
    {:else}
      <SwingDecomposition {race} weights={summary!.weights} />
      <p class="panel" role="status">
        Detailed county data isn't available for this race. <a href="{base}/#race-h">See the national race table</a>.
      </p>
    {/if}
  {:else}
    <p class="panel" role="alert">Projection unavailable. <a href="{base}/">Return to the national page.</a></p>
  {/if}
</div>

<style>
  .sticky { position: sticky; top: 0; z-index: 4; background: var(--bg); padding: 0.5rem 0; display: flex; flex-wrap: wrap; gap: 0.75rem 1.5rem; align-items: center; border-bottom: 1px solid var(--line); }
</style>
