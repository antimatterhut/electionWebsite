# Data dictionary (Phase 1)

All processed tables are parquet under `data/processed/` (git-ignored; rebuilt by `make fetch`). Every table carries
`source`, `retrieved_at` (UTC), `source_version`, `data_quality_flag` (`ok` | `manual`). Schemas: `src/senate/schemas.py`.

| Table | Producer | Key | Columns |
|---|---|---|---|
| `pres_county` | `ingest/pres_results.py` | `(year, geoid)` | year, geoid, state_po, votes_d, votes_r, votes_other, votes_total, margin_2p |
| `cvap_county` | `ingest/acs_cvap.py` | `(geoid, race5)` | geoid, race5 (wnh/black/hisp/asian/other), cvap, moe |
| `edu_county` | `ingest/acs_cvap.py` | `geoid` | geoid, college_share_wnh |
| `age_county` | `ingest/acs_cvap.py` | `(geoid, age_bin)` | geoid, age_bin (18-29/30-44/45-64/65+), cvap_share (adult-population proxy) |
| `geographies` | `ingest/shapes.py` | `geoid` | geoid, level, name, state_po, parent_geoid, centroid_lon, centroid_lat |
| `generic_polls` | `ingest/generic_ballot.py` | `(poll_id, pop)` | poll_id, pollster, sponsor, field_start, field_end, n, pop, mode, d_pct, r_pct, und_pct, partisan, source_url |
| `senate_polls` | `ingest/senate_polls.py` | `(poll_id, pop)` | poll_id, state_po, pollster, sponsor, field_start, field_end, n, pop, mode, dside_pct, rside_pct, other_pct, und_pct, matchup_type, partisan, source_url |
| `crosstabs` | `ingest/crosstabs.py` | - | poll_id, geography, group_dim, group_value, n_group, dside_pct, rside_pct, margin_2p |
| `validated_voter_priors` | `ingest/validated_voter.py` | - | study, year, geography, group_dim, group_value, d_share_2p, r_share_2p, turnout_rate, n, moe |

Margins are two-party, D-side minus R, in points. `partisan` is set when the pollster name carries an `(R)`/`(D)` tag.
Manual inputs live in `data/manual/` (see plan §4.9); crosswalks in `data/crosswalks/`.

## Source status (checked 2026-11-02)

| Source | Status |
|---|---|
| MEDSL county presidential (Harvard Dataverse, DOI 10.7910/DVN/VOQCHQ) | DOI valid; file download requires a guestbook response -> manual download into `data/manual/` |
| Census CVAP special tabulation | works without a key |
| Census ACS API (education, age) | requires a free `CENSUS_API_KEY` |
| Census cartographic boundaries (cb_2024_us_county_500k) | works |
| Wikipedia per-race Senate polls | works (23 of 35 races parsed; unnamed nominees cannot be matched) |
| Wikipedia generic-ballot raw polls | page named in plan 404s; falls back to `data/manual/generic_polls.csv` |

## Phase 2 additions

Run with `make model` (live 2026 state table -> `output/summary.json`, `state_swing_2026.csv`, `national_swing.json`,
`poll_audit/<ST>.csv`) and `make backtest` (-> `output/backtest/{report.md,sensitivity.md,metrics.json,<year>/state_errors.parquet}`).

