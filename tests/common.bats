# Tests for scripts/common.sh

load 'test_helper'

setup() {
  reset_plugin_env
  install_stubs
}

# ── strip_ansi ────────────────────────────────────────────────────────────────

@test "strip_ansi removes a single SGR escape" {
  source_common
  run strip_ansi $'\033[31mhello\033[0m'
  assert_success
  assert_output "hello"
}

@test "strip_ansi removes multiple escapes preserving inner text" {
  source_common
  run strip_ansi $'\033[1;38;2;100;200;50mfoo\033[0m \033[33mbar\033[0m'
  assert_success
  assert_output "foo bar"
}

@test "strip_ansi is a no-op for plain text" {
  source_common
  run strip_ansi "plain text 123"
  assert_success
  assert_output "plain text 123"
}

# ── sanitize_name ────────────────────────────────────────────────────────────

@test "sanitize_name trims leading/trailing whitespace" {
  source_common
  run sanitize_name "   hello   "
  assert_success
  assert_output "hello"
}

@test "sanitize_name replaces internal spaces with dashes" {
  source_common
  run sanitize_name "my new branch"
  assert_success
  assert_output "my-new-branch"
}

@test "sanitize_name on empty input returns empty" {
  source_common
  run sanitize_name ""
  assert_success
  assert_output ""
}

@test "sanitize_name on all-whitespace returns empty" {
  source_common
  run sanitize_name "      "
  assert_success
  assert_output ""
}

# ── format_session_name ──────────────────────────────────────────────────────

@test "format_session_name with no prefix replaces \$HOME with ~" {
  source_common
  run format_session_name "$HOME/Projects/foo"
  assert_success
  assert_output "~/Projects/foo"
}

@test "format_session_name strips a configured prefix" {
  source_common
  export TMUX_SESSIONS_STRIP_PREFIXES="$HOME/Projects"
  run format_session_name "$HOME/Projects/github.com/org/repo"
  assert_success
  assert_output "github.com/org/repo"
}

@test "format_session_name uses first listed prefix that matches (longest-first ordering)" {
  source_common
  export TMUX_SESSIONS_STRIP_PREFIXES="$HOME/Projects/github.com $HOME/Projects"
  run format_session_name "$HOME/Projects/github.com/org/repo"
  assert_success
  assert_output "org/repo"
}

@test "format_session_name expands literal \$HOME inside a configured prefix" {
  source_common
  export TMUX_SESSIONS_STRIP_PREFIXES='~/Projects'
  run format_session_name "$HOME/Projects/foo"
  assert_success
  assert_output "foo"
}

@test "format_session_name with no matching prefix falls back to ~ substitution" {
  TMUX_SESSIONS_STRIP_PREFIXES="/nonexistent" source_common
  run format_session_name "$HOME/anywhere"
  assert_success
  assert_output "~/anywhere"
}

# ── get_session_id ───────────────────────────────────────────────────────────

@test "get_session_id returns the matching session id" {
  source_common
  stub_tmux_sessions $'alpha\t$1\t/tmp/alpha\nbeta\t$2\t/tmp/beta'
  run get_session_id "beta"
  assert_success
  assert_output '$2'
}

@test "get_session_id returns empty when no session matches" {
  source_common
  stub_tmux_sessions $'alpha\t$1\t/tmp/alpha'
  run get_session_id "ghost"
  assert_success
  assert_output ""
}

@test "get_session_id treats dot in query as underscore (tmux normalisation)" {
  source_common
  stub_tmux_sessions $'foo_bar\t$7\t/tmp/foo'
  run get_session_id "foo.bar"
  assert_success
  assert_output '$7'
}

# ── update_score ─────────────────────────────────────────────────────────────

@test "update_score creates the score file with a fresh entry" {
  source_common
  update_score "alpha"
  run cat "$TMUX_SESSIONS_SCORES_FILE"
  assert_success
  [[ "${lines[0]}" == $'alpha\t1\t'* ]]
}

@test "update_score adds a row without disturbing existing rows" {
  source_common
  seed_score_file "alpha" 5 "$(date +%s)"
  update_score "beta"
  run cat "$TMUX_SESSIONS_SCORES_FILE"
  assert_success
  assert_line --partial "alpha"
  assert_line --partial "beta"
}

