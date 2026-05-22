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
- Every Python module under `scripts/tmux_sessions/` splits into a
  **pure layer** (no `os.environ`, `sys.stdin`/`stdout`/`argv`,
  `argparse`, wall-clock reads, or filesystem reads/writes for config
  or state) and a **CLI layer** in `scripts/tmux_sessions/__main__.py`
  that owns those concerns and calls into the pure layer with explicit
  parameters. Subprocess wrappers (`git`, `tmux`, `fzf`) and filesystem
  walks (`os.walk` for project discovery) belong in the pure layer when
  every input is an explicit parameter — they are external state queries,
  not CLI concerns. File I/O may live in the pure layer **only** when
  streaming gives a measurable performance/memory win that affects the
  plugin's interactivity, justified in a code comment at the call site.
  This rule applies to Python code only; the bash shims keep their own
  argv/env handling.
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

### Step 2 — Move `sort_by_score.py` into the package `[x]`

- Move `scripts/sort_by_score.py` to `scripts/tmux_sessions/score.py`.
- Expose `score sort` as a subcommand of the dispatcher.
- Update `sort_by_score()` in `scripts/common.sh` to call
  `python3 -m tmux_sessions score sort "$@"`.
- Add pytest cases mirroring the four bats `sort_by_score` cases.
- Keep the bats `sort_by_score` cases unchanged; they exercise the bash
  shim end-to-end.

**Acceptance:** `make check` green. `python3 -m tmux_sessions score sort`
works as a drop-in replacement for the old script path.

### Step 2.5 — Establish CLI / pure logic separation `[x]`

- Refactor `scripts/tmux_sessions/score.py` to be a pure module:
  `parse_score_table(text: str) -> list[tuple[str, float, float]]`,
  `current_scores(entries, *, now, half_life_secs) -> dict[str, float]`,
  `sort_rows(lines, *, boost_path, scores, path_boost) -> list[str]`,
  `common_prefix_len(a, b) -> int`. No `os.environ`, `sys.*`,
  `time.time()`, or `open()`. All keyword arguments after `*` are
  required — no `T | None = None` env-fallback parameters.
- Move the CLI layer into `scripts/tmux_sessions/__main__.py`:
  argparse subparsers with `set_defaults(handler=cmd_<group>_<verb>)`,
  one `cmd_score_sort` handler that reads env, opens the score file,
  reads stdin, calls the pure functions, and writes stdout.
- Rewrite `tests/python/test_score.py` as **pure** tests against the new
  functions (no env, no file I/O, no subprocess). Add
  `tests/python/test_score_cli.py` covering the CLI handler via
  `main(["score", "sort", ...])` with `monkeypatch` for env / stdin /
  stdout and a real `tmp_path` score file.
- Bash shim (`sort_by_score()` in `common.sh`) is unchanged: still
  `python3 -m tmux_sessions score sort "$@"`. Bats `sort_by_score`
  cases continue to exercise the round-trip end-to-end.

**Acceptance:** `make check` green. The pure / CLI split establishes
the shape every later migration step inherits.

---

## Phase 1 — Pure utilities

These are stateless string functions. Each step adds a pure
implementation in a domain module, registers a CLI subcommand in
`__main__.py`, and replaces the bash function body with a one-line
dispatcher call. Tests gain parallel pytest coverage; bats coverage is
unchanged.

### Step 3 — `strip_ansi` `[x]`

- Pure: `text.strip_ansi(s: str) -> str` in
  `scripts/tmux_sessions/text.py`.
- CLI: `cmd_text_strip_ansi` registers `text strip-ansi`, reads stdin
  (or argv), writes stdout.
- Replace `strip_ansi()` in `common.sh` with a dispatcher call.
- Add `tests/python/test_text.py` covering the same cases as bats.

### Step 4 — `sanitize_name` `[x]`

- Pure: `text.sanitize_name(s: str) -> str`.
- CLI: `cmd_text_sanitize_name` registers `text sanitize-name`.
- Replace bash function. Pytest parity with bats cases.

### Step 5 — `branch_to_dir` `[x]`

- Pure: `git.branch_to_dir(name: str) -> str` in a new
  `scripts/tmux_sessions/git.py` (seed for git helpers).
- CLI: `cmd_git_branch_to_dir` registers `git branch-to-dir`.
- Replace bash. Pytest parity.

### Step 6 — `format_session_name` `[x]`

- Pure: `text.format_session_name(path: str, *, home: str,
  strip_prefixes: list[str]) -> str`. Both kwargs required — no env
  fallbacks in the pure layer.
