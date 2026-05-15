# Tests for the tmux-sessions.tmux TPM entry point.
#
# The script reads @tmux-sessions-* options via `tmux show-option` and calls
# `tmux bind-key`. Tests stub tmux to canned option responses, run the script,
# and assert on the recorded bind-key invocation.

load 'test_helper'

setup() {
  reset_plugin_env
  install_stubs
}

# Pull the bind-key argv list out of TMUX_STUB_LOG (one TSV row per call).
# Returns the matching row on stdout, or empty if not found.
_bind_key_invocation() {
  awk -F'\t' '$2=="bind-key"' "$TMUX_STUB_LOG"
}

@test "tmux-sessions.tmux binds C-S-s by default" {
  stub_tmux_options ""
  run bash "$PLUGIN_ROOT/tmux-sessions.tmux"
  assert_success
  run _bind_key_invocation
  assert_output --partial $'\tC-S-s\t'
}

@test "tmux-sessions.tmux honours @tmux-sessions-key when set" {
  stub_tmux_options $'@tmux-sessions-key=M-x'
  run bash "$PLUGIN_ROOT/tmux-sessions.tmux"
  assert_success
  run _bind_key_invocation
  assert_output --partial $'\tM-x\t'
}

@test "tmux-sessions.tmux expands literal \$HOME in @tmux-sessions-projects-dir" {
  stub_tmux_options '@tmux-sessions-projects-dir=$HOME/MyProjects'
  run bash "$PLUGIN_ROOT/tmux-sessions.tmux"
  assert_success
  run _bind_key_invocation
  assert_output --partial "TMUX_SESSIONS_PROJECTS_DIRS='$HOME/MyProjects'"
  refute_output --partial '$HOME/MyProjects'
}

@test "tmux-sessions.tmux expands literal \$HOME in @tmux-sessions-strip-prefixes" {
  stub_tmux_options '@tmux-sessions-strip-prefixes=$HOME/Projects $HOME/work'
  run bash "$PLUGIN_ROOT/tmux-sessions.tmux"
  assert_success
  run _bind_key_invocation
  assert_output --partial "TMUX_SESSIONS_STRIP_PREFIXES='$HOME/Projects $HOME/work'"
}

@test "tmux-sessions.tmux forwards numeric option values" {
  stub_tmux_options $'@tmux-sessions-max-depth=8\n@tmux-sessions-score-half-life=30\n@tmux-sessions-score-path-boost=2.5'
  run bash "$PLUGIN_ROOT/tmux-sessions.tmux"
  assert_success
  run _bind_key_invocation
  assert_output --partial "TMUX_SESSIONS_MAX_DEPTH='8'"
  assert_output --partial "TMUX_SESSIONS_SCORE_HALF_LIFE='30'"
  assert_output --partial "TMUX_SESSIONS_SCORE_PATH_BOOST='2.5'"
}

@test "tmux-sessions.tmux exposes TMUX_PLUGIN_DIR as an absolute path" {
  stub_tmux_options ""
  run bash "$PLUGIN_ROOT/tmux-sessions.tmux"
  assert_success
  run _bind_key_invocation
  # Should reference the plugin directory (absolute path containing /scripts/sessions.sh).
  assert_output --partial "TMUX_PLUGIN_DIR='$PLUGIN_ROOT'"
  assert_output --partial "$PLUGIN_ROOT/scripts/sessions.sh"
}
