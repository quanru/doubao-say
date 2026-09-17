PYTHON ?= .venv/bin/python

.PHONY: check test test-unit test-contracts coverage lint compile shell whitespace release marketplace-check
check: lint test compile shell whitespace

test: test-unit test-contracts

test-unit:
	PYTHONPATH=src:. $(PYTHON) -m unittest discover -s tests/unit -t . -v

test-contracts:
	PYTHONPATH=src:. $(PYTHON) -m unittest discover -s tests/contracts -t . -v
	node --test tests/contracts/test_pages_report_history.mjs

coverage:
	PYTHONPATH=src:. $(PYTHON) -m coverage run -m unittest discover -s tests -t .
	$(PYTHON) -m coverage report
	$(PYTHON) -m coverage xml

lint:
	$(PYTHON) -m ruff check src tests packaging

compile:
	$(PYTHON) -m compileall -q src/doubao_input tests packaging

shell:
	bash -n install.sh setup-omarchy.sh start.sh

whitespace:
	git diff --check

release: check
	$(PYTHON) packaging/build-release.py

marketplace-check:
	$(PYTHON) packaging/check-marketplace.py --secrets