@test "update_score decays an existing entry by ~half over one half-life" {
  TMUX_SESSIONS_SCORE_HALF_LIFE=14 source_common
  local now hl_seconds_ago
  now=$(date +%s)
  hl_seconds_ago=$(( now - 14 * 24 * 3600 ))
  seed_score_file "alpha" 4 "$hl_seconds_ago"
  update_score "alpha"
  run awk -F'\t' '$1=="alpha"{print $2}' "$TMUX_SESSIONS_SCORES_FILE"
  assert_success
  # 4 * 0.5 + 1 = 3.0 (allow ±0.05 for floating math).
  awk -v v="$output" 'BEGIN { exit (v >= 2.95 && v <= 3.05) ? 0 : 1 }'
}

@test "update_score creates parent directory when missing" {
  TMUX_SESSIONS_SCORES_FILE="$BATS_TEST_TMPDIR/nested/dir/scores.tsv" source_common
  update_score "alpha"
  [[ -f "$BATS_TEST_TMPDIR/nested/dir/scores.tsv" ]]
}

# ── sort_by_score ────────────────────────────────────────────────────────────

@test "sort_by_score: higher score first" {
  seed_score_file "alpha" 1 "$(date +%s)"
  seed_score_file "beta"  9 "$(date +%s)"
  run bash -c '
    source "'"$PLUGIN_ROOT"'/scripts/common.sh"
    printf "alpha\t/p/a\t/p/a\nbeta\t/p/b\t/p/b\n" | sort_by_score ""
  '
  assert_success
  [[ "${lines[0]}" == beta* ]]
  [[ "${lines[1]}" == alpha* ]]
}

@test "sort_by_score: path boost lifts equal-score row sharing prefix" {
  seed_score_file "alpha" 1 "$(date +%s)"
  seed_score_file "beta"  1 "$(date +%s)"
  run bash -c '
    source "'"$PLUGIN_ROOT"'/scripts/common.sh"
    printf "alpha\t/p/repo\t/p/repo/main\nbeta\t/q/other\t/q/other\n" \
      | sort_by_score "/p/repo/feature"
  '
  assert_success
  [[ "${lines[0]}" == alpha* ]]
}

@test "sort_by_score: path boost disabled at 0 keeps base ordering" {
  seed_score_file "alpha" 1 "$(date +%s)"
  seed_score_file "beta"  2 "$(date +%s)"
  TMUX_SESSIONS_SCORE_PATH_BOOST=0 run bash -c '
    source "'"$PLUGIN_ROOT"'/scripts/common.sh"
    printf "alpha\t/p/repo\t/p/repo/main\nbeta\t/q/other\t/q/other\n" \
      | sort_by_score "/p/repo/feature"
  '
  assert_success
  [[ "${lines[0]}" == beta* ]]
}

@test "sort_by_score: missing score file treats all as zero" {
  rm -f "$TMUX_SESSIONS_SCORES_FILE"
  run bash -c '
    source "'"$PLUGIN_ROOT"'/scripts/common.sh"
    printf "alpha\t/p/a\t/p/a\nbeta\t/p/b\t/p/b\n" | sort_by_score ""
  '
  assert_success
  [[ "${#lines[@]}" -eq 2 ]]
}

# ── _resolve_remote ──────────────────────────────────────────────────────────

@test "_resolve_remote returns 'origin' when configured" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r" --remote
  run _resolve_remote "$BATS_TEST_TMPDIR/r"
  assert_success
  assert_output "origin"
}

@test "_resolve_remote falls back to first remote when origin is absent" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r"
  git init -q --bare -b main "$BATS_TEST_TMPDIR/upstream.git"
  git -C "$BATS_TEST_TMPDIR/r" remote add upstream "$BATS_TEST_TMPDIR/upstream.git"
  run _resolve_remote "$BATS_TEST_TMPDIR/r"
  assert_success
  assert_output "upstream"
}

@test "_resolve_remote returns empty when no remotes" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r"
  run _resolve_remote "$BATS_TEST_TMPDIR/r"
  assert_success
  assert_output ""
}

# ── get_default_branch ───────────────────────────────────────────────────────

