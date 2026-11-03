import { describe, expect, it, vi } from 'vitest';
import { DataError, dataUrl, getJson, loadState, loadSummary, parseCountiesNational } from '../../src/lib/data/loaders';

const ok = (body: unknown) => vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })) as unknown as typeof fetch;

describe('data loaders with mocked failures', () => {
  it('builds cache-busted URLs under the base path', () => {
    expect(dataUrl('/repo', 'states/GA.json', '2026 11')).toBe('/repo/data/states/GA.json?v=2026%2011');
    expect(dataUrl('', 'summary.json')).toBe('/data/summary.json');
  });
  it('returns parsed JSON', async () => expect(await getJson(ok({ a: 1 }), '/x')).toEqual({ a: 1 }));
  it('maps HTTP errors to DataError with status', async () => {
    const f = vi.fn(async () => new Response('nope', { status: 404 })) as unknown as typeof fetch;
    await expect(loadState(f, '', 'GA', 'r')).rejects.toMatchObject({ name: 'DataError', status: 404 });
  });
  it('maps network failure to DataError status 0', async () => {
    const f = vi.fn(async () => { throw new TypeError('Failed to fetch'); }) as unknown as typeof fetch;
    const e = await loadSummary(f, '').catch((x) => x);
    expect(e).toBeInstanceOf(DataError);
    expect(e.status).toBe(0);
  });
  it('maps invalid JSON to DataError', async () => {
    const f = vi.fn(async () => new Response('<html>', { status: 200 })) as unknown as typeof fetch;
    await expect(getJson(f, '/x')).rejects.toThrow(/Invalid JSON/);
  });
});

describe('counties_national.json compact format (plan §9.4)', () => {
  it('parses rows into a geoid map', () => {
    const m = parseCountiesNational({ cols: ['geoid', 'pres2024', 'proj', 'shift', 'p'], rows: [['13121', 46.2, 54.9, 8.7, 1.0], ['13135', -8.4, -0.4, 8.0, 0.41]] });
    expect(m.get('13135')).toEqual({ geoid: '13135', pres2024: -8.4, proj: -0.4, shift: 8, p: 0.41 });
  });
  it('is column-order independent and rejects missing columns', () => {
    const m = parseCountiesNational({ cols: ['p', 'shift', 'proj', 'pres2024', 'geoid'], rows: [[0.5, 1, 2, 3, '01001']] });
    expect(m.get('01001')?.proj).toBe(2);
    expect(() => parseCountiesNational({ cols: ['geoid'], rows: [] })).toThrow(/missing column/);
  });
});
