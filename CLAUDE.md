# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Testing

The test suite lives in `tests/` and runs under [bats-core](https://github.com/bats-core/bats-core). Install the runner from your package manager:

```sh
brew install bats-core
# or on Debian/Ubuntu:
sudo apt-get install bats
```

`tests/test_helper.bash` ships a minimal portable assertion library, so `bats-support` / `bats-assert` / `bats-file` are not required.

Run the full suite via the Makefile, or invoke bats directly for finer control:

```sh
make test                                      # full bats suite
bats tests/common.bats                         # one file
bats --filter "format_session_name" tests/     # one function
bats --print-output-on-failure tests/          # show captured output on failure
```

For ad-hoc smoke checks, you can still drive a script directly:

```sh
TMUX_SESSIONS_PROJECTS_DIRS="$HOME/Projects" \
TMUX_SESSIONS_ICON_STYLE=nerd \
bash scripts/sessions.sh
```

## Linting

Shell scripts are linted with [shellcheck](https://www.shellcheck.net/):

```sh
brew install shellcheck
# or on Debian/Ubuntu:
sudo apt-get install shellcheck
```

Run it from the repo root before committing:

```sh
make lint                  # shellcheck only
make check                 # lint + bats + Python checks (the default target)
```

The same scans run in CI via `.github/workflows/tests.yml`.

## Python tooling

A migration is in progress to move the bash scripts to a typed Python
package under `scripts/tmux_sessions/` (see `docs/python-migration.md`).
Python ≥ 3.8 is required; dev dependencies are declared in `pyproject.toml`.

Set up a project-local virtualenv and install dev dependencies:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

The Makefile auto-detects `.venv/bin/{python,ruff,mypy}` when present,
so the `make py-*` targets work without activating the venv. Override
`PY=`, `RUFF=`, or `MYPY=` on the make command line to point at tools
elsewhere.

Per-tool make targets are wired up so each check can be run in isolation:

```sh
make py-test           # pytest (tests/python)
make py-lint           # ruff check
make py-format-check   # ruff format --check
make py-typecheck      # mypy --strict on scripts/tmux_sessions
make py-check          # all four above
```

`make check` includes `py-check`, so a full local check is `make check`.

All Python code uses **explicit type annotations** on every function
signature; `mypy --strict` must pass. `tests/python/` mirrors the bats
suite as functions are migrated.

## Change policy

Every bug fix and every new feature MUST:

1. Update `tests/` to cover the changed behaviour, and `bats tests/` MUST pass.
2. Run shellcheck on any modified shell file and address every warning before commit. Suppress with `# shellcheck disable=SC####` only when the warning is a known false positive, and include a comment explaining why.

A change is not done until both the test suite and shellcheck are green.

- New function in `scripts/<name>.sh` → add cases to `tests/<name>.bats`.
- New external dependency invoked by the scripts → add a programmable stub under `tests/fixtures/bin/` and a loader hook in `tests/test_helper.bash`.
- Regression fixes → add a failing test first, then make it pass.

CI runs the bats suite on Linux and macOS, and shellcheck on Linux, for every push and pull request via `.github/workflows/tests.yml`.

## Architecture

The plugin is three bash scripts and one TPM entry point:

- **`tmux-sessions.tmux`** — TPM entry point. Reads `@tmux-sessions-*` tmux options, expands literal `$HOME` in option values (tmux does not shell-expand them), and binds the trigger key via `run-shell` with all config passed as environment variables.

- **`scripts/common.sh`** — Sourced by the other two scripts. Contains: fzf style flags (`FZF_INLINE`, `FZF_POPUP`), icon set selection, score tracking (`update_score`, `sort_by_score`), project discovery (`list_git_projects`), session switching (`switch_or_create_session`), and all git worktree helpers (`add_worktree`, `rename_worktree`, `pick_branch`).

- **`scripts/sessions.sh`** — The main picker. `build_entries` emits a 3-column TSV (`type<TAB>key<TAB>display`) where type is `s` (session), `p` (project), or `n` (new). `manage_sessions` runs the fzf loop and dispatches on the selected key. Ctrl-D/X/R actions are implemented as `_action_*` functions and re-invoked as subprocesses via fzf's `execute`/`execute-silent` bindings so they can mutate a shared tmpfile without blocking the picker.

- **`scripts/fetch_reload.sh`** — Background helper called by `pick_branch` (in common.sh) via fzf `execute-silent`. Runs `git fetch`, regenerates the branch list, and sends fzf a reload command over its `--listen` port. Shows a spinner in the fzf header while fetching.

## Key conventions

- All tmux targeting uses session IDs (`$N`) not names, because `/` inside session names is misread by tmux as the `session:window` separator.
- `_ICON_SEP` is derived from `_ICON_SESSION` — it is a single space when icons are non-empty, and empty string in `none` mode. Use `"${_ICON_X}${_ICON_SEP}"` for every icon+text pair rather than hardcoding spaces.
- The `FZF_INLINE` flags are used for nested pickers (rename, confirm dialogs) that run inside fzf `execute` callbacks; `FZF_POPUP` adds `--tmux` and is used for top-level pickers only.
- `format_session_name` strips configured prefixes then replaces `$HOME` with `~`. Session names may contain dots; tmux silently converts them to underscores, so comparisons use `${name//./_}`.
- Use conventional commits for commit messages
- Always check if the README.md needs to be updated after a fix or a new feature
- Never run `git push` (or any other publishing command) on your own. Commit locally when asked, then stop and let the user push.