| Input | Location | Notes |
|---|---|---|
| State presidential votes 2016/2020/2024 | `data/manual/backtest/pres_state_<year>.csv` | 2020/2024 summed from the tonmcg county files (GA matches certified totals), 2016 from the Wikipedia state table (tonmcg's 2016 file is incomplete). Used for the baseline when `processed/pres_county.parquet` is absent (MEDSL download is manual). |
| 538 archive polls 2018/2022 | `data/manual/backtest/<year>/{senate,generic}_polls.csv` | Wayback copies of the 538 historical CSVs (fivethirtyeight.com no longer serves them). One row per poll and population; `race` marks special elections (MN 2018, OK 2022). |
| Senate truth 2018/2022 | `data/manual/backtest/<year>/senate_truth.csv` | Wikipedia results tables, votes summed by party; independents standing in for the D-side: Sanders (VT 2018), King (ME 2018), McMullin (UT 2022). |
| Pollster ratings | `data/manual/pollster_ratings.csv` | Seeded from the 538 `numeric_grade` (0-3); unrated pollsters use `polls.unrated_rating`. |
| Aggregator headlines | `data/manual/aggregator_headlines.csv` | Wikipedia 2026 House-elections aggregator table, 2026-11-01. |

Rebuild all of the above with `python scripts/build_backtest_data.py`.

Excluded from the backtests (no usable two-party contest): CA 2018 (two Democrats), AK 2022 (ranked-choice, no D-vs-R
final round), MS 2018 special (four-candidate jungle). That leaves 33 races in 2018 and 34 in 2022.

Known gaps: no raw 2026 generic-ballot poll source (the Wikipedia raw-poll page named in plan 4.2 redirects to a
page with only the aggregator table), so the live national swing uses the median of the aggregator headlines
(`gb_source: aggregator_median_fallback` in `summary.json`) until `data/manual/generic_polls.csv` is filled.

## Phase 3 additions (EI, crosstab group swings, county swings)

Commands: `make ei` (all EI fits, then the 2020->2024 shift fit; owner's machine only, results are committed, CI never
runs it), `make crosstab`, `make county`, `make ei-validate`, `make county-backtest`.

| Table / file | Producer | Columns |
|---|---|---|
| `processed/ei_group_vote.parquet` | `ei/run_state.py` | `geoid, group, theta_mean, theta_p10, theta_p90, n_group, ei_status (ok/retry/fallback), rhat_max, ess_min, ei_shift_c` + provenance |
| `processed/ei_shift_2024.parquet` | `ei/shift_ei.py` | `region, group, delta_mean, delta_sd` (D-margin points, 2024 minus 2020), `n_group, theta24, rhat_max, ess_min, divergences` + provenance |
| `processed/group_swing.parquet` | `crosstab/run_group_swing.py` | `region, group, delta_mean, delta_sd, n_polls, shrinkage_factor` + provenance |
| `processed/gradients.json` | same | `age_gradient_per_sd, gender_gradient, n_cells, reason` |
| `processed/county_swing_2026.parquet`, `output/county_swing_2026.csv` | `county/run_county.py` | `geoid, state_po, region, m0, tilt, age_term, s_raw, s, lam, county_method, m_hat, omega` |
| `output/county/calibration_check.csv` | same | per state: `S_s`, weighted mean county swing, `abs_err`, `lambda`, `county_method` |
| `output/validation/ei_flags.csv` | `ei/validation.py` | `group, region, ei, benchmark, diff, study, flag` |
| `output/ei/run_report.json` | `ei/run_state.py` | per job: status, seconds, rhat/ess/divergences/bfmi |
| `output/county/backtest_2020_2024_*` | `county/backtest.py` | county errors and summary (IN-SAMPLE, see below) |

`config.county.max_tilt` (6.0) is the county-tilt cap named in plan §14; it is the only config key added.

### How Phase 3 inputs differ from the plan (because of what is in the repo today)

- **Votes.** `processed/pres_county.parquet` does not exist (MEDSL download is manual), so county 2020/2024 votes are read
  from the tonmcg raw files. Alaska is excluded: tonmcg gives state-house districts and `ak_district_to_borough.csv` is
  empty, so Alaska has no county layer. Hawaii's Kalawao and a few other units missing from tonmcg are dropped.
- **Covariates.** `edu_county` / `age_county` need `CENSUS_API_KEY` and are absent. The EI covariate set is therefore only
  standardised `log(CVAP)` (urbanicity proxy); income and foreign-born are not available in any table. The WNH
  college/non-college split uses a flat 38% college share (`edu_source = default` in the group table), so the split
  between those two groups is not county-specific until `edu_county` is fetched. The age term is 0 until `age_county`.
- **Priors.** `validated_voter_priors.csv` is empty. The EI priors are placeholders (`ei/inputs.py::PLACEHOLDER_PRIOR`,
  SD 0.35 logit), flagged UNVERIFIED, and **EI-vs-validated-voter validation cannot be evaluated**: `ei_flags.csv` is
  header-only.
- **Crosstabs.** `crosstabs.csv` is empty, so `group_swing` is prior-only: `S_nat + 0.5 x persisted EI pattern`,
  `n_polls = 0`, `shrinkage_factor = 1`. Fill `crosstabs.csv` and `group_map.csv` (seeded from plan §6.7) and re-run.
- **Regions.** Plan §6.7 names seven regions but not county membership. Rule used: state -> northeast/midwest/south/
  mountain/pacific; `black_belt` = counties in AL AR FL GA LA MS NC SC TN VA with Black CVAP >= 35%; `rio_grande` =
  AZ/NM/TX counties with Hispanic CVAP >= 50%.
- **EI accounting identity.** After sampling, each county gets a single logit shift (`ei_shift_c`) so that group shares
  reproduce that county's D votes exactly (plan §6.6 acceptance: within 0.5%). Between-group differences are untouched.
- **Turnout weights.** `county/construct.py::omega_groups` uses omega_ig = n_ig(2024) x drop-off_g, rescaled to the
  state's 2024 total; the T_s^2026 level and the early-vote reweighting are Phase 4/5 and do not change county tilts.
- **Age gradient.** `beta_age` = (18-44 minus 45+ swing gap from age crosstabs, relative to validated-voter age
  baselines) x SD of the county 18-44 share. Without age cells or age baselines it is 0 and `gradients.json` says why.
- **County backtest.** The plan's county RMSE gate needs county-level Senate truth (MEDSL county Senate 2018/2022),
  which is not in the repo. `make county-backtest` instead predicts 2020->2024 presidential county shifts from the
  shift-EI pattern given the true state swing. That is in-sample, so it checks the mechanism, not the §7.4 threshold.

## Phase 4 - early vote (plan §4.6, §6.9)

| Table / file | Producer | Notes |
|---|---|---|
| `processed/early_vote_daily.parquet` | `ingest/early_vote.py::ingest_early_vote` (stage `fetch_early_vote`) | 2026 snapshots, appended and de-duplicated on `(state_po, geoid, date, mode, party, age_bin, race5, cycle)`. Columns `state_po, geoid (null = state), date, days_out, mode, party, age_bin, race5, ballots, cycle` + provenance. `ballots` is CUMULATIVE (pandera checks it never decreases). Only marginals are stored: at most one of party/age_bin/race5 is not `all`; `mode` other than `total` appears only on total rows. |
| `processed/early_vote_hist.parquet` | same, from `data/manual/early_vote_{ST}.csv` rows with `cycle != 2026` | Same schema, day 0 = Election Day. No historical file ships in the repo. |
| `data/manual/early_vote_{ST}.csv` | hand-entered | Fallback for any adapter failure and the only source for states without an adapter (all but NC, GA, FL). Same columns as the long format; `cycle` column separates 2026 from history. |
| `data/manual/ev_final.csv` | hand-entered (header only) | `state_po, cycle, party, age_bin, race5, final_ballots` - certified final ballots per category (use `all` for unused dimensions). ADDED BY ME: the plan's `f^c_j(d) = EV^c_j(d) / Final^c_j` needs a denominator the §4.6 schema does not carry. |
| `data/manual/ev_rules.csv` | hand-entered (header only) | `state_po, cycle, early_period_scale, note`: early-period length of that cycle relative to 2026; days-out of cycle `c` is `d x scale`. Default 1. |
| `data/manual/ev_party_group.csv` | hand-entered (header only) | `state_po, group, party, count`: voter-file party mix by EI group, builds `Q[p,g]` (`party_to_group_matrix`). Without it party categories are unusable and the state falls back to age, race, then total. |
| `processed/early_vote_weights.parquet` | `make earlyvote` | `geoid, group, omega_base, omega_ev, state_po`. `make county` uses `omega_ev` as the final weights when the file exists. |
| `output/early_vote_component.csv` | `make earlyvote` | The separately exported component: `state_po, ev_detail, dim, as_of_days_out, E_raw, E, kappa, cap_binding, projected_total_ballots, total_ratio_{2018,2022,2024}`. `make model` reads `E` into `components.early_vote` and `proj_margin`. |
| `output/early_vote/days_out_<ST>.{csv,png}`, `output/early_vote_summary.json` | `make earlyvote` | Days-out curves per cycle (review item), `ev_detail` counts, states not `full`, binding caps. |
| `output/early_vote_backtest_2022.{csv,json}` | `make earlyvote-backtest` | 2022 turnout projection vs certified final, `rmse_pts` (target <= 3). |

Deviations and limits:

- **Adapters are unverified.** The NC/GA/FL URLs and column maps in `ingest/early_vote.py` were not checked against a live file; a layout change raises `layout changed` and falls back to the manual CSV. AZ, NV, MI, PA, OH, TX, WI are manual-only.
- **Age categories** are applied at county level (`sum_a share_ia psi_a` from `age_county`), because the EI groups carry no age dimension. Race maps directly (white -> both WNH groups). Party goes through `Q`.
- **Cap.** `gamma -> gamma x kappa` also scales the county-blend exponent so county-only states are capped too. `kappa` is the bisection bracket end with `|E| <= cap`.
- **Backtest comparators** are the other cycles in `early_vote_hist`, equally weighted (config has no 2020 weight). With no history or no `ev_final.csv` it reports `status: no_data` rather than a pass.
