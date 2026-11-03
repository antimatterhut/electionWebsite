import { describe, expect, it } from 'vitest';
import { contrast, colorFor, legendStops, PROJECTION_STOPS, projectionColor, SHIFT_STOPS, shiftColor, NEUTRAL_GRAY } from '../../src/lib/color';
import { PROJECTION, SHIFT } from '../../scripts/colors.mjs';

describe('projection scale (plan §10.5)', () => {
  const table: Array<[number, string]> = [
    [40, '#08306B'], [30, '#08519C'], [20, '#2171B5'], [10, '#6BAED6'], [5, '#9ECAE1'], [1, '#C6DBEF'], [0, '#F2F2F2'],
    [-1, '#FCCDBE'], [-5, '#FC9272'], [-10, '#EF6548'], [-20, '#CB181D'], [-30, '#A50F15'], [-40, '#67000D']
  ];
  it.each(table)('margin %d -> %s exactly', (m, hex) => expect(projectionColor(m)).toBe(hex));
  it('clamps beyond D+40 / R+40', () => {
    expect(projectionColor(75)).toBe('#08306B');
    expect(projectionColor(-99)).toBe('#67000D');
  });
  it('interpolates between stops and is monotone in lightness on each side', () => {
    expect(projectionColor(15)).not.toBe('#6BAED6');
    const lum = (h: string) => contrast(h, '#000000');
    for (let m = 0; m < 40; m++) expect(lum(projectionColor(m + 1))).toBeLessThanOrEqual(lum(projectionColor(m)) + 1e-9);
    for (let m = 0; m > -40; m--) expect(lum(projectionColor(m - 1))).toBeLessThanOrEqual(lum(projectionColor(m)) + 1e-9);
  });
  it('non-finite values get the neutral gray', () => expect(projectionColor(NaN)).toBe(NEUTRAL_GRAY));
});

describe('shift scale (plan §10.5)', () => {
  const table: Array<[number, string]> = [
    [16, '#01665E'], [12, '#35978F'], [8, '#80CDC1'], [4, '#C7EAE5'], [0, '#F5F5F5'], [-4, '#F6E8C3'], [-8, '#DFC27D'], [-12, '#BF812D'], [-16, '#8C510A']
  ];
  it.each(table)('shift %d -> %s exactly', (s, hex) => expect(shiftColor(s)).toBe(hex));
  it('is a different hue family from the projection scale at the same magnitude', () => {
    for (const v of [4, 8, 12, 16]) expect(shiftColor(v)).not.toBe(projectionColor(v));
  });
});

describe('view dispatch and sync with build scripts', () => {
  it('colorFor picks the scale', () => {
    expect(colorFor('projection', 10)).toBe('#6BAED6');
    expect(colorFor('shift', 8)).toBe('#80CDC1');
    expect(legendStops('shift')).toBe(SHIFT_STOPS);
    expect(legendStops('projection')).toBe(PROJECTION_STOPS);
  });
  it('scripts/colors.mjs matches src/lib/color.ts', () => {
    expect(PROJECTION).toEqual(PROJECTION_STOPS.map((s) => [s.at, s.hex]));
    expect(SHIFT).toEqual(SHIFT_STOPS.map((s) => [s.at, s.hex]));
  });
});

describe('contrast helper', () => {
  it('black on white is 21:1', () => expect(contrast('#000000', '#FFFFFF')).toBeCloseTo(21, 5));
  it('tooltip text colors meet 4.5:1 on their panels', () => {
    expect(contrast('#14181F', '#FFFFFF')).toBeGreaterThanOrEqual(4.5); // light theme text on panel
    expect(contrast('#4A5361', '#FFFFFF')).toBeGreaterThanOrEqual(4.5); // muted text
    expect(contrast('#EEF1F5', '#0F1319')).toBeGreaterThanOrEqual(4.5); // dark theme text
    expect(contrast('#B4BDCB', '#0F1319')).toBeGreaterThanOrEqual(4.5); // dark muted
  });
});
