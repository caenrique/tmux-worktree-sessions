# Contributing

Thanks for taking the time to contribute. This document covers how to
report issues, propose changes, and get a PR merged.

## Reporting issues

- **Bugs** — open an issue using the *Bug report* template. Include
  your tmux / fzf / git / Python versions, the relevant `@tws-*`
  options, and a minimal reproduction.
- **Features** — open an issue using the *Feature request* template
  before sending a PR for anything non-trivial. It's cheap to align on
  scope first.

## Development setup

The full setup lives in [BUILD.md](BUILD.md). Quick version:

```sh
devenv shell    # enter the dev shell (uv sync runs automatically)
devenv test     # run every check (what CI runs)
```

Tighter feedback loops:

```sh
uv run pytest tests/python/test_score.py    # one pytest file
uv run pytest tests/python -k worktree      # filter by name
devenv tasks run python:typecheck           # mypy --strict
devenv tasks run shellcheck:lint            # shellcheck on the .tmux file
```

## Change policy

Every bug fix and every new feature MUST:

1. **Add or update tests** under `tests/python/` covering the changed
   behaviour. `uv run pytest tests/python` must pass.
2. **Run shellcheck** on `tmux-worktree-sessions.tmux` if you touched
   it, and address every warning before commit. Suppress with
   `# shellcheck disable=SC####` only when the warning is a known
   false positive, with a comment explaining why.
3. **Pass `mypy --strict`** — every Python function signature carries
   explicit type annotations.
4. **Update `README.md`** if the change affects user-visible behaviour
   (key bindings, options, picker columns, etc.).

A change is not done until `devenv test` is green. The same command
runs in CI on Linux and macOS for every push and pull request.

Where new code lands:

- New function in `scripts/tmux_worktree_sessions/<module>.py` → add
  cases to `tests/python/test_<module>.py`.
- New external dependency invoked by the package → add a programmable
  stub under `tests/python/_stubs/` and a fixture hook in
  `tests/python/conftest.py`.
- Regression fixes → add a failing test first, then make it pass.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org):
`feat:`, `fix:`, `refactor:`, `test:`, `chore:`, `build:`, `docs:`.
Keep the subject under ~70 characters; put the *why* in the body.

## Pull requests

- Open against `main`.
- Fill in the PR template — Summary and Test plan are both useful even
  for small PRs.
- Keep PRs focused. One concern per PR makes review easier and bisect
  cleaner if a regression slips through.
- CI must be green. If a check is flaking, say so in the PR rather
  than re-running blindly.

## Code conventions

A few project-specific rules worth calling out — the rest is whatever
`ruff check` and `mypy --strict` enforce:

- All tmux targeting uses session IDs (`$N`), not session names —
  `/` inside a name is misread by tmux as the `session:window`
  separator.
- The Python package is split into pure modules (`score.py`,
  `text.py`, `git.py`, `tmux.py`, …) and a CLI dispatcher
  (`__main__.py`). Pure functions take all inputs as explicit,
  often keyword-only, parameters — no module-level globals or
  ambient env reads.
- The `_internal` argparse subcommand is hidden from `--help` and is
  only ever invoked by fzf binds the picker spawns into itself. The
  user-facing CLI surface is `sessions manage`,
  `sessions display-name`, and `worktree manage`.

## Releases

Maintainers cut releases — contributors don't need to bump versions or
edit changelogs as part of a PR.
