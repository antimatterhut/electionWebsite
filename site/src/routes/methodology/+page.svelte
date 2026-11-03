<script lang="ts">
  import { base } from '$app/paths';
  import { siteUrl } from '$lib/seo';

  let { data } = $props();
  const cycles = $derived(data.backtest ? Object.entries(data.backtest.cycles) : []);
  const jsonLd = $derived(
    JSON.stringify({
      '@context': 'https://schema.org', '@type': 'Dataset', name: '2026 U.S. Senate county-level projection',
      description: 'County-level projected margins and win probabilities for the 2026 U.S. Senate races.',
      url: `${siteUrl}${base}/`, isAccessibleForFree: true, license: 'https://creativecommons.org/licenses/by-sa/4.0/',
      temporalCoverage: '2026'
    }).replace(/</g, '\\u003c')
  );
</script>

<svelte:head>
  <title>Methodology - 2026 Senate county projection</title>
  <meta name="description" content="How the county-level 2026 Senate projection is built: baseline, national swing, race polls, ecological inference, calibration, turnout, early vote, uncertainty and backtests." />
  <link rel="canonical" href="{siteUrl}{base}/methodology" />
  {@html `<script type="application/ld+json">${jsonLd}</script>`}
</svelte:head>

<div class="wrap prose">
  {@html data.html.before}
  <div class="bt">
    {#if cycles.length}
      <table>
        <caption>Backtest, state level (one day before Election Day)</caption>
        <thead><tr><th scope="col">Cycle</th><th scope="col" class="num">Races</th><th scope="col" class="num">State RMSE</th><th scope="col" class="num">Uniform-swing RMSE</th><th scope="col" class="num">Bias</th><th scope="col" class="num">Brier</th><th scope="col" class="num">80% coverage</th></tr></thead>
        <tbody>
          {#each cycles as [yr, c]}
            <tr>
              <th scope="row">{yr}</th><td class="num">{c.metrics.n_races}</td><td class="num">{c.metrics.state_rmse.toFixed(2)}</td>
              <td class="num">{c.metrics.naive_rmse.toFixed(2)}</td><td class="num">{c.metrics.bias.toFixed(2)}</td>
              <td class="num">{c.sim ? c.sim.brier.toFixed(3) : 'n/a'}</td><td class="num">{c.sim ? c.sim.coverage80.toFixed(2) : 'n/a'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {:else}
      <p class="panel">Backtest results are not available for this build.</p>
    {/if}
  </div>
  {@html data.html.after}
</div>

<style>
  .prose { max-width: 800px; }
  .prose :global(h2) { margin-top: 1.75rem; }
  .bt { overflow-x: auto; margin: 0.75rem 0; }
  caption { text-align: left; font-weight: 600; padding-bottom: 0.4rem; }
</style>
