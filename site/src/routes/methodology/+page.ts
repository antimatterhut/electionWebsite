import { base } from '$app/paths';
import { getJson, loadParams, dataUrl } from '$lib/data/loaders';
import { render } from '$lib/methodology';
import md from '../../../../docs/methodology.md?raw';

export const prerender = true;

export interface BacktestCycle {
  metrics: { n_races: number; state_rmse: number; naive_rmse: number; bias: number; winner_accuracy: number };
  sim?: { brier: number; coverage80: number; log_loss: number; actual_d_wins: number; actual_seat_percentile: number };
}
export interface BacktestSummary { cycles: Record<string, BacktestCycle>; sensitivity?: Record<string, Record<string, { state_rmse: number; brier_sim?: number }>> }

export async function load({ fetch, parent }) {
  const { summary } = await parent();
  const runId = summary?.run_id ?? '';
  const params = await loadParams(fetch, base, runId);
  let backtest: BacktestSummary | null = null;
  try {
    backtest = await getJson<BacktestSummary>(fetch, dataUrl(base, 'backtest_summary.json', runId));
  } catch {
    backtest = null; // page still renders; the table shows "not available"
  }
  return { html: render(md, params), params, backtest };
}
