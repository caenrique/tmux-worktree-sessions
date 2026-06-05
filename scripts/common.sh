#!/usr/bin/env bash
# Shared utilities sourced by sessions.sh and fetch_reload.sh.
# Also contains all git-worktree helpers so sessions.sh can create
# worktrees without additional scripts.

# Shared fzf style flags (no --tmux; used for inline prompts inside execute).
FZF_INLINE="--reverse --no-scrollbar --no-info --no-separator --no-border --color header:#6c7086"
# Full-height tmux popup with the same chrome.
# shellcheck disable=SC2034  # consumed by sessions.sh after sourcing common.sh
FZF_POPUP="--tmux bottom,100%,100% --scheme=path $FZF_INLINE"

# Icons used across picker lists (TMUX_SESSIONS_ICON_STYLE: nerd|emoji|ascii; default: nerd).
# _ICON_STYLE caches the resolved style at source time so shims that pass
# it through to the Python layer don't depend on the env var still being
# set when the shim runs (bats tests scope the env override to source_common).
_ICON_STYLE="${TMUX_SESSIONS_ICON_STYLE:-nerd}"
case "$_ICON_STYLE" in
  nerd)
    _ICON_SESSION=" "
    _ICON_PROJECT=" "
    _ICON_BRANCH=" "
    _ICON_REMOTE=" "
    _ICON_NEW=" "
    ;;
  none)
    _ICON_SESSION=""
    _ICON_PROJECT=""
    _ICON_BRANCH=""
    _ICON_REMOTE=""
    _ICON_NEW=""
    ;;
  ascii)
    _ICON_SESSION="*"
    _ICON_PROJECT="."
    _ICON_BRANCH="-"
    _ICON_REMOTE="@"
    _ICON_NEW="+"
    ;;
  *)  # emoji
    _ICON_STYLE=emoji
    _ICON_SESSION="🖥️"
    _ICON_PROJECT="📦"
    _ICON_BRANCH="🌱"
    _ICON_REMOTE="☁️"
    _ICON_NEW="＋"
    ;;
esac
_ICON_SEP="${_ICON_SESSION:+ }"

# TSV file storing per-session pick scores for recency ranking.
SCORE_FILE="${TMUX_SESSIONS_SCORES_FILE:-$HOME/.local/share/tmux-sessions/scores.tsv}"

# Absolute path to this script's directory. Used as PYTHONPATH for the
# tmux_sessions Python package so `python3 -m tmux_sessions ...` resolves
# regardless of how common.sh was sourced.
_PLUGIN_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run `python3 -m tmux_sessions <args>` with PYTHONPATH set so the
# in-tree package is importable regardless of how the plugin was
# installed.
_tmux_sessions_py() {
  PYTHONPATH="$_PLUGIN_SCRIPTS_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m tmux_sessions "$@"
}

# ── String utilities ──────────────────────────────────────────────────────────

# Strip ANSI colour escape sequences from a string.
strip_ansi() { _tmux_sessions_py text strip-ansi "$1"; }

# Trim leading/trailing whitespace and replace internal spaces with dashes.
# Used to normalise user-entered branch and session names.
sanitize_name() { _tmux_sessions_py text sanitize-name "$1"; }

# Derive a short tmux session name from a filesystem path.
#
# Transformations applied in order:
#   1. Strip each prefix in TMUX_SESSIONS_STRIP_PREFIXES (longest-matching first)
#   2. Abbreviate the home directory with ~
#
# Dots are kept as-is.  All tmux operations use session IDs ($N) rather than
# names as targets, so dots are safe.
format_session_name() {
  TMUX_SESSIONS_STRIP_PREFIXES="${TMUX_SESSIONS_STRIP_PREFIXES:-}" \
    _tmux_sessions_py text format-session-name "$1"
}

# Return the tmux session ID ($N) for a session with the given exact name.
# Returns an empty string if no matching session exists.
get_session_id() { _tmux_sessions_py tmux session-id "$1"; }

# Switch to (or create) a tmux session for the given directory.
#
# Args:
#   $1  session_path  — working directory for the new or existing session
#   $2  session_name  — (optional) explicit session name; derived from $1 via
#                       format_session_name when omitted
switch_or_create_session() {
  TMUX_SESSIONS_STRIP_PREFIXES="${TMUX_SESSIONS_STRIP_PREFIXES:-}" \
    _tmux_sessions_py tmux switch-or-create "$1" "${2:-}"
}

# Increment the pick score for a session name, decaying the stored value first.
#
# Score formula:
#   new_score = old_score × e^(−ln2 × elapsed_seconds / half_life) + 1
#
# Half-life defaults to 7 days (604800 s); configurable via
# TMUX_SESSIONS_SCORE_HALF_LIFE (days).
#
# Storage: $SCORE_FILE — tab-separated columns: session_name, score, unix_ts
update_score() {
  SCORE_FILE="$SCORE_FILE" \
  TMUX_SESSIONS_SCORE_HALF_LIFE="${TMUX_SESSIONS_SCORE_HALF_LIFE:-14}" \
    _tmux_sessions_py score update "$1"
}

# Read "session_name<TAB>rest..." lines from stdin, sort them by current pick
# score (highest first), and write the same format to stdout.
#
# Optional arg: boost_path
#   Entries whose third TAB-delimited field shares a longer path prefix with
#   boost_path get an additive score boost, so same-repo worktrees outrank
#   same-org projects.
sort_by_score() {
  SCORE_FILE="$SCORE_FILE" \
  TMUX_SESSIONS_SCORE_HALF_LIFE="${TMUX_SESSIONS_SCORE_HALF_LIFE:-14}" \
  TMUX_SESSIONS_SCORE_PATH_BOOST="${TMUX_SESSIONS_SCORE_PATH_BOOST:-1.0}" \
    _tmux_sessions_py score sort "${1:-}"
}