@test "get_default_branch returns the remote HEAD branch" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r" --remote
  run get_default_branch "$BATS_TEST_TMPDIR/r"
  assert_success
  assert_output "main"
}

@test "get_default_branch returns empty when remote HEAD is unset" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r"
  run get_default_branch "$BATS_TEST_TMPDIR/r"
  assert_success
  assert_output ""
}

# ── list_branches ────────────────────────────────────────────────────────────

@test "list_branches: local + remote-only with origin/ prefix" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r" --remote --branches "main feature"
  # Push only main+feature; create a remote-only branch via direct ref update.
  git -C "$BATS_TEST_TMPDIR/r" update-ref refs/remotes/origin/server-only \
    "$(git -C "$BATS_TEST_TMPDIR/r" rev-parse main)"
  run list_branches "$BATS_TEST_TMPDIR/r"
  assert_success
  assert_line "main"
  assert_line "feature"
  assert_line "origin/server-only"
}

@test "list_branches: local branches that track a remote are not duplicated" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r" --remote
  run list_branches "$BATS_TEST_TMPDIR/r"
  assert_success
  # main is local AND a remote ref — should appear only once.
  count=0
  # `((count++))` returns the old value, so the first hit exits 1 and trips
  # bats' errexit on bash 5+. `((++count))` returns the new value (≥1).
  for line in "${lines[@]}"; do [[ "$line" == "main" ]] && (( ++count )); done
  (( count == 1 ))
}

@test "list_branches: no remote returns only local branches" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r" --branches "main feature"
  run list_branches "$BATS_TEST_TMPDIR/r"
  assert_success
  assert_line "main"
  assert_line "feature"
  refute_output --partial "origin/"
}

# ── branch_to_dir ────────────────────────────────────────────────────────────

@test "branch_to_dir replaces slashes with dashes" {
  source_common
  run branch_to_dir "feature/login"
  assert_success
  assert_output "feature-login"
}

@test "branch_to_dir replaces spaces with dashes" {
  source_common
  run branch_to_dir "with spaces"
  assert_success
  assert_output "with-spaces"
}

# ── list_worktrees ───────────────────────────────────────────────────────────

@test "list_worktrees emits path<TAB>branch for the main worktree" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r"
  run list_worktrees "$BATS_TEST_TMPDIR/r"
  assert_success
  assert_output --partial $'\tmain'
}

@test "list_worktrees lists multiple worktrees" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r"
  mkworktree "$BATS_TEST_TMPDIR/r" "feature" "$BATS_TEST_TMPDIR/feature"
  run list_worktrees "$BATS_TEST_TMPDIR/r"
  assert_success
  assert_line --partial "main"
  assert_line --partial "feature"
}

@test "list_worktrees marks detached HEAD branch column" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r"
  local sha
  sha=$(git -C "$BATS_TEST_TMPDIR/r" rev-parse HEAD)
  git -C "$BATS_TEST_TMPDIR/r" worktree add -q --detach "$BATS_TEST_TMPDIR/det" "$sha"
  run list_worktrees "$BATS_TEST_TMPDIR/r"
  assert_success
  assert_line --partial "(detached)"
}

# ── add_worktree ─────────────────────────────────────────────────────────────

@test "add_worktree creates a new branch from <remote>/<default>" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r" --remote
  mkdir -p "$BATS_TEST_TMPDIR/container"
  run --separate-stderr add_worktree "$BATS_TEST_TMPDIR/r" "$BATS_TEST_TMPDIR/container" "" "shiny"
  assert_success
  assert_output "$BATS_TEST_TMPDIR/container/shiny"
  [[ -d "$BATS_TEST_TMPDIR/container/shiny" ]]
  [[ "$(git -C "$BATS_TEST_TMPDIR/container/shiny" branch --show-current)" == "shiny" ]]
}

@test "add_worktree checks out an existing local branch under container/<dir>" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r" --remote --branches "main feature"
  mkdir -p "$BATS_TEST_TMPDIR/container"
  run --separate-stderr add_worktree "$BATS_TEST_TMPDIR/r" "$BATS_TEST_TMPDIR/container" "feature" ""
  assert_success
  assert_output "$BATS_TEST_TMPDIR/container/feature"
  [[ -d "$BATS_TEST_TMPDIR/container/feature" ]]
}

