# BUILD.md

Local development guide for `tmux-worktree-sessions`. Covers the dev shell,
running checks, dependency management, test layout, and lint setup.

## Prerequisites

- [Nix](https://nixos.org/download) with flakes enabled
  (`experimental-features = nix-command flakes` in `nix.conf`).

Everything else — tmux, fzf, fd, shellcheck, vhs, git, Python, uv,
ruff, mypy, pytest — is provisioned by the flake. There is no other
host-side install step.

## Entering the dev shell

```sh
nix develop
```

On entry, the flake's `devShells.default`:

1. Builds the Nix shell with the system tools listed in
   `flake.nix → packages` (`git`, `tmux`, `fzf`, `fd`, `shellcheck`,
   `vhs`, `python3`, `uv`).
2. Runs `uv sync` automatically via the `shellHook`, installing the
   `dev` dependency group from `pyproject.toml` into the project-local
   `.venv/`.

After that, system tools are on `PATH` directly. Python tools
(`pytest`, `ruff`, `mypy`) live in the uv venv — invoke them via
`uv run <tool>` or activate the venv yourself.

## Running checks

`./check.sh` is the single entry point that runs the entire suite —
the same checks CI invokes on every push and pull request via
`.github/workflows/tests.yml`.

```sh
./check.sh                     # run every check (what CI runs)
```

Each check is also a one-line command, so individual invocations are
identical to the slice of `./check.sh` that runs them:

```sh
uv run pytest tests/python                                    # pytest
uv run ruff check scripts/ tests/python                       # ruff lint
uv run ruff format --check scripts/ tests/python              # ruff format check
uv run mypy scripts/tmux_worktree_sessions                    # mypy --strict
shellcheck --severity=warning tmux-worktree-sessions.tmux     # shellcheck
```

For tighter feedback loops:

```sh
uv run pytest tests/python/test_score.py    # one pytest file
uv run pytest tests/python -k worktree      # filter by name
uv run ruff format scripts/ tests/python    # apply formatting
```

## Demo

The README GIF is rendered with [vhs](https://github.com/charmbracelet/vhs)
(provided by the flake). Render and publish:

```sh
bash demo/setup.sh && vhs demo/readme.tape    # render to /tmp/tws-demo/readme.gif
bash demo/publish.sh                          # upload to the demo-assets release
```

`demo/publish.sh` requires `gh` authenticated against github.com.

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

- **shellcheck** — runs over `tmux-worktree-sessions.tmux` (the only
  remaining shell file). Severity is `warning`; address every warning
  before commit. Suppress with `# shellcheck disable=SCxxxx` only when
  the warning is a known false positive, with a comment explaining why.
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
on `nix develop` entry via the flake's `shellHook`. Lockfile lives at
`uv.lock`.

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

Edit the `packages` list in `flake.nix`. After the change, `nix
develop` rebuilds the shell on next entry. Pin to nixpkgs attributes
(e.g. `pkgs.fd`); do not vendor binaries. To bump the nixpkgs pin, run
`nix flake update` and commit `flake.lock`.

## CI

`.github/workflows/tests.yml` runs `nix develop --command ./check.sh`
on `ubuntu-latest` and `macos-latest`, so CI uses the same flake and
the same aggregator script as local dev.

If `./check.sh` fails locally, it will fail in CI too — there is no
CI-only configuration.

## Layout

```
.github/workflows/tests.yml          # CI: matrix running `nix develop --command …`
flake.nix                            # devShells.default (packages + uv-sync shellHook)
flake.lock                           # nixpkgs pin
check.sh                             # aggregator: runs every check end-to-end
pyproject.toml                       # PEP 735 dev deps, ruff/mypy/pytest config
uv.lock                              # uv lockfile (committed)
tmux-worktree-sessions.tmux          # TPM entry point (bash; binds the picker key)
scripts/tmux_worktree_sessions/      # typed Python package
tests/python/                        # pytest suite covering the package
tests/python/_stubs/                 # programmable tmux/fzf/curl stubs
docs/python-migration.md             # migration history
```

## Conventions

- Conventional Commits for commit messages
  (`feat:`, `fix:`, `refactor:`, `test:`, `chore:`, `build:`, `docs:`).
