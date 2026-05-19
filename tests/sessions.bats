# Tests for scripts/sessions.sh
#
# Note: many _action_* tests wrap calls in `run` because the action helpers
# invoke git/tmux on paths that may legitimately fail (e.g. checking whether
# a path is a worktree). Bats's ERR trap fires on any non-zero command, so
# `run` is required to inspect side effects (tmpfile, stub log) without the
# test aborting mid-function.

load 'test_helper'

setup() {
  reset_plugin_env
  install_stubs
}

source_sessions() {
  # shellcheck source=../scripts/sessions.sh
  source "$PLUGIN_ROOT/scripts/sessions.sh"
}

last_line() {
  printf '%s\n' "${lines[$(( ${#lines[@]} - 1 ))]}"
}

# ── list_projects ────────────────────────────────────────────────────────────

@test "list_projects emits one row per discovered git project" {
  TMUX_SESSIONS_ICON_STYLE=ascii source_sessions
  mkrepo "$TMUX_SESSIONS_PROJECTS_DIRS/foo"
  mkrepo "$TMUX_SESSIONS_PROJECTS_DIRS/bar"
  run list_projects
  assert_success
  assert_line --partial $'\t'"$TMUX_SESSIONS_PROJECTS_DIRS/foo"
  assert_line --partial $'\t'"$TMUX_SESSIONS_PROJECTS_DIRS/bar"
}

@test "list_projects appends manual sessions after git projects" {
  source_sessions
  export TMUX_SESSIONS_MANUAL_SESSIONS="dotfiles:$BATS_TEST_TMPDIR/cfg"
  mkdir -p "$BATS_TEST_TMPDIR/cfg"
  run list_projects
  assert_success
  assert_line $'dotfiles\t'"$BATS_TEST_TMPDIR/cfg"
}

@test "list_projects expands ~ in manual session paths" {
  source_sessions
  export TMUX_SESSIONS_MANUAL_SESSIONS='home:~/somewhere'
  run list_projects
  assert_success
  assert_line $'home\t'"$HOME/somewhere"
}

# ── _is_orphaned_worktree_dir ────────────────────────────────────────────────

@test "_is_orphaned_worktree_dir: sibling is a git repo → orphaned (0)" {
  source_sessions
  mkdir -p "$BATS_TEST_TMPDIR/wt/orphan"
  mkrepo "$BATS_TEST_TMPDIR/wt/realrepo"
  run _is_orphaned_worktree_dir "$BATS_TEST_TMPDIR/wt/orphan"
  assert_success
}

@test "_is_orphaned_worktree_dir: no siblings → not orphaned (1)" {
  source_sessions
  mkdir -p "$BATS_TEST_TMPDIR/lonely/only"
  run _is_orphaned_worktree_dir "$BATS_TEST_TMPDIR/lonely/only"
  assert_failure
}

@test "_is_orphaned_worktree_dir: sibling without .git → not orphaned (1)" {
  source_sessions
  mkdir -p "$BATS_TEST_TMPDIR/wt/orphan" "$BATS_TEST_TMPDIR/wt/notes"
  run _is_orphaned_worktree_dir "$BATS_TEST_TMPDIR/wt/orphan"
  assert_failure
}

# ── build_entries ────────────────────────────────────────────────────────────

@test "build_entries: project-only (no sessions) ends with [n] sentinel" {
  TMUX_SESSIONS_ICON_STYLE=ascii source_sessions
  mkrepo "$TMUX_SESSIONS_PROJECTS_DIRS/foo"
  stub_tmux_sessions ""
  run build_entries
  assert_success
  assert_line --partial $'p\t'"$TMUX_SESSIONS_PROJECTS_DIRS/foo"
  run last_line
  assert_output --partial "new session"
  [[ "$output" == n$'\t\t'* ]]
}

@test "build_entries: pins current session first with yellow (current) label" {
  TMUX_SESSIONS_ICON_STYLE=none source_sessions
  stub_tmux_sessions $'alpha\t$1\t/p/alpha'
  stub_tmux_current_session "alpha"
  run build_entries
  assert_success
  [[ "${lines[0]}" == $'s\t1\t'*"alpha"*"(current)"* ]]
}