- CLI: `cmd_text_format_session_name` reads
  `TMUX_SESSIONS_STRIP_PREFIXES` and `$HOME` from env, calls the pure
  function. Registers `text format-session-name`.
- Replace bash. Pytest parity in pure tests including:
  longest-prefix-strip, `$HOME`→`~`, no-match fallthrough.

### Step 7 — Score writer `update_score` `[x]`

- Pure: `score.merge_score(entries: list[tuple[str, float, float]], *,
  name: str, now: float, half_life_secs: float) ->
  list[tuple[str, float, float]]`. Returns the rewritten table; no file
  I/O.
- CLI: `cmd_score_update` reads `SCORE_FILE` and
  `TMUX_SESSIONS_SCORE_HALF_LIFE` from env, parses the file via
  `parse_score_table`, calls `merge_score`, writes back atomically
  (tmpfile + rename, parent dir auto-created). Registers `score update`.
- Pytest cases: pure tests for `merge_score` (fresh entry, in-place
  update with decay, multiple existing entries preserved). CLI tests
  for the file-write side: fresh file, parent dir auto-created.

---

## Phase 2 — Git helpers (subprocess wrappers)

`scripts/tmux_sessions/git.py` accumulates here. Each function shells
out to real `git` exactly as the bash version does, but with structured
return types (`dataclass`es, `list[Branch]`, etc.). Subprocess calls
take `repo: Path` as an explicit parameter, so they live in the pure
layer; CLI handlers in `__main__.py` are one-line passthroughs.

### Step 8 — `_resolve_remote` and `get_default_branch` `[x]`

- Pure: `git.resolve_remote(repo: Path) -> str | None` and
  `git.default_branch(repo: Path) -> str | None` — both shell out to
  real `git`.
- CLI: `cmd_git_resolve_remote`, `cmd_git_default_branch` (one-line
  passthroughs).
- Replace the two bash helpers. Pytest parity using real tmpdir repos
  (the same `mkrepo` strategy as bats).

### Step 9 — `list_branches` `[x]`

- Pure: `git.list_branches(repo: Path) -> list[str]`.
- CLI: `cmd_git_list_branches` (passthrough).
- Replace bash. Pytest parity.

### Step 10 — `list_worktrees` `[x]`

- Pure: `git.list_worktrees(repo: Path) -> list[Worktree]` (dataclass
  with `path: Path`, `branch: str`).
- CLI: `cmd_git_list_worktrees` serialises the dataclass list to TSV
  for shell consumers.
- Replace bash. Pytest parity.

### Step 11 — `add_worktree` `[x]`

- Pure: `git.add_worktree(repo: Path, container: Path, branch:
  str | None, new_name: str | None) -> Path`.
- CLI: `cmd_git_add_worktree` (passthrough).
- Replace bash. Pytest parity covering the four bash branches (new
  branch, existing local, already checked out, remote-only tracking).

### Step 12 — `rename_worktree` `[x]`

- Pure: `git.rename_worktree(...)` — does the git/move/repair logic.
- CLI: `cmd_git_rename_worktree` (passthrough); the interactive fzf
  prompt stays in bash for now and passes the chosen new name in. (The
  fzf piece moves to Python in Phase 3.)
- Replace the post-prompt half of the bash function. Pytest parity for
  the git/move/repair logic.

### Step 13 — `_fetch_is_stale` `[x]`

- Pure: `git.fetch_is_stale(mtime: float | None, *, now: float,
  window_secs: int = 900) -> bool`. The pure function takes the mtime
  directly so it stays trivially testable; missing FETCH_HEAD is
  encoded as `mtime is None`.
- CLI: `cmd_git_fetch_is_stale` resolves the FETCH_HEAD path, calls
  `Path.stat().st_mtime` (handling `FileNotFoundError` → `None`), and
  passes the result in along with `time.time()`.
- No GNU/BSD `stat` divergence. Pytest parity (missing FETCH_HEAD,
  fresh, > 15 min old) covered in pure tests.

### Step 14 — `list_git_projects` `[x]`

- Pure: `git.list_git_projects(roots: list[Path], *, max_depth: int) ->
  list[Path]` shells out to `fd`. `fd` becomes a hard runtime
  dependency of the plugin (no Python `os.walk` fallback) so we keep
  one fast, well-tested traversal across bash and Python and we don't
  carry a slower second implementation.
