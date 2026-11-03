# Senate county projection: site

SvelteKit (Svelte 5, TypeScript strict) static site, plan §10. Prerendered with `@sveltejs/adapter-static`, deployable to
GitHub Pages (`BASE_PATH=/<repo> npm run build`).

```
npm ci
npm run build        # prebuild: topology + fixtures if absent, then OG cards; then vite build -> build/
npm run preview      # http://localhost:4173
npm run check        # svelte-check (strict TS)
npm test             # Vitest unit/contract tests
npm run cb           # Machado deuteranopia/protanopia check of both color scales
npm run size         # size-limit: initial JS <= 120 KB gz per page, data budgets
npm run test:e2e     # Playwright (desktop + mobile), axe, visual regression
npm run lhci         # Lighthouse CI budgets (set CHROME_PATH to a Chromium)
```

## Data

`static/data/` holds the published artifacts of plan §9. **In this repository they are fixtures**:

- `topo/*.topojson` come from `scripts/build_topo.mjs` (us-atlas, 2010s county vintage; stand-in until the pipeline's
  GENZ2024 shapes feed the Python exporter).
- `summary.json` state margins are the real Phase 2 output (`output/summary.json`); county detail, intervals,
  probabilities, group swings, early vote, polls and the seat distribution are synthetic (`scripts/make_mock_data.mjs`).
  Every fixture file is stamped `mock: true` and the UI shows a banner.

The deploy workflow (Phase 7) overwrites `static/data/` with the pipeline's artifacts before `npm run build`; the
prebuild step only generates topology/fixtures when the files are missing.

## Visual regression

Baselines are platform-specific. Create them once from the CI image with
`npx playwright test visual.spec.ts mobile.spec.ts --update-snapshots` and commit `tests/e2e/*-snapshots/`.
