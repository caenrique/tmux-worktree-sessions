.PHONY: check test lint help py-test py-lint py-format-check py-typecheck py-check

SHELL := /bin/bash

SHELLCHECK_TARGETS := scripts/*.sh tmux-sessions.tmux \
                      tests/test_helper.bash tests/helpers/*.bash \
                      tests/fixtures/bin/*

check: lint test py-check  ## Run shellcheck, bats, and Python checks (default).

test:  ## Run the bats suite.
	bats --print-output-on-failure tests/

lint:  ## Run shellcheck on all shell sources (severity=warning).
	shellcheck --severity=warning -x $(SHELLCHECK_TARGETS)

py-test:  ## Run the pytest suite.
	python3 -m pytest tests/python

py-lint:  ## Run ruff lint on Python sources.
	ruff check scripts/ tests/python

py-format-check:  ## Check Python formatting with ruff.
	ruff format --check scripts/ tests/python

py-typecheck:  ## Type-check the tmux_sessions package with mypy --strict.
	mypy scripts/tmux_sessions

py-check: py-lint py-format-check py-typecheck py-test  ## Run all Python checks.

help:  ## Show this help.
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