@test "add_worktree returns the existing path if branch is already checked out" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r" --remote --branches "main feature"
  mkdir -p "$BATS_TEST_TMPDIR/container"
  mkworktree "$BATS_TEST_TMPDIR/r" "feature" "$BATS_TEST_TMPDIR/container/feature"
  run --separate-stderr add_worktree "$BATS_TEST_TMPDIR/r" "$BATS_TEST_TMPDIR/container" "feature" ""
  assert_success
  assert_output "$BATS_TEST_TMPDIR/container/feature"
}

@test "add_worktree from origin/<remote-only> creates a tracking branch" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r" --remote
  git -C "$BATS_TEST_TMPDIR/r" update-ref refs/remotes/origin/remote-only \
    "$(git -C "$BATS_TEST_TMPDIR/r" rev-parse main)"
  mkdir -p "$BATS_TEST_TMPDIR/container"
  run --separate-stderr add_worktree "$BATS_TEST_TMPDIR/r" "$BATS_TEST_TMPDIR/container" "origin/remote-only" ""
  assert_success
  assert_output "$BATS_TEST_TMPDIR/container/remote-only"
  [[ "$(git -C "$BATS_TEST_TMPDIR/container/remote-only" branch --show-current)" == "remote-only" ]]
}

# ── _gen_branch_picker_entries ───────────────────────────────────────────────

@test "_gen_branch_picker_entries lists [new] sentinel first" {
  TMUX_SESSIONS_ICON_STYLE=ascii source_common
  mkrepo "$BATS_TEST_TMPDIR/r" --remote
  run _gen_branch_picker_entries "$BATS_TEST_TMPDIR/r"
  assert_success
  [[ "${lines[0]}" == $'[new]\t+ new branch' ]]
}

@test "_gen_branch_picker_entries marks remote-only entries with the remote icon" {
  TMUX_SESSIONS_ICON_STYLE=ascii source_common
  mkrepo "$BATS_TEST_TMPDIR/r" --remote
  git -C "$BATS_TEST_TMPDIR/r" update-ref refs/remotes/origin/server \
    "$(git -C "$BATS_TEST_TMPDIR/r" rev-parse main)"
  run _gen_branch_picker_entries "$BATS_TEST_TMPDIR/r"
  assert_success
  assert_line --partial $'\t@ origin/server'   # remote icon = '@' in ascii style
  assert_line --partial $'\t- main'            # local icon = '-' in ascii style
}

# ── _fetch_is_stale ──────────────────────────────────────────────────────────

@test "_fetch_is_stale: missing FETCH_HEAD is stale (returns 0)" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r"
  run _fetch_is_stale "$BATS_TEST_TMPDIR/r"
  assert_success  # 0 == stale
}