# ── Project discovery ─────────────────────────────────────────────────────────

# Emit one "session_name<TAB>path" line per git repo found under the configured
# project directories.  Manual sessions are NOT included here; sessions.sh
# appends them via TMUX_SESSIONS_MANUAL_SESSIONS.
#
# Uses fd when available; falls back to find.
# Controlled by TMUX_SESSIONS_PROJECTS_DIRS and TMUX_SESSIONS_MAX_DEPTH.
list_git_projects() {
  TMUX_SESSIONS_PROJECTS_DIRS="${TMUX_SESSIONS_PROJECTS_DIRS:-$HOME/Projects}" \
  TMUX_SESSIONS_MAX_DEPTH="${TMUX_SESSIONS_MAX_DEPTH:-6}" \
  TMUX_SESSIONS_STRIP_PREFIXES="${TMUX_SESSIONS_STRIP_PREFIXES:-}" \
    _tmux_sessions_py git list-projects
}

# ── Git worktree helpers ──────────────────────────────────────────────────────

# Return the remote to use for a repo: "origin" if configured, otherwise the
# first remote listed by git remote.  Returns empty if no remotes exist.
_resolve_remote() { _tmux_sessions_py git resolve-remote "$1"; }

# Return the name of the default remote branch (e.g. "main" or "master").
# Reads refs/remotes/<remote>/HEAD, which git sets after 'git remote set-head'.
get_default_branch() { _tmux_sessions_py git default-branch "$1"; }

# List branches available for a new worktree checkout.
# Outputs local branch names first, then remote-only branches prefixed with
# "origin/" so the user can distinguish them.
list_branches() { _tmux_sessions_py git list-branches "$1"; }

# Convert a branch name to a safe directory name.
#   /       → -   (feature/login → feature-login)
#   (space) → -
branch_to_dir() { _tmux_sessions_py git branch-to-dir "$1"; }

# List the worktrees belonging to the same repo as $repo_path.
# Outputs one "path<TAB>branch" line per worktree.
list_worktrees() { _tmux_sessions_py git list-worktrees "$1"; }

# Create a git worktree under $container for the given branch or new name.
# All git output is redirected to stderr so stdout stays clean for callers.
# Returns the new (or existing) worktree path on stdout.
add_worktree() {
  TMUX_SESSIONS_DEFAULT_BRANCH="${TMUX_SESSIONS_DEFAULT_BRANCH:-main}" \
    _tmux_sessions_py git add-worktree "$1" "$2" "$3" "$4"
}

# Rename a worktree: prompts for a new name, then asks Python to rename the
# git branch, move the directory, and repair the worktree linkage. Bash still
# owns the fzf prompt and the post-rename tmux session switch.
rename_worktree() {
  local repo_path="$1"
  local container="$2"
  local wt_path="$3"

  local old_branch
  old_branch=$(git -C "$wt_path" branch --show-current 2>/dev/null)
  if [[ -z "$old_branch" ]]; then
    echo "Cannot rename: worktree is in detached HEAD state" >&2
    return 1
  fi

  local rename_output rename_rc rename_key new_name
  rename_output=$(echo "" | fzf $FZF_INLINE \
    --print-query --no-select-1 \
    --query "$old_branch" \
    --prompt "Rename to: " \
    --header "enter:rename  ctrl-bs:cancel" \
    --expect "ctrl-bs")
  rename_rc=$?
  [[ $rename_rc -eq 130 ]] && return 1
  rename_key=$(printf '%s' "$rename_output" | sed -n '2p')
  [[ "$rename_key" == "ctrl-bs" ]] && return 1
  new_name=$(sanitize_name "$(printf '%s' "$rename_output" | head -1)")
  [[ -z "$new_name" || "$new_name" == "$old_branch" ]] && return 1

  local new_wt_path
  new_wt_path=$(_tmux_sessions_py git rename-worktree \
    "$repo_path" "$container" "$wt_path" "$new_name") || return 1

  local old_session_id pane_root
  old_session_id=$(get_session_id "$(format_session_name "$wt_path")")
  [[ -n "$old_session_id" ]] && tmux kill-session -t "$old_session_id" 2>/dev/null

  pane_root=$(git -C "$(tmux display-message -p '#{pane_current_path}')" \
    rev-parse --show-toplevel 2>/dev/null)
  [[ "$pane_root" == "$wt_path" ]] && switch_or_create_session "$new_wt_path"
}

# Emit tab-delimited branch picker entries for fzf: [new] sentinel + all branches.
_gen_branch_picker_entries() {
  TMUX_SESSIONS_ICON_STYLE="$_ICON_STYLE" \
    _tmux_sessions_py picker branch-entries "$1"
}

# Return 0 if git fetch should run (FETCH_HEAD missing or >15 min old).
# Uses --git-common-dir so the check works correctly from inside linked worktrees.
_fetch_is_stale() { _tmux_sessions_py git fetch-is-stale "$1"; }

# Interactively pick a branch for a new worktree.
# Returns "new:<name>" or "existing:<branch>" on stdout with exit 0.
# Exit 1 = ctrl-bs (go back), exit 2 = Esc (close all).
pick_branch() {
  TMUX_SESSIONS_ICON_STYLE="$_ICON_STYLE" \
    _tmux_sessions_py picker pick-branch "$1" "$_PLUGIN_SCRIPTS_DIR/fetch_reload.sh"
}
