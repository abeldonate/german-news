VENV = venv
PYTHON = $(VENV)/bin/python3
PIP = $(VENV)/bin/pip
PORT ?= 5000

.PHONY: run setup

run: $(VENV)/bin/activate
	FLASK_APP=src/main.py $(PYTHON) -m flask run --host=0.0.0.0 --port=$(PORT)

setup: requirements.txt
	@if [ ! -x "$(PIP)" ]; then \
		rm -rf "$(VENV)"; \
		python3 -m venv $(VENV) || (echo "Missing dependency: install python3-venv first." && exit 1); \
	fi
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
