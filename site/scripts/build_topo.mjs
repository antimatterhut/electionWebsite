// Build topo/counties.topojson, topo/states.topojson and topo/states/<ST>.topojson (plan §9.3) from us-atlas.
// us-atlas counties are the Census 2010s vintage, pre-projected (Albers USA, 975x610). That is a STAND-IN until the
// pipeline's GENZ2024 shapes (Connecticut planning regions, Alaska boroughs) feed the Python exporter; ids are FIPS.
import { createRequire } from 'node:module';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { feature, quantize } from 'topojson-client';
import { topology } from 'topojson-server';
import { presimplify, simplify, quantile } from 'topojson-simplify';
import { parseCsv, STATES } from './states.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');
const out = join(here, '..', 'static', 'data', 'topo');
const require = createRequire(import.meta.url);
const atlas = JSON.parse(readFileSync(require.resolve('us-atlas/counties-albers-10m.json'), 'utf8'));

const races = parseCsv(readFileSync(join(root, 'data', 'manual', 'races_2026.csv'), 'utf8'));
const raceStates = new Set(races.map((r) => r.state_po));

const counties = feature(atlas, atlas.objects.counties).features.map((f) => {
  const [po] = STATES[String(f.id).slice(0, 2)] ?? [];
  return { type: 'Feature', id: String(f.id), properties: { geoid: String(f.id), name: f.properties.name, state: po }, geometry: f.geometry };
}).filter((f) => f.properties.state);
const states = feature(atlas, atlas.objects.states).features.map((f) => {
  const [po, name] = STATES[String(f.id)] ?? [];
  return { type: 'Feature', id: String(f.id), properties: { geoid: String(f.id), name, state: po, race: raceStates.has(po) }, geometry: f.geometry };
}).filter((f) => f.properties.state);

function build(objects, q, keepFrac) {
  let t = topology(objects); // unquantised: simplify first, then quantise
  t = presimplify(t);
  if (keepFrac < 1) t = simplify(t, quantile(t, 1 - keepFrac)); // drop the lowest-weight (1 - keepFrac) of points
  return quantize(t, q);
}
function write(path, topo) {
  const json = JSON.stringify(topo);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, json);
  const gz = gzipSync(json).length;
  console.log(`${path.replace(root, '.')}  ${(json.length / 1024).toFixed(0)} KB  ${(gz / 1024).toFixed(0)} KB gz`);
  return gz;
}

const raceCounties = counties.filter((f) => raceStates.has(f.properties.state));
const fc = (features) => ({ type: 'FeatureCollection', features });
const budgets = [];
budgets.push(['counties.topojson', write(join(out, 'counties.topojson'),
  build({ counties: fc(raceCounties) }, 1e5, 0.5)), 700 * 1024]);
budgets.push(['states.topojson', write(join(out, 'states.topojson'), build({ states: fc(states) }, 1e5, 0.5)), 700 * 1024]);
for (const st of [...raceStates].sort()) {
  const cs = raceCounties.filter((f) => f.properties.state === st);
  budgets.push([`states/${st}.topojson`, write(join(out, 'states', `${st}.topojson`),
    build({ counties: fc(cs) }, 1e6, 0.9)), 150 * 1024]);
}
const bad = budgets.filter(([, gz, max]) => gz > max);
if (bad.length) { console.error('Over budget:', bad.map((b) => `${b[0]} ${(b[1] / 1024).toFixed(0)}KB`)); process.exit(1); }
console.log(`${budgets.length} topology files within budget`);
