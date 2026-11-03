// Initial-JS budget per page type (plan §10.6: <= 120 KB gzip) plus data budgets. The JS list is read from each
// prerendered page's modulepreload links, so lazily loaded chunks are not counted against the initial budget.
// Run `npm run build` first.
const fs = require('node:fs');
const path = require('node:path');

const build = path.join(__dirname, 'build');
function initialJs(html) {
  const file = path.join(build, html);
  if (!fs.existsSync(file)) return [];
  const src = fs.readFileSync(file, 'utf8');
  const hrefs = new Set();
  for (const m of src.matchAll(/(?:href|import\()\s*=?\s*["']\.?\/?(_app\/immutable\/[^"']+\.js)["']/g)) hrefs.add(m[1]);
  for (const m of src.matchAll(/["']([^"']*\/_app\/immutable\/[^"']+\.js)["']/g)) hrefs.add(m[1].replace(/^\.?\//, '').replace(/^.*?(_app\/immutable\/)/, '$1'));
  return [...hrefs].map((h) => path.join('build', h));
}

module.exports = [
  ...['index.html', 'state/GA.html', 'methodology.html', 'about.html'].map((p) => ({
    name: `initial JS: ${p}`, path: initialJs(p), gzip: true, limit: '120 kB'
  })),
  { name: 'national TopoJSON', path: 'build/data/topo/counties.topojson', gzip: true, limit: '700 kB' },
  { name: 'counties_national.json', path: 'build/data/counties_national.json', gzip: true, limit: '250 kB' },
  { name: 'summary.json', path: 'build/data/summary.json', gzip: true, limit: '250 kB' },
  { name: 'largest state file (TX)', path: 'build/data/states/TX.json', gzip: true, limit: '250 kB' },
  { name: 'largest state TopoJSON (TX)', path: 'build/data/topo/states/TX.topojson', gzip: true, limit: '150 kB' }
].filter((c) => (Array.isArray(c.path) ? c.path.length : true));
