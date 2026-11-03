// Number formatting: margins as "D+54.9" / "R+3.2" (plan §10.4), probabilities, counts.
import type { View } from './data/types';

export function margin(m: number | null | undefined, digits = 1): string {
  if (m == null || !Number.isFinite(m)) return 'n/a';
  const r = Math.round(Math.abs(m) * 10 ** digits) / 10 ** digits;
  if (r === 0) return 'Even';
  return `${m > 0 ? 'D' : 'R'}+${r.toFixed(digits)}`;
}

export function marginRange(range: [number, number] | undefined, digits = 0): string {
  if (!range) return 'n/a';
  return `${margin(range[0], digits)} to ${margin(range[1], digits)}`;
}

export function shift(s: number | null | undefined, digits = 1): string {
  if (s == null || !Number.isFinite(s)) return 'n/a';
  const r = Math.round(Math.abs(s) * 10 ** digits) / 10 ** digits;
  if (r === 0) return 'No shift';
  return `${s > 0 ? 'D' : 'R'}+${r.toFixed(digits)} toward ${s > 0 ? 'Democrats' : 'Republicans'}`;
}

export const primary = (view: View, m: number, s: number): string => (view === 'shift' ? shift(s) : margin(m));

export function pct(p: number | null | undefined, digits = 0): string {
  if (p == null || !Number.isFinite(p)) return 'n/a';
  if (p > 0.995) return '>99%';
  if (p < 0.005) return '<1%';
  return `${(p * 100).toFixed(digits)}%`;
}

export const int = (n: number): string => Math.round(n).toLocaleString('en-US');

export const signed = (n: number | null | undefined, d = 1): string =>
  n == null || !Number.isFinite(n) ? 'n/a' : `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(d)}`;

const GROUP_LABEL: Record<string, string> = {
  wnh_college: 'White college', wnh_noncollege: 'White non-college', black: 'Black', hispanic: 'Hispanic',
  asian: 'Asian', other: 'Other'
};
export const groupLabel = (g: string): string => GROUP_LABEL[g] ?? g;

export function relativeTime(iso: string, now = Date.now()): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return iso;
  const h = Math.round((now - t) / 36e5);
  if (h < 1) return 'less than an hour ago';
  if (h < 48) return `${h} hour${h === 1 ? '' : 's'} ago`;
  return `${Math.round(h / 24)} days ago`;
}
