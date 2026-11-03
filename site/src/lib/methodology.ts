// Methodology page helpers: fill {{param}} placeholders from methodology_params.json and render the Markdown.
import { marked } from 'marked';
import type { MethodologyParams } from './data/types';

export const MARKER = '<!--BACKTEST-->';

function lookup(obj: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((o, k) => (o && typeof o === 'object' ? (o as Record<string, unknown>)[k] : undefined), obj);
}

export function fillParams(md: string, params: MethodologyParams): string {
  const ctx = { ...params, market: { ...params.market, enabled_label: params.market.enabled ? 'enabled' : 'disabled' } };
  return md.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_, k: string) => {
    const v = lookup(ctx, k);
    if (v === undefined) throw new Error(`methodology.md references unknown parameter "${k}"`);
    return String(v);
  });
}

/** Render to HTML; the marker splits the text so the live backtest table can be placed in the middle. */
export function render(md: string, params: MethodologyParams): { before: string; after: string } {
  const filled = fillParams(md, params);
  const [a, b = ''] = filled.split(MARKER);
  return { before: marked.parse(a!, { async: false }) as string, after: b ? (marked.parse(b, { async: false }) as string) : '' };
}
