# Python migration plan

Goal: migrate the bash scripts under `scripts/` to a typed Python package, in
small steps that each leave the plugin fully functional and the test suite
green. Bash and Python coexist for the entire migration; the final step
removes the last bash file once parity is reached.

## Ground rules

- Each step is independently shippable. After every step:
  - `make check` must pass (bats + shellcheck).
  - Any new Python checks (`make py-check`) must pass.
  - The plugin must still work end-to-end (manual smoke check on tmux).
- All Python code uses **explicit type annotations** on every function
  signature and on non-obvious local variables. `mypy --strict` must pass.
- Bash and Python interoperate through a single CLI dispatcher
  (`python3 -m tmux_sessions <command> [args...]`). Each migrated bash
  function is replaced by a thin shim that calls the dispatcher.
- Existing **bats tests are kept and must continue to pass** through the
  whole migration. Bash shims are tested by the existing bats cases; new
  Python implementations get parallel pytest cases. Bats tests are only
  retired in the final step, once 100% pytest parity is reached.
- Pure-bash gets to stay only where it is genuinely simpler — the TPM
  entry point (`tmux-sessions.tmux`) and one-line subprocess wrappers if
  they survive the cost/benefit check at step 24.
- Each step lands as a single conventional commit (`refactor:`, `feat:`,
  `test:`, `chore:` as appropriate) so the migration is easy to bisect.

## Progress legend

- `[ ]` not started
- `[~]` in progress
- `[x]` done

---

## Phase 0 — Tooling

### Step 1 — Set up Python project tooling `[x]`

- Add `pyproject.toml` at repo root declaring:
  - Build/runtime: `requires-python = ">=3.8"`, package layout pointing at
    `scripts/tmux_sessions/`.
  - Dev tools: `pytest`, `pytest-mock`, `ruff`, `mypy`.
  - `[tool.ruff]` config: line length 100, target py38, enable `E,F,I,UP,B,SIM`.
  - `[tool.mypy]` strict mode (`strict = true`), explicit package bases.
  - `[tool.pytest.ini_options]` test path `tests/python`.
- Add `scripts/tmux_sessions/__init__.py` (empty).
- Add `scripts/tmux_sessions/__main__.py` with an argparse-based dispatcher
  that prints usage and exits 1 (commands get registered in later steps).
- Add `tests/python/__init__.py` and `tests/python/test_smoke.py` with a
  trivial `test_dispatcher_prints_usage` case.
- Update `Makefile`:
  - `py-test`: `python3 -m pytest tests/python`
  - `py-lint`: `ruff check scripts/ tests/python`
  - `py-format-check`: `ruff format --check scripts/ tests/python`
  - `py-typecheck`: `mypy scripts/tmux_sessions`
  - `py-check`: depends on the four above.
  - `check`: extend to depend on `py-check`.
- Update `.github/workflows/tests.yml` to install Python deps and run
  `make py-check` on both Linux and macOS.
- Update `CLAUDE.md` and `README.md` Development section with Python
  setup instructions.

**Acceptance:** `make check` passes (bats + shellcheck + Python tooling).
The dispatcher exists but does nothing useful yet.

### Step 2 — Move `sort_by_score.py` into the package `[ ]`

- Move `scripts/sort_by_score.py` to `scripts/tmux_sessions/score.py`.
- Expose `score sort` as a subcommand of the dispatcher.
- Update `sort_by_score()` in `scripts/common.sh` to call
  `python3 -m tmux_sessions score sort "$@"`.
- Add pytest cases mirroring the four bats `sort_by_score` cases.
- Keep the bats `sort_by_score` cases unchanged; they exercise the bash
  shim end-to-end.

**Acceptance:** `make check` green. `python3 -m tmux_sessions score sort`
works as a drop-in replacement for the old script path.

---

## Phase 1 — Pure utilities

These are stateless string functions. Each step adds the Python
implementation, registers a CLI subcommand, and replaces the bash
function body with a one-line dispatcher call. Tests gain parallel
pytest coverage; bats coverage is unchanged.

### Step 3 — `strip_ansi` `[ ]`

- Add `scripts/tmux_sessions/text.py` with `strip_ansi(s: str) -> str`.
- Register `text strip-ansi` subcommand.
- Replace `strip_ansi()` in `common.sh` with a dispatcher call.
- Add `tests/python/test_text.py` covering the same cases as bats.

### Step 4 — `sanitize_name` `[ ]`

- Add `sanitize_name(s: str) -> str` to `text.py`.
- Register `text sanitize-name`.
- Replace bash function. Pytest parity with bats cases.

### Step 5 — `branch_to_dir` `[ ]`

