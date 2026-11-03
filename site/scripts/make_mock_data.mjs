// Fixture artifacts for the frontend (plan §13 Phase 6: "mock data first").
//
// NOT A PROJECTION. State-level margins/components are taken from the real Phase 2 output (output/summary.json) when it
// exists; everything else (county swings, intervals, win probabilities, group swings, early vote, polls, seat
// distribution, changes) is synthetic and seeded. Every file is stamped mock:true and the UI shows a banner.
// County baselines (2024 margin, votes) are real (tonmcg 2024 county results).
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { feature } from 'topojson-client';
import { NAME_BY_PO, parseCsv, STATES } from './states.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');
const data = join(here, '..', 'static', 'data');
mkdirSync(join(data, 'states'), { recursive: true });

const rng = (() => { let a = 20261103; return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; })();
const normal = () => Math.sqrt(-2 * Math.log(rng() + 1e-12)) * Math.cos(2 * Math.PI * rng());
const r1 = (x) => Math.round(x * 10) / 10;
const r3 = (x) => Math.round(x * 1000) / 1000;
const phi = (x) => 0.5 * (1 + erf(x / Math.SQRT2));
function erf(x) { const s = Math.sign(x); x = Math.abs(x); const t = 1 / (1 + 0.3275911 * x);
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x); return s * y; }

const races = parseCsv(readFileSync(join(root, 'data', 'manual', 'races_2026.csv'), 'utf8'));
const realPath = join(root, 'output', 'summary.json');
const real = existsSync(realPath) ? JSON.parse(readFileSync(realPath, 'utf8')) : null;
const realBy = Object.fromEntries((real?.races ?? []).map((r) => [r.state, r]));
const asOf = real?.as_of ?? '2026-11-02';
const runId = (real?.run_id ?? '20261102T120000Z') + '-mock';

// ---- county baselines (real 2024 results) ----
const dir = join(root, 'data', 'raw', 'tonmcg_2024');
const csvDir = readdirSync(dir).sort().pop();
const res24 = new Map(parseCsv(readFileSync(join(dir, csvDir, '2024_US_County_Level_Presidential_Results.csv'), 'utf8'))
  .map((r) => [r.county_fips.padStart(5, '0'), r]));
const topo = JSON.parse(readFileSync(join(data, 'topo', 'counties.topojson'), 'utf8'));
const cfeatures = feature(topo, topo.objects.counties).features;

const GROUPS = ['wnh_college', 'wnh_noncollege', 'black', 'hispanic', 'asian', 'other'];
const DROP = { wnh_college: 0.85, wnh_noncollege: 0.74, black: 0.66, hispanic: 0.56, asian: 0.62, other: 0.6 };
const mk = (po) => {
  const sr = realBy[po];
  const csv = races.find((r) => r.state_po === po);
  const base = sr?.pres2024_margin ?? 0;
  const proj = sr?.proj_margin ?? base + 8;
  const comp = sr?.components ?? { national: 11, state_poll: null, market: null, market_weight: 0, state_swing: proj - base, turnout: 0, early_vote: 0 };
  return {
    state: po, name: NAME_BY_PO[po], class: Number(csv.class), special: csv.special === 'true',
    incumbent: csv.incumbent || null, incumbent_party: csv.incumbent_party,
    dside: { name: csv.dside_name || null, party: csv.dside_party, endorsed_by_dem: csv.dside_endorsed_by_dem === 'true' },
    rside: { name: csv.rside_name || null, party: csv.rside_party }, rcv: csv.rcv === 'true',
    pres2024_margin: r1(base), proj_margin: r1(proj), shift: r1(proj - base),
    swing_source: sr?.swing_source ?? 'combined', components: Object.fromEntries(Object.entries(comp).map(([k, v]) => [k, v == null ? null : r1(v)])),
    polls: sr?.polls ?? { n: 0, avg_margin: null, n_eff: 0 }
  };
};

