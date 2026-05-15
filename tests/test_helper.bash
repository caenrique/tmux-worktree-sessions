# Shared bats helper. Sourced by every .bats file via:
#   load 'test_helper'
#
# Provides:
#   - PLUGIN_ROOT       — repo root (used to source scripts under test)
#   - reset_plugin_env  — wipe TMUX_SESSIONS_* and seed safe defaults
#   - install_stubs     — copy stubs onto PATH; default {tmux,fzf,curl}
#   - install_stub      — install a single named stub
#   - remove_stub       — remove a named stub from the test PATH
#   - source_common     — source scripts/common.sh after env is configured
#   - assert_*          — minimal portable assertions, no bats-assert dependency
#   - mkrepo / mkworktree / seed_score_file — git fixture helpers
#   - stub_*            — programming helpers for the tmux/fzf/curl stubs

bats_require_minimum_version 1.5.0

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PLUGIN_ROOT

load_helpers() {
  # shellcheck source=helpers/stubs.bash
  source "$PLUGIN_ROOT/tests/helpers/stubs.bash"
  # shellcheck source=helpers/git_fixtures.bash
  source "$PLUGIN_ROOT/tests/helpers/git_fixtures.bash"
}
load_helpers

reset_plugin_env() {
  # Resolve symlinks (macOS /var → /private/var) so paths produced by git/realpath
  # inside the test compare equal to paths constructed from $BATS_TEST_TMPDIR.
  if BATS_TEST_TMPDIR=$(cd "$BATS_TEST_TMPDIR" 2>/dev/null && pwd -P); then
    export BATS_TEST_TMPDIR
  fi

  unset TMUX_SESSIONS_PROJECTS_DIRS \
        TMUX_SESSIONS_SCORES_FILE \
        TMUX_SESSIONS_STRIP_PREFIXES \
        TMUX_SESSIONS_MANUAL_SESSIONS \
        TMUX_SESSIONS_MAX_DEPTH \
        TMUX_SESSIONS_DEFAULT_BRANCH \
        TMUX_SESSIONS_SCORE_HALF_LIFE \
        TMUX_SESSIONS_SCORE_PATH_BOOST \
        TMUX_SESSIONS_ICON_STYLE \
        TMUX_PLUGIN_DIR

  export TMUX_PLUGIN_DIR="$PLUGIN_ROOT"
  export TMUX_SESSIONS_PROJECTS_DIRS="$BATS_TEST_TMPDIR/projects"
  export TMUX_SESSIONS_SCORES_FILE="$BATS_TEST_TMPDIR/scores.tsv"
  export TMUX_SESSIONS_STRIP_PREFIXES=""
  export TMUX_SESSIONS_MANUAL_SESSIONS=""
  export TMUX_SESSIONS_MAX_DEPTH=4
  export TMUX_SESSIONS_DEFAULT_BRANCH=main
  export TMUX_SESSIONS_SCORE_HALF_LIFE=14
  export TMUX_SESSIONS_SCORE_PATH_BOOST=1.0
  export TMUX_SESSIONS_ICON_STYLE=none

  mkdir -p "$TMUX_SESSIONS_PROJECTS_DIRS"
}

source_common() {
  # shellcheck source=../scripts/common.sh
  source "$PLUGIN_ROOT/scripts/common.sh"
}

# ── Minimal assertion library (subset of bats-assert, no install required) ────
# These functions read $status, $output, and $lines — bats's `run` builtin
# populates them in the calling scope, so shellcheck cannot see the assignment.

# shellcheck disable=SC2154
assert_success() {
  if (( status != 0 )); then
    printf 'expected success, got status=%d\noutput:\n%s\n' "$status" "$output" >&2
    return 1
  fi
}

# shellcheck disable=SC2154
assert_failure() {
  local expected="${1:-}"
  if (( status == 0 )); then
    printf 'expected failure, got status=0\noutput:\n%s\n' "$output" >&2
    return 1
  fi
  if [[ -n "$expected" && "$status" != "$expected" ]]; then
    printf 'expected exit code %s, got %d\n' "$expected" "$status" >&2
    return 1
  fi
}

assert_equal() {
  local expected="$1" actual="$2"
  if [[ "$expected" != "$actual" ]]; then
    printf 'expected: %q\nactual:   %q\n' "$expected" "$actual" >&2
    return 1
  fi
}

# shellcheck disable=SC2154
assert_output() {
  local mode=exact want
  case "$1" in
    --partial) mode=partial; want="$2" ;;
    --regexp)  mode=regexp;  want="$2" ;;
    *)         want="$1" ;;
  esac
  case "$mode" in
    exact)
      [[ "$output" == "$want" ]] && return 0
      printf 'expected output:\n%s\n---\nactual:\n%s\n' "$want" "$output" >&2
      return 1 ;;
    partial)
      [[ "$output" == *"$want"* ]] && return 0
      printf 'expected substring: %q\nactual output:\n%s\n' "$want" "$output" >&2
      return 1 ;;
    regexp)
      [[ "$output" =~ $want ]] && return 0
      printf 'expected regexp: %q\nactual output:\n%s\n' "$want" "$output" >&2
      return 1 ;;
  esac
}

# shellcheck disable=SC2154
refute_output() {
  local mode=exact want
  case "$1" in
    --partial) mode=partial; want="$2" ;;
    *)         want="$1" ;;
  esac
  case "$mode" in
    exact)
      [[ "$output" != "$want" ]] && return 0
      printf 'output unexpectedly equals: %s\n' "$want" >&2
      return 1 ;;
    partial)
      [[ "$output" != *"$want"* ]] && return 0
      printf 'output unexpectedly contains: %q\nfull:\n%s\n' "$want" "$output" >&2
      return 1 ;;
  esac
}

# shellcheck disable=SC2154
assert_line() {
  local n="" mode=exact want
  while (( $# )); do
    case "$1" in
      -n) n="$2"; shift 2 ;;
      --partial) mode=partial; shift ;;
      *) want="$1"; shift ;;
    esac
  done
  if [[ -n "$n" ]]; then
    local actual="${lines[$n]}"
    case "$mode" in
      exact)   [[ "$actual" == "$want" ]] && return 0 ;;
      partial) [[ "$actual" == *"$want"* ]] && return 0 ;;
    esac
    printf 'line %s mismatch.\nexpected: %q\nactual:   %q\n' "$n" "$want" "$actual" >&2
    return 1
  fi
  local line
  for line in "${lines[@]}"; do
    case "$mode" in
      exact)   [[ "$line" == "$want" ]]   && return 0 ;;
      partial) [[ "$line" == *"$want"* ]] && return 0 ;;
    esac
  done
  printf 'no line matches: %q\noutput:\n%s\n' "$want" "$output" >&2
  return 1
}
