# Tests for scripts/fetch_reload.sh
#
# fetch_reload.sh forks immediately (disown) so the caller returns at once.
# Tests poll curl_log until the final reload post arrives, with a timeout.

load 'test_helper'

setup() {
  reset_plugin_env
  install_stubs
}

# Wait until $1 substring appears in CURL_STUB_LOG (or timeout).
_wait_for_curl() {
  local needle="$1" timeout_s="${2:-5}" elapsed=0
  while (( $(awk 'BEGIN{print int('"$timeout_s"' * 10)}') > elapsed )); do
    if grep -qF -- "$needle" "$CURL_STUB_LOG" 2>/dev/null; then
      return 0
    fi
    sleep 0.1
    # ((elapsed++)) returns the old value (0 → exit 1) and trips bats' errexit
    # on bash 5. ((++elapsed)) returns the new value, which is ≥1.
    (( ++elapsed ))
  done
  return 1
}

@test "fetch_reload posts a final reload to fzf's listen port" {
  TMUX_SESSIONS_ICON_STYLE=ascii
  mkrepo "$BATS_TEST_TMPDIR/r" --remote
  local tmpfile="$BATS_TEST_TMPDIR/branch-entries"
  : > "$tmpfile"

  TMUX_SESSIONS_ICON_STYLE=ascii \
    bash "$PLUGIN_ROOT/scripts/fetch_reload.sh" \
      "$BATS_TEST_TMPDIR/r" "$tmpfile" "12345" "header-base"

  _wait_for_curl "reload(cat"
  run cat "$CURL_STUB_LOG"
  assert_line --partial "localhost:12345"
  assert_line --partial "reload(cat"
  assert_line --partial "header-base"
}

@test "fetch_reload regenerates the branch entries file with [new] sentinel" {
  TMUX_SESSIONS_ICON_STYLE=ascii
  mkrepo "$BATS_TEST_TMPDIR/r" --remote --branches "main feature"
  local tmpfile="$BATS_TEST_TMPDIR/branch-entries"
  : > "$tmpfile"

  TMUX_SESSIONS_ICON_STYLE=ascii \
    bash "$PLUGIN_ROOT/scripts/fetch_reload.sh" \
      "$BATS_TEST_TMPDIR/r" "$tmpfile" "12346" "h"

  _wait_for_curl "reload(cat"
  run cat "$tmpfile"
  assert_success
  assert_line --partial "[new]"
  assert_line --partial "main"
}

@test "fetch_reload uses the supplied port in the curl URL" {
  TMUX_SESSIONS_ICON_STYLE=ascii
  mkrepo "$BATS_TEST_TMPDIR/r" --remote
  local tmpfile="$BATS_TEST_TMPDIR/branch-entries"
  : > "$tmpfile"

  TMUX_SESSIONS_ICON_STYLE=ascii \
    bash "$PLUGIN_ROOT/scripts/fetch_reload.sh" \
      "$BATS_TEST_TMPDIR/r" "$tmpfile" "59999" "h"

  _wait_for_curl "localhost:59999"
  run cat "$CURL_STUB_LOG"
  assert_line --partial "localhost:59999"
}

@test "fetch_reload still posts the final reload when git fetch fails" {
  TMUX_SESSIONS_ICON_STYLE=ascii
  # Repo with no remotes — git fetch --all has nothing to fetch but exits 0.
  # Force a failure by setting a bogus remote URL.
  mkrepo "$BATS_TEST_TMPDIR/r"
  git -C "$BATS_TEST_TMPDIR/r" remote add origin "/nonexistent/repo.git"
  local tmpfile="$BATS_TEST_TMPDIR/branch-entries"
  : > "$tmpfile"

  TMUX_SESSIONS_ICON_STYLE=ascii \
    bash "$PLUGIN_ROOT/scripts/fetch_reload.sh" \
      "$BATS_TEST_TMPDIR/r" "$tmpfile" "12348" "h"

  _wait_for_curl "reload(cat"
  run cat "$CURL_STUB_LOG"
  assert_line --partial "reload(cat"
}
