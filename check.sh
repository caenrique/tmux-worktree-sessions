#!/usr/bin/env bash
set -euo pipefail

echo "==> ruff check"
uv run ruff check scripts/ tests/python

echo "==> ruff format --check"
uv run ruff format --check scripts/ tests/python

echo "==> mypy --strict"
uv run mypy scripts/tmux_worktree_sessions

echo "==> pytest"
uv run pytest tests/python

echo "==> shellcheck"
shellcheck --severity=warning tmux-worktree-sessions.tmux

echo "All checks passed"
