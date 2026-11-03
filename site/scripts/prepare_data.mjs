// `npm run build` prebuild: make sure the published data exists, then render the OG cards.
// Real artifacts (from the Python pipeline) are copied into static/data by the deploy workflow before this runs; the
// topology and fixtures are only generated when absent so a real run is never overwritten.
import { existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const data = join(here, '..', 'static', 'data');
const run = (s) => execFileSync(process.execPath, [join(here, s)], { stdio: 'inherit' });

if (!existsSync(join(data, 'topo', 'counties.topojson'))) run('build_topo.mjs');
if (!existsSync(join(data, 'summary.json'))) run('make_mock_data.mjs');
if (!process.argv.includes('--no-og')) run('make_og.mjs');
