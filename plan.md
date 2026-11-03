# 2026 Senate County-Level Projection Site — Implementation Plan

> Plan date: **2026-11-02** (Election Day is 2026-11-03). Sources checked on this date unless stated.
> Markers: `⚠️ UNVERIFIED` = could not confirm in research; `❓ DECISION` = needs the owner's decision.
> Owner preferences (confirmed): SvelteKit + GitHub Pages; strong Python / some JS; **no precinct phase for now**; permitted sources first with manual-CSV fallback; build a **reusable** pipeline (2026 night + future cycles).

## Table of contents
0. [Executive summary](#0-executive-summary)
1. [Assumptions and open questions](#1-assumptions-and-open-questions)
2. [Scope](#2-scope)
3. [Repository structure](#3-repository-structure)
4. [Data sources and ingestion](#4-data-sources-and-ingestion)
5. [Data model](#5-data-model)
6. [Model specification](#6-model-specification)
7. [Validation and backtesting](#7-validation-and-backtesting)
8. [Pipeline orchestration](#8-pipeline-orchestration)
9. [Output artifacts](#9-output-artifacts)
10. [Website](#10-website)
11. [Testing strategy](#11-testing-strategy)
12. [Configuration reference](#12-configuration-reference)
13. [Phased implementation plan](#13-phased-implementation-plan)
14. [Risks and mitigations](#14-risks-and-mitigations)
15. [Methodology write-up outline](#15-methodology-write-up-outline)
16. [Glossary](#16-glossary)

---

## 0. Executive summary

**What is built.** A static website showing, for all 2026 U.S. Senate races, a projected 2026 two-party margin and the shift from the 2024 presidential two-party margin, for every state and every county (or county-equivalent), plus win probabilities, 80% intervals and a Senate seat distribution.

**The model in five sentences.**
1. Baseline is the 2024 presidential two-party margin (D−R) in every geography.
2. The national swing is `S_nat = GenericBallotAvg − NPV2024`; the race-specific swing is `S_poll_s = SenatePollAvg_s − Pres2024Margin_s`; they combine 2:1 as `S_base_s = (2·S_nat + 1·S_poll_s)/3` (unpolled states use `S_nat`), and betting-market odds then contribute a small, capped share: `S_state_s = (1−μ)·S_base_s + μ·S_mkt_s` (default μ = 10%, liquidity-scaled, cap 20%).
3. Crosstab-derived group swings (shrunk toward the state swing) and Bayesian R×C ecological inference (EI) on CVAP × county results decide *where inside a state* the swing lands, then county swings are calibrated so the turnout-weighted mean equals `S_state_s` exactly.
4. Early-vote comparisons (same days-out vs 2022, 2018, 2024) adjust expected electorate composition/turnout only, with the statewide effect capped at ±1.5 pts and shown as a separate component.
5. A correlated Monte Carlo (national, regional/demographic, state, county error terms calibrated on 2006–2022 midterm poll misses) yields win probabilities, 80% intervals and a seat distribution.

**Tech stack.** Python 3.12 pipeline (pandas, geopandas, PyMC 6.x + PyEI 1.1.x, numpyro/JAX, DuckDB/Parquet), `make`-driven DAG, GitHub Actions scheduling; SvelteKit (static adapter) + D3-geo + TopoJSON on GitHub Pages.

**Phase timeline** (focused-engineer weeks; see §13):

| Phase | Content | Effort |
|---|---|---|
| 1 | Data ingestion | 2.0 wk |
| 2 | National + state swing model + backtest | 1.5 wk |
| 3 | EI + demographic distribution | 3.0 wk |
| 4 | Early vote | 1.5 wk |
| 5 | Turnout + simulation | 1.5 wk |
| 6 | Frontend | 3.0 wk |
| 7 | Deployment + automation | 1.0 wk |
| 8 | Precinct extension | **deferred** (stub only) |

Because Election Day is tomorrow, the first public deliverable should be **Phase 1 + 2 + 6-lite** (state and county map from the swing model, no EI: county swing = state swing with a simple demographic tilt placeholder, clearly labelled). EI, early vote and simulation follow. ❓ DECISION: whether to ship that v0 before or after Nov 3.

---

## 1. Assumptions and open questions

### 1.1 Assumptions

| # | Assumption | Why |
|---|---|---|
| A1 | "Margin" = two-party margin `(D − R)/(D + R)` in percentage points; third-party/independent votes are excluded from the denominator except where an independent is the de-facto D-side candidate. | Matches requirement 1 and removes third-party noise from swing arithmetic. |
| A2 | Generic-ballot and poll averages are converted to two-party margin before use. | Raw margins (D% − R%) in polls with undecideds understate two-party margin; conversion keeps units comparable to `NPV2024`. |
| A3 | `NPV2024` = 2024 national presidential two-party margin ≈ **R+1.5** (Trump ≈ 49.8%, Harris ≈ 48.3% of the raw vote). Pipeline recomputes it from the certified county file; value here is illustrative. ⚠️ UNVERIFIED to the decimal. | Needed for worked examples. |
| A4 | The generic ballot is a **House** measure; it is used as the *national environment* for Senate swing per requirement 2. The Senate-vs-House difference is absorbed by `S_poll_s` and the simulation's race-level error. | User's decision. |
| A5 | Special elections (OH, FL) are modelled identically to regular races. | Same ballot, same electorate. |
| A6 | Where the Democratic nominee withdrew and an independent is the de-facto challenger (NE: Osborn; and, per Wikipedia snapshot, ID, MT, SD ⚠️ UNVERIFIED), the independent is the **"D-side" candidate** and the UI labels them by name and party ("Ind., Dem.-endorsed" where true). Margin = D-side − R. | Satisfies §2 independents rule. |
| A7 | Ranked-choice (ME, AK) is modelled as the **final-round two-candidate margin**; polling inputs use final-round/head-to-head numbers where available, else two-party-converted first-choice. | Requirement §2. |
| A8 | CVAP and ACS use **ACS 2019–2023 5-year** (released Dec 2024) with CVAP special tabulation 2019–2023 (⚠️ UNVERIFIED availability date; fallback = 2018–2022 CVAP). | Latest verifiable pair at plan time. |
| A9 | The site is **static**; results of Election Night are handled by a "results overlay" JSON (post-election mode, §8.6), not by server code. | GitHub Pages. |
| A10 | No paid data (Catalist, Leip). Validated-voter priors come from published Pew validated-voter reports and AP VoteCast tables entered by hand into `data/manual/`. | User chose permitted/open sources. |
| A11 | Compute: **zero-cost only** — GitHub Actions *standard* free runners for the light nightly jobs, and the owner's own computer for the heavy one-off EI runs (results cached and committed). No larger/paid runners. | Runtime budget §8.5. |
| A13 | **Zero-spend constraint (owner decision): no paid services, data, domains, APIs or hosting of any kind.** The repo is **public** (free GitHub Pages and unlimited free Actions minutes on standard runners; private repos would hit plan limits and Pages-on-private needs a paid plan). Only free data: Census (free API key), MEDSL, Wikipedia, state SoS, Kalshi/Polymarket public read-only market data, Pew/AP published tables. If any free source turns out to require payment or a paid key, it is dropped to its manual-CSV fallback, not purchased. | Owner request. |
| A12 | Dates: the project continues past 2026; paths are cycle-parametrised (`cycle: 2026`). | User asked for reusable build. |

### 1.2 Open questions for the owner

| ID | Question | Default if unanswered |
|---|---|---|
| Q1 | ❓ DECISION: ship a no-EI "v0" before Nov 3? | No: ship after Phase 2 passes backtest. |
| Q2 | ❓ DECISION: acceptable to display win probabilities before simulation calibration passes §7 thresholds? | No. |
| Q3 | ❓ DECISION: site name / branding. (No custom domain: costs money.) | `senate-county-projection` repo; free `github.io` project-pages URL. |
| Q4 | ❓ DECISION: should independents who caucus with Democrats be coloured on the D scale? | Yes, with distinct label. |
| Q5 | ❓ DECISION: poll-volume-scaled combination (§6.5) — leave off? | Off. |
| Q6 | ❓ DECISION: scrape aggregators whose ToS are unclear, or hand-enter? | Hand-enter / download only where permitted. |
| Q7 | ✅ DECIDED: market weight `μ` = 10% (liquidity-scaled, cap 20%); site shows **derived values only** (`p_market`, implied margin), never raw prices/order books. | — |

---

## 2. Scope

### 2.1 Races

Verified source: Wikipedia “2026 United States Senate elections” (snapshot read 2026-11-02; text truncated after ~100k chars, so the table below must be re-verified against Ballotpedia and each state's SoS before launch). **35 races: 33 regular (Class 2) + 2 specials (OH, FL, Class 3).** Candidates marked ⚠️ are from a partial, possibly stale snapshot.

| State | Class | Incumbent | Special | Notable candidates (⚠️ verify) | Non-standard rules |
|---|---|---|---|---|---|
| AL | 2 | Tuberville (R), retiring | No | Barry Moore (R), Everett Wess (D) | — |
| AK | 2 | Sullivan (R) | No | Sullivan (R), Mary Peltola (D) | **Ranked-choice general**; boroughs/House districts (§2.2). ⚠️ confirm RCV still in force in 2026 |
| AR | 2 | Cotton (R) | No | Hallie Shoffner (D) | — |
| CO | 2 | Hickenlooper (D) | No | Mark Baisley (R) | — |
| DE | 2 | Coons (D) | No | Michael Katz (R) | — |
| FL | 3 | Moody (R), appointed | **Yes** (term to Jan 2029) | Angie Nixon (D) | Special; primary Aug 18 |
| GA | 2 | Ossoff (D) | No | Mike Collins (R) | General-election runoff law (Dec) applies if no majority |
| ID | 2 | Risch (R) | No | Todd Achilles (Ind.) ⚠️; D nominee withdrew | Independent de-facto challenger |
| IL | 2 | Durbin (D), retiring | No | Juliana Stratton (D), Don Tracy (R) | — |
| IA | 2 | Ernst (R), retiring | No | Ashley Hinson (R), Josh Turek (D) | — |
| KS | 2 | Marshall (R) | No | Adam Hamilton (D) | — |
| KY | 2 | McConnell (R), retiring | No | Andy Barr (R), Charles Booker (D) | — |
| LA | 2 | Cassidy (R), lost renomination ⚠️ | No | Julia Letlow (R), Jamie Davis (D) | Closed party primary + runoff system |
| ME | 2 | Collins (R) | No | Collins (R), Troy Jackson (D) ⚠️ (replaced Platner per snapshot) | **Ranked-choice general**; New England towns |
| MA | 2 | Markey (D) | No | John Deaton (R) | Town-level reporting |
| MI | 2 | Peters (D), retiring | No | Abdul El-Sayed (D) ⚠️, Mike Rogers (R) | — |
| MN | 2 | Smith (DFL), retiring | No | Peggy Flanagan (DFL), Michele Tafoya (R) | Party label DFL → D |
| MS | 2 | Hyde-Smith (R) | No | Scott Colom (D) | — |
| MT | 2 | Daines (R), retiring ⚠️ | No | Kurt Alme (R), Seth Bodnar (Ind.), Alani Bankhead (D) | Independent + nominal D split the D-side ⚠️ |
| NE | 2 | Ricketts (R) | No | **Dan Osborn (Ind.)**; D nominee withdrew, state Dems endorsed Osborn | Independent = D-side |
| NH | 2 | Shaheen (D), retiring | No | Chris Pappas (D), John E. Sununu (R) | Town-level reporting |
| NJ | 2 | Booker (D) | No | Justin Murphy (R) | — |
| NM | 2 | Luján (D) | No | not in snapshot | — |
| NC | 2 | Tillis (R), retiring | No | Roy Cooper (D), Michael Whatley (R) | — |
| OH | 3 | Husted (R), appointed | **Yes** (term to Jan 2029) | Sherrod Brown (D), Jon Husted (R) | Special |
| OK | 2 | Alan Armstrong (R), appointed ⚠️ | No | not in snapshot | ⚠️ unusual; verify |
| OR | 2 | Merkley (D) | No | not in snapshot | — |
| RI | 2 | Reed (D) | No | not in snapshot | Town-level reporting |
| SC | 2 | Darline Graham (R) ⚠️ | No | not in snapshot | ⚠️ verify incumbent |
| SD | 2 | Rounds (R) | No | independent challenger ⚠️ | — |
| TN | 2 | Hagerty (R) | No | not in snapshot | — |
| TX | 2 | Cornyn (R), lost renomination ⚠️ | No | Ken Paxton (R), James Talarico (D) | Runoff law if no majority (general: none) |
| VA | 2 | Warner (D) | No | not in snapshot | Independent cities |
| WV | 2 | Capito (R) | No | not in snapshot | — |
| WY | 2 | Lummis (R), retiring ⚠️ | No | not in snapshot | — |

Data file: `data/manual/races_2026.csv` is the canonical list (schema in §4.9); the table above seeds it. A pipeline check (`tests/data/test_races.py::test_35_races`) enforces 35 rows, 33 class-2, 2 class-3.

### 2.2 Geography rules

| Case | Rule |
|---|---|
| **Independent as D-side (NE, and any other race flagged `dside_candidate_type = 'independent'`)** | `dside_name`, `dside_party` stored per race. All margins are D-side − R. Labels: "Osborn (I)". Color scale is the D scale; tooltip shows "Independent (Democratic-endorsed)" when `dside_endorsed_by_dem = true`. Baseline for the geography is still Harris−Trump. |
| **Ranked-choice (ME, AK)** | Model `margin_final = P(D-side beats R in final round)` margin: final-round two-candidate margin. Poll input priority: (1) explicit final-round head-to-head; (2) first-round shares with minor-candidate transfers by `config.rcv.transfer_to_dside = 0.50` (⚠️ tune from 2018 ME-02 / 2022 AK data); (3) two-party-converted first-round. Output flags `rcv: true`. |
| **New England towns (CT, MA, ME, NH, RI, VT)** | Pipeline ingests town results, then aggregates to counties via `data/crosswalks/town_to_county.csv` for the county layer; the town layer is optional (`config.geo.town_layer: false`). CT uses 2022+ planning regions (below). Maine's unorganized territories map to the host county; MA/ME/NH/RI/VT/CT town splits across counties (rare) use the Census county subdivision GEOID. |
| **Connecticut** | Census 2022 replaced 8 counties with 9 planning regions (FIPS 09110–09190). 2024 results are published by town; 2020 results used old counties (09001–09015). Crosswalk `ct_town_to_planning_region.csv` + `ct_county_to_planning_region_2020.csv` (area/pop-weighted, from Census relationship file). The site shows planning regions; EI for CT uses towns as units to avoid vintage mismatch. |
| **Alaska** | Results are by 40 State House districts (2024) not boroughs; ACS by borough/census area. Crosswalk `ak_district_to_borough.csv` using Census block-level overlay (pop-weighted). Display layer = 30 boroughs/census areas, noting approximation. Also 2024 Alaska had Dec-2022 redistricting; use post-2022 districts for 2020 and 2024 consistently. |
| **Virginia** | 38 independent cities are county-equivalents with their own FIPS (51510…51840); keep them separate. Where ACS/CVAP merges (e.g., Bedford city/county pre-2013, Fairfax city/county shares), use FIPS-year crosswalk. |
| **Louisiana** | Parishes; FIPS 22xxx. |
| **DC** | No Senate race; excluded. |
| **Kalawao, Hawaii; Oglala Lakota SD (46102 vs 46113 old); Shannon→Oglala** | Crosswalk `fips_aliases.csv`. |
| **Missing/combined** | Kansas City MO, Yellowstone Park MT, Rio Arriba edge cases: handled via `geographies.is_special_unit`. |

---

## 3. Repository structure

```
.
├── plan.md                         # this document
├── Makefile                        # `make update`, `make backtest`, `make site`
├── pyproject.toml                  # uv-managed Python 3.12 project (pinned deps)
├── config/
│   ├── config.yaml                 # all tunables (§12)
│   └── config.test.yaml            # small fixture config for CI
├── data/
│   ├── raw/                        # immutable downloads, date-stamped: raw/<source>/<YYYY-MM-DD>/...
│   ├── interim/                    # cleaned parquet per source
│   ├── processed/                  # model-ready tables (parquet)
│   ├── manual/                     # hand-maintained CSV fallbacks (versioned in git)
│   ├── crosswalks/                 # geography & vintage crosswalks (csv)
│   └── cache/                      # HTTP cache (sqlite), EI traces (netcdf)
├── src/senate/
│   ├── __init__.py
│   ├── config.py                   # pydantic Settings loader
│   ├── io.py                       # fetch(), cache, UA, rate limiting
│   ├── geo/                        # fips.py, crosswalks.py, shapes.py
│   ├── ingest/
│   │   ├── pres_results.py
│   │   ├── generic_ballot.py
│   │   ├── senate_polls.py
│   │   ├── crosstabs.py
│   │   ├── acs_cvap.py
│   │   ├── early_vote.py
│   │   ├── validated_voter.py
│   │   └── shapes.py
│   ├── polls/                      # weights.py, house_effects.py, average.py, lv_rv.py
│   ├── swing/                      # national.py, state.py, combine.py
│   ├── ei/                         # groups.py, model_rxc.py, run_state.py, shift_ei.py, diagnostics.py
│   ├── crosstab/                   # harmonize.py, hier_model.py
│   ├── county/                     # construct.py, calibrate.py
│   ├── earlyvote/                  # compare.py, weights.py
│   ├── turnout/                    # model.py
│   ├── sim/                        # errors.py, covariance.py, simulate.py, outputs.py
│   ├── backtest/                   # run_backtest.py, metrics.py
│   ├── export/                     # to_json.py, to_topojson.py, diff.py
│   └── cli.py                      # `python -m senate.cli <stage>`
├── tests/                          # unit/, integration/, data/, fixtures/
├── scripts/                        # one-off helpers (build_crosswalks.py, seed_races.py)
├── output/                         # build artefacts consumed by the site (git-ignored; copied to site/static/data)
├── site/                           # SvelteKit app
│   ├── src/routes/                 # +page.svelte (national), state/[abbr]/, methodology/, about/
│   ├── src/lib/components/         # Map.svelte, StateTable.svelte, Tooltip.svelte, Toggle.svelte, ...
│   ├── src/lib/data/               # loaders, types
│   ├── static/data/                # published JSON/TopoJSON
│   └── tests/                      # vitest + playwright
├── .github/workflows/              # update.yml, deploy.yml, ci.yml
└── docs/                           # methodology.md source, data_dictionary.md
```

---

## 4. Data sources and ingestion

**Global policy (applies to every source).**
- User-Agent: `SenateCountyProjection/1.0 (+https://<site-url>/about; research project)` — descriptive, generic, no personal info.
- Respect `robots.txt` (checked at fetch via `urllib.robotparser`; cache 24 h). Disallowed ⇒ the fetch is refused and the stage falls back to `data/manual/`.
- Rate limit: ≥ 2 s between requests per host (`config.http.min_interval_s: 2.0`), max 1 concurrent connection per host, exponential backoff on 429/5xx (base 5 s, 4 tries).
- Cache: sqlite HTTP cache in `data/cache/http.sqlite` keyed by URL + ETag/Last-Modified; raw bodies saved to `data/raw/<source>/<date>/`.
- Failure fallback: every ingest function `ingest_X()` accepts `allow_fallback=True`; on any fetch/parse failure it logs `WARN source=X fallback=manual`, loads `data/manual/X.csv`, and stamps `data_quality_flag = 'manual'`.
- Every processed table carries `source`, `retrieved_at` (UTC), `source_version`.

### 4.1 2024 and 2020 presidential county results

| Item | Detail |
|---|---|
| Primary | MIT Election Data + Science Lab (MEDSL) “County Presidential Election Returns 2000–2024”, Harvard Dataverse, DOI `10.7910/DVN/VOQCHQ` ⚠️ UNVERIFIED (third-party pages cite it; confirm on dataverse.harvard.edu). CSV/TAB. Updated: per release. Terms: CC0 per MEDSL convention ⚠️ UNVERIFIED; may require API token/guestbook ⚠️. |
| Secondary | Dave Leip's Atlas (paywalled; **not used**). State SoS certified results (used for audit of battlegrounds). Ad-hoc GitHub datasets (e.g., tonmcg county results) used only as cross-check. |
| Method | Download CSV via Dataverse API (`/api/access/datafile/:persistentId?persistentId=doi:...`), store raw. |
| Fields | `year, state, state_po, county_name, county_fips, office, candidate, party, candidatevotes, totalvotes, mode`. |
| Cleaning steps | (1) Filter `office='US PRESIDENT'`, `year ∈ {2020, 2024}`. (2) Keep `mode='TOTAL'` or sum modes if split (some states list EARLY/ELECTION DAY/MAIL separately: sum). (3) Map `party` to `D`, `R`, `OTHER` (DEMOCRAT→D, REPUBLICAN→R; all else OTHER). (4) Zero-pad `county_fips` to 5 chars. (5) Alaska: reported by district — apply crosswalk; Connecticut: towns→planning regions; Maine/NH/MA/RI/VT: towns→counties when town-level. (6) Drop DC (11001), territories. (7) Fix known FIPS issues: Oglala Lakota, Kalawao HI, VA independent cities, Bedford. (8) Assert `sum(candidatevotes) ≤ totalvotes` and national D+R total within 0.1% of FEC certified totals. (9) Missing counties (e.g., Kansas City MO overlay, Alaska) flagged. |
| Raw → processed | table below |
| Fallback | `data/manual/pres_county_{2020,2024}.csv` from state SoS exports, same schema. |
| Known issues | Duplicated rows for write-ins; `totalvotes` including blank/over/under; some versions list Alaska by district only; MEDSL occasionally lists Dane County WI in two lines for absentee. Resolved by sum/aggregate steps above. |

**Processed: `processed/pres_county.parquet`**

| column | type | description | example |
|---|---|---|---|
| `year` | int16 | election year | 2024 |
| `geoid` | str(5) | county FIPS (or planning-region FIPS for CT) | `13121` |
| `state_po` | str(2) | postal | `GA` |
| `votes_d` | int32 | Harris/Biden votes | 380,000 (illustrative) |
| `votes_r` | int32 | Trump votes | 140,000 (illustrative) |
| `votes_other` | int32 | other | 5,000 |
| `votes_total` | int32 | all votes | 525,000 |
| `margin_2p` | float32 | `(D−R)/(D+R)×100` | 52.3 |
| `source`, `retrieved_at`, `data_quality_flag` | str, ts, str | provenance | `medsl`, ... , `ok` |

### 4.2 Generic ballot (aggregators and raw polls)

Verified 2026-11-02:

| Source | URL | Format | Status | Notes |
|---|---|---|---|---|
| Silver Bulletin | `https://www.natesilver.net/p/generic-ballot-average-2026-nate-silver-bulletin-congress-polls` | HTML page (Substack); poll table + chart; probably embedded data download | **Active**, snapshot Oct 26: ~D+9, also LV-adjusted | robots.txt (`natesilver.net/robots.txt`, checked today): general crawlers allowed except `/action/`, `/subscribe`, `/embed`, etc.; content signal `ai-train=no`. Fetch of the article page is allowed by robots; ToS ⚠️ UNVERIFIED ⇒ use **manual entry of the headline average** + raw poll list only if a documented download exists. |
| PollCheck | `https://www.pollcheck.co.uk/us-midterms-2026/generic-ballot` | HTML | Active, Oct 27: D+8.7 (51.1–42.4), lists 40 polls | ToS ⚠️ UNVERIFIED. |
| FiftyPlusOne | `https://blog.fiftyplusone.news/p/an-updated-generic-ballot-polling` | HTML/Substack | Active; LV/RV-aware method | ⚠️ ToS. |
| RealClearPolling | `realclearpolling.com` | HTML | Exists; current generic-ballot page not confirmed | Their ToS restrict automated collection ⚠️ UNVERIFIED ⇒ **manual only**. |
| Decision Desk HQ / The Hill | — | — | Generic-ballot average not found ⚠️ | Omit unless found. |
| VoteHub | — | — | No result found ⚠️ | Omit unless found (the project is modelled on its site layout, not its data). |
| FiveThirtyEight | — | — | **Shut down 2025** (per user) | Historical CSVs (`fivethirtyeight/data` GitHub, polls through 2024) usable for backtests only. |
| Raw poll rows | Wikipedia “Opinion polling for the 2026 United States House of Representatives elections” (CC BY-SA, scrapeable with attribution ⚠️ verify table layout) | HTML table | Active | Used as **primary raw-poll source** for the project's own average; aggregators used as cross-checks. |

**Method.** `ingest/generic_ballot.py::ingest_generic_polls() -> DataFrame`: scrape the Wikipedia table (pandas `read_html`, `lxml`), manual CSV `data/manual/generic_polls.csv` as fallback and for supplements. Aggregator headline values are stored in `data/manual/aggregator_headlines.csv` (hand-entered daily during election week) and used only as a diagnostic (`|ours − median(agg)| ≤ 1.5` else warn).

**Processed: `processed/generic_polls.parquet`**

| column | type | description |
|---|---|---|
| `poll_id` | str | `sha1(pollster|field_end|sample|pop)[:12]` |
| `pollster` | str | normalised via `data/manual/pollster_aliases.csv` |
| `sponsor` | str | |
| `field_start`, `field_end` | date | |
| `n` | int | sample size |
| `pop` | cat | `LV`, `RV`, `A` |
| `mode` | str | |
| `d_pct`, `r_pct`, `und_pct` | float | |
| `partisan` | bool | internal/partisan sponsor flag |
| `source_url` | str | |

Known issues: multiple versions of one poll (LV and RV) — keep both, dedupe via `poll_id+pop`, choose by `pop_priority = [LV, RV, A]` when averaging a single pollster-period; tracking polls overlapping windows — use only non-overlapping latest release per pollster per `tracker_gap_days = 7`; "if the election were held today" lean-only questions ignored.

### 4.3 Senate race polls

| Item | Detail |
|---|---|
| Sources | Wikipedia per-race polling tables (`2026 United States Senate election in <State>`), Silver Bulletin / Ballotpedia / RCP / 270toWin as cross-check (manual headlines). 538 historical archive for backtests. |
| Method | `ingest/senate_polls.py::ingest_senate_polls(states: list[str])` scrapes each race page's polling table; handles multi-candidate columns by mapping to `dside`, `rside`, `other`. Manual fallback `data/manual/senate_polls.csv`. |
| Schema | `poll_id, state_po, pollster, sponsor, field_start, field_end, n, pop, mode, dside_pct, rside_pct, other_pct, und_pct, matchup_type ('two_way','multi','rcv_final'), partisan, source_url`. |
| Cleaning | Drop hypothetical-matchup rows once nominees are known; for primaries-era polls drop all but nominee matchups; convert to two-party margin `m = 100·(d−r)/(d+r)`; for NE/ID/MT/SD map independent → `dside`; keep multi-way matchups with `matchup_type='multi'` and downweight 0.8. |
| Issues | Name changes (Maine nominee swap; Nebraska) — rows tagged to old nominee are dropped via `data/manual/nominee_changes.csv`. |

### 4.4 Demographic crosstabs

| Item | Detail |
|---|---|
| Sources | Poll PDFs/toplines published by pollsters (NYT/Siena, Pew, AP-NORC, Quinnipiac, Marist, Emerson, CNN/SSRS, Fox, etc.), AP VoteCast 2024 (for priors), generic-ballot subgroup tables. |
| Method | **Manual curation first**: `data/manual/crosstabs.csv` entered by the maintainer from poll releases; semi-automated PDF table extraction with `pdfplumber` as helper (`ingest/crosstabs.py::extract_pdf_tables`), outputs reviewed by hand. No automated scraping of paywalled sources. |
| Schema | `poll_id, geography ('national' or state_po or region), group_dim (race, age, edu_race, gender, region), group_value, n_group (effective, if given; else n·pop_share), dside_pct, rside_pct, margin_2p`. |
| Cleaning | Harmonise group labels via `data/manual/group_map.csv` (§6.7); set `n_group` from reported unweighted n else `n·share`; discard cells with `n_group < config.crosstab.min_n = 75`. |
| Issues | Small n (shrunk in §6.7); inconsistent education×race definitions; Asian-American and Native cells (EI-only). |

### 4.5 ACS / CVAP

| Item | Detail |
|---|---|
| Source | Census Bureau CVAP Special Tabulation (2019–2023 5-yr, ⚠️ UNVERIFIED availability; fallback 2018–2022): `https://www.census.gov/programs-surveys/decennial-census/about/voting-rights/cvap.html`; ACS API `https://api.census.gov/data/2023/acs/acs5` (key free; rate limit generous). Terms: public domain. |
| Fields (CVAP by county) | `CVAP_TOT, CVAP_WHT (nonHisp white), CVAP_BLK, CVAP_HSP, CVAP_ASN, CVAP_AIA, CVAP_2MR/other`. |
| Fields (ACS) | Age×education by race: tables B15002 (sex×edu), C15002A–I (edu by race), B01001 (age×sex), B03002. |
| Processed | `processed/cvap_county.parquet`: `geoid, race5 (wnh, black, hisp, asian, other), cvap (int32), moe`; `processed/edu_county.parquet`: `geoid, college_share_wnh (float)`; `processed/age_county.parquet`: `geoid, age_bin ('18-29','30-44','45-64','65+'), cvap_share`. |
| Cleaning | Collapse AIA+2MR+NHPI into `other`; zero-pad GEOID; CT planning-region crosswalk (2022 vintage) applied to CVAP; AK borough ↔ district crosswalk; MOE propagation via sqrt-sum-squares. |
| Issues | CVAP MOE large for small counties (EI uses `cvap` as point estimate; noise term in §6.6); education-by-race for CVAP is not published jointly ⇒ approximated by ACS shares ×CVAP (documented). |

### 4.6 2026 early vote and historical days-out

| Item | Detail |
|---|---|
| Sources | **University of Florida Election Lab** (`electionlab.ufl.edu` / “US Elections Project”, Michael McDonald) — national early-vote counts by state; state SoS files for party/age/race (NC, GA, FL, NV, AZ, MI, PA, OH, TX, WI, etc.); TargetSmart/Catalist public trackers ⚠️ ToS; Early Vote Information Center. |
| Method | `ingest/early_vote.py::ingest_state_ev(state)` — **per-state adapters** that download the official daily ballot-return file (NC: `ncsbe.gov` absentee/early files, GA: SoS absentee voter file, FL: DOS vote-by-mail & early voting reports); each adapter implements `fetch() -> raw`, `parse(raw) -> EVRow`. Non-reporting states: only total counts from UF. Daily snapshot appended to `processed/early_vote_daily.parquet`. |
| Schema | `state_po, geoid (nullable), date, days_out (int), mode ('early_in_person','mail','total'), party ('D','R','O','U','total'), age_bin, race5, ballots (int)`. |
| Historical | Same schema for 2018, 2022, 2024, assembled to `days_out` alignment (day 0 = Election Day) from archived state files (NC, GA, FL via SoS archives) and UF data; stored `processed/early_vote_hist.parquet` with `cycle` column. |
| Issues | States with no-excuse expansions (e.g., changed rules between 2022 and 2026); mail-ballot deadline differences; day-count alignment across Sundays; party registration vs. primary-registration (NC); GA/FL/AZ undercount of mail ballots received late; **Republican early-vote behavior changed after 2020** (modelled in §6.9). |
| Fallback | `data/manual/early_vote_{state}.csv`. |

### 4.7 Validated-voter studies

| Source | Use | Method |
|---|---|---|
| Pew “Validated Voters” 2020 / 2022 / 2024 (`pewresearch.org`) | priors on group vote shares (race, age, edu×race) and turnout | Hand-entered tables to `data/manual/validated_voter_priors.csv` |
| AP VoteCast 2020/2022/2024 | group vote shares by state/region | Hand-entered published tables; AP terms forbid redistribution ⇒ keep numbers only, cite source |
| Catalist “What Happened” | priors (public summaries only) | Hand-entered if public |
| Schema | `study, year, geography, group_dim, group_value, d_share_2p, r_share_2p, turnout_rate, n, moe` |
| Issue | Studies disagree by 3–5 pts in some groups; model uses their spread as prior SD (§6.6). |

### 4.8 County / town shapefiles

| Item | Detail |
|---|---|
| Source | Census TIGER/Line 2024 cartographic boundary files `cb_2024_us_county_500k.zip` and `cb_2024_us_cousub_500k.zip` (CT planning regions: `cb_2024_us_county_500k` already uses 2022 regions ⚠️ verify). `https://www2.census.gov/geo/tiger/GENZ2024/shp/`. Public domain. |
| Processing | geopandas read → reproject to EPSG:4326 → simplify (`topojson.Topology(prequantize=1e5, toposimplify=0.001)`) → state/national TopoJSON (§9). Alaska/Hawaii inset handled in the frontend projection (`geoAlbersUsa`). |
| Issues | Water-clipped shapes vs. full; VA independent cities; CT regions; slivers → drop polygons < 1e-6 sq deg. |

### 4.8b Betting-market odds

| Item | Detail |
|---|---|
| Sources | **Kalshi** (official API, `docs.kalshi.com`), **Polymarket** (public market-data API, `docs.polymarket.com`) — ⚠️ UNVERIFIED: I could not open either vendor's docs, only a third-party tracker (DeFi Rate) that says it reads both via their APIs and tracks all 35 races with bid/ask, last price and 24h volume. Confirm endpoints, auth requirements, rate limits and ToS (including any restriction on republishing prices or on US access) before building. Aggregator pages (DeFi Rate, Prediction Hunt) are **cross-checks only**; PredictIt not planned. |
| Method | `ingest/markets.py::ingest_markets(states) -> DataFrame`: per race, find the D-side and R-side contracts (series/ticker mapping kept in `data/manual/market_contract_map.csv`: `state_po, platform, contract_id, side ('D','R'), resolves_on`), read order-book top (bid/ask), last price and 24h volume via read-only endpoints. No trading, no authenticated account actions. |
| Schema `processed/market_quotes.parquet` | `state_po, platform, contract_id, side, bid, ask, last, volume_24h_usd, retrieved_at` |
| Cleaning | verify contract wording is "wins the Senate seat" (not control, not margin buckets); map independents to D-side per §2.2 (Nebraska/Osborn); drop contracts resolved or with ambiguous resolution rules; reject quotes with ask < bid. |
| Fallback | `data/manual/market_probs.csv` (`state_po, date, p_dside, source, volume_24h_usd`) hand-entered from the platforms' public pages. |
| Known issues | Large cross-platform spreads on thin races (one tracker snapshot showed a 12% outlier vs 73.5% elsewhere); contract wording differences; long-shot bias; platform-specific user bases; ToS/jurisdiction limits. Handled by spread/volume filters and logit-volume pooling (§6.5.1). |
| Display | Showing market prices on the site may be restricted by platform terms ⚠️ UNVERIFIED; decided (Q7): publish only the derived `p_market` and `S_mkt`, with attribution. Cost: read-only market-data endpoints only, no account, no key, no trading; if either platform requires a paid or KYC'd account for data access, it is dropped to `market_probs.csv` hand-entry. |

### 4.9 Manual reference tables (`data/manual/`)

| File | Columns |
|---|---|
| `races_2026.csv` | `state_po, class, incumbent, incumbent_party, special (bool), dside_name, dside_party, dside_endorsed_by_dem (bool), rside_name, rside_party, rcv (bool), notes` |
| `pollster_ratings.csv` | `pollster, rating (0–3.0), source, partisan_flag, last_reviewed` (seeded from Silver Bulletin pollster ratings if re-publishable, else own A–F scale ⚠️ licensing) |
| `pollster_aliases.csv` | `alias, canonical` |
| `nominee_changes.csv` | `state_po, old_name, new_name, effective_date` |
| `aggregator_headlines.csv` | `date, source, d_pct, r_pct, margin` |
| `historical_midterm_polling_misses.csv` | `year, state_po, race, poll_avg_margin, actual_margin, n_polls` for 2006–2022 (from 538 archive + MEDSL Senate returns 1976–2024, Dataverse, V8 May 2026 ⚠️) |

---

## 5. Data model

### 5.1 Entities

```
Race(state_po PK) 1—1 Geography(state)
Geography(geoid PK) —— parent_geoid ——> Geography
County(geoid) 1—N PresResult(year, geoid)
County(geoid) 1—N CVAP(geoid, race5)
Poll(poll_id) 1—N PollCrosstab(poll_id, group)
State(state_po) 1—N SenatePoll(poll_id)
EIEstimate(geoid, group, draw/summary)
Projection(geoid, run_id)
```

Primary keys: 5-digit county FIPS (CT: 2022 planning-region FIPS); 10-digit GEOID for county subdivisions (New England towns); 2-digit state FIPS; `run_id = YYYYMMDDTHHMMSSZ`.

### 5.2 Crosswalks (`data/crosswalks/`)

| File | Columns | Source |
|---|---|---|
| `ct_town_to_planning_region.csv` | `town_geoid, pr_geoid` | Census |
| `ct_county2020_to_pr.csv` | `county_geoid, pr_geoid, weight_pop` | Census relationship file |
| `ak_district_to_borough.csv` | `house_district, borough_geoid, weight_pop` | block overlay |
| `town_to_county.csv` | `town_geoid, county_geoid` | Census cousub |
| `fips_aliases.csv` | `old_geoid, new_geoid, valid_from, valid_to` | manual |

### 5.3 Canonical `geographies` table (`processed/geographies.parquet`)

| column | type | description |
|---|---|---|
| `geoid` | str | county FIPS / PR FIPS / state FIPS |
| `level` | cat | `state`, `county` |
| `name` | str | |
| `state_po` | str | |
| `parent_geoid` | str | state FIPS for counties |
| `region` | cat | `northeast, midwest, south, mountain, pacific, black_belt, rio_grande, ...` (EI/crosstab pooling region, §6.7) |
| `urbanicity` | cat | `urban, suburban, small_town, rural` (NCHS 2013 codes) |
| `is_special_unit` | bool | |
| `centroid_lon`, `centroid_lat` | float | |
| `in_race_2026` | bool | state has a 2026 Senate race |
| `cvap_total` | int32 | |

---
## 6. Model specification

**Notation.** Margins are two-party, percentage points, D-side minus R. `s` = state, `i` = county, `g` = demographic group, `r` = region, `k` = poll. `m0` = 2024 presidential baseline. Swing = change in margin relative to `m0`.

**Illustrative numbers used in worked examples** (clearly *not* live outputs; replace with pipeline values): generic ballot average = D+9.0 (two-party-converted ≈ +9.6; we use +9.0 here for simplicity; Silver Bulletin 10-26: ~D+9, PollCheck 10-27: D+8.7); `NPV2024 = −1.5`; Georgia `Pres2024Margin = −2.2` (Trump 2,663,117 vs Harris 2,548,017 ⚠️ UNVERIFIED to the vote); Georgia Senate poll average (illustrative) = D+6.0; Fulton County `m0 ≈ +46.0` ⚠️ UNVERIFIED.

### 6.1 Baseline — two-party margin

$$m^{0}_{g}=100\cdot\frac{V^{D}_{g}-V^{R}_{g}}{V^{D}_{g}+V^{R}_{g}}$$

*The baseline margin of a geography is the Democratic minus Republican share of the 2024 presidential two-party vote, in points.*

```python
def baseline_margin(votes_d: int, votes_r: int) -> float:
    return 100.0 * (votes_d - votes_r) / (votes_d + votes_r)   # raise if D+R == 0
```

- Inputs: `processed/pres_county.parquet` (2024). Outputs: `processed/baseline.parquet` (`geoid, level, m0, v2p_2024`). State rows are computed from summed county votes, never averaged from county margins.
- Config: `baseline.year: 2024`, `baseline.office: "president"`.
- Worked: GA: `100·(2,548,017−2,663,117)/5,211,134 = −2.21`. Fulton (illustrative): D 380k, R 140k → `m0 = 100·240/520 = +46.2`.
- Acceptance: national sum of two-party votes within 0.1% of FEC; `NPV2024` computed here and stored in `processed/national.json`.

### 6.2 Poll averaging

Used for both the generic ballot (national) and each Senate race. Function:

```python
def poll_average(polls: pd.DataFrame, as_of: date, cfg: PollCfg, house_effects: dict[str,float] | None
                 ) -> PollAverage:  # (margin, se, n_eff, n_polls, weights_df)
```

**Step 1 — convert to two-party margin** `m_k = 100(d_k − r_k)/(d_k + r_k)`.

**Step 2 — raw weight**

$$w_k = w^{time}_k\; w^{n}_k\; w^{q}_k\; w^{pop}_k\; w^{typ}_k,\qquad w^{time}_k = 2^{-a_k/H}$$

| Factor | Formula | Default |
|---|---|---|
| time (`a_k` = days from `field_end` to `as_of`) | `2^(-a/H)` | `H = 14` (Senate), `H = 10` (generic); drop polls older than `max_age_days = 60` (Senate) / 45 (generic) |
| sample size | `min(sqrt(n/600), 1.5)`, `n` capped at `n_cap = 2000`; floor `n_min = 300` | as stated |
| pollster quality | `0.5 + 0.5·rating/3` where `rating∈[0,3]` from `pollster_ratings.csv`; unrated = `unrated_rating = 1.0` | as stated |
| population | `LV: 1.0, RV: 0.9, A: 0.75` | after Step 4 adjustment |
| type | partisan/internal sponsor ×`0.6`; multi-way (non-two-way) matchup ×`0.8`; tracking poll de-duplicated | as stated |

*Newer, larger, better-rated, likelier-voter polls count more; sponsor-biased polls count less.*

**Step 3 — house effects (model form).** For pollster `p` in poll `k`:

$$m_k=\theta_{c(k),t(k)}+h_{p(k)}+\varepsilon_k,\quad h_p\sim\mathcal N(0,\tau_h^2),\quad \varepsilon_k\sim\mathcal N(0,\sigma_k^2),\quad \sum_p \bar n_p h_p=0$$

where `c(k)` = contest (generic ballot or each state race) and `θ` is the contest's latent margin (time-smoothed). Estimation (cheap, deterministic) via alternating weighted least squares in `polls/house_effects.py::estimate_house_effects(all_polls) -> dict`:

```python
h = {p: 0.0}
repeat 5 times:
    theta[c] = weighted_avg(m_k - h[p(k)]  for polls in contest c)      # uses w_k
    for p: r_p = weighted_mean(m_k - theta[c(k)] for polls of p)
           h[p] = (n_p_eff / (n_p_eff + k_shrink)) * r_p                # k_shrink = 3
    h -= weighted_mean(h, by pollster volume)                            # sum-to-zero
```

Pooling across the generic ballot and all Senate contests is required (few polls per pollster per race). Contest-level means use `θ` as fixed effects so national/state level differences do not leak into `h`. Config: `polls.house_effect.enabled: true`, `shrink_k: 3`, `max_abs: 4.0` (clip). Applied only for pollsters with ≥ `min_polls = 3`.

**Step 4 — LV/RV/A adjustment.** For pollster-period pairs reporting both, estimate `δ_LV = mean(m_LV − m_RV)` (shrunk toward `0` with `k=5`), and shift RV and A polls by `δ_LV` (RV) or `1.5·δ_LV` (A) when the contest is generic/Senate and `polls.lv_rv.adjust: true`. Default prior `δ_LV = 0` until ≥ 8 pairs. Midterm-year convention: LV screens help R by ~1–2 pts in some cycles and D in 2022-style enthusiasm gaps; empirical estimate decides.

**Step 5 — cap on any pollster.** After weights normalised `ŵ_k = w_k/Σw`, enforce `Σ_{k∈p} ŵ_k ≤ cap_p = 0.25` by water-filling: excess redistributed pro-rata to uncapped polls; iterate until stable (≤ 10 iterations). For contests with <4 distinct pollsters, `cap_p = 0.5`.

**Step 6 — average and uncertainty.**

$$\hat m=\sum_k \hat w_k (m_k-h_{p(k)}-\delta_k),\qquad n_{eff}=\frac{(\sum w_k)^2}{\sum w_k^2},\qquad SE_{avg}=\sqrt{\frac{\sigma_{poll}^2}{n_{eff}}+\sigma_{floor}^2}$$

`σ_poll = 3.9` (typical SD of single-poll margin incl. design effect), `σ_floor = 1.0`. The *poll average* is the margin; `SE_avg` feeds the simulation (§6.12).

- Worked (GA, illustrative): 5 polls, margins `[+7, +5, +4, +8, +6]`, weights `[.31,.22,.12,.15,.20]`, house effects ≈ 0 ⇒ `m̂ = 6.0`.
- Acceptance: tests in §11; average with all weights equal equals arithmetic mean; capping holds; adding a duplicate poll from a capped pollster does not move the average by more than 0.2.

### 6.3 National swing

$$S_{nat}=\hat m_{GB}-NPV_{2024}$$

*The nation has moved by the generic-ballot margin minus the 2024 national presidential margin.*

```python
def national_swing(gb_avg_margin_2p: float, npv2024_margin_2p: float) -> float:
    return gb_avg_margin_2p - npv2024_margin_2p
```

Worked: `9.0 − (−1.5) = +10.5`. Config: `swing.national.generic_ballot_source: "own_average"` (alternative: `"aggregator_median"` for sanity checking only). Output: `processed/national_swing.json {s_nat, gb_margin, npv2024, as_of, n_polls, se}`.

### 6.4 State poll swing

$$S^{poll}_s=\hat m^{Sen}_s-m^{0}_s$$

*A state's race-specific swing is the polling average minus the state's 2024 presidential margin.*

Worked (GA): `6.0 − (−2.2) = +8.2`. A state is "polled" iff `n_polls ≥ min_polls_for_state = 1` within `max_age_days` and `n_eff ≥ 0.8` (config `swing.state.min_n_eff`). RCV states use the final-round margin (§2.2).

### 6.5 The 2:1 combination

$$S_s=\frac{a\,S_{nat}+b\,S^{poll}_s}{a+b},\quad (a,b)=(2,1)\ \text{by default}$$

*The state swing is two parts national environment to one part race-specific polling.*

```python
def state_swing(s_nat, s_poll, a=2.0, b=1.0, polled=True, scale_by_volume=False, n_eff=None, n_ref=6.0):
    if not polled: return s_nat, "national_fallback"
    b_eff = b * (min(1.0, n_eff / n_ref) if scale_by_volume else 1.0)   # optional mode, off by default
    return (a*s_nat + b_eff*s_poll) / (a + b_eff), "combined"
```

Worked (GA): `(2·10.5 + 8.2)/3 = 9.73` (this is `S_base`, before the market blend below). Unpolled states return `S_nat` as `S_base` with `swing_source = "national_fallback"` (surfaced in the UI as "No recent state polling"). Config: `swing.weights.national: 2`, `swing.weights.state_poll: 1`, `swing.scale_by_poll_volume: false`, `swing.n_ref: 6.0`.

#### 6.5.1 Betting-market blend (small third component)

The 2:1 national-to-poll core is unchanged. Betting-market odds enter as a **small, separate blend** on top of it:

$$S_s=(1-\mu_s)\,S^{base}_s+\mu_s\,S^{mkt}_s,\qquad S^{base}_s=\frac{2S_{nat}+1\,S^{poll}_s}{3}$$

*The state swing is mostly the 2:1 national/poll swing, with a small share (default 10%) taken from what betting markets imply.*

**Market-implied margin.** Convert the de-vigged market win probability `p_s` for the D-side candidate to a margin using the same normal-error model the simulation uses (§6.12):

$$\hat m^{mkt}_s=\sigma_{mkt}\,\Phi^{-1}(p_s),\qquad S^{mkt}_s=\hat m^{mkt}_s-m^{0}_s$$

*A market giving the D-side candidate an 80% chance implies roughly a +4-point margin if the typical total error is about 5 points.* `σ_mkt = 5.0` by default (`swing.market.sigma_pts`), deliberately set to approximately the total state-level SD in §6.12 and re-fit from the backtest.

**Market probability `p_s`** (`markets/average.py::market_probability(quotes, cfg) -> MarketProb`):
1. Per contract use mid = (best_bid + best_ask)/2; if the spread > `max_spread = 0.08` or 24h volume < `min_volume_usd = 5,000`, drop it.
2. De-vig: normalise the D-side and R-side contract prices of the same race so they sum to 1 (`p = pD/(pD+pR)`); independents/third parties are excluded from the denominator (same two-party logic as A1).
3. Combine platforms with a volume-weighted average of logit probabilities; clip to `[0.02, 0.98]` before `Φ⁻¹` (avoids ±∞ and extreme implied margins). Cap the implied margin at `±market.max_abs_margin = 25`.
4. Staleness: drop quotes older than `max_age_hours = 48`.

**Weight `μ_s`.** Default constant `μ = 0.10`; optional liquidity scaling `μ_s = μ_max · min(1, V_s / V_ref)` with `μ_max = 0.10`, `V_ref = 50,000` USD of 24h volume, **on by default** so thin markets contribute less. `μ_s = 0` (no market term; `S_s = S_base`) if there is no qualifying market. The market weight is hard-capped at `swing.market.weight_cap = 0.20` and never applies to `S_nat`.

```python
def state_swing_with_market(s_base, s_mkt, v24h, mu_max=0.10, v_ref=50_000, scale=True, cap=0.20):
    if s_mkt is None: return s_base, 0.0
    mu = min(cap, mu_max * (min(1.0, v24h / v_ref) if scale else 1.0))
    return (1 - mu) * s_base + mu * s_mkt, mu
```

Worked (GA, **illustrative**: market D-side win probability 0.80, 24h volume ≥ 50k): `m_mkt = 5.0·Φ⁻¹(0.80) = 5.0·0.8416 = +4.2`; `S_mkt = 4.2 − (−2.2) = 6.4`; `μ = 0.10`; `S_s = 0.9·9.73 + 0.1·6.4 = 9.40`. Projected margin before turnout/early-vote components: `−2.2 + 9.40 = +7.2` (vs +7.5 without markets). Unpolled states with a liquid market now get `S_s = 0.9·S_nat + 0.1·S_mkt` with `swing_source = "national_market"`; polled states without a market stay `"combined"`; both → `"combined_market"`.

Rules: markets only enter at the **state** level (§6.5); the county calibration (§6.8) and everything below it are unchanged and still reproduce `S_s` exactly. The market component is exported separately (`components.market`) and the market probability is shown on the state page for transparency. The simulation (§6.12) is **not** recentred on market odds: win probabilities come from the model's own margins and error terms, so markets do not enter twice. Config: see `swing.market.*` in §12.

*Caveat:* markets partly price in the same polls, so the blend double-counts some information; the small default weight, liquidity scaling and 20% cap limit this, and §7 reports the backtest sensitivity (μ = 0, 0.10, 0.20) for information only.

### 6.6 Ecological inference

**Groups (R = 6).** `wnh_college`, `wnh_noncollege`, `black`, `hispanic`, `asian`, `other`. (Age is handled in §6.7 as an additive gradient since county-level age × race CVAP is not published jointly; this is a documented limitation.) Group counts per county: `n_ig = ω^{2024}_i · π_ig` where `π_ig` is the group's share of 2024 voters derived from CVAP shares × relative turnout factors `κ_g` (validated-voter data: Pew 2024 turnout by group; default `κ = {wnh_college: 1.00, wnh_noncollege: 0.88, black: 0.86, hispanic: 0.72, asian: 0.75, other: 0.75}` relative to the most-voting group; normalised so `Σ_g n_ig = V_i`) ⚠️ placeholders until `validated_voter_priors.csv` is filled.

**Model (2024 levels; two-party D share `θ_ig`).** Production model, PyMC 6.x with numpyro NUTS backend, per state (see parallelisation below):

$$\operatorname{logit}\theta_{ig}=\mu_g+\mathbf x_i^\top\boldsymbol\beta_g+u_{r(i)g}+\epsilon_{ig}$$
$$\mu_g\sim\mathcal N(\operatorname{logit}\pi^{prior}_g,\ \sigma_{prior,g}^2),\ \beta_{gj}\sim\mathcal N(0,0.5^2),\ u_{rg}\sim\mathcal N(0,\tau_u^2),\ \epsilon_{ig}\sim\mathcal N(0,\tau_\epsilon^2)$$
$$\tau_u,\tau_\epsilon\sim\text{HalfNormal}(0.5),\qquad V^D_i\mid\theta\sim\mathcal N\!\Big(\sum_g n_{ig}\theta_{ig},\ \sigma_i^2\Big),\quad \sigma_i^2=\phi\,V_i,\ \phi\sim\text{HalfNormal}(25)$$

*Each county's Democratic vote is the sum over groups of group voters times their (unknown) Democratic share; shares vary smoothly with county covariates and region and are anchored by priors from validated-voter studies.*

`x_i` = standardised urbanicity, median-income z-score, share of foreign-born, share of age 65+. Plain-language: homogeneous counties contribute little information; priors and cross-county variation do the work.

- **Priors from validated voters.** `π_g^{prior}` = state-region-specific two-party D share for group `g` in 2024 from Pew validated-voter + AP VoteCast tables (mean of available studies); `σ_prior,g = max(0.20, SD across studies on logit scale)`; national values used where state values are missing (flag `prior_level = 'national'`).
- **Baseline implementation check.** Before trusting the custom model, run PyEI `RowByColumnEI(model_name="multinomial-dirichlet-modified")` on the same data in `ei/model_rxc.py::run_pyei_reference()` and assert group-level medians agree within 5 pts for groups ≥ 10% of CVAP (`test_ei_reference_agreement`).
- **Sampler settings.** `chains: 4, tune: 1000, draws: 1000, target_accept: 0.92, max_treedepth: 10, random_seed: 20260`. Diagnostics (`ei/diagnostics.py`): `rhat < 1.01`, `ess_bulk > 400`, `ess_tail > 400`, `divergences == 0`, `bfmi > 0.3`. On failure: retry with `target_accept=0.97` and `tune=2000`; if still failing, mark state `ei_status='fallback'` and use priors-only distribution (§6.8 fallback).
- **Pooling for small states.** States with < 25 counties (CT, DE, HI?, MA, NH, NJ, NM?, RI, VT… as determined by `len(counties)<ei.min_counties_for_state_run`) are fit together with their census division as one hierarchical run, with `state` as an extra random effect level.
- **Runtime estimate (⚠️ UNVERIFIED, to be measured in Phase 3).** 150-county state (GA 159): ~6–10 min on 4 cores. TX (254): ~20 min. Small states: <3 min. Total sequential ≈ 3.5 h; with `joblib` 8 workers (each limited to 2 NUTS chains-in-parallel) ≈ 30–40 min. **Zero-cost rule:** EI runs on the owner's own machine (`make ei`, a few hours worst case on a laptop, run once and on input changes only); the resulting small summary parquet (`ei_group_vote`, `ei_shift_2024`, a few MB) is committed to the repo, and CI never runs EI. Caching: results keyed by `sha1(inputs + code_version)` in `data/cache/ei/<state>_<hash>.nc`; EI is **not** re-run in the nightly job unless inputs change.
- **Outputs → `processed/ei_group_vote.parquet`**

| column | type | description |
|---|---|---|
| `geoid` | str | county |
| `group` | cat | one of 6 groups |
| `theta_mean`, `theta_p10`, `theta_p90` | float | posterior two-party D share (0–1) |
| `n_group` | float | estimated group voters 2024 |
| `ei_status` | cat | `ok`, `retry`, `fallback` |
| `rhat_max`, `ess_min` | float | per-state diagnostics |

**2020→2024 shift EI.** Model the *change*:

$$\Delta_{ig}=\operatorname{logit}\theta^{24}_{ig}-\operatorname{logit}\theta^{20}_{ig}=\delta_g+\delta_{r(i)g}+\mathbf x_i^\top\boldsymbol\gamma_g+\nu_{ig}$$
$$V^{D,24}_i\mid\cdot\ \text{and}\ V^{D,20}_i\mid\cdot \text{ jointly via the level model with } \theta^{24}=\operatorname{logit}^{-1}(\operatorname{logit}\theta^{20}+\Delta)$$

with 2020 counts from CVAP 2016–2020/ACS 2020 and same `κ`. Outputs `processed/ei_shift_2024.parquet`: `region, group, delta_mean, delta_sd`. Use: these are the **regional group swing patterns** that form the prior mean for the shape of the 2026 swing (relative group differences), after being converted to margin points: `pattern_{r,g} = (delta_{r,g} − Σ_g' w_{r,g'} delta_{r,g'})`, i.e., deviations from the regional average. *Groups that moved more than average 2020→2024 in a region are assumed to move more than average again.* Down-weight with `ei.pattern_persistence = 0.5` (config) because 2024 shifts partially mean-revert in midterms.

- Validation of EI vs validated voters is in §7.3.
- Acceptance: all 35 states `ei_status ∈ {ok, retry}` or documented fallback; reproduction of each county's actual 2024 D votes within 0.5% by posterior mean.

### 6.7 Group swings from crosstabs

**Harmonisation.** `data/manual/group_map.csv` maps poll labels → EI groups:

| Poll label | EI group(s) | Rule |
|---|---|---|
| "White, college" / "White, bachelor's+" | `wnh_college` | direct |
| "White, no college" | `wnh_noncollege` | direct |
| "Black" | `black` | direct |
| "Hispanic/Latino" | `hispanic` | direct |
| "Asian" | `asian` | direct (usually pooled with "Other") |
| "Non-white" | `black, hispanic, asian, other` | same observed swing assigned to all, with `n_group` split by vote share; `variance ×2` |
| Age: 18–29, 30–44, 45–64, 65+ | age gradient (not an EI group) | converted to age-gradient `γ_age` |
| Gender | gender gradient `γ_gen` (county gender CVAP is ~50/50 ⇒ ignored in allocation, shown in methodology only) | |

Geography labels: `national` ⇒ pooled across regions; state-level crosstabs are rare, used only for large states (n_group≥200).

**Observation.** Poll `k`, group `g`, region `r(k)`: group margin `y_kg`; group baseline `b_{r g}` = EI group margin in 2024 in the poll's geography (`2·theta − 1` ×100); observed group swing `z_kg = y_kg − b_{rg}`. Variance:

$$\operatorname{Var}(z_{kg})=\Big(\tfrac{100\cdot2\sqrt{p(1-p)}}{\sqrt{n_{kg}/\mathrm{deff}}}\Big)^2+\sigma_{b}^2$$

`deff = 1.5`, `σ_b` = EI posterior SD of baseline. `p` = poll group D two-party share.

**Hierarchical shrinkage model (PyMC, `crosstab/hier_model.py`).**

$$z_{kg}\sim\mathcal N(\delta_{g,r(k)},\ v_{kg}),\qquad \delta_{g,r}=S_{ref}+a_g+b_{g,r}$$
$$a_g\sim\mathcal N(0,\tau_a^2),\ \ b_{g,r}\sim\mathcal N(0,\tau_b^2),\ \ \tau_a,\tau_b\sim\text{HalfNormal}(3.0),\ \ \text{prior mean for } a_g: \text{persisted EI pattern}\ \lambda\,p_{g}$$

where `S_ref` is the overall swing the polls imply (the national generic ballot swing `S_nat` for national crosstabs; `S_s` for state crosstabs), so shrinkage is **toward the overall swing**, and `a_g`'s prior mean is `λ · pattern_g` with `λ = ei.pattern_persistence`. Region × group partial pooling comes from `b_{g,r}`; regions: Northeast, Midwest, South (non-Black-Belt), Black Belt, Southwest/Rio Grande, Mountain West, Pacific (`geographies.region`). Sampler: 4×1000 draws, `target_accept=0.9`; run once nationally per update (≈ 1 min).

Output `processed/group_swing.parquet`: `region, group, delta_mean, delta_sd, n_polls, shrinkage_factor` (= posterior var / prior var). Plain-language: *a group with few, noisy poll cells is assigned nearly the overall swing; a group with consistent, large samples keeps its own.*

Age and gender gradients: `processed/gradients.json` (`age_gradient_per_sd`, `gender_gradient`) from the same model with a continuous covariate.

### 6.8 County swing construction and calibration

**Raw county swing.**

$$s^{raw}_i=S_s+\sum_{g}\omega_{ig}\big(\delta_{g,r(i)}-\bar\delta_{r(i)}\big)+\beta_{age}\,z^{age}_i$$

where `ω_ig` = group's share of the county's expected 2026 two-party votes (from §6.10), `δ̄_r = Σ_g ω̄_{rg} δ_{g,r}` (region-average group swing at regional weights, so the second term is mean-zero by construction), and `z^{age}_i` is the county's standardised share of 18–44 voters. *A county's swing is the state swing plus a tilt up or down according to which groups live there and how much those groups are estimated to move relative to the average.*

**Exact calibration.** Let `ν_i = ω_i / Σω` be county weights (expected 2026 two-party votes, §6.10). Find scalar `λ_s` solving

$$\sum_i \nu_i\,\operatorname{clip}\!\big(m^0_i+s^{raw}_i+\lambda_s,\,-100,100\big) \;=\; \sum_i\nu_i\,m^0_i+S_s$$

and set `s_i = clip(m0_i + s_raw_i + λ_s, −100, 100) − m0_i`. Without clipping this is closed form `λ_s = S_s − Σ ν_i s^raw_i`. With clipping the left side is monotone non-decreasing in `λ_s` so bisection converges (`tol 1e-10`, ≤ 200 iterations).

```python
def calibrate(m0: np.ndarray, s_raw: np.ndarray, w: np.ndarray, S: float) -> tuple[np.ndarray, float]:
    nu = w / w.sum()
    target = (nu * m0).sum() + S
    f = lambda lam: (nu * np.clip(m0 + s_raw + lam, -100, 100)).sum() - target
    lo, hi = -200.0, 200.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
        if hi - lo < 1e-10: break
    lam = (lo + hi) / 2
    s = np.clip(m0 + s_raw + lam, -100, 100) - m0
    assert abs((nu * s).sum() - S) < 1e-6
    return s, lam
```

**Statement/proof.** Without clipping, `Σν_i s_i = Σν_i s_raw_i + λ_s = S_s`. With clipping, `f` is continuous and non-decreasing with `f(−200) ≤ −…` and `f(200) ≥ …` so a root exists whenever `|target|` is attainable (`target ∈ [−100,100]`); the bisection returns it. Unit tests `test_calibration_exact_*` and a hypothesis property test (`test_calibration_property`) assert the sum constraint to `1e-6` for random inputs.

**Fallback when EI failed or no crosstabs:** `s_raw = S_s + β_age z_age` (age only) or `S_s` (uniform). Flag `county_method ∈ {'ei_crosstab','age_only','uniform'}`.

**Statewide decomposition shown on the site:** `margin_s = m0_s + S_s + T_s + E_s` where `T_s` = turnout-composition component (§6.10) and `E_s` = early-vote component (§6.9). Because `s_i` is calibrated with the *final* weights `ω` (including both T and E), `Σν_i m0_i = m0_s + T_s + E_s` by definition of `T_s, E_s` below, so statewide margin = `Σ ν_i (m0_i + s_i)`.

**Worked numeric example (illustrative).** GA: `S_s = 9.73`. Fulton County: `m0 = +46.2`; groups: `wnh_college 28%, wnh_noncollege 9%, black 44%, hispanic 8%, asian 8%, other 3%`; region = Southeast; group swings (posterior means) `[+6, +14, +7, +11, +8, +10]` against regional weights giving `δ̄ = 9.4`; tilt `= Σ ω (δ_g − δ̄) = .28(−3.4)+.09(4.6)+.44(−2.4)+.08(1.6)+.08(−1.4)+.03(0.6) = −1.95`; age term `+0.3` ⇒ `s_raw = 9.73 −1.95 + 0.3 = 8.08`. Across all GA counties the weighted mean of `s_raw` is `9.13`, so `λ = +0.60`; Fulton `s = 8.68`, projected `m = 46.2 + 8.68 = +54.9` ✓ (before T, E components which enter through ω).

### 6.9 Early-vote module

**Same-day-out comparison.** For state `s`, today's `d` days out, cycle `c ∈ {2022, 2018, 2024}` and category `j` (party registration D/R/O/U if reported; else age bin; else race; else total):

$$\rho_{j,c}=\frac{EV^{2026}_{j}(d)}{EV^{c}_{j}(d)},\qquad f^{c}_j(d)=\frac{EV^{c}_{j}(d)}{Final^{c}_j}$$

$$\widehat{Final}^{2026}_{j}=\frac{EV^{2026}_{j}(d)}{\bar f_j(d)},\qquad \bar f_j(d)=\sum_c \alpha_c f^c_j(d)$$

*Project each group's final turnout from how much it has already voted, using the typical share of its final vote that was in at this point in past cycles.*

- Cycle weights (`earlyvote.cycle_weights`): `2022: 0.40, 2018: 0.30, 2024: 0.30` for age/race/total. **Party-registration categories use only 2022 (0.6) and 2024 (0.4)** because Republican early-voting behaviour changed after 2020 (R voters moved from election-day-heavy to early/mail-heavy under party encouragement; 2018 party splits are non-comparable). 2018 contributes to party categories only through the "level shift" `Δ_R = f^{2022}_R − f^{2018}_R` applied as an informational diagnostic, not to the projection. `earlyvote.party_cycles: [2022, 2024]`.
- Handling `d` mismatch: interpolate `EV^c(d)` linearly on the daily cumulative curve.
- Sunday/ballot-deadline mismatches: align on `days_out` not calendar dates; where a state's early period length changed, use `early_period_scale` from `data/manual/ev_rules.csv`.

**Conversion to turnout weights.** Group projected final-turnout relative to the 2026 no-EV baseline (§6.10) yields multipliers

$$\psi_j=\frac{\widehat{Final}^{2026}_j/\overline{Final}^{base}_j}{\widehat{Final}^{2026}_{tot}/\overline{Final}^{base}_{tot}}$$

shrunk: `ψ_j^{shr} = exp(γ · log ψ_j)` with `γ = earlyvote.shrink = 0.5`. For party categories, translate into EI groups using the state's party-by-group crosswalk (`earlyvote/weights.py::party_to_group_matrix` built from the state voter-file composition or 2024 exit/validated-voter data); for age/race categories the map is direct. County weights: `ω_i = Σ_g n^{base}_{ig} ψ_g^{shr}`; where counties report EV counts (NC, GA, FL, ...), blend `ω_i ← ω_i · (EV_i^{2026}/EV_i^{hist})^{0.25}` renormalised to the state total.

**Cap.** The early-vote component is `E_s = m0_s(ω^{EV}) − m0_s(ω^{base})` where `m0_s(ω) = Σν_i(ω) m0_i`. Enforce `|E_s| ≤ cap` (`earlyvote.cap_pts = 1.5`) by scaling `γ → γ·κ` with `κ ∈ (0,1]` found by bisection so `|E_s| = cap`. Component is exported separately (`components.early_vote`).

**States without party/demographics.** If only total ballots are reported: uniform `ψ`, `E_s = 0`, but the total-turnout projection still updates the turnout total (affects nothing in the margin). If county totals are reported: use the county blend only (`κ_county = 0.25`). The UI flags `ev_detail ∈ {full, county_only, total_only, none}`.

- Acceptance: back-test the module on 2022 (using 2018 + 2020/2024 as comparators ⚠️ data) shows projected turnout RMSE ≤ 3 pts statewide.

### 6.10 Turnout model

$$\omega_{ig}^{base}=V^{2024}_{ig}\cdot d_{g,r(i)}\cdot c_s,\qquad \omega^{base}_i=\sum_g\omega^{base}_{ig}$$

- `V_ig^{2024}`: EI-estimated 2024 group voters (§6.6).
- `d_{g,r}`: midterm/presidential drop-off ratios by group and region, estimated from CPS Voting & Registration Supplement (2014/2018/2022 vs 2012/2016/2020) validated against Pew ⚠️ **initial placeholders**: `wnh_college .85, wnh_noncollege .74, black .66, hispanic .56, asian .62, other .60`.
- `c_s`: state-level scaler so total turnout `Σ_i ω_i` equals `T_s^{2026}`, where `T_s^{2026} = V_s^{2024} · ρ_s`, `ρ_s = 0.7·(V^{2022}_s/V^{2020}_s) + 0.3·(V^{2018}_s/V^{2016}_s)`, bumped by `turnout.environment_beta·|S_nat|` (default `0.0005` per pt) because high-environment years increase turnout.
- Output `processed/turnout.parquet`: `geoid, group, omega_base, omega_ev, share_of_state`.
- `T_s = m0_s(ω^{base}) − m0_s^{2024}`: the turnout-composition component (midterm drop-off typically helps the party with older/whiter voters).
- Acceptance: backtests §7: projected 2022 turnout within 4% for 90% of states.

### 6.11 Final projection and roll-up

For each county `i` in state `s`:

$$\hat m_i = m^0_i+s_i,\qquad \text{swing}_i=\hat m_i-m^0_i = s_i$$

For each state: `m̂_s = Σ ν_i m̂_i` (with `ν_i` from `ω^{EV}`) `= m0_s + S_s + T_s + E_s`. County shift displayed = `s_i + (turnout composition effect on the county margin is zero by construction)`. Roll-up checks (`export/validate_rollup.py`): `|m̂_s − (m0_s + S_s + T_s + E_s)| < 1e-6`; sum of county projected D-side votes equals `ν`-weighted total.

County vote counts shown: projected D-side/R-side votes `= ω^{EV}_i · (1 ± m̂_i/100)/2`.

### 6.12 Simulation

**Error structure.** For draw `n=1..N`, county margin

$$M^{(n)}_i=\hat m_i+\underbrace{e^{nat}}_{}+e^{reg}_{r(s)}+\sum_g\bar\omega_{sg}e^{grp}_{g}+e^{state}_s+e^{cty}_i$$

| Term | Distribution | Covariance | Default SD |
|---|---|---|---|
| `e^nat` | Student-t(ν=6), scaled | perfectly shared | σ_nat = 2.5 |
| `e^reg_r` | t(ν=6) | independent across 7 regions, plus correlation `ρ_{rr'} = 0.3` with neighbours | σ_reg = 2.0 |
| `e^grp_g` | MVN(0, Σ_g), 6 groups, `corr(black,hispanic)=0.3, corr(wnh_college,wnh_noncollege)=−0.3`, others 0 | | σ_grp = 1.5 per unit weight (acts through county group weights) |
| `e^state_s` | t(ν=6) | `Cov(e_s,e_s') = σ²_state · (δ_ss' + ρ_state·sim(s,s'))`, `sim` = cosine similarity of CVAP composition (≥0), `ρ_state=0.2` | σ_state = 3.0 (+ polls: `σ_state,s² = 3.0² + SE_avg,s²` if polled; unpolled `σ² = 3.0²+2.0²`) |
| `e^cty_i` | N(0, σ_cty²) then **demeaned with ω-weights within state** (zero-sum, so it never moves the state total) | independent | σ_cty = 2.5 (scaled by 1/√(votes/10⁴) floor 0.5×) |

**Calibration of magnitudes** (`sim/errors.py::fit_error_model`): from `historical_midterm_polling_misses.csv` (Senate 2006–2022, plus generic-ballot-vs-House-popular-vote for the national term) fit
`miss_{s,y} = u_y + v_{reg(s),y} + w_s + η_{sy}` with REML mixed model (statsmodels `MixedLM`) → σ_nat, σ_reg, σ_state; the county term from 2018/2022 backtest residuals after calibration (§7). For polled states add heteroskedasticity `σ² ∝ 1/√n_polls`. ⚠️ defaults above are placeholders until fitted; acceptance requires fitted values within a factor of 1.5 of defaults or documented reason.

**Draws.** `N = 20,000` full simulation (`sim.n_draws`), 2,000 for CI. Antithetic pairs on `e^nat`. Draws stored as `int8`-quantised margins per county (×10 → 0.1-pt resolution) in `output/sim_draws.npz` (not published).

**Outputs** (`sim/outputs.py`):
- `P(D-side win)_s = mean_n[M^{(n)}_s > 0]`, state margin `M_s = Σν_i M_i`.
- 80% interval = (10th, 90th percentile) of `M_s`; also for each county.
- Seat distribution: `D_seats = H_D + Σ_s 1[M_s>0 for D-side]`, `H_D` = D-caucus seats not up (computed from `races_2026.csv`; ⚠️ verify composition, appointments); Democrats control iff `D_seats ≥ 51` (VP tie-break R: `≥50` is not control; config `sim.control_threshold: 51`).
- Tipping-point state frequencies; correlation heatmap of state outcomes (published as `/data/correlations.json` optional).
- Median-draw reporting: headline margin is the deterministic `m̂`; probabilities from draws.

---
## 7. Validation and backtesting

All backtests run through the same code path with `cycle` and `baseline_year` parameters (`src/senate/backtest/run_backtest.py`). Only information available as of the **cutoff date** is used (`backtest.as_of_days_before: 1`, plus a rolling check at 30/60/90 days).

### 7.1 Full 2022 backtest (baseline 2020 presidential)

| Input | Source |
|---|---|
| Baseline | 2020 presidential county two-party margin |
| Generic ballot | 538 archive (2022) raw polls re-averaged by our own code; `NPV2020 = +4.5` two-party (Biden 51.3 vs Trump 46.8 ⇒ +4.5/98.1 ≈ +4.6 ⚠️ computed from data) |
| Senate polls | 538 archive `senate_polls_2022` |
| Crosstabs | `data/manual/crosstabs_2022.csv` (best effort, 10–15 national polls; if empty, EI/crosstab layer is run with priors only and reported as such) |
| ACS/CVAP | ACS 2016–2020 + CVAP 2016–2020 |
| Early vote | UF + NC/GA/FL archives for 2022 vs 2018/2020 |
| Truth | MEDSL Senate returns by county 2022 (the “county Senate 1976–2024” release) |

Races: all 34 contested 2022 Senate races (including special OK). Output `output/backtest/2022/{state,county}_errors.parquet` and `report.md`.

### 7.2 Full 2018 backtest (baseline 2016 presidential)

Same pipeline; `NPV2016 = +2.2` two-party (Clinton 48.2 vs Trump 46.1) ⚠️ computed. Races: 35 incl. specials (MN, MS). Early vote comparison base: 2014 and 2016 (2018 is the first cycle in the "primary comparison" set, so the 2018 backtest cannot use itself; documented limitation).

### 7.3 Metrics

Market-weight sensitivity (information only): re-run with `μ ∈ {0, 0.10, 0.20}` for 2022 (Kalshi/PredictIt history limited ⚠️ UNVERIFIED; if historical market data cannot be obtained for 2018, the market term is validated only on 2022 and reported as such, and the 0.10 default is a judgement call rather than a fitted value).

| Metric | Definition | Level |
|---|---|---|
| County RMSE | `sqrt(mean_i w_i (m̂_i − m_i^{actual})²)`, vote-weighted and unweighted | county |
| State RMSE | `sqrt(mean_s (M̂_s − M_s^{actual})²)` | state |
| Bias | `mean(M̂_s − M^{actual}_s)` (signed; D−R) | state, county, region |
| Shift RMSE | RMSE of projected vs actual *shift from baseline* | county |
| Group-level EI error | `|θ̂_{g} − θ^{validated}_g|`, pts | group × region |
| Calibration | reliability of win probabilities in 10 bins; **Brier score** `mean((P−y)²)`; log-loss | race |
| Interval coverage | share of actuals within the 80% interval (target 0.75–0.85) | state, county |
| Seat distribution | actual D seats percentile in simulated distribution | national |
| Sensitivity (info only) | state RMSE & Brier under weights 1:1, 2:1, 3:1 | state |

**EI validation vs validated-voter studies:** compare EI-estimated national and regional group D shares to Pew validated voters and AP VoteCast (2020, 2022, 2024). **Flag any group with absolute difference > 8 pts** (`validation.ei_flag_pts: 8`) in `output/validation/ei_flags.csv` (cols: `group, region, ei, benchmark, diff, study, flag`). Flags require a written note before launch; they do not auto-fail unless > 12 pts for groups ≥ 10% of CVAP.

**Sensitivity table (informational; default remains 2:1).**

| Weights (nat:state) | 2022 State RMSE | 2022 Brier | 2018 State RMSE | 2018 Brier |
|---|---|---|---|---|
| 1:1 | filled by backtest | | | |
| **2:1 (default)** | | | | |
| 3:1 | | | | |

(Table is generated by `make backtest` into `output/backtest/sensitivity.md`; the plan intentionally does not hard-code results.)

### 7.4 Go-live acceptance thresholds

| Check | Threshold |
|---|---|
| Calibration constraint | county ν-weighted swing equals `S_s` within 1e-6 in all 35 states |
| State RMSE (2022 & 2018 backtests) | ≤ 5.0 pts each (aim ≤ 4.0); not worse than a naive "uniform national swing" baseline |
| County RMSE (vote-weighted) | ≤ 5.5 pts; and ≤ the "state swing uniform" baseline − 0.3 pts (EI must add value) |
| Bias | |mean state bias| ≤ 1.5 pts; no region bias > 3 pts |
| Brier (win prob) | ≤ 0.10 (a coin-flip scores 0.25) |
| 80% interval coverage | 0.70–0.90 (states) |
| EI diagnostics | all states `rhat<1.01`, `ess_bulk>400`, 0 divergences, or documented fallback |
| EI vs validated | no flag > 12 pts for large groups |
| Data checks | all pandera schemas pass; 35 races; no missing county |
| Frontend | Lighthouse perf ≥ 90 (mobile), a11y ≥ 95; map TopoJSON budgets met |

---

## 8. Pipeline orchestration

### 8.1 `make update` DAG

```
fetch_pres ─┐
fetch_acs_cvap ─┼─> geo_build ─> baseline ─────────────────────────────┐
fetch_shapes ─┘                                                         │
fetch_generic ─> generic_avg ─> s_nat ─────────────────┐               │
fetch_senate_polls ─> house_effects ─> state_avg ─> s_poll ─> s_state ──┤
fetch_crosstabs ─> harmonize ─> group_swing ────────────────────────────┤
validated_priors ─> ei_levels ─> ei_shift (cached) ──> patterns ────────┤
fetch_early_vote ─> ev_compare ─> ev_weights ───────┐                   │
turnout_base ────────────────────────────────────────┴─> turnout ───────┤
                                              county_raw ─> calibrate ──┘
                                                  └─> rollup ─> simulate ─> export_json ─> export_topojson ─> diff_report
```

`Makefile` targets: `make update` (all), `make fetch`, `make model`, `make sim`, `make export`, `make site`, `make backtest`, `make test`. Stage runner: `python -m senate.cli run --stage <name> --as-of <date>`. Each stage declares `inputs`, `outputs`, `code_version` in `src/senate/stages.py`; hash-based incremental skipping (`data/cache/stage_hashes.json`).

### 8.2 Incremental re-runs

- Fetch stages always run (conditional GET/ETag); downstream stages re-run only if an input hash changed.
- EI levels/shift stages key on `(pres_county hash, cvap hash, priors hash, code_version)`; nightly runs normally skip them.
- Simulation re-runs when any projection changes (≈ 5–8 min at N=20,000; vectorised numpy).

### 8.3 Logging

`structlog` JSON lines to `logs/<run_id>.jsonl` and human summary to stdout. Required events: `source_fetch{source,status,rows,fallback}`, `stage_start/stage_end{stage,seconds,skipped}`, `warning{code}` (e.g., `AGG_MISMATCH`, `FALLBACK_USED`, `EI_RETRY`). Failed stage ⇒ non-zero exit and **previous published artifacts stay live**.

### 8.4 “What changed since last run” diff

`export/diff.py::diff_runs(prev_dir, new_dir) -> DiffReport` writes `output/diff.md` and `output/changes.json`:
- national: `s_nat`, GB average, control probability Δ.
- per state: Δ margin, Δ win probability, `swing_source` changes, new polls count, EV component Δ.
- per county: top 20 absolute Δ margin.
- data health: sources in fallback, EI status changes.
Thresholds (`diff.alert_margin_pts: 1.0`, `diff.alert_prob: 0.05`) mark rows ⚠️; CI posts the diff as a job summary.

### 8.5 Scheduling and run-time budget

| Job | Trigger | Budget |
|---|---|---|
| `update.yml` | cron `0 */6 * * *` (every 6 h; hourly in final week via `workflow_dispatch` schedule override) | ≤ 20 min total (fetch 3, models 4, sim 8, export 3, test 2) |
| ~~`ei_refresh.yml`~~ | **Removed (zero-cost):** EI is run locally with `make ei` and its small outputs committed | local only |
| `deploy.yml` | on push to `main` of `site/` or `site/static/data` | ≤ 5 min |
| Local | `make update` | ≤ 30 min cold (sans EI), EI cold ≈ 40 min |

All workflows use the free standard `ubuntu-latest` runner on a **public** repo (no billed minutes); the nightly job does not run EI and fits in ~20 min and the 6-hour job limit. Final-week hourly runs stay free for public repos, but keep the job under 10 min so GitHub's scheduler does not queue-drop it. GitHub Actions caches `data/cache` and `~/.cache/uv`. Published data committed to a `data` branch or `site/static/data` through `peaceiris/actions-gh-pages` (or `actions/deploy-pages`).

### 8.6 Election-night / results-overlay mode

`config.results.mode: "off" | "overlay"`. In `overlay`, ingest county results from AP-alternative open sources only if licensed (⚠️ AP data is paid; NYT/others scraping is disallowed) — default plan: **manual CSV** `data/manual/results_2026.csv` (`geoid, votes_d, votes_r, pct_reporting`) plus state SoS pages for ~6 priority states; exports `/data/results_overlay.json`. Projection page shows “Actual vs projected” once ≥ 90% reporting, never replaces projection.

---

## 9. Output artifacts

Published under `site/static/data/` (all UTF-8, gzip-friendly). Margins in points rounded to 0.1; probabilities to 0.001. `run_id` and `as_of` in every file. Colors are computed on the client.

### 9.1 `summary.json`

```json
{
  "run_id": "20261102T120000Z",
  "as_of": "2026-11-02",
  "model_version": "1.0.0",
  "national": {
    "generic_ballot": {"margin": 9.0, "n_polls": 38, "n_eff": 21.4, "se": 1.1},
    "npv2024": -1.5,
    "s_nat": 10.5,
    "senate": {
      "d_seats_median": 49, "d_seats_p10": 46, "d_seats_p90": 53,
      "p_d_control": 0.31, "distribution": {"44": 0.001, "45": 0.004, "46": 0.02}
    }
  },
  "weights": {"national": 2, "state_poll": 1},
  "races": [
    {"state": "GA", "name": "Georgia", "class": 2, "special": false,
     "incumbent": "Jon Ossoff", "incumbent_party": "D",
     "dside": {"name": "Jon Ossoff", "party": "D", "endorsed_by_dem": true},
     "rside": {"name": "Mike Collins", "party": "R"},
     "rcv": false,
     "pres2024_margin": -2.2,
     "proj_margin": 7.5, "shift": 9.7,
     "interval80": [2.1, 12.9],
     "p_dside_win": 0.84,
     "swing_source": "combined",
     "components": {"national": 10.5, "state_poll": 8.2, "market": 6.4, "market_weight": 0.10, "state_swing": 9.4, "turnout": -0.4, "early_vote": 0.3},
     "market": {"p_dside": 0.80, "implied_margin": 4.2, "platforms": ["kalshi", "polymarket"], "volume_24h_usd": 62000},
     "polls": {"n": 5, "avg_margin": 6.0, "n_eff": 3.8},
     "ev_detail": "full", "ei_status": "ok", "county_method": "ei_crosstab"}
  ]
}
```

(Example values illustrative; `proj_margin` = `pres2024 + state_swing + turnout + early_vote`: here −2.2 + 9.7 − 0.4 + 0.3 = 7.4 ≈ 7.5 after rounding in the real file; the exporter asserts the identity within 0.05.)

### 9.2 `states/<ST>.json` (one per race)

```json
{
  "state": "GA", "run_id": "...", "as_of": "...",
  "counties": [
    {"geoid": "13121", "name": "Fulton", "pres2024_margin": 46.2,
     "proj_margin": 54.9, "shift": 8.7, "interval80": [49.0, 60.5],
     "votes_2024": 520000, "votes_proj": 430000,
     "p_dside_win": 1.0, "group_shares": {"wnh_college": 0.28, "black": 0.44},
     "group_swings": {"wnh_college": 6.0, "black": 7.0},
     "flags": []}
  ],
  "groups": [{"group": "black", "swing": 7.0, "sd": 2.1, "shrinkage": 0.55, "n_polls": 9}],
  "early_vote": {"as_of_days_out": 1, "vs_2022": {"total_ratio": 1.12}, "vs_2018": {"total_ratio": 1.45}, "vs_2024": {"total_ratio": 0.74},
                 "party_share": {"2026": {"D": 0.43, "R": 0.38}, "2022": {"D": 0.45, "R": 0.36}}, "cap_binding": false},
  "polls_recent": [{"pollster": "…", "end": "2026-10-28", "n": 800, "pop": "LV", "margin": 6.0}]
}
```

### 9.3 `topo/counties.topojson` and `topo/states.topojson`

TopoJSON, quantised (`1e5` for counties national; `1e6` state-level files), objects `counties` / `states`, `properties: {geoid, name, state}`. Joins by `id = geoid`. National file only includes counties for states with a 2026 race; others rendered via `states` layer in neutral gray. State detail files `topo/states/<ST>.topojson` (≤ 150 KB each gz). Budget: national counties ≤ 700 KB gz.

### 9.4 `counties_national.json`

Compact array for the national map to avoid 35 fetches:

```json
{"cols": ["geoid","pres2024","proj","shift","p"], "rows": [["13121",46.2,54.9,8.7,1.0], ["13135",-8.4,-0.4,8.0,0.41]]}
```

### 9.5 `changes.json`, `data_health.json`, `methodology_params.json`

- `changes.json`: output of §8.4 (public top-level changes only).
- `data_health.json`: `{"sources": [{"name": "generic_polls", "status": "ok|fallback|stale", "retrieved_at": "…"}], "flags": ["…"]}`.
- `methodology_params.json`: current config values displayed on the methodology page (weights, half-life, caps).

### 9.6 Validation of artifacts

`export/schema.py` uses pydantic models; `site/src/lib/data/types.ts` mirrors them (generated via `datamodel-code-generator` → `json-schema-to-typescript`). CI fails if either diverges.

---
## 10. Website

### 10.1 Stack and justification

| Layer | Choice | Why |
|---|---|---|
| Framework | **SvelteKit** with `@sveltejs/adapter-static` (prerender) | Small bundles, easy for a Python-first developer, static output suits GitHub Pages |
| Language | TypeScript (strict) | Generated types from artifact schemas |
| Map | `d3-geo` + `topojson-client`, SVG for states, **Canvas** for the ~3,100-county national layer (hit-testing via `d3-quadtree`/`d3.Delaunay`) | SVG with 3k paths is sluggish on mobile |
| Charts | `layerchart` or hand-rolled D3 (seat histogram, margin ranges) | Light |
| Styling | CSS variables + utility CSS (no heavy UI kit); dark-mode tokens | Accessibility, perf |
| Tests | Vitest, Playwright, `@axe-core/playwright` | §11 |
| Hosting | **GitHub Pages** (project site; `base` path configured via `paths.base`) with GitHub Actions | Owner's choice; free for public repos; data refreshed by workflow commits; all libraries (Svelte, D3, TopoJSON, satori, resvg, Lighthouse CI) are open source; fonts self-hosted or system fonts (no paid font/CDN) |

### 10.2 Pages

**Routes:** `/` national, `/state/[abbr]`, `/methodology`, `/about`. Prerender `/state/*` for the 35 races.

#### National (`/`)
| Component | Data file | Behavior | States |
|---|---|---|---|
| `HeaderBar` | `summary.json` | last updated (relative + absolute), run id | skeleton text |
| `ControlGauge` | `summary.json.national.senate` | D-control probability, median seats, 80% range | loading skeleton; error: “Projection unavailable — last good run shown” banner using cached copy |
| `SeatHistogram` | `summary.json…distribution` | hover shows P(exactly k seats); 51 threshold line | empty: hidden |
| `NationalMap` | `topo/counties.topojson` + `counties_national.json` | county Canvas layer, state outlines; **Projection / Shift toggle** (§10.3); hover/tap tooltip (§10.4); click → state page | loading: gray silhouette + spinner (≤ 1 s); error: static PNG fallback `og/national.png` + retry button |
| `RaceTable` | `summary.json.races` | sortable columns: state, proj margin, shift, P(win), polls count; filter by competitive/ratings | empty: “No races match”; mobile: card list |
| `ComponentsPanel` | `summary.json` | shows S_nat, weights (2:1) | static |
| `ChangesFeed` | `changes.json` | last-run diff | empty: “No notable changes” |

#### State (`/state/GA`)
| Component | Data file | Behavior |
|---|---|---|
| `StateHeader` | `states/GA.json`, `summary.json` | candidates (D-side label rules §2.2), P(win), 80% interval bar |
| `SwingDecomposition` | `summary.json.races[].components` | stacked bar: 2024 baseline → national → race polls (combined) → turnout → early vote → projection |
| `StateMap` | `topo/states/GA.topojson` + counties array | same toggle/tooltips; legend |
| `CountyTable` | `states/GA.json.counties` | sortable/searchable; CSV download |
| `GroupSwings` | `states/GA.json.groups` | dot-and-whisker; shrinkage indicator tooltip |
| `EarlyVotePanel` | `states/GA.json.early_vote` | days-out line chart 2026 vs 2022/2018/2024; badge `ev_detail`; notes “capped at ±1.5” |
| `PollList` | `states/GA.json.polls_recent` | most recent polls |
Empty/Loading/Error: skeletons; if `states/XX.json` 404 → “Detailed county data isn't available for this race” + link to table; `swing_source=national_fallback` shows banner “No recent state polling; this projection uses only the national environment.”

#### Methodology (`/methodology`)
Prerendered from `docs/methodology.md` (outline in §15) with live parameters from `methodology_params.json` and the validation table from `output/backtest/summary.json`.

#### About (`/about`)
Authors, contact, data credits (Census, MEDSL, polling sources, Wikipedia CC BY-SA attribution), corrections policy, update schedule, disclaimer (“not an official result”).

### 10.3 Projection / Shift toggle

Segmented control (`role="radiogroup"`), query param `?view=projection|shift`, default `projection`, persisted in `localStorage` (try/catch). Switching animates fills 200 ms (disabled under `prefers-reduced-motion`). Legend, tooltip headings, and the table's primary column change with the view; the tooltip always shows both numbers.

### 10.4 County tooltip contents

```
Fulton County, GA
Projected 2026 Senate:  D+54.9  (80%: D+49 to D+60)
2024 presidential:      D+46.2
Shift from 2024:        D+8.7 toward Democrats
Expected 2026 votes:    430,000  (2024: 520,000)
Largest groups:         Black 44% · White college 28%
Method:                 EI + crosstabs   [or "Uniform state swing"]
```
Tap on mobile pins a bottom-sheet with the same content and a “View state” link.

### 10.5 Color scales (exact hex)

**Projection (diverging):** conventional blue (D) ↔ neutral ↔ red (R), with monotone lightness steps so the two sides stay distinguishable under deuteranopia/protanopia.

| Margin (pts) | Hex |
|---|---|
| ≥ D+40 | `#08306B` |
| D+30 | `#08519C` |
| D+20 | `#2171B5` |
| D+10 | `#6BAED6` |
| D+5 | `#9ECAE1` |
| D+1 | `#C6DBEF` |
| 0 | `#F2F2F2` |
| R+1 | `#FCCDBE` |
| R+5 | `#FC9272` |
| R+10 | `#EF6548` |
| R+20 | `#CB181D` |
| R+30 | `#A50F15` |
| ≥ R+40 | `#67000D` |

**Shift (diverging, different hue family so it cannot be confused with margin):** teal = shift toward D, amber/brown = shift toward R (ColorBrewer BrBG).

| Shift (pts) | Hex |
|---|---|
| ≥ +16 toward D | `#01665E` |
| +12 | `#35978F` |
| +8 | `#80CDC1` |
| +4 | `#C7EAE5` |
| 0 | `#F5F5F5` |
| −4 | `#F6E8C3` |
| −8 | `#DFC27D` |
| −12 | `#BF812D` |
| ≤ −16 toward R | `#8C510A` |

Legends include numeric labels and pattern hints for the extremes. Both scales validated with a Machado deuteranopia/protanopia simulation script `site/scripts/check_cb.mjs`; contrast of text on fills ≥ 4.5:1 (labels in tooltips/legends sit on white/dark panels, not on map fills). Independents-as-D-side use the same blue scale with a diamond marker in lists.

### 10.6 Mobile, accessibility, performance, SEO

- **Mobile:** single column; map first at 100% width/aspect 1.6; pinch/zoom with `d3-zoom` on the state map only (national map taps to state); table → cards; sticky toggle.
- **A11y (WCAG 2.2 AA):** every map has a data-table equivalent; keyboard-focusable counties via state map (`tabindex` roving) and the table for national; `aria-live="polite"` region announces tooltip content on focus; no information by color alone (values printed); focus outlines 3:1; `prefers-reduced-motion`; `prefers-color-scheme` tokens; skip links; language attr.
- **Performance budget:** LCP ≤ 2.5 s on 4G mobile; total JS ≤ 120 KB gz initial; national TopoJSON ≤ 700 KB gz; per-state TopoJSON ≤ 150 KB gz; national map interactive ≤ 1.5 s after JS; data JSON ≤ 250 KB gz each; images WebP. Enforced via Lighthouse CI (`lighthouserc.json`) and `size-limit`.
- **SEO/social:** per-page `<title>`, meta description, canonical URL, JSON-LD `Dataset` on methodology, `sitemap.xml` + `robots.txt`; OG/Twitter cards 1200×630 per state generated at build with `satori` + `resvg` showing race, projection and P(win); `og:updated_time`.
- **Hosting/deploy:** GitHub Pages; `paths.base = '/<repo>'` for project pages; no custom domain (free `github.io` URL only; zero-spend rule A13); `404.html` fallback; cache busting through hashed filenames; data files fetched with `?v=<run_id>`.

---

## 11. Testing strategy

### 11.1 Unit tests (`tests/unit/`)

| Test name | Asserts |
|---|---|
| `test_margin_2p_basic` | `(60,40) → +20.0`; zero-vote raises |
| `test_margin_state_from_county_sums` | state margin ≠ mean of county margins; equals vote-sum formula |
| `test_national_swing_sign` | GB +9, NPV −1.5 ⇒ +10.5; NPV +4.5 ⇒ +4.5 |
| `test_state_swing_2to1` | `(2*10.5+8.2)/3 == 9.7333` |
| `test_state_swing_unpolled_fallback` | returns `S_nat` and `national_fallback` |
| `test_state_swing_ratio_configurable` | 1:1, 3:1 give expected values |
| `test_state_swing_volume_scaled_off_by_default` | config default false |
| `test_market_devig_sums_to_one` | D/R contract prices normalise to 1 |
| `test_market_prob_to_margin` | p=0.5 ⇒ 0; p=0.8, σ=5 ⇒ 4.21; clip at 0.02/0.98 |
| `test_market_weight_zero_without_quotes` | no qualifying market ⇒ `S_s == S_base` |
| `test_market_weight_liquidity_scaling_and_cap` | μ ≤ 0.20; thin market ⇒ smaller μ |
| `test_market_does_not_change_2to1_core` | `S_base` identical with market on/off |
| `test_market_unpolled_state_blend` | `0.9·S_nat + 0.1·S_mkt`, source `national_market` |
| `test_market_stale_and_wide_spread_dropped` | filters applied |
| `test_calibration_with_market_swing` | county constraint still equals market-blended `S_s` |
| `test_poll_weight_time_decay_halflife` | weight halves at H days |
| `test_poll_weight_sample_cap` | n=5000 weight equals n=2000 weight |
| `test_poll_weight_quality_monotone` | higher rating ⇒ higher weight |
| `test_poll_pop_adjustment_lv_rv` | RV shifted by δ_LV |
| `test_pollster_cap_25pct` | no pollster > 0.25 after water-filling (and 0.5 when <4 pollsters) |
| `test_pollster_cap_converges` | ≤ 10 iterations, weights sum to 1 |
| `test_house_effects_sum_zero` | volume-weighted sum ≈ 0 |
| `test_house_effects_shrinkage` | pollster with 1 poll has |h| < raw residual |
| `test_calibration_exact_no_clip` | `Σν s = S` to 1e-9 |
| `test_calibration_exact_with_clip` | counties near ±100 clip; constraint still holds |
| `test_calibration_property` (hypothesis) | random m0, s_raw, w≥0 ⇒ constraint holds |
| `test_calibration_flat_weights_equals_mean_shift` | |
| `test_group_shrinkage_toward_overall` | tiny n ⇒ δ_g ≈ S_ref |
| `test_group_harmonization_nonwhite_split` | variance ×2 rule |
| `test_earlyvote_cap_binding` | huge ψ tilt ⇒ `|E_s| ≤ 1.5` |
| `test_earlyvote_cap_not_binding_unchanged` | small tilt unchanged |
| `test_earlyvote_party_cycles_exclude_2018` | |
| `test_earlyvote_total_only_zero_component` | |
| `test_earlyvote_days_out_alignment_interpolation` | |
| `test_turnout_weights_sum_to_state_total` | |
| `test_crosswalk_ct_planning_regions_sum` | votes preserved (±0) |
| `test_crosswalk_ak_district_to_borough_sum` | votes preserved within rounding of pop weights |
| `test_crosswalk_town_to_county_ne` | all town GEOIDs map; counts preserved |
| `test_fips_aliases_oglala` | 46113 → 46102 |
| `test_rollup_identity` | `m̂_s = m0_s + S_s + T_s + E_s` within 1e-6 |
| `test_sim_state_total_unaffected_by_county_term` | county error zero-sum under ω |
| `test_sim_seed_reproducible` | |
| `test_sim_prob_monotone_in_margin` | |
| `test_dside_independent_labeling` | NE yields Osborn as D-side |
| `test_rcv_final_round_conversion` | transfer rule |

### 11.2 Integration tests (`tests/integration/`)

- `test_end_to_end_fixture_state`: 10-county fake state through baseline→swing→calibrate→export; schema valid.
- `test_backtest_2022_smoke`: 3 states, N=500, runs < 3 min.
- `test_ei_reference_agreement`: custom model vs PyEI reference on synthetic data with known truth — recovers group shares within 3 pts when counties are heterogeneous; and **fails gracefully** (wide posteriors, `ei_status='retry'/'fallback'`) on homogeneous synthetic counties (identification test).
- `test_pipeline_idempotent`: two runs with same inputs produce identical outputs hash.
- `test_manual_fallback_path`: block network ⇒ every ingest uses `data/manual` and flags it.

### 11.3 Data validation (`tests/data/`, pandera)

- `pres_county`: unique `(year, geoid)`, `votes_d+votes_r ≤ votes_total`, 3,100+ counties (+CT regions), national total within 0.1% of FEC.
- `cvap_county`: shares sum to 1 ± 0.01; MOE ≥ 0.
- `generic_polls`, `senate_polls`: `field_end ≥ field_start`, `d_pct + r_pct ≤ 100`, `pop ∈ {LV,RV,A}`, no duplicate `poll_id`.
- `races_2026`: 35 rows, classes {2: 33, 3: 2}, 2 specials.
- `early_vote_daily`: monotone non-decreasing cumulative counts per `(state, party)`.
- Artifact schema checks (pydantic) and cross-file consistency (`summary` vs `states/*`).

### 11.4 Frontend tests

- Vitest: toggle state logic, color scale function (breakpoints, exact hex), tooltip formatter (rounding, signs "D+54.9"), data loaders with mocked failures.
- Playwright: national map loads < 3 s; toggle changes legend; click county opens state page; keyboard navigation reaches table; offline error state; mobile viewport screenshots.
- axe-core: zero serious/critical violations on all 4 page types.
- Lighthouse CI budgets (§10.6).
- Visual regression: Playwright screenshots of both toggle states (tolerance 1%).

---

## 12. Configuration reference

`config/config.yaml` (validated by `src/senate/config.py`, pydantic):

```yaml
cycle: 2026
as_of: null                      # null = today (UTC); date for backtests
baseline:
  year: 2024
  office: president
swing:
  weights: {national: 2, state_poll: 1}
  market:
    enabled: true
    mu: 0.10                 # max market share of the state swing
    weight_cap: 0.20
    scale_by_volume: true
    v_ref_usd: 50000
    sigma_pts: 5.0
    prob_clip: [0.02, 0.98]
    max_abs_margin: 25
    max_spread: 0.08
    min_volume_usd: 5000
    max_age_hours: 48
    platforms: [kalshi, polymarket]
  scale_by_poll_volume: false
  n_ref: 6.0
  national: {generic_ballot_source: own_average}
  state: {min_polls: 1, min_n_eff: 0.8}
polls:
  half_life_days: {senate: 14, generic: 10}
  max_age_days: {senate: 60, generic: 45}
  n_cap: 2000
  n_min: 300
  n_ref: 600
  n_weight_max: 1.5
  unrated_rating: 1.0
  population_weight: {LV: 1.0, RV: 0.9, A: 0.75}
  partisan_weight: 0.6
  multiway_weight: 0.8
  pollster_cap: 0.25
  pollster_cap_few: 0.5
  tracker_gap_days: 7
  sigma_poll: 3.9
  sigma_floor: 1.0
  house_effect: {enabled: true, shrink_k: 3, max_abs: 4.0, min_polls: 3}
  lv_rv: {adjust: true, prior_delta: 0.0, min_pairs: 8}
rcv: {transfer_to_dside: 0.50}
crosstab:
  min_n: 75
  deff: 1.5
  sampler: {chains: 4, tune: 1000, draws: 1000, target_accept: 0.9}
ei:
  groups: [wnh_college, wnh_noncollege, black, hispanic, asian, other]
  sampler: {chains: 4, tune: 1000, draws: 1000, target_accept: 0.92, seed: 20260}
  rhat_max: 1.01
  ess_min: 400
  retry_target_accept: 0.97
  min_counties_for_state_run: 25
  pattern_persistence: 0.5
  workers: 8
  relative_turnout: {wnh_college: 1.00, wnh_noncollege: 0.88, black: 0.86, hispanic: 0.72, asian: 0.75, other: 0.75}
earlyvote:
  cap_pts: 1.5
  cycle_weights: {2022: 0.40, 2018: 0.30, 2024: 0.30}
  party_cycles: [2022, 2024]
  party_cycle_weights: {2022: 0.6, 2024: 0.4}
  shrink: 0.5
  county_blend_kappa: 0.25
turnout:
  dropoff: {wnh_college: 0.85, wnh_noncollege: 0.74, black: 0.66, hispanic: 0.56, asian: 0.62, other: 0.60}
  environment_beta: 0.0005
  rho_weights: {r22_20: 0.7, r18_16: 0.3}
sim:
  n_draws: 20000
  seed: 20261103
  t_df: 6
  sd: {national: 2.5, region: 2.0, group: 1.5, state: 3.0, state_unpolled_extra: 2.0, county: 2.5}
  rho: {region_neighbor: 0.3, state_similarity: 0.2}
  control_threshold: 51
  interval: [0.10, 0.90]
geo: {town_layer: false}
http: {min_interval_s: 2.0, retries: 4, user_agent: "SenateCountyProjection/1.0 (+about-page-url; research project)"}
validation: {ei_flag_pts: 8, ei_fail_pts: 12}
diff: {alert_margin_pts: 1.0, alert_prob: 0.05}
results: {mode: off}
backtest: {as_of_days_before: 1}
```

(Types: ints/floats/bools/strings/maps as shown; every key above is required with its stated default.)

---

## 13. Phased implementation plan

Effort is focused-engineer weeks (owner: strong Python, some JS).

### Phase 1 — Data ingestion (2.0 wk)
**Goal:** all inputs land as validated parquet with manual fallbacks.
**Tasks**
- [ ] `pyproject.toml`, `uv` lock, `Makefile`, `config/config.yaml`, `src/senate/config.py`, `io.py` (UA, cache, robots, rate limit)
- [ ] `data/manual/races_2026.csv` seeded from §2 and verified against Ballotpedia + SoS pages
- [ ] `ingest/pres_results.py` (MEDSL) + crosswalks (`geo/crosswalks.py`, CT, AK, towns, aliases)
- [ ] `ingest/acs_cvap.py`, `ingest/shapes.py`
- [ ] `ingest/generic_ballot.py`, `ingest/senate_polls.py`, pollster ratings/aliases CSVs
- [ ] `ingest/crosstabs.py` (manual + PDF helper), `ingest/validated_voter.py` (manual tables)
- [ ] pandera schemas; tests `tests/data/*`
**Dependencies:** none. **DoD:** `make fetch` succeeds from clean checkout; all §11.3 checks pass; fallbacks proven. **Review:** data dictionary, race table, source status table (`output/data_health.json`), counts of counties by state.

### Phase 2 — National + state swing model, with backtest (1.5 wk)
**Tasks**
- [ ] `polls/{weights,house_effects,lv_rv,average}.py`; `swing/{national,state,combine}.py`
- [ ] `export/to_json.py` minimal `summary.json`
- [ ] `backtest/run_backtest.py`, `metrics.py`; 2018 + 2022 state-level runs; sensitivity table
- [ ] Unit tests (poll weights, swing math)
**Dependencies:** Phase 1. **DoD:** state RMSE thresholds (§7.4); 2:1 default intact. **Review:** backtest report, 2026 state table with `swing_source`, poll average audit for 5 states.

### Phase 3 — EI and demographic distribution (3.0 wk)
**Tasks**
- [ ] `ei/groups.py`, `ei/model_rxc.py` (PyMC), `ei/run_state.py` (joblib), `ei/diagnostics.py`, PyEI reference
- [ ] `ei/shift_ei.py` (2020→2024)
- [ ] `crosstab/{harmonize,hier_model}.py`
- [ ] `county/{construct,calibrate}.py`; calibration tests
- [ ] EI validation vs validated voters; county backtest
**Dependencies:** 1, 2. **DoD:** diagnostics pass or documented fallback; county RMSE better than uniform baseline; EI flags reviewed. **Review:** EI group tables for 6 states, shrinkage plots, calibration test results, flag list.

### Phase 4 — Early vote (1.5 wk)
**Tasks:** per-state adapters (NC, GA, FL first, then AZ, NV, MI, PA, OH, TX, WI as available); `earlyvote/{compare,weights}.py`; historical days-out tables; cap logic; tests.
**Dependencies:** 1, 3. **DoD:** component exported separately; cap test passes; backtest of module on 2022. **Review:** days-out charts for 6 states; component sizes; states with `ev_detail` ≠ full.

### Phase 5 — Turnout + simulation (1.5 wk)
**Tasks:** `turnout/model.py`; `sim/{errors,covariance,simulate,outputs}.py`; fit error model from `historical_midterm_polling_misses.csv`; calibration/Brier in backtests; seat distribution.
**Dependencies:** 2–4. **DoD:** thresholds §7.4 (Brier, coverage). **Review:** fitted σ's vs defaults, reliability plot, seat distribution.

### Phase 6 — Frontend (3.0 wk)
**Tasks:** SvelteKit scaffold; Canvas national map; state page; toggle; tooltips; tables; methodology/about; color scales; a11y; Lighthouse/size budgets; OG card generation; Vitest/Playwright/axe.
**Dependencies:** artifact schemas from Phase 2 onward (mock data first). **DoD:** all §11.4 tests, budgets met. **Review:** deployed preview, mobile screenshots, a11y report.

### Phase 7 — Deployment and automation (1.0 wk)
**Tasks:** `.github/workflows/{ci,update,deploy}.yml`; caching; diff summary; failure alerts; results-overlay mode; runbook `docs/runbook.md`.
**DoD:** unattended 6-hourly update with previous-good fallback; a week of green runs. **Review:** workflow logs, diff output sample.

### Phase 8 — Optional precinct-level extension (deferred)
Owner chose to skip. Stub: if revived, add `ingest/precinct_results.py` (Redistricting Data Hub / state SoS precinct files, shapes from VEST/MGGG), EI at precinct level for priority states ❓ DECISION (candidates previously listed: GA, MI, NC, ME, TX, OH), vector-tile delivery (PMTiles) and a precinct layer. No work scheduled.

---

## 14. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **Scraper breakage / ToS limits** (Wikipedia layout changes, aggregators prohibit scraping, Substack changes) | Missing polls | Prefer Wikipedia (CC BY-SA, tables) + manual CSV; layout-change detector (column checks) fails loudly; aggregator headlines are diagnostics only; weekly `data_health.json` review; no bypass of robots.txt/paywalls |
| **Sparse state polling** | Noisy `S_poll`, many fallbacks | 2:1 weight already damps; fallback to `S_nat` flagged; wide SE in sim for unpolled; optional volume scaling mode (off) |
| **Noisy crosstabs** | Spurious group swings | Hierarchical shrinkage toward `S_ref`; `min_n=75`; deff 1.5; persisted-EI prior; cap on county tilt `|tilt| ≤ 6 pts` (config `county.max_tilt: 6.0`) |
| **EI identification problems in homogeneous counties** | Wrong group shares | Informative priors from validated voters; covariates; hierarchical pooling; posterior width reported; reference comparison; `ei_status='fallback'` path; EI only moves *within-state distribution*, never the state total |
| **Early-vote misreads** (changed R behaviour, rule changes, late mail processing) | Biased turnout weights | Party categories use post-2020 cycles only; cap ±1.5; separate component; total-only states have zero effect; shrink 0.5 |
| **Election Night timing** | Stale projection vs live returns confusion | Freeze projection at 2026-11-03 06:00 local; results overlay mode only with licensed/manual data; label “Pre-election projection”; no automated scrape of news results |
| Candidate/nominee changes (ME, NE, ID, MT, SD per snapshot) | Wrong labels, polls | `nominee_changes.csv`; unit test on labelling; manual verification before each deploy |
| FIPS/vintage mismatch (CT, AK) | Missing/misallocated counties | Crosswalks with vote-preservation tests; CT EI at town level |
| Market data access/ToS, thin or manipulable markets, double-counting polls | Distorted state swing | Small capped weight (≤ 20%), liquidity scaling, spread/staleness filters, manual fallback, can be disabled with `swing.market.enabled: false`, backtest sensitivity reported |
| Overconfident probabilities | Reputational | Student-t tails, floors on σ, backtest coverage targets; “probabilities are not forecasts of margins” explainer |
| Compute failure of EI | Missing county layer | Cached traces; fallback modes; flagged in UI |
| Licensing (AP VoteCast, Pew tables, Wikipedia) | Legal | Hand-entered numeric facts with citation; Wikipedia attribution on About; no redistribution of AP files |
| Time pressure (election is tomorrow) | Quality | Ship staged v0 (Phase 1+2+6-lite) only after §7.4 state checks; label clearly |

---

## 15. Methodology write-up outline (public page)

1. **What this is** — a county-level projection of 2026 Senate races; what it isn't (not an official result, not a poll).
2. **The starting point** — 2024 presidential two-party margin; why not House/Senate 2024.
3. **The national mood** — generic ballot minus 2024 national vote ⇒ national swing; table of polls used.
4. **Race-specific polling** — how polls are averaged (recency, size, quality, population, house effects, caps); examples.
5. **Combining them 2:1** — why national gets twice the weight; what happens in unpolled states; the sensitivity note (1:1 and 3:1 shown for transparency).
5b. **A small nudge from betting markets** — how odds become an implied margin, why the weight is small (default 10%, capped 20%), and what it means that markets and polls overlap.
6. **Where the swing lands** — groups, crosstabs, shrinkage; ecological inference in plain language; why counties differ; **the state total is fixed first**.
7. **Calibration** — county swings are adjusted so they average to the state swing.
8. **Early vote and turnout** — what is compared (same days out vs 2022/2018/2024); why party registration is handled carefully; the ±1.5 cap; shown as a separate bar.
9. **Uncertainty** — correlated errors (national, regional, group, state, county), calibration on past misses; how to read probabilities and 80% intervals.
10. **Special cases** — independents as D-side (Nebraska), ranked-choice (Maine, Alaska), New England towns, Connecticut regions, Alaska boroughs, Virginia cities, special elections.
11. **Backtests** — 2018 and 2022 results tables, calibration plot.
12. **Data sources and credits** — with dates; limitations; known issues.
13. **Changelog and corrections.**

---

## 16. Glossary

| Term | Meaning |
|---|---|
| ACS | American Community Survey (Census) |
| AP VoteCast | AP/NORC survey of voters |
| Baseline | 2024 presidential two-party margin |
| Brier score | Mean squared error of probability forecasts |
| Calibration (county) | Shifting county swings so the weighted average equals the state swing |
| Catalist | Democratic-aligned voter-file data firm; validated-voter research |
| Class (Senate) | The 1/2/3 staggered cycle grouping of seats |
| County-equivalent | Parish, borough, independent city, planning region |
| Crosstab | Poll results broken out by demographic group |
| CVAP | Citizen voting-age population |
| D-side candidate | The Democratic nominee or the independent standing in for one |
| Deff | Design effect inflating variance of weighted surveys |
| EI | Ecological inference: estimating group behavior from aggregate data |
| ESS | Effective sample size (MCMC) |
| FIPS / GEOID | Geographic codes |
| Generic ballot | Poll question on which party's candidate respondents prefer for Congress |
| House effect | A pollster's systematic lean relative to the average |
| LV / RV / A | Likely voters / registered voters / all adults |
| MCMC / NUTS | Sampling algorithms for Bayesian models |
| MEDSL | MIT Election Data + Science Lab |
| NPV | National popular vote |
| Partial pooling | Estimating group effects by borrowing strength across groups/regions |
| PyEI | Python ecological inference library (MGGG) |
| R-hat | Convergence diagnostic (should be < 1.01) |
| RCV | Ranked-choice voting |
| Shift | Projected margin minus 2024 presidential margin |
| Shrinkage | Pulling noisy estimates toward a group mean |
| Special election | Election to fill the remainder of a term |
| Swing | Change in margin from baseline |
| Two-party margin | (D−R)/(D+R) in points |
| Unpolled fallback | Using only the national swing when no race polls exist |
| VAP | Voting-age population |
| Validated-voter study | Survey matched to voter-file records to confirm who voted |
| WNH | White non-Hispanic |