const summaryRaces = [];
const countiesNational = { cols: ['geoid', 'pres2024', 'proj', 'shift', 'p'], rows: [] };
for (const po of races.map((r) => r.state_po).sort()) {
  const r = mk(po);
  const sigma = 4 + rng() * 1.5;
  r.interval80 = [r1(r.proj_margin - 1.2816 * sigma), r1(r.proj_margin + 1.2816 * sigma)];
  r.p_dside_win = r3(phi(r.proj_margin / sigma));
  r.ev_detail = ['full', 'county_only', 'total_only', 'none'][Math.min(3, Math.floor(rng() * 4.5))];
  r.ei_status = rng() < 0.9 ? 'ok' : 'fallback';
  r.county_method = r.ei_status === 'ok' ? 'ei_crosstab' : 'uniform';
  summaryRaces.push(r);

  const fs = cfeatures.filter((f) => f.properties.state === po);
  const rows = fs.map((f) => {
    const x = res24.get(f.properties.geoid);
    const votes = x ? Number(x.total_votes) : 2000 + Math.floor(rng() * 20000);
    const pres = x ? 100 * (Number(x.votes_dem) - Number(x.votes_gop)) / (Number(x.votes_dem) + Number(x.votes_gop)) : r.pres2024_margin + normal() * 12;
    const dem = Math.min(0.5, Math.max(0.02, 0.5 + pres / 140));
    const raw = [0.45 - dem * 0.3, 0.5 - dem * 0.4, 0.04 + dem * 0.3 * rng(), 0.05 + 0.15 * rng(), 0.01 + 0.04 * rng(), 0.03];
    const tot = raw.reduce((a, b) => a + Math.max(0.01, b), 0);
    const shares = Object.fromEntries(GROUPS.map((g, i) => [g, Math.max(0.01, raw[i]) / tot]));
    return { f, votes, pres, shares };
  });
  const w = rows.map((c) => c.votes);
  const W = w.reduce((a, b) => a + b, 0);
  const tilt = rows.map((c) => (c.shares.wnh_college - 0.2) * 12 - (c.shares.wnh_noncollege - 0.35) * 6 + normal() * 1.2);
  const lam = r.shift - rows.reduce((a, c, i) => a + (w[i] / W) * (tilt[i]), 0); // exact calibration: weighted mean = S
  const counties = rows.map((c, i) => {
    const shift = tilt[i] + lam;
    const proj = Math.max(-100, Math.min(100, c.pres + shift));
    const half = 1.2816 * (3 + 25 / Math.sqrt(Math.max(1, c.votes / 1000)) * 0.4);
    const turnout = Object.entries(c.shares).reduce((a, [g, s]) => a + s * DROP[g], 0);
    const gsw = Object.fromEntries(GROUPS.map((g) => [g, r1(r.shift + normal() * 2)]));
    return {
      geoid: c.f.properties.geoid, name: c.f.properties.name, pres2024_margin: r1(c.pres), proj_margin: r1(proj), shift: r1(proj - c.pres),
      interval80: [r1(proj - half), r1(proj + half)], votes_2024: c.votes, votes_proj: Math.round(c.votes * turnout),
      p_dside_win: r3(phi(proj / (half / 1.2816))), group_shares: Object.fromEntries(GROUPS.map((g) => [g, r3(c.shares[g])])),
      group_swings: gsw, method: r.county_method, flags: []
    };
  });
  for (const c of counties) countiesNational.rows.push([c.geoid, c.pres2024_margin, c.proj_margin, c.shift, c.p_dside_win]);

  const curve = (scale) => Array.from({ length: 15 }, (_, i) => [14 - i, Math.round(scale * 100000 * (1 - Math.exp(-(i + 1) / 5)))]);
  const earlyVote = r.ev_detail === 'none' ? null : {
    as_of_days_out: 1,
    vs_2022: { total_ratio: r3(0.9 + rng() * 0.4) }, vs_2018: { total_ratio: r3(1.1 + rng() * 0.5) }, vs_2024: { total_ratio: r3(0.55 + rng() * 0.3) },
    party_share: { '2026': { D: 0.43, R: 0.38 }, '2022': { D: 0.45, R: 0.36 } }, cap_binding: Math.abs(r.components.early_vote ?? 0) >= 1.5,
    curves: { '2026': curve(1.0).slice(0, 14), '2022': curve(0.9), '2018': curve(0.7), '2024': curve(1.5) }
  };
  const pollsRecent = Array.from({ length: r.polls.n ? Math.min(6, r.polls.n + 1) : 0 }, (_, i) => ({
    pollster: ['Mock Research', 'Example Poll', 'Sample Strategies', 'Fixture Insights'][i % 4], end: `2026-10-${String(30 - i * 2).padStart(2, '0')}`,
    n: 600 + Math.floor(rng() * 600), pop: ['LV', 'RV'][i % 2], margin: r1((r.polls.avg_margin ?? r.proj_margin) + normal() * 2.5)
  }));
  writeFileSync(join(data, 'states', `${po}.json`), JSON.stringify({
    state: po, run_id: runId, as_of: asOf, mock: true, counties,
    groups: GROUPS.map((g) => ({ group: g, swing: r1(r.shift + normal() * 2), sd: r1(1.5 + rng() * 2), shrinkage: r3(0.3 + rng() * 0.5), n_polls: 2 + Math.floor(rng() * 8) })),
    early_vote: earlyVote, polls_recent: pollsRecent
  }));
}

