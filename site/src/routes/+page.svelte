<script lang="ts">
  import { base } from '$app/paths';
  import ChangesFeed from '$lib/components/ChangesFeed.svelte';
  import ComponentsPanel from '$lib/components/ComponentsPanel.svelte';
  import ControlGauge from '$lib/components/ControlGauge.svelte';
  import HeaderBar from '$lib/components/HeaderBar.svelte';
  import Legend from '$lib/components/Legend.svelte';
  import NationalMap from '$lib/components/NationalMap.svelte';
  import RaceTable from '$lib/components/RaceTable.svelte';
  import SeatHistogram from '$lib/components/SeatHistogram.svelte';
  import Toggle from '$lib/components/Toggle.svelte';
  import { useSummary } from '$lib/context';
  import { siteUrl } from '$lib/seo';

  const get = useSummary();
  const summary = $derived(get());
  const canonical = `${siteUrl}${base}/`;
</script>

<svelte:head>
  <title>2026 Senate county-level projection</title>
  <meta name="description" content="County-level projection of the 2026 U.S. Senate races: national environment, race polling, turnout and early vote, with uncertainty." />
  <link rel="canonical" href={canonical} />
  <meta property="og:title" content="2026 Senate county-level projection" />
  <meta property="og:description" content="County-level projection of the 2026 U.S. Senate races." />
  <meta property="og:type" content="website" />
  <meta property="og:url" content={canonical} />
  <meta property="og:image" content="{siteUrl}{base}/og/national.png" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:updated_time" content={summary?.as_of ?? ''} />
  <meta name="twitter:card" content="summary_large_image" />
</svelte:head>

<div class="wrap grid page">
  <HeaderBar {summary} />
  <div class="grid two hero">
    <ControlGauge {summary} />
    <SeatHistogram {summary} />
  </div>
  <div class="sticky"><Toggle /><Legend /></div>
  <div class="mapblock">
    {#if summary}
      <NationalMap runId={summary.run_id} />
    {:else}
      <div class="skeleton" style="aspect-ratio: 1.6"></div>
    {/if}
  </div>
  {#if summary}
    <RaceTable races={summary.races} />
  {/if}
  <div class="grid two">
    <ComponentsPanel {summary} />
    {#if summary}<ChangesFeed runId={summary.run_id} />{/if}
  </div>
</div>

<style>
  /* Mobile: map first (plan §10.6). Order is visual only; the DOM keeps the headline numbers first. */
  @media (max-width: 720px) {
    .page { display: flex; flex-direction: column; }
    .sticky { order: -2; }
    .mapblock { order: -1; }
  }
  .sticky { position: sticky; top: 0; z-index: 4; background: var(--bg); padding: 0.5rem 0; display: flex; flex-wrap: wrap; gap: 0.75rem 1.5rem; align-items: center; border-bottom: 1px solid var(--line); }
</style>