@test "build_entries: pins previous session second with green (previous) label" {
  TMUX_SESSIONS_ICON_STYLE=none source_sessions
  stub_tmux_sessions $'alpha\t$1\t/p/alpha\nbeta\t$2\t/p/beta'
  stub_tmux_current_session "alpha"
  stub_tmux_prev_session "beta"
  run build_entries
  assert_success
  [[ "${lines[0]}" == $'s\t1\t'*"alpha"*"(current)"* ]]
  [[ "${lines[1]}" == $'s\t2\t'*"beta"*"(previous)"* ]]
}

@test "build_entries: remaining sessions ordered by session_last_attached desc" {
  TMUX_SESSIONS_ICON_STYLE=none source_sessions
  # current=alpha, previous=beta. The remaining sessions (gamma, delta, epsilon)
  # carry distinct last_attached timestamps; the picker should list them
  # newest→oldest after the two pinned rows.
  stub_tmux_sessions \
    $'alpha\t$1\t/p/alpha\t1000\nbeta\t$2\t/p/beta\t900\ngamma\t$3\t/p/gamma\t800\ndelta\t$4\t/p/delta\t950\nepsilon\t$5\t/p/epsilon\t850'
  stub_tmux_current_session "alpha"
  stub_tmux_prev_session "beta"
  run build_entries
  assert_success
  [[ "${lines[0]}" == $'s\t1\t'*"alpha"*"(current)"* ]]
  [[ "${lines[1]}" == $'s\t2\t'*"beta"*"(previous)"* ]]
  [[ "${lines[2]}" == $'s\t4\t'*"delta"* ]]    # last_attached=950
  [[ "${lines[3]}" == $'s\t5\t'*"epsilon"* ]]  # last_attached=850
  [[ "${lines[4]}" == $'s\t3\t'*"gamma"* ]]    # last_attached=800
}

@test "build_entries: project matching an open session is filtered out" {
  TMUX_SESSIONS_ICON_STYLE=none source_sessions
  mkrepo "$TMUX_SESSIONS_PROJECTS_DIRS/foo"
  local proj_name
  proj_name=$(format_session_name "$TMUX_SESSIONS_PROJECTS_DIRS/foo")
  stub_tmux_sessions "${proj_name}"$'\t$3\t'"$TMUX_SESSIONS_PROJECTS_DIRS/foo"
  run build_entries
  assert_success
  refute_output --partial $'p\t'"$TMUX_SESSIONS_PROJECTS_DIRS/foo"
  assert_line --partial "$proj_name"
}

@test "build_entries: every emitted line has exactly 3 TSV fields" {
  TMUX_SESSIONS_ICON_STYLE=none source_sessions
  mkrepo "$TMUX_SESSIONS_PROJECTS_DIRS/foo"
  stub_tmux_sessions $'alpha\t$1\t/p/alpha'
  stub_tmux_current_session "alpha"
  run build_entries
  assert_success
  local line
  for line in "${lines[@]}"; do
    local fields
    fields=$(awk -F'\t' '{print NF}' <<<"$line")
    (( fields == 3 )) || { printf 'bad line: %q (fields=%d)\n' "$line" "$fields" >&2; return 1; }
  done
}

# ── _action_ctrl_d ───────────────────────────────────────────────────────────

@test "_action_ctrl_d: session+worktree kills session, removes worktree, strips line" {
  TMUX_SESSIONS_ICON_STYLE=none source_sessions
  mkrepo "$BATS_TEST_TMPDIR/r" --remote
  mkworktree "$BATS_TEST_TMPDIR/r" "feature" "$BATS_TEST_TMPDIR/wt/feature"
  stub_tmux_sessions "feature"$'\t$5\t'"$BATS_TEST_TMPDIR/wt/feature"
  local tmpfile="$BATS_TEST_TMPDIR/entries"
  printf 's\t5\tfeature\np\t/other/proj\tother\n' > "$tmpfile"

  run _action_ctrl_d "s" "5" "$tmpfile"
  wait

  run cat "$tmpfile"
  refute_output --partial $'s\t5\t'
  assert_line --partial $'p\t/other/proj'
  run cat "$TMUX_STUB_LOG"
  assert_line --partial $'kill-session\t-t\t$5'
  [[ ! -d "$BATS_TEST_TMPDIR/wt/feature" ]]
}

