// Swing decomposition for the state page waterfall (plan §10.2 SwingDecomposition, §6.5 formulas).
import type { Race } from './data/types';

export interface Step { key: string; label: string; value: number; note?: string }

/**
 * baseline (2024) -> national environment -> race polls -> market -> turnout -> early vote -> projection.
 * state_swing = (1-mu) * ((1-w)*S_prior + w*S_poll) + mu*S_mkt for polled states, where w is the race's precision
 * weight (races[].polls.w_poll; the fixed b/(a+b) when absent); unpolled states have only the prior. The prior is the
 * national swing plus components.demographic (national group swings applied to the state's electorate). Any
 * remainder (e.g. the incumbency shift) is shown as "other" so the steps always sum to proj_margin.
 */
export function decompose(r: Race, weights: { national: number; state_poll: number }): { steps: Step[]; total: number } {
  const c = r.components;
  const mu = c.market_weight ?? 0;
  const a = weights.national, b = weights.state_poll;
  const polled = r.swing_source !== 'national_fallback' && c.state_poll != null;
  const base = 1 - mu;
  const w = r.polls.w_poll ?? b / (a + b);
  const share = polled ? base * (1 - w) : base; // weight the prior gets in the state swing
  const nat = c.national == null ? 0 : share * c.national;
  const demo = share * (c.demographic ?? 0);
  const poll = polled ? base * w * (c.state_poll as number) : 0;
  const mkt = c.market != null && mu > 0 ? mu * c.market : 0;
  const state = c.state_swing ?? nat + poll + mkt;
  const other = state - nat - demo - poll - mkt;
  const steps: Step[] = [
    { key: 'national', label: 'National environment', value: nat, note: polled ? `${(1 - w).toFixed(2)} of the pre-market swing` : undefined },
    ...(Math.abs(demo) > 0.005 ? [{ key: 'demographic', label: 'Demographic mix', value: demo, note: 'national group swings applied to this electorate' }] : []),
    { key: 'polls', label: 'Race polls', value: poll, note: polled ? undefined : 'no recent state polling' }
  ];
  if (mkt !== 0) steps.push({ key: 'market', label: 'Betting markets', value: mkt });
  if (Math.abs(other) > 0.05) steps.push({ key: 'other', label: 'Other swing adjustments', value: other });
  steps.push({ key: 'turnout', label: 'Turnout composition', value: c.turnout ?? 0 });
  steps.push({ key: 'early_vote', label: 'Early vote', value: c.early_vote ?? 0, note: r.ev_detail ? `detail: ${r.ev_detail}` : undefined });
  const total = r.pres2024_margin + steps.reduce((s, x) => s + x.value, 0);
  return { steps, total };
}
