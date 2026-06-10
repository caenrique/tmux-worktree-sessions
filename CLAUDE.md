# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development

See [BUILD.md](BUILD.md) for the full dev setup: `devenv shell`,
`devenv test`, individual task names, dependency management, lint
configuration, and test layout. Quick reference:

```sh
devenv shell                              # enter dev shell (uv sync runs automatically)
devenv test                               # run every check (what CI runs)
devenv tasks run python:test              # one task at a time
uv run pytest tests/python/test_score.py  # one pytest file
uv run pytest tests/python -k worktree    # filter by name
```

The plugin's logic lives in a typed Python package under
`scripts/tmux_worktree_sessions/`. Python ≥ 3.8 is required; all Python code
uses **explicit type annotations** on every function signature, and
`mypy --strict` must pass. The bash side is now just `tmux-worktree-sessions.tmux`,
the TPM hook that reads tmux options and dispatches to the Python entry
point.

## Change policy

Every bug fix and every new feature MUST:

1. Update `tests/python/` to cover the changed behaviour, and `uv run pytest tests/python` MUST pass.
2. Run shellcheck on `tmux-worktree-sessions.tmux` if you touched it, and address every warning before commit. Suppress with `# shellcheck disable=SC####` only when the warning is a known false positive, and include a comment explaining why.

A change is not done until `devenv test` is green.

- New function in `scripts/tmux_worktree_sessions/<module>.py` → add cases to `tests/python/test_<module>.py`.
- New external dependency invoked by the package → add a programmable stub under `tests/python/_stubs/` and a fixture hook in `tests/python/conftest.py`.
- Regression fixes → add a failing test first, then make it pass.

CI runs `devenv test` on Linux and macOS for every push and pull request via `.github/workflows/tests.yml` — that runs the Python checks and shellcheck together.

## Architecture

The plugin is one bash entry point and a Python package:

- **`tmux-worktree-sessions.tmux`** — TPM entry point. Reads `@tws-*` tmux options, expands literal `$HOME` in option values (tmux does not shell-expand them), and binds the trigger key via `run-shell` with all config passed as environment variables. The bound command invokes `python3 -m tmux_worktree_sessions sessions manage` with `PYTHONPATH` pointing at the plugin's `scripts/` directory.

- **`scripts/tmux_worktree_sessions/`** — Typed Python package with the pure / CLI split called out in `docs/python-migration.md`:
  - `__main__.py` — argparse dispatcher split into two clearly separated tiers: user-facing subcommands (`sessions manage`, `sessions display-name`, `worktree manage`) and an `_internal` subcommand group hidden from `--help` (`_internal session-action <key>`, `_internal fetch-reload`). The internal hatches are fzf-bind-only — the picker shelling back into itself — and may be renamed freely as long as the `picker.py` call sites move in lockstep.
  - `score.py`, `text.py`, `git.py`, `tmux.py`, `picker.py`, `fetch_reload.py`, `sessions.py` — pure modules; functions take all inputs as explicit (often keyword-only) parameters.
  - `sessions.build_entries` emits the 4-column TSV (`type<TAB>key<TAB>search<TAB>display`) the picker consumes. `cmd_sessions_manage` runs the fzf loop and dispatches on the selected key. The `picker.picker_action_ctrl_x|r|d` family handles Ctrl-D/X/R by mutating the shared tmpfile in place; fzf binds invoke them via `_internal session-action <key>` so the picker stays open and just calls `reload(cat ...)` to pick up the new rows.
  - `fetch_reload.fetch_and_reload` is the background helper called from the branch picker via fzf `execute-silent` (through `_internal fetch-reload`): runs `git fetch`, regenerates the branch list, and sends fzf a reload command over its `--listen` port.

## Key conventions

- All tmux targeting uses session IDs (`$N`) not names, because `/` inside session names is misread by tmux as the `session:window` separator.
- `_ICON_SEP` is derived from `_ICON_SESSION` — it is a single space when icons are non-empty, and empty string in `none` mode. Use `"${_ICON_X}${_ICON_SEP}"` for every icon+text pair rather than hardcoding spaces.
- The `FZF_INLINE` flags are used for nested pickers (rename, confirm dialogs) that run inside fzf `execute` callbacks; `FZF_POPUP` adds `--tmux` and is used for top-level pickers only.
- `format_session_name` strips configured prefixes then replaces `$HOME` with `~`. Session names may contain dots; tmux silently converts them to underscores, so comparisons use `${name//./_}`.
- Use conventional commits for commit messages
- Always check if the README.md needs to be updated after a fix or a new feature
- Never run `git push` (or any other publishing command) on your own. Commit locally when asked, then stop and let the user push.