@test "_action_ctrl_d: session-only path kills session and strips line" {
  TMUX_SESSIONS_ICON_STYLE=none source_sessions
  mkdir -p "$BATS_TEST_TMPDIR/plain"
  stub_tmux_sessions "plain"$'\t$7\t'"$BATS_TEST_TMPDIR/plain"
  local tmpfile="$BATS_TEST_TMPDIR/entries"
  printf 's\t7\tplain\np\t/other/proj\tother\n' > "$tmpfile"

  run _action_ctrl_d "s" "7" "$tmpfile"

  run cat "$tmpfile"
  refute_output --partial $'s\t7\t'
  assert_line --partial $'p\t/other/proj'
  run cat "$TMUX_STUB_LOG"
  assert_line --partial $'kill-session\t-t\t$7'
}

@test "_action_ctrl_d: project linked to a worktree removes worktree and strips row" {
  TMUX_SESSIONS_ICON_STYLE=none source_sessions
  mkrepo "$BATS_TEST_TMPDIR/r" --remote
  mkworktree "$BATS_TEST_TMPDIR/r" "feature" "$BATS_TEST_TMPDIR/wt/feature"
  local tmpfile="$BATS_TEST_TMPDIR/entries"
  printf 'p\t%s\tfeature\np\t/other/proj\tother\n' "$BATS_TEST_TMPDIR/wt/feature" > "$tmpfile"

  run _action_ctrl_d "p" "$BATS_TEST_TMPDIR/wt/feature" "$tmpfile"
  wait

  run cat "$tmpfile"
  refute_output --partial "$BATS_TEST_TMPDIR/wt/feature"
  assert_line --partial "/other/proj"
  [[ ! -d "$BATS_TEST_TMPDIR/wt/feature" ]]
}

@test "_action_ctrl_d: project on orphaned dir prompts; 'Yes' deletes" {
  TMUX_SESSIONS_ICON_STYLE=none source_sessions
  mkrepo "$BATS_TEST_TMPDIR/wt/realrepo"
  mkdir -p "$BATS_TEST_TMPDIR/wt/orphan"
  stub_fzf_response "Yes"
  local tmpfile="$BATS_TEST_TMPDIR/entries"
  printf 'p\t%s\torphan\np\t/other\tother\n' "$BATS_TEST_TMPDIR/wt/orphan" > "$tmpfile"

  run _action_ctrl_d "p" "$BATS_TEST_TMPDIR/wt/orphan" "$tmpfile"
  wait

  run cat "$tmpfile"
  refute_output --partial "$BATS_TEST_TMPDIR/wt/orphan"
  [[ ! -d "$BATS_TEST_TMPDIR/wt/orphan" ]]
}

@test "_action_ctrl_d: project on orphaned dir; 'No' keeps directory" {
  TMUX_SESSIONS_ICON_STYLE=none source_sessions
  mkrepo "$BATS_TEST_TMPDIR/wt/realrepo"
  mkdir -p "$BATS_TEST_TMPDIR/wt/orphan"
  stub_fzf_response "No"
  local tmpfile="$BATS_TEST_TMPDIR/entries"
  printf 'p\t%s\torphan\n' "$BATS_TEST_TMPDIR/wt/orphan" > "$tmpfile"

  run _action_ctrl_d "p" "$BATS_TEST_TMPDIR/wt/orphan" "$tmpfile"

  [[ -d "$BATS_TEST_TMPDIR/wt/orphan" ]]
  run cat "$tmpfile"
  assert_line --partial "$BATS_TEST_TMPDIR/wt/orphan"
}

@test "_action_ctrl_d: project on non-orphan, non-worktree dir → display-message" {
  TMUX_SESSIONS_ICON_STYLE=none source_sessions
  mkdir -p "$BATS_TEST_TMPDIR/lonely/notes"
  local tmpfile="$BATS_TEST_TMPDIR/entries"
  printf 'p\t%s\tnotes\n' "$BATS_TEST_TMPDIR/lonely/notes" > "$tmpfile"

  run _action_ctrl_d "p" "$BATS_TEST_TMPDIR/lonely/notes" "$tmpfile"

  [[ -d "$BATS_TEST_TMPDIR/lonely/notes" ]]
  run cat "$TMUX_STUB_LOG"
  assert_line --partial "display-message"
  assert_line --partial "not a linked worktree"
}

# ── _action_ctrl_x ───────────────────────────────────────────────────────────

