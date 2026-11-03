// County tooltip content (plan §10.4). Always shows both projection and shift regardless of the active view.
import type { County, GroupName } from './data/types';
import { groupLabel, int, margin, marginRange, shift } from './format';

export interface TooltipRow { label: string; value: string }
export interface TooltipContent { title: string; rows: TooltipRow[]; stateLink: string; text: string }

export function methodLabel(m: string | undefined): string {
  switch (m) {
    case 'ei_crosstab': return 'EI + crosstabs';
    case 'age_only': return 'State swing + age term';
    case 'uniform': return 'Uniform state swing';
    default: return m ?? 'n/a';
  }
}

export function largestGroups(shares: County['group_shares'], k = 2): string {
  return (Object.entries(shares) as Array<[GroupName, number]>)
    .sort((a, b) => b[1] - a[1]).slice(0, k)
    .map(([g, v]) => `${groupLabel(g)} ${Math.round(v * 100)}%`).join(' · ') || 'n/a';
}

export function countyTooltip(c: County, state: string, base = ''): TooltipContent {
  const rows: TooltipRow[] = [
    { label: 'Projected 2026 Senate', value: `${margin(c.proj_margin)}  (80%: ${marginRange(c.interval80)})` },
    { label: '2024 presidential', value: margin(c.pres2024_margin) },
    { label: 'Shift from 2024', value: shift(c.shift) },
    { label: 'Expected 2026 votes', value: `${int(c.votes_proj)}  (2024: ${int(c.votes_2024)})` },
    { label: 'Largest groups', value: largestGroups(c.group_shares) },
    { label: 'Method', value: methodLabel(c.method) }
  ];
  const title = `${c.name}, ${state}`;
  return {
    title, rows, stateLink: `${base}/state/${state}`,
    text: `${title}. ` + rows.map((r) => `${r.label}: ${r.value}`).join('. ')
  };
}
