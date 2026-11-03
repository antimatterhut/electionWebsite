import { error } from '@sveltejs/kit';
import { base } from '$app/paths';
import { loadState } from '$lib/data/loaders';
import { RACE_STATES } from '$lib/states';
import type { StateFile } from '$lib/data/types';

export const prerender = true;
export const entries = () => RACE_STATES.map((abbr) => ({ abbr }));

export async function load({ params, fetch, parent }) {
  const { summary } = await parent();
  const abbr = params.abbr.toUpperCase();
  if (summary && !summary.races.some((r) => r.state === abbr)) error(404, `No 2026 Senate race for ${params.abbr}`);
  let detail: StateFile | null = null;
  let detailError: string | null = null;
  try {
    detail = await loadState(fetch, base, abbr, summary?.run_id ?? '');
  } catch (e) {
    detailError = (e as Error).message; // 404 => "Detailed county data isn't available for this race"
  }
  return { abbr, detail, detailError };
}
