// Colour-blind safety check for both scales (plan §10.5): Machado et al. (2009) severity-1.0 deuteranopia/protanopia
// simulation. For each scale we require that (a) lightness is monotone along each side of the neutral midpoint,
// (b) the two sides stay distinguishable (CIE76 delta-E >= 20 between matching-magnitude steps, >= 15 for the innermost pair) after simulation, and
// (c) adjacent steps stay >= 5 delta-E apart. Exits non-zero on failure.
import { PROJECTION, SHIFT } from './colors.mjs';

const MACHADO = {
  deuteranopia: [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.01182, 0.04294, 0.968881]],
  protanopia: [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]]
};
const toLin = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
const toSrgb = (c) => { c = Math.min(1, Math.max(0, c)); return 255 * (c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055); };
const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const sim = (c, m) => { const l = c.map(toLin); return MACHADO[m].map((row) => toSrgb(row[0] * l[0] + row[1] * l[1] + row[2] * l[2])); };
function lab([r, g, b]) {
  const [R, G, B] = [r, g, b].map(toLin);
  const [x, y, z] = [(0.4124 * R + 0.3576 * G + 0.1805 * B) / 0.95047, 0.2126 * R + 0.7152 * G + 0.0722 * B, (0.0193 * R + 0.1192 * G + 0.9505 * B) / 1.08883];
  const f = (t) => (t > 216 / 24389 ? Math.cbrt(t) : (24389 / 27 * t + 16) / 116);
  return [116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))];
}
const dE = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

let failed = 0;
function check(name, stops, zeroIdx) {
  for (const mode of ['normal', ...Object.keys(MACHADO)]) {
    const labs = stops.map(([, h]) => lab(mode === 'normal' ? rgb(h) : sim(rgb(h), mode)));
    const problems = [];
    // (a) lightness monotone away from the midpoint on each side
    for (let i = zeroIdx; i > 0; i--) if (labs[i - 1][0] > labs[i][0] + 0.5) problems.push(`L not monotone at ${stops[i - 1][0]}`);
    for (let i = zeroIdx; i < stops.length - 1; i++) if (labs[i + 1][0] > labs[i][0] + 0.5) problems.push(`L not monotone at ${stops[i + 1][0]}`);
    // (b) opposite sides distinguishable
    for (let k = 1; k <= Math.min(zeroIdx, stops.length - 1 - zeroIdx); k++) {
      const d = dE(labs[zeroIdx - k], labs[zeroIdx + k]);
      // The innermost pair (+/-1 step, near-neutral) is ambiguous by design, so it only needs dE >= 15; the values are
      // always printed next to the colour (no information by colour alone, plan §10.6).
      const min = k === 1 ? 15 : 20;
      if (d < min) problems.push(`sides too similar at step ${k} (dE ${d.toFixed(1)} < ${min})`);
    }
    // (c) adjacent steps distinct
    for (let i = 1; i < labs.length; i++) { const d = dE(labs[i - 1], labs[i]); if (d < 5) problems.push(`steps ${stops[i - 1][0]}/${stops[i][0]} too close (dE ${d.toFixed(1)})`); }
    console.log(`${problems.length ? 'FAIL' : 'ok  '} ${name} / ${mode}${problems.length ? ': ' + problems.join('; ') : ''}`);
    failed += problems.length;
  }
}
check('projection', PROJECTION, PROJECTION.findIndex(([v]) => v === 0));
check('shift', SHIFT, SHIFT.findIndex(([v]) => v === 0));
process.exit(failed ? 1 : 0);
