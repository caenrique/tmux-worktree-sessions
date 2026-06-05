#!/usr/bin/env bash
# Session manager invoked by the tmux-sessions key binding.
# manage_sessions and the main entry point now exec the Python dispatcher;
# the bash shims below remain as thin passthroughs so the bats suite (which
# sources this file and calls the helpers directly) stays green until
# tests/*.bats is retired in Step 24 of docs/python-migration.md.

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

# Emit one "session_name<TAB>cwd" line per discoverable project, then one
# per manual session. TMUX_SESSIONS_MANUAL_SESSIONS is a space-separated list
# of "name:path" pairs; a leading ~ in the path is expanded to $HOME.
list_projects() {
  TMUX_SESSIONS_PROJECTS_DIRS="${TMUX_SESSIONS_PROJECTS_DIRS:-$HOME/Projects}" \
  TMUX_SESSIONS_MAX_DEPTH="${TMUX_SESSIONS_MAX_DEPTH:-6}" \
  TMUX_SESSIONS_STRIP_PREFIXES="${TMUX_SESSIONS_STRIP_PREFIXES:-}" \
  TMUX_SESSIONS_MANUAL_SESSIONS="${TMUX_SESSIONS_MANUAL_SESSIONS:-}" \
    _tmux_sessions_py sessions list-projects
}

# Emit the unified 4-field TSV list consumed by the picker.
build_entries() {
  SCORE_FILE="$SCORE_FILE" \
  TMUX_SESSIONS_ICON_STYLE="$_ICON_STYLE" \
  TMUX_SESSIONS_PROJECTS_DIRS="${TMUX_SESSIONS_PROJECTS_DIRS:-$HOME/Projects}" \
  TMUX_SESSIONS_MAX_DEPTH="${TMUX_SESSIONS_MAX_DEPTH:-6}" \
  TMUX_SESSIONS_STRIP_PREFIXES="${TMUX_SESSIONS_STRIP_PREFIXES:-}" \
  TMUX_SESSIONS_MANUAL_SESSIONS="${TMUX_SESSIONS_MANUAL_SESSIONS:-}" \
  TMUX_SESSIONS_SCORE_HALF_LIFE="${TMUX_SESSIONS_SCORE_HALF_LIFE:-14}" \
  TMUX_SESSIONS_SCORE_PATH_BOOST="${TMUX_SESSIONS_SCORE_PATH_BOOST:-1.0}" \
    _tmux_sessions_py sessions build-entries
}

# ── Action functions ──────────────────────────────────────────────────────────
# Called as: sessions.sh --action <name> <type> <id> <tmpfile>

_is_orphaned_worktree_dir() {
  _tmux_sessions_py sessions is-orphaned-worktree "$1"
}

_action_ctrl_d() {
  _tmux_sessions_py sessions action ctrl-d "$1" "$2" "$3"
}

_action_ctrl_x() {
  TMUX_SESSIONS_ICON_STYLE="$_ICON_STYLE" \
    _tmux_sessions_py sessions action ctrl-x "$1" "$2" "$3"
}

_action_ctrl_r() {
  SCORE_FILE="$SCORE_FILE" \
  TMUX_SESSIONS_ICON_STYLE="$_ICON_STYLE" \
  TMUX_SESSIONS_PROJECTS_DIRS="${TMUX_SESSIONS_PROJECTS_DIRS:-$HOME/Projects}" \
  TMUX_SESSIONS_MAX_DEPTH="${TMUX_SESSIONS_MAX_DEPTH:-6}" \
  TMUX_SESSIONS_STRIP_PREFIXES="${TMUX_SESSIONS_STRIP_PREFIXES:-}" \
  TMUX_SESSIONS_MANUAL_SESSIONS="${TMUX_SESSIONS_MANUAL_SESSIONS:-}" \
  TMUX_SESSIONS_SCORE_HALF_LIFE="${TMUX_SESSIONS_SCORE_HALF_LIFE:-14}" \
  TMUX_SESSIONS_SCORE_PATH_BOOST="${TMUX_SESSIONS_SCORE_PATH_BOOST:-1.0}" \
    _tmux_sessions_py sessions action ctrl-r "$1" "$2" "$3"
}

manage_sessions() {
  SCORE_FILE="$SCORE_FILE" \
  TMUX_SESSIONS_ICON_STYLE="$_ICON_STYLE" \
  TMUX_SESSIONS_PROJECTS_DIRS="${TMUX_SESSIONS_PROJECTS_DIRS:-$HOME/Projects}" \
  TMUX_SESSIONS_MAX_DEPTH="${TMUX_SESSIONS_MAX_DEPTH:-6}" \
  TMUX_SESSIONS_STRIP_PREFIXES="${TMUX_SESSIONS_STRIP_PREFIXES:-}" \
  TMUX_SESSIONS_MANUAL_SESSIONS="${TMUX_SESSIONS_MANUAL_SESSIONS:-}" \
  TMUX_SESSIONS_DEFAULT_BRANCH="${TMUX_SESSIONS_DEFAULT_BRANCH:-main}" \
  TMUX_SESSIONS_SCORE_HALF_LIFE="${TMUX_SESSIONS_SCORE_HALF_LIFE:-14}" \
  TMUX_SESSIONS_SCORE_PATH_BOOST="${TMUX_SESSIONS_SCORE_PATH_BOOST:-1.0}" \
  TMUX_PLUGIN_DIR="${TMUX_PLUGIN_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}" \
    _tmux_sessions_py sessions manage
}

# ── Entry point ───────────────────────────────────────────────────────────────
# Skip dispatch when this file is sourced (e.g. by tests) rather than executed.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  if [[ "${1:-}" == --action ]]; then
    case "$2" in
      ctrl-d) _action_ctrl_d "${@:3}" ;;
      ctrl-x) _action_ctrl_x "${@:3}" ;;
      ctrl-r) _action_ctrl_r "${@:3}" ;;
    esac
    exit
  fi

  # --display-name <session_path> <session_name>
  # For use in the tmux status bar to restore dots that tmux converted to
  # underscores. Delegates to the Python equivalent.
  if [[ "${1:-}" == --display-name ]]; then
    TMUX_SESSIONS_STRIP_PREFIXES="${TMUX_SESSIONS_STRIP_PREFIXES:-}" \
      _tmux_sessions_py sessions display-name "$2" "$3"
    exit
  fi

  manage_sessions
fi
