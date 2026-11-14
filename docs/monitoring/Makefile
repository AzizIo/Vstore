PYTHON ?= python3

.PHONY: check simulate test
check:
	$(PYTHON) scripts/check_monitoring.py
	$(PYTHON) -m py_compile scripts/*.py

simulate:
	$(PYTHON) scripts/check_monitoring.py --simulate

test:
	$(PYTHON) -m unittest discover -s tests -v
