import { base } from '$app/paths';
import { loadSummary, DataError } from '$lib/data/loaders';
import type { Summary } from '$lib/data/types';

export const prerender = true;
export const trailingSlash = 'never';

export async function load({ fetch, depends }) {
  depends('app:summary'); // re-run via invalidate('app:summary') for the periodic refresh
  try {
    const summary: Summary = await loadSummary(fetch, base);
    return { summary, summaryError: null as string | null };
  } catch (e) {
    // The page falls back to the last good copy cached in localStorage (plan §10.2 ControlGauge error state).
    return { summary: null as Summary | null, summaryError: e instanceof DataError ? e.message : String(e) };
  }
}
