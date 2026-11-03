// Shared UI state (Svelte 5 runes). The view comes from ?view=, then localStorage, then the default (plan §10.3).
import { DEFAULT_VIEW, readStored, resolveView, writeStored } from './view';
import type { View } from './data/types';

class ViewState {
  view = $state<View>(DEFAULT_VIEW);

  /** Call once on the client after hydration (reading the URL during prerender is not allowed). */
  init(): void {
    const param = new URL(location.href).searchParams.get('view');
    this.view = resolveView(param, readStored());
  }

  set(v: View): void {
    this.view = v;
    writeStored(v);
    try {
      const u = new URL(location.href);
      u.searchParams.set('view', v);
      history.replaceState(history.state, '', u);
    } catch {
      /* URL sync is best effort */
    }
  }
}

export const viewState = new ViewState();

const CACHE_KEY = 'senate.lastGoodSummary';
export function cacheSummary(json: string): void {
  try { localStorage.setItem(CACHE_KEY, json); } catch { /* storage unavailable */ }
}
export function cachedSummary<T>(): T | null {
  try {
    const s = localStorage.getItem(CACHE_KEY);
    return s ? (JSON.parse(s) as T) : null;
  } catch {
    return null;
  }
}
