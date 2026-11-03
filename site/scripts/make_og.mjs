// 1200x630 OG/Twitter cards per race and one national card (plan §10.6), rendered with satori + resvg at build time.
// Font: Inter (OFL) from @fontsource, self-hosted via node_modules; no CDN.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Resvg } from '@resvg/resvg-js';
import satori from 'satori';
import { projectionHex } from './colors.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const data = join(here, '..', 'static', 'data');
const out = join(here, '..', 'static', 'og');
mkdirSync(out, { recursive: true });
const font = (w) => readFileSync(join(here, '..', 'node_modules', '@fontsource', 'inter', 'files', `inter-latin-${w}-normal.woff`));
const fonts = [{ name: 'Inter', data: font(400), weight: 400 }, { name: 'Inter', data: font(700), weight: 700 }];

const summary = JSON.parse(readFileSync(join(data, 'summary.json'), 'utf8'));
const fmt = (m) => (Math.abs(m) < 0.05 ? 'Even' : `${m > 0 ? 'D' : 'R'}+${Math.abs(m).toFixed(1)}`);
const el = (type, style, children) => ({ type, props: { style: { display: 'flex', ...style }, children } });

async function card(file, { kicker, title, big, bigColor, lines }) {
  const tree = el('div', { width: '100%', height: '100%', flexDirection: 'column', justifyContent: 'space-between', background: '#0f1319', color: '#eef1f5', padding: 64, fontFamily: 'Inter' }, [
    el('div', { flexDirection: 'column' }, [
      el('div', { fontSize: 28, color: '#b4bdcb' }, kicker),
      el('div', { fontSize: 64, fontWeight: 700, marginTop: 8 }, title)
    ]),
    el('div', { flexDirection: 'column' }, [
      el('div', { fontSize: 120, fontWeight: 700, color: bigColor }, big),
      ...lines.map((l) => el('div', { fontSize: 32, color: '#d5dbe5', marginTop: 6 }, l))
    ]),
    el('div', { fontSize: 24, color: '#8a94a4' }, `Pre-election projection · data as of ${summary.as_of}${summary.mock ? ' · FIXTURE DATA' : ''}`)
  ]);
  const svg = await satori(tree, { width: 1200, height: 630, fonts });
  writeFileSync(join(out, file), new Resvg(svg, { fitTo: { mode: 'width', value: 1200 } }).render().asPng());
}

const sen = summary.national.senate;
await card('national.png', {
  kicker: '2026 U.S. Senate', title: 'County-level projection',
  big: sen ? `${Math.round(sen.p_d_control * 100)}%` : '35 races', bigColor: '#6baed6',
  lines: sen ? ['chance Democrats control the Senate', `Median ${sen.d_seats_median} seats (80%: ${sen.d_seats_p10}-${sen.d_seats_p90})`] : ['races projected by county']
});
for (const r of summary.races) {
  await card(`${r.state}.png`, {
    kicker: `2026 U.S. Senate${r.special ? ' special election' : ''}`, title: r.name,
    big: fmt(r.proj_margin), bigColor: projectionHex(r.proj_margin, true),
    lines: [r.p_dside_win != null ? `${r.p_dside_win > 0.995 ? '>99' : r.p_dside_win < 0.005 ? '<1' : Math.round(r.p_dside_win * 100)}% chance the D-side candidate wins` : 'projected margin',
      `${r.dside.name ?? 'D-side TBD'} (${r.dside.party}) vs ${r.rside.name ?? 'R TBD'} (${r.rside.party})`]
  });
}
console.log(`og: ${summary.races.length + 1} cards`);
