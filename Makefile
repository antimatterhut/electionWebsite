PY ?= python
AS_OF ?=

.PHONY: fetch test update
fetch:
	$(PY) -m senate.cli run --stage fetch $(if $(AS_OF),--as-of $(AS_OF),)

test:
	$(PY) -m pytest

update: fetch
