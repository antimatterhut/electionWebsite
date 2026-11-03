// The layout publishes the best available summary (fresh, else last good) to pages through context.
import { getContext, setContext } from 'svelte';
import type { Summary } from './data/types';

const KEY = Symbol('summary');
export function provideSummary(get: () => Summary | null): void {
  setContext(KEY, get);
}
export const useSummary = (): (() => Summary | null) => getContext<() => Summary | null>(KEY);
