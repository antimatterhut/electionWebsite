PY ?= python
AS_OF ?=

.PHONY: site site-test fetch model backtest test update ei crosstab county ei-validate county-backtest earlyvote earlyvote-backtest turnout sim export overlay diff publish
fetch:
	$(PY) -m senate.cli run --stage fetch $(if $(AS_OF),--as-of $(AS_OF),)

test:
	$(PY) -m pytest

model:
	$(PY) -m senate.cli run --stage model $(if $(AS_OF),--as-of $(AS_OF),)

backtest:
	$(PY) -m senate.cli run --stage backtest

# EI runs on the owner's machine only (hours worst case); results are committed, CI never runs it (plan §6.6).
ei:
	$(PY) -m senate.cli run --stage ei

crosstab:
	$(PY) -m senate.cli run --stage crosstab

county:
	$(PY) -m senate.cli run --stage county

ei-validate:
	$(PY) -m senate.cli run --stage ei-validate

county-backtest:
	$(PY) -m senate.cli run --stage county-backtest

earlyvote:
	$(PY) -m senate.cli run --stage earlyvote

earlyvote-backtest:
	$(PY) -m senate.cli run --stage earlyvote-backtest

turnout:
	$(PY) -m senate.cli run --stage turnout

sim:
	$(PY) -m senate.cli run --stage sim

# Site artifacts (states/, counties_national, methodology_params, site data_health) from the finished run.
export:
	$(PY) -m senate.cli run --stage export

# Frontend (plan §13 Phase 6). `site` builds the static site (fixture data is generated only if no real artifacts exist).
site:
	cd site && npm ci && npm run build

site-test:
	cd site && npm run check && npm test && npm run cb && npm run size && npm run test:e2e

# Results overlay, diff and publish (plan 8.4-8.6, Phase 7). PREV = previous-good published data dir.
PREV ?= .published
overlay:
	$(PY) -m senate.cli run --stage overlay

diff:
	$(PY) -m senate.cli run --stage diff --prev $(PREV)

publish:
	$(PY) -m senate.cli run --stage publish --prev $(PREV) --dest site/static/data

update: fetch model county earlyvote turnout sim export overlay
