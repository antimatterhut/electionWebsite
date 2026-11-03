# Methodology

Parameter values on this page are filled in from the current run's `methodology_params.json`. This page follows the project plan (§15); sections describing components that are not yet live in a given run say so explicitly.

## 1. What this is

A county-level projection of the 2026 U.S. Senate races. It is a **pre-election projection**: not an official result, not a poll, and not a prediction that any single county will land exactly on its projected margin. Probabilities describe model uncertainty; they are not forecasts of margins.

## 2. The starting point

Every projection starts from the **2024 presidential two-party margin** in each county (Democratic minus Republican votes, divided by their sum). Presidential results are used rather than 2024 House or Senate results because they are contested everywhere on the same ballot line, so county differences are not distorted by uncontested seats or candidate quality.

## 3. The national mood

The national swing is the generic-ballot margin minus the 2024 national presidential two-party margin. A positive swing means the national environment is more Democratic than in 2024. The generic-ballot average is built from individual polls, weighted by recency, sample size, pollster quality and population (likely voters, registered voters, adults). When raw polls are unavailable the median of published aggregator headlines is used and the run is flagged.

## 4. Race-specific polling

Polls for each Senate race are averaged with: a recency half-life of {{half_life_days.senate}} days, a sample-size cap, pollster quality ratings, a likely-voter adjustment, house-effect corrections shrunk toward zero, and a cap so no single pollster dominates. States without enough recent polling use the national swing alone and are labelled on their pages.

## 5. Combining them 2:1

The state swing is a weighted average of the national swing and the swing implied by the race's own polls, with weights **{{weights.national}}:{{weights.state_poll}}** (national : race polls). National polling is far more abundant and less noisy than state polling, so it receives twice the weight. In unpolled states the swing is the national swing. For transparency the backtest below also reports 1:1 and 3:1; the default is not tuned to those results.

## 5b. A small nudge from betting markets

Prediction-market prices can be converted to an implied margin and blended in with a small weight (default {{market.mu}}, capped at {{market.weight_cap}}). Markets and polls overlap, so the weight is deliberately small. In this run markets are **{{market.enabled_label}}**.

## 6. Where the swing lands

The state total is fixed first. Inside a state, the swing is distributed across counties according to who lives there: counties with more of a demographic group that is swinging get more of that group's swing. Group swings come from published poll crosstabs, combined with a hierarchical model that shrinks noisy groups toward the overall swing. Group behaviour at the county level is estimated with ecological inference: a statistical method that infers how groups voted from the way county results vary with county demographics. It is informative but not exact, and counties where it cannot identify group behaviour fall back to a uniform swing (the tooltip says which method each county used). The county tilt is capped at ±{{county.max_tilt}} points.

## 7. Calibration

County swings are adjusted by a single constant per state so that their vote-weighted average equals the state swing exactly. County detail therefore can never change who wins a state.

## 8. Early vote and turnout

Midterm electorates differ from presidential ones. The turnout model applies group-specific drop-off from 2024 and scales to an expected state total; its effect on the margin is shown as the **turnout composition** step. Early-vote returns are compared with the same number of days out in 2022, 2018 and 2024. Party registration is handled carefully because Republican early-voting habits changed after 2020, so party comparisons use only 2022 and 2024. The early-vote effect is shrunk by {{earlyvote.shrink}}, **capped at ±{{earlyvote.cap_pts}} points**, and shown as its own bar. States that report only totals have no effect on the margin.

## 9. Uncertainty

{{sim.n_draws}} simulated elections add correlated errors at the national, regional, demographic-group, state and county levels (heavy-tailed, so rare large misses are possible). State errors are correlated more strongly between states with similar electorates. The county error term averages to zero within a state, so it spreads county results without moving the state total. The 80% intervals shown are the 10th–90th percentiles of those draws. Error sizes are set from historical Senate polling misses where that history is available, and otherwise from documented defaults; a run's page states which. Control of the Senate requires {{sim.control_threshold}} Democratic-caucus seats.

## 10. Special cases

- **Independents as the Democratic side** (for example Nebraska): the independent standing in for the Democrats is treated as the D-side candidate and marked with a diamond.
- **Ranked-choice voting** (Maine, Alaska): the margin is computed on the final round; transfers are modelled with a stated rule.
- **New England towns, Connecticut planning regions, Alaska boroughs, Virginia independent cities**: geography follows the entities that report results; some are combined to the nearest county-equivalent.
- **Special elections** (Ohio, Florida) are separate races with their own candidates.

## 11. Backtests

The same code is run as of one day before the 2018 and 2022 elections, using only information available then. <!--BACKTEST--> A coin-flip forecaster has a Brier score of 0.25. The table reports honest results, including any miss against the pre-registered acceptance thresholds.

## 12. Data sources and credits

See the About page. Limitations: poll coverage is thin in many states; crosstabs are noisy; ecological inference cannot identify everything; early-vote data are partial. Known issues for this run are listed on the national page when present.

## 13. Changelog and corrections

Corrections are listed here with the date and what changed. Model-version changes are announced here before they take effect.
