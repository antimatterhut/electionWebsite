import { describe, expect, it } from 'vitest';
import { countyTooltip, largestGroups, methodLabel } from '../../src/lib/tooltip';
import { int, margin, marginRange, pct, primary, relativeTime, shift, signed } from '../../src/lib/format';
import { csvEscape } from '../../src/lib/csv';
import type { County } from '../../src/lib/data/types';

describe('margin formatting', () => {
  it('signs and rounds', () => {
    expect(margin(54.9)).toBe('D+54.9');
    expect(margin(-3.24)).toBe('R+3.2');
    expect(margin(0)).toBe('Even');
    expect(margin(0.04)).toBe('Even');
    expect(margin(-0.06)).toBe('R+0.1');
    expect(margin(null)).toBe('n/a');
    expect(margin(NaN)).toBe('n/a');
  });
  it('ranges', () => expect(marginRange([49.0, 60.5])).toBe('D+49 to D+61'));
  it('range crossing zero', () => expect(marginRange([-3.2, 4.4])).toBe('R+3 to D+4'));
  it('shift wording', () => {
    expect(shift(8.7)).toBe('D+8.7 toward Democrats');
    expect(shift(-2)).toBe('R+2.0 toward Republicans');
    expect(shift(0)).toBe('No shift');
  });
  it('primary column follows the view', () => {
    expect(primary('projection', 7.5, 9.7)).toBe('D+7.5');
    expect(primary('shift', 7.5, 9.7)).toBe('D+9.7 toward Democrats');
  });
  it('probabilities clamp at the extremes', () => {
    expect(pct(0.84)).toBe('84%');
    expect(pct(0.999)).toBe('>99%');
    expect(pct(0.001)).toBe('<1%');
    expect(pct(undefined)).toBe('n/a');
  });
  it('numbers', () => {
    expect(int(430000)).toBe('430,000');
    expect(signed(-0.4)).toBe('−0.4');
    expect(signed(0.3)).toBe('+0.3');
  });
  it('relative time', () => {
    const now = Date.parse('2026-11-02T12:00:00Z');
    expect(relativeTime('2026-11-02T10:00:00Z', now)).toBe('2 hours ago');
    expect(relativeTime('2026-10-30T12:00:00Z', now)).toBe('3 days ago');
  });
});

const fulton: County = {
  geoid: '13121', name: 'Fulton', pres2024_margin: 46.2, proj_margin: 54.9, shift: 8.7, interval80: [49.0, 60.5],
  votes_2024: 520000, votes_proj: 430000, p_dside_win: 1, group_shares: { black: 0.44, wnh_college: 0.28, hispanic: 0.1 },
  group_swings: {}, method: 'ei_crosstab', flags: []
};

describe('county tooltip (plan §10.4)', () => {
  const t = countyTooltip(fulton, 'GA', '/repo');
  it('matches the specified content', () => {
    expect(t.title).toBe('Fulton, GA');
    const m = Object.fromEntries(t.rows.map((r) => [r.label, r.value]));
    expect(m['Projected 2026 Senate']).toBe('D+54.9  (80%: D+49 to D+61)');
    expect(m['2024 presidential']).toBe('D+46.2');
    expect(m['Shift from 2024']).toBe('D+8.7 toward Democrats');
    expect(m['Expected 2026 votes']).toBe('430,000  (2024: 520,000)');
    expect(m['Largest groups']).toBe('Black 44% · White college 28%');
    expect(m['Method']).toBe('EI + crosstabs');
  });
  it('always shows both projection and shift, and links to the state', () => {
    expect(t.text).toContain('D+54.9');
    expect(t.text).toContain('toward Democrats');
    expect(t.stateLink).toBe('/repo/state/GA');
  });
  it('labels fallback methods', () => {
    expect(methodLabel('uniform')).toBe('Uniform state swing');
    expect(methodLabel(undefined)).toBe('n/a');
    expect(largestGroups({})).toBe('n/a');
  });
});

describe('csv export', () => {
  it('quotes and neutralises formulas', () => {
    expect(csvEscape('Smith, John')).toBe('"Smith, John"');
    expect(csvEscape('say "hi"')).toBe('"say ""hi"""');
    expect(csvEscape('=SUM(A1)')).toBe("'=SUM(A1)");
    expect(csvEscape(-3.5)).toBe('-3.5'); // numbers are not text
  });
});
