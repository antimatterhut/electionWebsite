// Exact color scales from plan §10.5. Between stops we interpolate linearly in sRGB; at stops the hex is exact.
import type { View } from './data/types';

export interface Stop { at: number; hex: string }

/** Projection scale: positive = Democratic margin (D+). */
export const PROJECTION_STOPS: Stop[] = [
  { at: -40, hex: '#67000D' }, { at: -30, hex: '#A50F15' }, { at: -20, hex: '#CB181D' }, { at: -10, hex: '#EF6548' },
  { at: -5, hex: '#FC9272' }, { at: -1, hex: '#FCCDBE' }, { at: 0, hex: '#F2F2F2' }, { at: 1, hex: '#C6DBEF' },
  { at: 5, hex: '#9ECAE1' }, { at: 10, hex: '#6BAED6' }, { at: 20, hex: '#2171B5' }, { at: 30, hex: '#08519C' },
  { at: 40, hex: '#08306B' }
];

/** Shift scale: positive = shift toward Democrats (teal), negative = toward Republicans (amber/brown). */
export const SHIFT_STOPS: Stop[] = [
  { at: -16, hex: '#8C510A' }, { at: -12, hex: '#BF812D' }, { at: -8, hex: '#DFC27D' }, { at: -4, hex: '#F6E8C3' },
  { at: 0, hex: '#F5F5F5' }, { at: 4, hex: '#C7EAE5' }, { at: 8, hex: '#80CDC1' }, { at: 12, hex: '#35978F' },
  { at: 16, hex: '#01665E' }
];

export const NEUTRAL_GRAY = '#D4D4D4';

const hexToRgb = (h: string): [number, number, number] =>
  [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
const rgbToHex = (c: number[]): string =>
  '#' + c.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('').toUpperCase();

export function scaleColor(stops: Stop[], v: number): string {
  const first = stops[0]!, last = stops[stops.length - 1]!;
  if (!Number.isFinite(v)) return NEUTRAL_GRAY;
  if (v <= first.at) return first.hex;
  if (v >= last.at) return last.hex;
  for (let i = 1; i < stops.length; i++) {
    const b = stops[i]!, a = stops[i - 1]!;
    if (v <= b.at) {
      if (v === b.at) return b.hex;
      const t = (v - a.at) / (b.at - a.at);
      const ca = hexToRgb(a.hex), cb = hexToRgb(b.hex);
      return rgbToHex(ca.map((x, k) => x + (cb[k]! - x) * t));
    }
  }
  return last.hex;
}

export const projectionColor = (m: number): string => scaleColor(PROJECTION_STOPS, m);
export const shiftColor = (s: number): string => scaleColor(SHIFT_STOPS, s);
export const colorFor = (view: View, v: number): string => (view === 'shift' ? shiftColor(v) : projectionColor(v));
export const legendStops = (view: View): Stop[] => (view === 'shift' ? SHIFT_STOPS : PROJECTION_STOPS);

/** Relative luminance and contrast ratio (WCAG 2.x). */
export function luminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function contrast(a: string, b: string): number {
  const la = luminance(a), lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}