// ---- seat distribution (Poisson-binomial over the mock win probabilities) ----
const HD = 34;
let dist = [1];
for (const r of summaryRaces) { const p = r.p_dside_win; const nd = new Array(dist.length + 1).fill(0);
  dist.forEach((q, k) => { nd[k] += q * (1 - p); nd[k + 1] += q * p; }); dist = nd; }
const seats = dist.map((q, k) => [k + HD, q]);
const cum = (t) => { let a = 0; for (const [s, q] of seats) { a += q; if (a >= t) return s; } return seats.at(-1)[0]; };
const national = {
  generic_ballot: real?.national?.generic_ballot ?? { margin: 9, n_polls: 38, n_eff: 21.4, se: 1.1 },
  npv2024: real?.national?.npv2024 ?? -1.5, s_nat: real?.national?.s_nat ?? 10.5,
  senate: {
    d_seats_median: cum(0.5), d_seats_p10: cum(0.1), d_seats_p90: cum(0.9), threshold: 51,
    p_d_control: r3(seats.filter(([s]) => s >= 51).reduce((a, [, q]) => a + q, 0)),
    distribution: Object.fromEntries(seats.filter(([, q]) => q > 5e-4).map(([s, q]) => [String(s), r3(q)]))
  }
};
const summary = { run_id: runId, as_of: asOf, model_version: 'mock-fixture', mock: true, national, weights: real?.weights ?? { national: 2, state_poll: 1 }, races: summaryRaces };
writeFileSync(join(data, 'summary.json'), JSON.stringify(summary));
writeFileSync(join(data, 'counties_national.json'), JSON.stringify(countiesNational));

const movers = [...summaryRaces].sort((a, b) => b.shift - a.shift);
writeFileSync(join(data, 'changes.json'), JSON.stringify({
  run_id: runId, as_of: asOf, items: [
    { kind: 'p_win', state: movers[0].state, text: `${movers[0].name}: D win probability ${Math.round(movers[0].p_dside_win * 100)}% (mock change)`, delta: 0.04 },
    { kind: 'margin', state: movers[1].state, text: `${movers[1].name}: projected margin moved 0.6 pts toward Democrats (mock change)`, delta: 0.6 }
  ]
}));
writeFileSync(join(data, 'data_health.json'), JSON.stringify({
  sources: [{ name: 'generic_polls', status: 'fallback', retrieved_at: `${asOf}T06:00:00Z` }, { name: 'senate_polls', status: 'ok', retrieved_at: `${asOf}T06:00:00Z` }],
  flags: ['Fixture data: not a projection']
}));
writeFileSync(join(data, 'methodology_params.json'), JSON.stringify({
  weights: { national: 2, state_poll: 1 }, combine: 'precision', precision: { sigma_prior: 4, sigma_bias: 1, sigma_poll: 3.9, w_min: 0.4, w_max: 0.9, incumbent_pts: 3 }, half_life_days: { senate: 14, generic: 21 }, market: { enabled: false, mu: 0.1, weight_cap: 0.2 },
  earlyvote: { cap_pts: 1.5, shrink: 0.5 }, county: { max_tilt: 6 }, sim: { n_draws: 20000, control_threshold: 51 }
}));
const bt = join(root, 'output', 'backtest', 'metrics.json');
if (existsSync(bt)) writeFileSync(join(data, 'backtest_summary.json'), readFileSync(bt));
console.log(`mock data: ${summaryRaces.length} races, ${countiesNational.rows.length} counties, run ${runId}`);
