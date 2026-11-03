// Contract tests on the published artifacts (plan §9, §11.3 "cross-file consistency") and the decomposition logic.
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { decompose } from '../../src/lib/decompose';
import { fillParams } from '../../src/lib/methodology';
import { RACE_STATES } from '../../src/lib/states';
import type { MethodologyParams, Race, StateFile, Summary } from '../../src/lib/data/types';

const here = dirname(fileURLToPath(import.meta.url));
const data = join(here, '..', '..', 'static', 'data');
const read = <T>(p: string): T => JSON.parse(readFileSync(join(data, p), 'utf8')) as T;
const summary = read<Summary>('summary.json');

describe('summary.json', () => {
  it('has 35 races matching the prerender list and the manual races table', () => {
    expect(summary.races.map((r) => r.state).sort()).toEqual([...RACE_STATES].sort());
    const csv = readFileSync(join(here, '..', '..', '..', 'data', 'manual', 'races_2026.csv'), 'utf8').split('\n').slice(1).filter(Boolean);
    expect(csv.map((l) => l.split(',')[0]).sort()).toEqual([...RACE_STATES].sort());
  });
  it('proj_margin = pres2024 + state_swing + turnout + early_vote within 0.15 (rounding)', () => {
    for (const r of summary.races) {
      const c = r.components;
      const sum = r.pres2024_margin + (c.state_swing ?? 0) + (c.turnout ?? 0) + (c.early_vote ?? 0);
      expect(Math.abs(sum - r.proj_margin), r.state).toBeLessThan(0.15);
    }
  });
  it('probabilities and intervals are coherent', () => {
    for (const r of summary.races) {
      expect(r.p_dside_win).toBeGreaterThanOrEqual(0);
      expect(r.p_dside_win).toBeLessThanOrEqual(1);
      const [lo, hi] = r.interval80!;
      expect(lo).toBeLessThanOrEqual(r.proj_margin);
      expect(hi).toBeGreaterThanOrEqual(r.proj_margin);
    }
    const dist = summary.national.senate!.distribution;
    expect(Object.values(dist).reduce((a, b) => a + b, 0)).toBeGreaterThan(0.97);
  });
  it('fixture builds are labelled', () => {
    if (summary.run_id.endsWith('-mock')) expect(summary.mock).toBe(true);
  });
});

describe('states/<ST>.json', () => {
  it('exists for every race and agrees with the summary', () => {
    const files = readdirSync(join(data, 'states')).map((f) => f.replace('.json', '')).sort();
    expect(files).toEqual([...RACE_STATES].sort());
    for (const r of summary.races) {
      const s = read<StateFile>(`states/${r.state}.json`);
      expect(s.run_id).toBe(summary.run_id);
      expect(s.counties.length).toBeGreaterThan(0);
      const w = s.counties.reduce((a, c) => a + c.votes_proj, 0);
      const mean = s.counties.reduce((a, c) => a + c.votes_proj * c.shift, 0) / w;
      // county shifts average (vote-weighted) to the state shift: the calibration constraint, up to 0.1-pt rounding and
      // the use of projected votes for weights in the fixture
      expect(Math.abs(mean - r.shift), r.state).toBeLessThan(1.0);
    }
  });
  it('every state county exists in the national table and the topology', () => {
    const nat = read<{ cols: string[]; rows: Array<Array<string | number>> }>('counties_national.json');
    const ids = new Set(nat.rows.map((x) => x[0]));
    const topo = read<{ objects: { counties: { geometries: Array<{ id: string }> } } }>('topo/counties.topojson');
    const tids = new Set(topo.objects.counties.geometries.map((g) => g.id));
    for (const r of summary.races) for (const c of read<StateFile>(`states/${r.state}.json`).counties) {
      expect(ids.has(c.geoid)).toBe(true);
      expect(tids.has(c.geoid)).toBe(true);
    }
  });
});

