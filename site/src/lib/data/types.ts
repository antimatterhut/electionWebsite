// Mirrors plan §9 artifact schemas. (§9.6 calls for generation from the pydantic models; until export/schema.py
// exists in the Python package these are maintained by hand and contract-tested against the built artifacts by tests/unit/data.test.ts.)

export type Party = 'D' | 'R' | 'I' | string;
export type View = 'projection' | 'shift';
export type EvDetail = 'full' | 'county_only' | 'total_only' | 'none';
export type SwingSource = 'combined' | 'national_fallback' | 'national_market' | string;

export interface Candidate { name: string | null; party: Party; endorsed_by_dem?: boolean }

export interface Components {
  national: number | null;
  state_poll: number | null;
  market: number | null;
  market_weight: number | null;
  state_swing: number | null;
  turnout: number | null;
  early_vote: number | null;
  /** kappa * D_s: the state's demographic deviation from the national swing (national group swings x its electorate) */
  demographic?: number | null;
}

export interface Race {
  state: string;
  name?: string;
  class: number;
  special: boolean;
  incumbent: string | null;
  incumbent_party: Party;
  dside: Candidate;
  rside: Candidate;
  rcv: boolean;
  pres2024_margin: number;
  proj_margin: number;
  shift: number;
  interval80?: [number, number];
  p_dside_win?: number;
  swing_source: SwingSource;
  components: Components;
  polls: { n: number; avg_margin: number | null; n_eff: number | null; w_poll?: number | null; poll_var?: number | null };
  ev_detail?: EvDetail;
  ei_status?: string;
  county_method?: string;
}

export interface SenateSummary {
  d_seats_median: number;
  d_seats_p10: number;
  d_seats_p90: number;
  p_d_control: number;
  distribution: Record<string, number>;
  threshold?: number;
}

export interface Summary {
  run_id: string;
  as_of: string;
  model_version: string;
  mock?: boolean;
  national: {
    generic_ballot: { margin: number | null; n_polls: number; n_eff: number | null; se: number | null; source?: string };
    npv2024: number;
    s_nat: number;
    senate?: SenateSummary;
  };
  weights: { national: number; state_poll: number };
  races: Race[];
}

export type GroupName = 'wnh_college' | 'wnh_noncollege' | 'black' | 'hispanic' | 'asian' | 'other';

export interface County {
  geoid: string;
  name: string;
  pres2024_margin: number;
  proj_margin: number;
  shift: number;
  interval80: [number, number];
  votes_2024: number;
  votes_proj: number;
  p_dside_win: number;
  group_shares: Partial<Record<GroupName, number>>;
  group_swings: Partial<Record<GroupName, number>>;
  method?: string;
  flags: string[];
}

export interface GroupSwing { group: GroupName; swing: number; sd: number; shrinkage: number; n_polls: number }

export interface EarlyVote {
  as_of_days_out: number;
  vs_2022?: { total_ratio: number };
  vs_2018?: { total_ratio: number };
  vs_2024?: { total_ratio: number };
  party_share?: Record<string, Record<string, number>>;
  cap_binding: boolean;
  /** cumulative ballots by days out per cycle (published for the days-out chart) */
  curves?: Record<string, Array<[number, number]>>;
}

export interface PollRow { pollster: string; end: string; n: number; pop: string; margin: number }

export interface StateFile {
  state: string;
  run_id: string;
  as_of: string;
  counties: County[];
  groups: GroupSwing[];
  early_vote: EarlyVote | null;
  polls_recent: PollRow[];
}

export interface CountiesNational { cols: string[]; rows: Array<Array<string | number>> }

export interface ChangeItem { kind: string; state?: string; text: string; delta?: number }
export interface Changes { run_id: string; as_of: string; items: ChangeItem[] }

export interface DataHealth {
  sources: Array<{ name: string; status: 'ok' | 'fallback' | 'stale'; retrieved_at: string }>;
  flags: string[];
}

export interface MethodologyParams {
  weights: { national: number; state_poll: number };
  combine?: string;
  precision?: { sigma_prior: number; sigma_bias: number; sigma_poll: number; w_min: number; w_max: number; incumbent_pts: number };
  half_life_days: { senate: number; generic: number };
  market: { enabled: boolean; mu: number; weight_cap: number };
  earlyvote: { cap_pts: number; shrink: number };
  county: { max_tilt: number };
  sim: { n_draws: number; control_threshold: number };
}