@test "_action_ctrl_x: session row becomes a project row above the n sentinel" {
  TMUX_SESSIONS_ICON_STYLE=none source_sessions
  stub_tmux_sessions "alpha"$'\t$3\t/p/alpha'
  local tmpfile="$BATS_TEST_TMPDIR/entries"
  {
    printf 's\t3\talpha\n'
    printf 'p\t/p/other\tother\n'
    printf 'n\t\tnew session\n'
  } > "$tmpfile"

  run _action_ctrl_x "s" "3" "$tmpfile"

  run cat "$tmpfile"
  assert_success
  refute_output --partial $'s\t3\t'
  [[ "${lines[0]}" == $'p\t/p/other\tother' ]]
  [[ "${lines[1]}" == $'p\t/p/alpha\talpha' ]]
  [[ "${lines[2]}" == $'n\t\tnew session' ]]
  run cat "$TMUX_STUB_LOG"
  assert_line --partial $'kill-session\t-t\t$3'
}

@test "_action_ctrl_x: non-session row is a no-op" {
  TMUX_SESSIONS_ICON_STYLE=none source_sessions
  local tmpfile="$BATS_TEST_TMPDIR/entries"
  printf 'p\t/p/foo\tfoo\n' > "$tmpfile"
  local before
  before=$(cat "$tmpfile")

  run _action_ctrl_x "p" "/p/foo" "$tmpfile"

  run cat "$tmpfile"
  assert_output "$before"
}

# ── _action_ctrl_r ───────────────────────────────────────────────────────────

@test "_action_ctrl_r: session+non-worktree calls tmux rename-session with sanitized name" {
  TMUX_SESSIONS_ICON_STYLE=none source_sessions
  mkdir -p "$BATS_TEST_TMPDIR/plain"
  stub_tmux_sessions "alpha"$'\t$3\t'"$BATS_TEST_TMPDIR/plain"
  stub_fzf_response "shiny new"
  local tmpfile="$BATS_TEST_TMPDIR/entries"
  printf 's\t3\talpha\n' > "$tmpfile"

  run _action_ctrl_r "s" "3" "$tmpfile"

  run cat "$TMUX_STUB_LOG"
  assert_line --partial $'rename-session\t-t\t$3\tshiny-new'
}

@test "_action_ctrl_r: project+non-worktree displays a warning" {
  TMUX_SESSIONS_ICON_STYLE=none source_sessions
  mkdir -p "$BATS_TEST_TMPDIR/plain"
  local tmpfile="$BATS_TEST_TMPDIR/entries"
  printf 'p\t%s\tplain\n' "$BATS_TEST_TMPDIR/plain" > "$tmpfile"

  run _action_ctrl_r "p" "$BATS_TEST_TMPDIR/plain" "$tmpfile"

  run cat "$TMUX_STUB_LOG"
  assert_line --partial "display-message"
  assert_line --partial "not a linked worktree"
}

# ── Entry-point dispatch ─────────────────────────────────────────────────────

@test "entry-point: --display-name returns derived name when it normalises to the session name" {
  # tmux replaces dots with underscores in session names, so the runtime $3 has
  # underscores. The script reverses that by checking ${derived//./_} == $3.
  run bash "$PLUGIN_ROOT/scripts/sessions.sh" --display-name "$HOME/with.dot" "~/with_dot"
  assert_success
  assert_output "~/with.dot"
}

@test "entry-point: --display-name falls back to raw session name on mismatch" {
  run bash "$PLUGIN_ROOT/scripts/sessions.sh" --display-name "$HOME/foo" "manual_name"
  assert_success
  assert_output "manual_name"
}

@test "entry-point: --action ctrl-x reaches the handler" {
  TMUX_SESSIONS_ICON_STYLE=none
  stub_tmux_sessions "alpha"$'\t$5\t/p/alpha'
  local tmpfile="$BATS_TEST_TMPDIR/entries"
  {
    printf 's\t5\talpha\n'
    printf 'n\t\tnew session\n'
  } > "$tmpfile"

  run bash "$PLUGIN_ROOT/scripts/sessions.sh" --action ctrl-x s 5 "$tmpfile"
  assert_success

  run cat "$tmpfile"
  refute_output --partial $'s\t5\t'
  assert_line --partial $'p\t/p/alpha\t'
  run cat "$TMUX_STUB_LOG"
  assert_line --partial $'kill-session\t-t\t$5'
}

@test "entry-point: default invocation calls fzf with popup args (stub returns 130 → exit 0)" {
  TMUX_SESSIONS_ICON_STYLE=none
  stub_tmux_sessions ""
  run bash "$PLUGIN_ROOT/scripts/sessions.sh"
  assert_success
  run cat "$FZF_STUB_INVOCATION_LOG"
  assert_line --partial "--tmux"
  assert_line --partial "Sessions > "
}
