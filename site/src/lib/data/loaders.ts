// Data loaders: fetch published artifacts with ?v=<run_id> cache busting (plan §10.6). Failures raise typed errors so
// pages can show the documented empty/error states instead of crashing.
import type { Changes, CountiesNational, DataHealth, MethodologyParams, StateFile, Summary } from './types';

export class DataError extends Error {
  constructor(public status: number, public url: string, message?: string) {
    super(message ?? `Failed to load ${url} (${status})`);
    this.name = 'DataError';
  }
}

export type Fetch = typeof fetch;

export async function getJson<T>(f: Fetch, url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await f(url, init);
  } catch (e) {
    throw new DataError(0, url, `Network error loading ${url}: ${(e as Error).message}`);
  }
  if (!res.ok) throw new DataError(res.status, url);
  try {
    return (await res.json()) as T;
  } catch {
    throw new DataError(res.status, url, `Invalid JSON in ${url}`);
  }
}

export const dataUrl = (base: string, path: string, runId?: string): string =>
  `${base}/data/${path}${runId ? `?v=${encodeURIComponent(runId)}` : ''}`;

export const loadSummary = (f: Fetch, base: string) => getJson<Summary>(f, dataUrl(base, 'summary.json'), { cache: 'no-store' });
export const loadChanges = (f: Fetch, base: string, runId: string) =>
  getJson<Changes>(f, dataUrl(base, 'changes.json', runId));
export const loadCountiesNational = (f: Fetch, base: string, runId: string) =>
  getJson<CountiesNational>(f, dataUrl(base, 'counties_national.json', runId));
export const loadTopo = <T>(f: Fetch, base: string, path: string, runId: string) =>
  getJson<T>(f, dataUrl(base, `topo/${path}`, runId));
export const loadState = (f: Fetch, base: string, st: string, runId: string) =>
  getJson<StateFile>(f, dataUrl(base, `states/${st}.json`, runId));
export const loadHealth = (f: Fetch, base: string, runId: string) =>
  getJson<DataHealth>(f, dataUrl(base, 'data_health.json', runId));
export const loadParams = (f: Fetch, base: string, runId: string) =>
  getJson<MethodologyParams>(f, dataUrl(base, 'methodology_params.json', runId));

/** A national-map row keyed by geoid (counties_national.json compact format, plan §9.4). */
export interface CountyRow { geoid: string; pres2024: number; proj: number; shift: number; p: number }

export function parseCountiesNational(d: CountiesNational): Map<string, CountyRow> {
  const idx: Record<string, number> = Object.fromEntries(d.cols.map((c, i) => [c, i]));
  for (const k of ['geoid', 'pres2024', 'proj', 'shift', 'p']) {
    if (!(k in idx)) throw new Error(`counties_national.json missing column ${k}`);
  }
  const out = new Map<string, CountyRow>();
  for (const r of d.rows) {
    const geoid = String(r[idx.geoid!]);
    out.set(geoid, {
      geoid, pres2024: Number(r[idx.pres2024!]), proj: Number(r[idx.proj!]),
      shift: Number(r[idx.shift!]), p: Number(r[idx.p!])
    });
  }
  return out;
}