describe('topology budgets (plan §10.6)', () => {
  it('national <= 700 KB and each state <= 150 KB gzip', async () => {
    const { gzipSync } = await import('node:zlib');
    const gz = (p: string) => gzipSync(readFileSync(join(data, p))).length;
    expect(gz('topo/counties.topojson')).toBeLessThanOrEqual(700 * 1024);
    for (const s of RACE_STATES) expect(gz(`topo/states/${s}.topojson`), s).toBeLessThanOrEqual(150 * 1024);
    for (const f of ['summary.json', 'counties_national.json']) expect(gz(f)).toBeLessThanOrEqual(250 * 1024);
  });
});

const race = (over: Partial<Race> = {}): Race => ({
  state: 'GA', class: 2, special: false, incumbent: 'x', incumbent_party: 'D', dside: { name: 'a', party: 'D' }, rside: { name: 'b', party: 'R' },
  rcv: false, pres2024_margin: -2.2, proj_margin: 7.4, shift: 9.6, swing_source: 'combined',
  components: { national: 10.5, state_poll: 8.2, market: null, market_weight: 0, state_swing: 9.7333, turnout: -0.4, early_vote: 0.3 },
  polls: { n: 5, avg_margin: 6, n_eff: 3.8 }, ...over
});

describe('swing decomposition', () => {
  it('2:1 split of the pre-market swing and steps sum to the projection', () => {
    const d = decompose(race({ proj_margin: -2.2 + 9.7333 - 0.4 + 0.3 }), { national: 2, state_poll: 1 });
    const by = Object.fromEntries(d.steps.map((s) => [s.key, s.value]));
    expect(by.national).toBeCloseTo((2 * 10.5) / 3, 6);
    expect(by.polls).toBeCloseTo(8.2 / 3, 6);
    expect(d.total).toBeCloseTo(7.4333, 3);
  });
  it('unpolled states have only the national component', () => {
    const r = race({ swing_source: 'national_fallback', components: { national: 10.5, state_poll: null, market: null, market_weight: 0, state_swing: 10.5, turnout: 0, early_vote: 0 } });
    const d = decompose(r, { national: 2, state_poll: 1 });
    expect(d.steps.find((s) => s.key === 'polls')!.value).toBe(0);
    expect(d.steps.find((s) => s.key === 'national')!.value).toBeCloseTo(10.5, 9);
  });
  it('market blend keeps the identity and shows the market step', () => {
    const swing = 0.9 * ((2 * 10 + 6) / 3) + 0.1 * 4;
    const r = race({ components: { national: 10, state_poll: 6, market: 4, market_weight: 0.1, state_swing: swing, turnout: 0, early_vote: 0 } });
    const d = decompose(r, { national: 2, state_poll: 1 });
    expect(d.steps.find((s) => s.key === 'market')!.value).toBeCloseTo(0.4, 9);
    expect(d.steps.find((s) => s.key === 'other')).toBeUndefined();
    expect(d.total).toBeCloseTo(r.pres2024_margin + swing, 9);
  });
  it('unexplained remainder (e.g. volume scaling) is shown, not hidden', () => {
    const r = race({ components: { national: 10, state_poll: 6, market: null, market_weight: 0, state_swing: 9, turnout: 0, early_vote: 0 } });
    expect(decompose(r, { national: 2, state_poll: 1 }).steps.find((s) => s.key === 'other')).toBeDefined();
  });
});

describe('methodology params', () => {
  const params = read<MethodologyParams>('methodology_params.json');
  it('fills placeholders and rejects unknown ones', () => {
    expect(fillParams('w {{weights.national}}:{{weights.state_poll}}', params)).toBe('w 2:1');
    expect(() => fillParams('{{nope.x}}', params)).toThrow(/unknown parameter/);
  });
  it('the methodology source only references known parameters', () => {
    const md = readFileSync(join(here, '..', '..', '..', 'docs', 'methodology.md'), 'utf8');
    expect(() => fillParams(md, params)).not.toThrow();
  });
  it('the OG cards exist', () => expect(existsSync(join(here, '..', '..', 'static', 'og', 'GA.png'))).toBe(true));
});