- Add `branch_to_dir(name: str) -> str` to a new
  `scripts/tmux_sessions/git.py` (this is the seed for git helpers).
- Register `git branch-to-dir`. Replace bash. Pytest parity.

### Step 6 — `format_session_name` `[ ]`

- Add `format_session_name(path: str, *, home: str | None = None,
  strip_prefixes: list[str] | None = None) -> str` to
  `scripts/tmux_sessions/text.py`.
- Read `TMUX_SESSIONS_STRIP_PREFIXES` and `$HOME` from env when
  arguments are omitted (mirroring the bash function).
- Register `text format-session-name`. Replace bash. Pytest parity
  including: longest-prefix-strip, `$HOME`→`~`, no-match fallthrough.

### Step 7 — Score writer `update_score` `[ ]`

- Add `update_score(name: str, score_file: Path, half_life_days: float,
  now: float | None = None) -> None` to `score.py`.
- Register `score update`. Replace the bash awk pipeline.
- Pytest cases: fresh file, in-place update with decay, parent dir
  auto-created, simultaneous concurrent writes.

---

## Phase 2 — Git helpers (subprocess wrappers)

`scripts/tmux_sessions/git.py` accumulates here. Each function shells out
to real `git` exactly as the bash version does, but with structured
return types (`dataclass`es, `list[Branch]`, etc.).

### Step 8 — `_resolve_remote` and `get_default_branch` `[ ]`

- Add `resolve_remote(repo: Path) -> str | None` and
  `default_branch(repo: Path) -> str | None`.
- Register `git resolve-remote`, `git default-branch`.
- Replace the two bash helpers. Pytest parity using real tmpdir repos
  (the same `mkrepo` strategy as bats).

### Step 9 — `list_branches` `[ ]`

- Add `list_branches(repo: Path) -> list[str]`.
- Register `git list-branches`. Replace bash. Pytest parity.

### Step 10 — `list_worktrees` `[ ]`

- Add `list_worktrees(repo: Path) -> list[Worktree]` (dataclass with
  `path: Path`, `branch: str`).
- Register `git list-worktrees` (TSV output for shell consumers).
- Replace bash. Pytest parity.

### Step 11 — `add_worktree` `[ ]`

- Add `add_worktree(repo: Path, container: Path, branch: str | None,
  new_name: str | None) -> Path`.
- Register `git add-worktree`. Replace bash. Pytest parity covering the
  four bash branches (new branch, existing local, already checked out,
  remote-only tracking).

### Step 12 — `rename_worktree` `[ ]`

- Add `rename_worktree(...)`.
- This one has interactive fzf inside the bash version. Migrate the
  pure git/move/repair logic to Python; keep the fzf prompt in bash and
  pass the chosen new name into the Python helper. (The fzf piece moves
  to Python in Phase 3.)
- Register `git rename-worktree`. Replace the post-prompt half of the
  bash function. Pytest parity for the git/move/repair logic.

### Step 13 — `_fetch_is_stale` `[ ]`

- Add `fetch_is_stale(repo: Path, window_secs: int = 900) -> bool`.
- Use `Path.stat().st_mtime` directly — no GNU/BSD `stat` divergence.
- Register `git fetch-is-stale`. Replace bash. Pytest parity (missing
  FETCH_HEAD, fresh, > 15 min old).

### Step 14 — `list_git_projects` `[ ]`

- Add `list_git_projects(roots: list[Path], max_depth: int) ->
  list[Project]` using `os.walk` (no fd/find shellout, simpler in
  Python). Drop the fd/find branching entirely.
- Register `git list-projects`. Replace bash. Pytest parity.
- Update bats `list_projects` test if the output format changes
  meaningfully (it should not).

---

## Phase 3 — tmux + interactive helpers

### Step 15 — `get_session_id`, `switch_or_create_session` `[ ]`

- Add `scripts/tmux_sessions/tmux.py` with these helpers, calling real
  `tmux` via `subprocess.run`.
- Register `tmux session-id`, `tmux switch-or-create`.
- Replace bash. Pytest parity using the existing tmux stub
  (reuse `tests/fixtures/bin/tmux` from a Python fixture that prepends
  it to `PATH`).

### Step 16 — `_gen_branch_picker_entries` `[ ]`

- Add `gen_branch_picker_entries(repo: Path, icon_set: str) ->
  Iterator[str]` to `scripts/tmux_sessions/picker.py`.
- Register `picker branch-entries`. Replace bash. Pytest parity.

### Step 17 — `pick_branch` `[ ]`

