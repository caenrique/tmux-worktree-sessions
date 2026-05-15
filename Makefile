.PHONY: check test lint help

SHELL := /bin/bash

SHELLCHECK_TARGETS := scripts/*.sh tmux-sessions.tmux \
                      tests/test_helper.bash tests/helpers/*.bash \
                      tests/fixtures/bin/*

check: lint test  ## Run lint then tests (default).

test:  ## Run the bats suite.
	bats --print-output-on-failure tests/

lint:  ## Run shellcheck on all shell sources (severity=warning).
	shellcheck --severity=warning -x $(SHELLCHECK_TARGETS)

help:  ## Show this help.
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-10s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
