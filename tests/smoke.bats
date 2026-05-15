# Sanity check that the test harness loads and stubs work.

load 'test_helper'

setup() {
  reset_plugin_env
  install_stubs
}

@test "harness loads PLUGIN_ROOT" {
  [[ -d "$PLUGIN_ROOT/scripts" ]]
}

@test "tmux stub is on PATH and responds to ls" {
  stub_tmux_sessions $'foo\t$1\t/tmp/foo'
  run tmux ls -F '#{session_name}'$'\t''#{session_id}'
  assert_success
  assert_output $'foo\t$1'
}

@test "fzf stub returns queued response then 130" {
  stub_fzf_select "selected"
  run bash -c 'echo input | fzf'
  assert_success
  assert_output "selected"
  run bash -c 'echo input | fzf'
  assert_failure 130
}

@test "common.sh sources cleanly with default test env" {
  source_common
  type strip_ansi
}

@test "mkrepo creates a working git repo with main branch" {
  mkrepo "$BATS_TEST_TMPDIR/r"
  run git -C "$BATS_TEST_TMPDIR/r" branch --show-current
  assert_success
  assert_output "main"
}
