// The 35 race states, used to prerender /state/[abbr] (plan §10.2). tests/unit/states.test.ts checks it against
// data/manual/races_2026.csv so the list cannot silently drift.
export const RACE_STATES = [
  'AK', 'AL', 'AR', 'CO', 'DE', 'FL', 'GA', 'IA', 'ID', 'IL', 'KS', 'KY', 'LA', 'MA', 'ME', 'MI', 'MN', 'MS', 'MT',
  'NC', 'NE', 'NH', 'NJ', 'NM', 'OH', 'OK', 'OR', 'RI', 'SC', 'SD', 'TN', 'TX', 'VA', 'WV', 'WY'
] as const;
