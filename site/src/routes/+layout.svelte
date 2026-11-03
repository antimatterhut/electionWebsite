<script lang="ts">
  import '../app.css';
  import { base } from '$app/paths';
  import { invalidate } from '$app/navigation';
  import { page } from '$app/state';
  import { provideSummary } from '$lib/context';
  import { onMount } from 'svelte';
  import { cacheSummary, cachedSummary, viewState } from '$lib/stores.svelte';
  import type { Summary } from '$lib/data/types';

  let { data, children } = $props();

  // Last-good fallback (plan §10.2): remember every successful summary; if a refresh fails keep showing it, with a banner.
  let lastGood = $state<Summary | null>(null);
  $effect(() => {
    if (data.summary) {
      lastGood = data.summary;
      cacheSummary(JSON.stringify(data.summary));
    }
  });
  const summary = $derived(data.summary ?? lastGood);
  provideSummary(() => summary);

  onMount(() => {
    viewState.init();
    if (!data.summary) lastGood = cachedSummary<Summary>();
    // Pages stay open on election night: refresh when the tab regains focus, the network returns, or every 5 minutes.
    const refresh = () => void invalidate('app:summary');
    const onVisible = () => { if (!document.hidden) refresh(); };
    const timer = setInterval(refresh, 5 * 60_000);
    window.addEventListener('online', refresh);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(timer);
      window.removeEventListener('online', refresh);
      document.removeEventListener('visibilitychange', onVisible);
    };
  });

  const nav = [
    { href: '/', label: 'National' },
    { href: '/methodology', label: 'Methodology' },
    { href: '/about', label: 'About' }
  ];
  const active = (href: string) => (href === '/' ? page.url.pathname === `${base}` || page.url.pathname === `${base}/` : page.url.pathname.startsWith(`${base}${href}`));
  const mock = $derived(summary?.mock === true);
</script>

<a class="skip" href="#main">Skip to main content</a>
{#if mock}
  <div class="banner" role="note">
    <strong>Fixture data.</strong> County detail, intervals and probabilities on this build are synthetic test data, not a projection.
  </div>
{/if}
{#if !data.summary}
  <div class="banner error" role="alert">
    Projection unavailable{summary ? ' — last good run shown' : ''}. {data.summaryError}
  </div>
{/if}
<header class="top">
  <div class="wrap bar">
    <a class="brand" href="{base}/">2026 Senate county projection</a>
    <nav aria-label="Main">
      {#each nav as n}
        <a href="{base}{n.href === '/' ? '/' : n.href}" aria-current={active(n.href) ? 'page' : undefined}>{n.label}</a>
      {/each}
    </nav>
  </div>
</header>
<main id="main" tabindex="-1">
  {@render children()}
</main>
<footer>
  <div class="wrap">
    <p class="muted">
      Pre-election projection, not an official result and not a poll. See <a href="{base}/methodology">methodology</a> and
      <a href="{base}/about">about</a>.
    </p>
  </div>
</footer>

<style>
  .top { border-bottom: 1px solid var(--line); background: var(--bg); }
  .bar { display: flex; flex-wrap: wrap; gap: 0.5rem 1.5rem; align-items: center; justify-content: space-between; padding-block: 0.6rem; }
  .brand { font-weight: 700; color: var(--text); text-decoration: none; }
  nav { display: flex; gap: 1rem; }
  nav a { color: var(--text); padding: 0.25rem 0; }
  nav a[aria-current='page'] { font-weight: 700; border-bottom: 2px solid var(--accent); text-decoration: none; }
  main { min-height: 60vh; padding-block: 1rem 2rem; }
  main:focus { outline: none; }
  footer { border-top: 1px solid var(--line); padding-block: 1rem; font-size: 0.9rem; }
</style>