- CLI: `cmd_git_list_projects` reads `TMUX_SESSIONS_PROJECTS_DIRS` and
  `TMUX_SESSIONS_MAX_DEPTH` from env, expands `~`, calls the pure
  function, prints TSV. README and CI install `fd` unconditionally.
- Replace bash. Pytest parity. Update bats `list_projects` test if the
  output format changes meaningfully (it should not).

---

## Phase 3 — tmux + interactive helpers

### Step 15 — `get_session_id`, `switch_or_create_session` `[x]`

- Pure: `tmux.session_id(name: str) -> str | None` and
  `tmux.switch_or_create(path: Path, name: str) -> None` in
  `scripts/tmux_sessions/tmux.py`. Both shell out to real `tmux` via
  `subprocess.run`.
- CLI: `cmd_tmux_session_id`, `cmd_tmux_switch_or_create`
  (passthroughs).
- Replace bash. Pytest parity using the existing tmux stub
  (reuse `tests/fixtures/bin/tmux` from a Python fixture that prepends
  it to `PATH`).

### Step 16 — `_gen_branch_picker_entries` `[ ]`

- Pure: `picker.gen_branch_picker_entries(repo: Path, *, icons:
  IconSet) -> Iterator[str]` in `scripts/tmux_sessions/picker.py`.
- CLI: `cmd_picker_branch_entries` reads `TMUX_SESSIONS_ICON_STYLE`
  from env, builds the `IconSet`, calls the pure function.
- Replace bash. Pytest parity.

### Step 17 — `pick_branch` `[ ]`

- Pure: `picker.pick_branch(repo: Path, *, icons: IconSet) ->
  BranchChoice` — spawns fzf via `subprocess.Popen` with the same
  flags; background fetch+reload via `concurrent.futures` or
  `multiprocessing`. Subprocess calls are external state queries, so
  this stays in the pure layer.
- CLI: `cmd_picker_pick_branch` (passthrough; resolves icons from env).
- Replace bash. Pytest parity using the fzf stub (the bats stub
  strategy ports cleanly).

### Step 18 — `fetch_reload.sh` `[ ]`

- Pure: `fetch_reload.fetch_and_reload(repo: Path, tmpfile: Path, port:
  int, header_base: str) -> None` in
  `scripts/tmux_sessions/fetch_reload.py`. Spinner via a thread;
  `requests`-free (use `urllib.request` to keep the package
  zero-dependency at runtime).
- CLI: `cmd_fetch_reload` (passthrough).
- Replace `scripts/fetch_reload.sh` with a one-line shim that calls
  `python3 -m tmux_sessions fetch-reload "$@"`. Once Phase 4 lands,
  `pick_branch` invokes the Python entry point directly and the shim
  is deleted.
- Pytest parity for the four bats fetch_reload cases.

---

## Phase 4 — Sessions orchestration

### Step 19 — `list_projects` (sessions.sh) and `_is_orphaned_worktree_dir` `[ ]`

- Pure: `sessions.list_projects(...)` and
  `sessions.is_orphaned_worktree(path: Path, *, container: Path) ->
  bool` in `scripts/tmux_sessions/sessions.py`.
- CLI: `cmd_sessions_list_projects`,
  `cmd_sessions_is_orphaned_worktree` (passthroughs).
- Replace bash. Pytest parity.

### Step 20 — `_action_ctrl_x`, `_action_ctrl_r`, `_action_ctrl_d` `[ ]`

- Migrate one action per substep (so this is really three commits
  inside Step 20: 20a, 20b, 20c).
- Pure: three action implementations in `sessions.py`, each taking the
  tmpfile path and the selected entry as explicit parameters.
- CLI: one `cmd_sessions_action_<name>` per action.
- Each action is replaced atomically: bash dispatcher in `sessions.sh`
  calls `python3 -m tmux_sessions sessions action <name> ...`.
- The shared tmpfile state-machine logic stays correct because the
  Python action mutates the same tmpfile.
- Pytest parity per action.

### Step 21 — `build_entries` `[ ]`

- Pure: `sessions.build_entries(...)` — the 3-column TSV builder. Calls
  into Phase 1–3 pure helpers directly (no shellout) so the inner
  loops avoid spawning Python repeatedly.
- CLI: `cmd_sessions_build_entries` (passthrough).
- Replace bash. Pytest parity.

### Step 22 — `manage_sessions` `[ ]`

- Pure: `sessions.manage_sessions(...)` — the main fzf loop. Largest
  single step; dispatches on the chosen key and calls into the
  migrated helpers.
- CLI: `cmd_sessions_manage` is a one-line passthrough.
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
