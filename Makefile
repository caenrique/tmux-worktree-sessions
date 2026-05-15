.PHONY: check test lint help py-test py-lint py-format-check py-typecheck py-check

SHELL := /bin/bash

# Use the project virtualenv when present so `make py-*` works without
# activating it first. Override with `PY_BIN=python3` etc. if you'd
# rather rely on tools on PATH.
VENV_BIN ?= .venv/bin
PY       ?= $(if $(wildcard $(VENV_BIN)/python),$(VENV_BIN)/python,python3)
RUFF     ?= $(if $(wildcard $(VENV_BIN)/ruff),$(VENV_BIN)/ruff,ruff)
MYPY     ?= $(if $(wildcard $(VENV_BIN)/mypy),$(VENV_BIN)/mypy,mypy)

SHELLCHECK_TARGETS := scripts/*.sh tmux-sessions.tmux \
                      tests/test_helper.bash tests/helpers/*.bash \
                      tests/fixtures/bin/*

check: lint test py-check  ## Run shellcheck, bats, and Python checks (default).

test:  ## Run the bats suite.
	bats --print-output-on-failure tests/

lint:  ## Run shellcheck on all shell sources (severity=warning).
	shellcheck --severity=warning -x $(SHELLCHECK_TARGETS)

py-test:  ## Run the pytest suite.
	$(PY) -m pytest tests/python

py-lint:  ## Run ruff lint on Python sources.
	$(RUFF) check scripts/ tests/python

py-format-check:  ## Check Python formatting with ruff.
	$(RUFF) format --check scripts/ tests/python

py-typecheck:  ## Type-check the tmux_sessions package with mypy --strict.
	$(MYPY) scripts/tmux_sessions

py-check: py-lint py-format-check py-typecheck py-test  ## Run all Python checks.

help:  ## Show this help.
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
