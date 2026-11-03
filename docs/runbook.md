# Runbook

## How it runs
- `update.yml`: every 6 h (hourly from 2026-10-27 via the gated `30 * * * *` cron) and on demand. Steps: `make update`
  (fetch, model, early vote, turnout, sim, overlay) -> `make test` -> `make diff` (job summary) -> `make publish`
  (validate + stage) -> force-push to the `data` branch -> call `deploy.yml`.
- `deploy.yml`: on push to `master` touching `site/**`, or called by `update.yml`. Builds with the `data` branch as
  `site/static/data` and publishes to GitHub Pages. It refuses to deploy if there is no `data` branch or the summary is mock.
- `ci.yml`: pytest, then svelte-check, vitest, build, colour-blind check, size budget and Playwright/axe on PRs and pushes.
- EI is never run in CI. Run `make ei` locally and commit its small outputs.

## Previous-good fallback
The `data` branch only changes after fetch, tests, diff and `publish` validation all succeed (`export/publish.py`:
required files present, 0 <= p <= 1, |margin| <= 100, not mock, JSON parses). Anything missing from the new run is carried
over from the previous tree. Any failure ends the run non-zero, so the live site keeps the last good data. A failed run
opens (or comments on) a GitHub issue labelled `update-failed`.

## Common situations
| Symptom | Action |
|---|---|
| Issue "Scheduled update failed" | Open the linked run; the `logs-*` artifact has `logs/<run_id>.jsonl`. Fix, then re-run via Actions -> update -> Run workflow. |
| Source layout changed (fetch error) | Fix the ingester or drop a manual CSV into `data/manual/` (see data dictionary); commit. |
| Bad projection that passed validation | Revert: `git push --force origin <good-sha>:data` (find it in `git log origin/data`), then re-run `deploy`. |
| Freeze the site | Disable the `update` workflow in the Actions tab. Election-night freeze: 2026-11-03 06:00 local. |
| Local run | `make update PREV=<dir with last published data>`, then `make diff publish PREV=<same dir>`. |

## Results overlay (election night)
1. Set `results: {mode: "overlay"}` in `config/config.yaml`.
2. Maintain `data/manual/results_2026.csv` (`geoid,votes_d,votes_r,pct_reporting`) from licensed or official sources only. No scraping of news or AP.
3. Commit and run `update`; `results_overlay.json` is published. States qualify for "Actual vs projected" at >= 90% reporting. The projection is never replaced.

## Repo settings
Settings -> Pages -> Source: GitHub Actions. Optional secret `CENSUS_API_KEY`. The default branch is `master` (workflows are written for it).