@test "_fetch_is_stale: fresh FETCH_HEAD is not stale (returns non-zero)" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r"
  local git_dir
  git_dir=$(git -C "$BATS_TEST_TMPDIR/r" rev-parse --git-common-dir)
  [[ "$git_dir" != /* ]] && git_dir="$BATS_TEST_TMPDIR/r/$git_dir"
  : > "$git_dir/FETCH_HEAD"
  run _fetch_is_stale "$BATS_TEST_TMPDIR/r"
  assert_failure  # non-zero == fresh
}

@test "_fetch_is_stale: backdated FETCH_HEAD older than 15 minutes is stale" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r"
  local git_dir
  git_dir=$(git -C "$BATS_TEST_TMPDIR/r" rev-parse --git-common-dir)
  [[ "$git_dir" != /* ]] && git_dir="$BATS_TEST_TMPDIR/r/$git_dir"
  : > "$git_dir/FETCH_HEAD"
  # Backdate 30 minutes — works on both BSD and GNU touch via -t.
  if touch -t "$(date -v-30M +%Y%m%d%H%M.%S 2>/dev/null)" "$git_dir/FETCH_HEAD" 2>/dev/null; then
    : # macOS touch -v
  else
    touch -d "30 minutes ago" "$git_dir/FETCH_HEAD"  # GNU touch
  fi
  run _fetch_is_stale "$BATS_TEST_TMPDIR/r"
  assert_success
}

# ── switch_or_create_session ─────────────────────────────────────────────────

@test "switch_or_create_session uses existing session id when present" {
  source_common
  stub_tmux_sessions $'alpha\t$5\t/tmp/alpha'
  switch_or_create_session "/tmp/alpha" "alpha"
  run cat "$TMUX_STUB_LOG"
  assert_success
  assert_line --partial $'switch-client\t-t\t$5'
  refute_output --partial "new-session"
}

@test "switch_or_create_session creates a new session when name is unknown" {
  source_common
  stub_tmux_sessions ""
  stub_tmux_new_session_id '$42'
  switch_or_create_session "/tmp/fresh" "fresh"
  run cat "$TMUX_STUB_LOG"
  assert_success
  assert_line --partial $'new-session\t-c\t/tmp/fresh\t-s\tfresh'
  assert_line --partial $'switch-client\t-t\t$42'
}

# ── pick_branch ──────────────────────────────────────────────────────────────

# Helper: pre-create a fresh FETCH_HEAD so the staleness check skips fetch_reload.
_make_fresh_fetch_head() {
  local repo="$1"
  local git_dir
  git_dir=$(git -C "$repo" rev-parse --git-common-dir)
  [[ "$git_dir" != /* ]] && git_dir="$repo/$git_dir"
  : > "$git_dir/FETCH_HEAD"
}

@test "pick_branch: ctrl-bs returns 1" {
  TMUX_SESSIONS_ICON_STYLE=ascii source_common
  mkrepo "$BATS_TEST_TMPDIR/r" --remote
  _make_fresh_fetch_head "$BATS_TEST_TMPDIR/r"
  stub_fzf_response $'ctrl-bs\n'
  run pick_branch "$BATS_TEST_TMPDIR/r"
  assert_failure 1
}

@test "pick_branch: Esc returns 2" {
  TMUX_SESSIONS_ICON_STYLE=ascii source_common
  mkrepo "$BATS_TEST_TMPDIR/r" --remote
  _make_fresh_fetch_head "$BATS_TEST_TMPDIR/r"
  stub_fzf_esc
  run pick_branch "$BATS_TEST_TMPDIR/r"
  assert_failure 2
}

@test "pick_branch: existing branch returns 'existing:<branch>'" {
  TMUX_SESSIONS_ICON_STYLE=ascii source_common
  mkrepo "$BATS_TEST_TMPDIR/r" --remote --branches "main feature"
  _make_fresh_fetch_head "$BATS_TEST_TMPDIR/r"
  # First call to fzf: empty key (Enter), selection is "feature\t- feature".
  stub_fzf_response $'\nfeature\t- feature'
  run pick_branch "$BATS_TEST_TMPDIR/r"
  assert_success
  assert_output "existing:feature"
}

@test "pick_branch: [new] then a name returns 'new:<name>'" {
  TMUX_SESSIONS_ICON_STYLE=ascii source_common
  mkrepo "$BATS_TEST_TMPDIR/r" --remote
  _make_fresh_fetch_head "$BATS_TEST_TMPDIR/r"
  # First fzf call: pick "[new]". Output line uses cut -f1 so first TSV col matters.
  stub_fzf_response $'\n[new]\t+ new branch'
  # Second fzf call (name prompt with --print-query --expect "ctrl-bs"):
  # line 1 = query ("shiny"), line 2 = expect-key (empty since Enter was pressed).
  stub_fzf_response "shiny"
  run pick_branch "$BATS_TEST_TMPDIR/r"
  assert_success
  assert_output "new:shiny"
}

# ── rename_worktree ──────────────────────────────────────────────────────────

@test "rename_worktree: detached HEAD returns 1" {
  source_common
  mkrepo "$BATS_TEST_TMPDIR/r" --remote
  local sha
  sha=$(git -C "$BATS_TEST_TMPDIR/r" rev-parse HEAD)
  git -C "$BATS_TEST_TMPDIR/r" worktree add -q --detach "$BATS_TEST_TMPDIR/det" "$sha"
  run rename_worktree "$BATS_TEST_TMPDIR/r" "$BATS_TEST_TMPDIR" "$BATS_TEST_TMPDIR/det"
  assert_failure
}
