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