- Add `pick_branch(repo: Path) -> BranchChoice` to `picker.py`.
- Spawn fzf via `subprocess.Popen` with the same flags. Background
  fetch+reload via `concurrent.futures` or `multiprocessing`.
- Register `picker pick-branch`. Replace bash. Pytest parity using the
  fzf stub (the bats stub strategy ports cleanly).

### Step 18 — `fetch_reload.sh` `[ ]`

- Move logic to `scripts/tmux_sessions/fetch_reload.py`. Spinner via
  a thread or async task; `requests`-free (use `urllib.request` to keep
  the package zero-dependency at runtime).
- Replace `scripts/fetch_reload.sh` with a one-line shim that calls
  `python3 -m tmux_sessions fetch-reload "$@"`. Once Phase 4 lands,
  pick_branch invokes the Python entry point directly and the shim
  is deleted.
- Pytest parity for the four bats fetch_reload cases.

---

## Phase 4 — Sessions orchestration

### Step 19 — `list_projects` (sessions.sh) and `_is_orphaned_worktree_dir` `[ ]`

- Move both to `scripts/tmux_sessions/sessions.py`.
- Register `sessions list-projects`, `sessions is-orphaned-worktree`.
- Replace bash. Pytest parity.

### Step 20 — `_action_ctrl_x`, `_action_ctrl_r`, `_action_ctrl_d` `[ ]`

- Migrate one action per substep (so this is really three commits
  inside Step 20: 20a, 20b, 20c).
- Each action is replaced atomically: bash dispatcher in `sessions.sh`
  calls `python3 -m tmux_sessions sessions action <name> ...`.
- The shared tmpfile state-machine logic stays correct because the
  Python action mutates the same tmpfile.
- Pytest parity per action.

### Step 21 — `build_entries` `[ ]`

- Migrate the 3-column TSV builder to Python. Calls into Phase 1–3
  helpers directly (no shellout) so the inner loops avoid spawning
  Python repeatedly.
- Register `sessions build-entries`. Replace bash. Pytest parity.

### Step 22 — `manage_sessions` `[ ]`

- Migrate the main fzf loop. This is the largest single step; the
  function dispatches on the chosen key and calls into the migrated
  helpers.
- After this step, `scripts/sessions.sh` is reduced to a one-line
  shim: `exec python3 -m tmux_sessions sessions manage`.

---

## Phase 5 — Cleanup

### Step 23 — Collapse the bash shims `[ ]`

- Delete `scripts/common.sh`, `scripts/sessions.sh`, `scripts/fetch_reload.sh`
  (they are now all one-liner shims).
- Update `tmux-sessions.tmux` to call
  `python3 -m tmux_sessions sessions manage` directly.
- The `.tmux` file stays bash — it is one TPM hook and `run-shell`
  invocation, simpler in bash than reimplementing tmux option parsing.
- Drop shellcheck from `make check` for the deleted files; keep it
  scoped to `tmux-sessions.tmux` (and any leftover `.bash` test
  helpers).

### Step 24 — Retire bats tests `[ ]`

- Verify pytest covers every bats case (one-to-one map produced as a
  table in this PR's description).
- Delete `tests/*.bats`, `tests/test_helper.bash`, `tests/helpers/`,
  `tests/fixtures/bin/`. Replace with their Python equivalents under
  `tests/python/`.
- Update `Makefile`: `make test` becomes `make py-test`. Drop bats
  install instructions from `CLAUDE.md` and `README.md`.
- Update CI to drop bats install.

### Step 25 — Final polish `[ ]`

- Add a `pyproject.toml` console script entry (`tmux-sessions = ...`)
  and document it in the README so users can invoke it directly when
  debugging.
- Run `mypy --strict` one more time across the whole tree; address any
  remaining `Any` leaks.
- Tag the release commit `v1.0-python`.

---

## Open questions (decide before Step 1)

- **Distribution:** users currently `git clone` the plugin via TPM. Do
  we ship a vendored `pyproject.toml`-based install, or just rely on
  the system Python with no third-party runtime deps? **Default plan:
  zero runtime deps**, dev deps only. Revisit if any helper genuinely
  benefits from a library.
- **Minimum Python version:** the existing `sort_by_score.py` already
  declares 3.8 (in `README.md`); keeping that bound. Bumping to 3.10+
  would let us drop `from __future__ import annotations` and
  `typing.Optional`, which is nice but not blocking — defer.
- **Subprocess vs in-process for pytest:** pure functions are tested
  in-process; CLI subcommands are tested by invoking
  `python3 -m tmux_sessions ...` via `subprocess.run` so the parity
  with the bash shim is observable. Both styles coexist in
  `tests/python/`.
