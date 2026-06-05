# BUILD.md

Local development guide for `tmux-worktree-sessions`. Covers the dev shell,
task runner, dependency management, test layout, and lint setup.

## Prerequisites

- [Nix](https://nixos.org/download)
- [devenv](https://devenv.sh/getting-started/)

Everything else — tmux, fzf, fd, shellcheck, git, Python, uv, ruff,
mypy, pytest — is provisioned by `devenv`. There is no other host-side
install step.

## Entering the dev shell

```sh
devenv shell
```

On entry, devenv:

1. Builds the Nix shell with the system tools listed in
   `devenv.nix → packages` (`git`, `tmux`, `fzf`, `fd`, `shellcheck`).
2. Provisions a project-local Python venv via
   `languages.python.uv.enable`.
3. Runs `uv sync` automatically (`languages.python.uv.sync.enable`),
   installing the `dev` dependency group from `pyproject.toml` into
   `.devenv/state/venv/`.

After that, `shellcheck` and the other system tools are on `PATH`
directly. Python tools (`pytest`, `ruff`, `mypy`) live in the uv
venv — invoke them via `uv run <tool>` or activate the venv yourself.

## Running checks

`devenv test` is the single entry point that runs the entire suite —
the same command CI invokes on every push and pull request via
`.github/workflows/tests.yml`.

```sh
devenv test                    # run every check (what CI runs)
```

Each check is also a standalone task wired with
`before = [ "devenv:enterTest" ]`, so individual invocations are
identical to the slice of `devenv test` that runs them:

```sh
devenv tasks run python:test           # pytest tests/python
devenv tasks run python:lint           # ruff check
devenv tasks run python:format-check   # ruff format --check
devenv tasks run python:typecheck      # mypy --strict
devenv tasks run shellcheck:lint       # shellcheck on tmux-worktree-sessions.tmux
```

For tighter feedback loops, invoke the underlying tool directly:

```sh
uv run pytest tests/python/test_score.py    # one pytest file
uv run pytest tests/python -k worktree      # filter by name
```

## Smoke-checking the plugin

```sh
TWS_PROJECTS_DIRS="$HOME/Projects" \
TWS_ICON_STYLE=nerd \
PYTHONPATH=scripts \
python3 -m tmux_worktree_sessions sessions manage
```

## Tests

- `tests/python/` — pytest suite covering the typed Python package.
  `tests/python/conftest.py` exposes shared fixtures
  (`make_repo` for tmpdir git repos, `tmux_stub` / `fzf_stub` /
  `curl_stub` for prepending programmable binaries onto PATH).
- `tests/python/_stubs/` — programmable stubs (`tmux`, `fzf`, `curl`)
  loaded by the corresponding fixtures.

When adding a feature or fixing a bug, add coverage under
`tests/python/`. Regression fixes start with a failing test.

## Linting

- **shellcheck** — runs over `tmux-worktree-sessions.tmux` (the only remaining
  shell file) via the `shellcheck:lint` task. Severity is `warning`;
  address every warning before commit. Suppress with
  `# shellcheck disable=SCxxxx` only when the warning is a known
  false positive, with a comment explaining why.
- **ruff** — runs `ruff check` (lint) and `ruff format --check`
  (format) over `scripts/` and `tests/python`. Configured in
  `pyproject.toml` under `[tool.ruff]` (line length 120,
  `target-version = py38`, rule set `E,F,I,UP,B,SIM`).
- **mypy** — runs `mypy --strict` against
  `scripts/tmux_worktree_sessions`. Every Python function signature must have
  explicit type annotations.

## Dependency management

### Python

Dev dependencies are declared in `pyproject.toml` under
`[dependency-groups].dev` (PEP 735). uv syncs that group by default
on `devenv shell` entry. Lockfile lives at `uv.lock`.

```sh
uv add --group dev <pkg>             # add a dev dependency
uv remove --group dev <pkg>          # remove one
uv sync                              # re-sync after editing pyproject.toml
uv lock --upgrade                    # refresh the lockfile
```

There are zero runtime Python dependencies — the plugin invokes the
package via `python3 -m tmux_worktree_sessions` and assumes only the standard
library at runtime.

### System tools

Edit the `packages` list in `devenv.nix`. After the change,
`devenv shell` rebuilds the Nix shell on next entry. Pin to nixpkgs
attributes (e.g. `pkgs.fd`); do not vendor binaries.

## CI

`.github/workflows/tests.yml` runs `devenv test` on
`ubuntu-latest` and `macos-latest`. The matrix uses
`cachix/install-nix-action` and `cachix/cachix-action` (cache name
`devenv`) so Nix evaluation is cached across runs.

If a check fails locally on `devenv test`, it will fail in CI too —
there is no CI-only configuration.

## Layout

```
.github/workflows/tests.yml   # CI: matrix calling `devenv test`
devenv.nix                    # packages + python.uv + tasks + enterTest
devenv.yaml                   # Nix input pinning (devenv-nixpkgs/rolling)
pyproject.toml                # PEP 735 dev deps, ruff/mypy/pytest config
uv.lock                       # uv lockfile (committed)
tmux-worktree-sessions.tmux            # TPM entry point (bash; binds the picker key)
scripts/tmux_worktree_sessions/        # typed Python package
tests/python/                 # pytest suite covering the package
tests/python/_stubs/          # programmable tmux/fzf/curl stubs
docs/python-migration.md      # migration history
```

## Conventions

- Conventional Commits for commit messages
  (`feat:`, `fix:`, `refactor:`, `test:`, `chore:`, `build:`, `docs:`).
