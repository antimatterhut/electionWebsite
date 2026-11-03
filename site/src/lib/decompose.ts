// Swing decomposition for the state page waterfall (plan §10.2 SwingDecomposition, §6.5 formulas).
import type { Race } from './data/types';

export interface Step { key: string; label: string; value: number; note?: string }

/**
 * baseline (2024) -> national environment -> race polls -> market -> turnout -> early vote -> projection.
 * state_swing = (1-mu) * (a*S_nat + b*S_poll)/(a+b) + mu*S_mkt for polled states; unpolled states have only the
 * national part. Any remainder (e.g. volume scaling) is shown as "other" so the steps always sum to proj_margin.
 */
export function decompose(r: Race, weights: { national: number; state_poll: number }): { steps: Step[]; total: number } {
  const c = r.components;
  const mu = c.market_weight ?? 0;
  const a = weights.national, b = weights.state_poll;
  const polled = r.swing_source !== 'national_fallback' && c.state_poll != null;
  const base = 1 - mu;
  const nat = c.national == null ? 0 : polled ? (base * a * c.national) / (a + b) : base * c.national;
  const poll = polled ? (base * b * (c.state_poll as number)) / (a + b) : 0;
  const mkt = c.market != null && mu > 0 ? mu * c.market : 0;
  const state = c.state_swing ?? nat + poll + mkt;
  const other = state - nat - poll - mkt;
  const steps: Step[] = [
    { key: 'national', label: 'National environment', value: nat, note: `${(a / (a + b)).toFixed(2)} of the pre-market swing` },
    { key: 'polls', label: 'Race polls', value: poll, note: polled ? undefined : 'no recent state polling' }
  ];
  if (mkt !== 0) steps.push({ key: 'market', label: 'Betting markets', value: mkt });
  if (Math.abs(other) > 0.05) steps.push({ key: 'other', label: 'Other swing adjustments', value: other });
  steps.push({ key: 'turnout', label: 'Turnout composition', value: c.turnout ?? 0 });
  steps.push({ key: 'early_vote', label: 'Early vote', value: c.early_vote ?? 0, note: r.ev_detail ? `detail: ${r.ev_detail}` : undefined });
  const total = r.pres2024_margin + steps.reduce((s, x) => s + x.value, 0);
  return { steps, total };
}
