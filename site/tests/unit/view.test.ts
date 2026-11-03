import { describe, expect, it } from 'vitest';
import { DEFAULT_VIEW, nextView, readStored, resolveView, STORAGE_KEY, writeStored } from '../../src/lib/view';

const mem = () => {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m };
};
const broken = {
  getItem: () => { throw new Error('denied'); },
  setItem: () => { throw new Error('denied'); }
};

describe('projection / shift toggle logic (plan §10.3)', () => {
  it('defaults to projection', () => expect(DEFAULT_VIEW).toBe('projection'));
  it('query param wins over storage; invalid values are ignored', () => {
    expect(resolveView('shift', 'projection')).toBe('shift');
    expect(resolveView('bogus', 'shift')).toBe('shift');
    expect(resolveView(null, null)).toBe('projection');
  });
  it('persists to storage', () => {
    const s = mem();
    expect(writeStored('shift', s)).toBe(true);
    expect(s.m.get(STORAGE_KEY)).toBe('shift');
    expect(readStored(s)).toBe('shift');
  });
  it('survives unavailable storage (private mode / blocked site data)', () => {
    expect(writeStored('shift', broken)).toBe(false);
    expect(readStored(broken)).toBeNull();
  });
  it('ignores corrupt stored values', () => {
    const s = mem();
    s.setItem(STORAGE_KEY, '{"x":1}');
    expect(readStored(s)).toBeNull();
  });
  it('arrow keys move through the radiogroup and wrap', () => {
    expect(nextView('projection', 'ArrowRight')).toBe('shift');
    expect(nextView('shift', 'ArrowRight')).toBe('projection');
    expect(nextView('projection', 'ArrowLeft')).toBe('shift');
    expect(nextView('projection', 'a')).toBeNull();
  });
});
