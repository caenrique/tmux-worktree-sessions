# Stub binary helpers — install programmable stand-ins for tmux/fzf/curl/fd
# at the front of PATH and provide helpers for tests to script their behaviour.
#
# Each stub writes one line per invocation to its log file (TSV: arg0\targ1\t...)
# and returns canned output based on env vars set by the test.

install_stubs() {
  local stub_dir="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$stub_dir"
  export TMUX_STUB_LOG="$BATS_TEST_TMPDIR/tmux.log"
  export FZF_STUB_STDIN_LOG="$BATS_TEST_TMPDIR/fzf.stdin.log"
  export FZF_STUB_INVOCATION_LOG="$BATS_TEST_TMPDIR/fzf.invocations.log"
  export FZF_STUB_QUEUE="$BATS_TEST_TMPDIR/fzf.queue"
  export FZF_STUB_EXIT_QUEUE="$BATS_TEST_TMPDIR/fzf.exit.queue"
  export CURL_STUB_LOG="$BATS_TEST_TMPDIR/curl.log"
  : > "$TMUX_STUB_LOG"
  : > "$FZF_STUB_STDIN_LOG"
  : > "$FZF_STUB_INVOCATION_LOG"
  : > "$FZF_STUB_QUEUE"
  : > "$FZF_STUB_EXIT_QUEUE"
  : > "$CURL_STUB_LOG"
  install_stub tmux
  install_stub fzf
  install_stub curl
  export PATH="$stub_dir:$PATH"
}

install_stub() {
  local name="$1"
  local stub_dir="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$stub_dir"
  cp "$PLUGIN_ROOT/tests/fixtures/bin/$name" "$stub_dir/$name"
  chmod +x "$stub_dir/$name"
}

remove_stub() {
  rm -f "$BATS_TEST_TMPDIR/bin/$1"
}

# ── tmux stub programming ────────────────────────────────────────────────────

# Configure the tmux stub's `tmux ls -F …` output. Pass TSV rows of
#   name<TAB>id<TAB>path
# Example: stub_tmux_sessions $'foo\t$1\t/tmp/foo\nbar\t$2\t/tmp/bar'
stub_tmux_sessions() {
  export TMUX_STUB_SESSIONS="$1"
}

stub_tmux_current_session() { export TMUX_STUB_CURRENT="$1"; }
stub_tmux_prev_session()    { export TMUX_STUB_PREV="$1"; }
stub_tmux_pane_path()       { export TMUX_STUB_PANE_PATH="$1"; }
stub_tmux_new_session_id()  { export TMUX_STUB_NEW_ID="$1"; }

# Provide a key=value mapping for `tmux show-option -gqv KEY`.
# Pass newline-separated lines.
stub_tmux_options() { export TMUX_STUB_OPTIONS="$1"; }

# Read tmux invocation log entries (TSV per line). Use grep over the result.
tmux_log() { cat "$TMUX_STUB_LOG"; }

# ── fzf stub programming ─────────────────────────────────────────────────────

# Append one canned response to the queue. Each call to fzf consumes the next.
# `output` is exactly what the stub will print to stdout (newlines preserved).
stub_fzf_response() {
  local output="$1" exit_code="${2:-0}"
  printf '%s\n###END###\n' "$output" >> "$FZF_STUB_QUEUE"
  printf '%s\n' "$exit_code" >> "$FZF_STUB_EXIT_QUEUE"
}

# Convenience: have fzf select a single line (no --expect key prefix).
stub_fzf_select() { stub_fzf_response "$1" 0; }

# Convenience: have fzf return as if Esc was pressed (130).
stub_fzf_esc() { stub_fzf_response "" 130; }

# Convenience: --expect mode response — first line is the key, second is the line.
stub_fzf_expect() {
  local key="$1" line="$2"
  stub_fzf_response "$(printf '%s\n%s' "$key" "$line")" 0
}

fzf_invocations() { cat "$FZF_STUB_INVOCATION_LOG"; }
fzf_stdin()       { cat "$FZF_STUB_STDIN_LOG"; }

# ── curl stub programming ────────────────────────────────────────────────────

curl_log() { cat "$CURL_STUB_LOG"; }
