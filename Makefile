PY ?= python
AS_OF ?=

.PHONY: fetch model backtest test update ei crosstab county ei-validate county-backtest earlyvote earlyvote-backtest
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

update: fetch model
