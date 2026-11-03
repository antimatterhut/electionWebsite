// Plain-JS copy of the §10.5 stops for build scripts (the app uses src/lib/color.ts; tests/unit/color.test.ts asserts
// the two stay identical).
export const PROJECTION = [[-40, '#67000D'], [-30, '#A50F15'], [-20, '#CB181D'], [-10, '#EF6548'], [-5, '#FC9272'], [-1, '#FCCDBE'], [0, '#F2F2F2'],
  [1, '#C6DBEF'], [5, '#9ECAE1'], [10, '#6BAED6'], [20, '#2171B5'], [30, '#08519C'], [40, '#08306B']];
export const SHIFT = [[-16, '#8C510A'], [-12, '#BF812D'], [-8, '#DFC27D'], [-4, '#F6E8C3'], [0, '#F5F5F5'], [4, '#C7EAE5'], [8, '#80CDC1'], [12, '#35978F'], [16, '#01665E']];

const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
export function interpolate(stops, v) {
  if (v <= stops[0][0]) return stops[0][1];
  if (v >= stops.at(-1)[0]) return stops.at(-1)[1];
  for (let i = 1; i < stops.length; i++) {
    if (v <= stops[i][0]) {
      const [a, ha] = stops[i - 1], [b, hb] = stops[i];
      const t = (v - a) / (b - a);
      const ca = rgb(ha), cb = rgb(hb);
      return '#' + ca.map((x, k) => Math.round(x + (cb[k] - x) * t).toString(16).padStart(2, '0')).join('').toUpperCase();
    }
  }
}
/** On the dark OG background the dark-blue extremes would vanish, so lighten them for text use. */
export function projectionHex(m, forDark = false) {
  const c = interpolate(PROJECTION, m);
  if (!forDark) return c;
  return m > 0 ? interpolate(PROJECTION, Math.min(m, 10) === m ? m : 10) : interpolate(PROJECTION, Math.max(m, -10));
}
