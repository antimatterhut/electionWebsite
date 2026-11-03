// Projection / Shift toggle logic (plan §10.3): query param > localStorage > default, persisted in try/catch.
import type { View } from './data/types';

export const VIEWS: View[] = ['projection', 'shift'];
export const DEFAULT_VIEW: View = 'projection';
export const STORAGE_KEY = 'senate.view';

export const isView = (v: unknown): v is View => v === 'projection' || v === 'shift';

export function readStored(storage?: Pick<Storage, 'getItem'>): View | null {
  try {
    const v = (storage ?? globalThis.localStorage)?.getItem(STORAGE_KEY);
    return isView(v) ? v : null;
  } catch {
    return null;
  }
}

export function writeStored(v: View, storage?: Pick<Storage, 'setItem'>): boolean {
  try {
    (storage ?? globalThis.localStorage).setItem(STORAGE_KEY, v);
    return true;
  } catch {
    return false;
  }
}

export function resolveView(param: string | null | undefined, stored: View | null): View {
  if (isView(param)) return param;
  return stored ?? DEFAULT_VIEW;
}

/** Arrow-key navigation for a radiogroup: returns the next view or null. */
export function nextView(current: View, key: string): View | null {
  const i = VIEWS.indexOf(current);
  if (key === 'ArrowRight' || key === 'ArrowDown') return VIEWS[(i + 1) % VIEWS.length]!;
  if (key === 'ArrowLeft' || key === 'ArrowUp') return VIEWS[(i + VIEWS.length - 1) % VIEWS.length]!;
  return null;
}
