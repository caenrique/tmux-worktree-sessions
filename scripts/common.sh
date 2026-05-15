#!/usr/bin/env bash
# Shared utilities sourced by sessions.sh and fetch_reload.sh.
# Also contains all git-worktree helpers so sessions.sh can create
# worktrees without additional scripts.

# Shared fzf style flags (no --tmux; used for inline prompts inside execute).
FZF_INLINE="--reverse --no-scrollbar --no-info --no-separator --no-border --color header:#6c7086"
# Full-height tmux popup with the same chrome.
FZF_POPUP="--tmux bottom,100%,100% --scheme=path $FZF_INLINE"

# Icons used across picker lists (TMUX_SESSIONS_ICON_STYLE: nerd|emoji|ascii; default: nerd).
case "${TMUX_SESSIONS_ICON_STYLE:-nerd}" in
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

# ── String utilities ──────────────────────────────────────────────────────────

# Strip ANSI colour escape sequences from a string.
strip_ansi() { printf '%s' "$1" | sed $'s/\033\\[[0-9;]*m//g'; }

# Trim leading/trailing whitespace and replace internal spaces with dashes.
# Used to normalise user-entered branch and session names.
sanitize_name() { printf '%s' "$1" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//;s/[[:space:]]/-/g'; }

# Derive a short tmux session name from a filesystem path.
#
# Transformations applied in order:
#   1. Strip each prefix in TMUX_SESSIONS_STRIP_PREFIXES (longest-matching first)
#   2. Abbreviate the home directory with ~
#
# Dots are kept as-is.  All tmux operations use session IDs ($N) rather than
# names as targets, so dots are safe.
format_session_name() {
  local session_name="$1"

  # Strip longest-matching configured prefix first.
  local prefix
  for prefix in ${TMUX_SESSIONS_STRIP_PREFIXES:-}; do
    prefix="${prefix/#\~/$HOME}"
    if [[ "$session_name" == "$prefix/"* ]]; then
      session_name="${session_name#$prefix/}"
      break
    fi
  done

  # Replace the home directory path with a tilde. Done with prefix-strip + concat
  # rather than ${var/#$HOME/~}: bash 5 tilde-expands the replacement, undoing the
  # substitution on Linux while working "by accident" on bash 3.2 (macOS).
  if [[ "$session_name" == "$HOME" || "$session_name" == "$HOME"/* ]]; then
    session_name="~${session_name#"$HOME"}"
  fi
  echo "$session_name"
}

# Return the tmux session ID ($N) for a session with the given exact name.
# Returns an empty string if no matching session exists.
#
# Uses 'tmux ls' with awk exact-match to avoid tmux's '/' parsing (which
# interprets a slash as the session:window separator in -t targets).
# tmux silently replaces '.' with '_' when storing session names, so the
# lookup uses the same substitution.
get_session_id() {
  local session_name="${1//./_}"
  tmux ls -F "#{session_name}"$'\t'"#{session_id}" 2>/dev/null \
    | awk -F'\t' -v n="$session_name" '$1 == n { print $2 }'
}

# Switch to (or create) a tmux session for the given directory.
#
# Args:
#   $1  session_path  — working directory for the new or existing session
#   $2  session_name  — (optional) explicit session name; derived from $1 via
#                       format_session_name when omitted
#
# All targeting uses session IDs rather than names so that '/' inside names is
# never misread as the tmux session:window separator.
switch_or_create_session() {
  local session_path="$1"
  local session_name="${2:-$(format_session_name "$1")}"

  local session_id
  session_id=$(get_session_id "$session_name")

  if [[ -z "$session_id" ]]; then
    session_id=$(tmux new-session -c "$session_path" -s "$session_name" -d \
      -P -F '#{session_id}')
  fi

  tmux switch-client -t "$session_id"
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
  local session_name="$1"
  local now half_life
  now=$(date +%s)
  half_life=$(( ${TMUX_SESSIONS_SCORE_HALF_LIFE:-14} * 24 * 3600 ))

  mkdir -p "$(dirname "$SCORE_FILE")"
  [[ -f "$SCORE_FILE" ]] || touch "$SCORE_FILE"

  local tmp
  tmp=$(mktemp)

  awk -F'\t' -v OFS='\t' \
      -v name="$session_name" -v now="$now" -v hl="$half_life" '
    $1 == name {
      elapsed = now - ($3 + 0)
      if (elapsed < 0) elapsed = 0
      decay = exp(-0.693147 * elapsed / hl)
      print $1, ($2 + 0) * decay + 1, now
      found = 1
      next
    }
    { print }
    END { if (!found) print name, 1, now }
  ' "$SCORE_FILE" > "$tmp" && mv "$tmp" "$SCORE_FILE"
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
  PYTHONPATH="$_PLUGIN_SCRIPTS_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m tmux_sessions score sort "${1:-}"
}

# ── Project discovery ─────────────────────────────────────────────────────────

# Emit one "session_name<TAB>path" line per git repo found under the configured
# project directories.  Manual sessions are NOT included here; sessions.sh
# appends them via TMUX_SESSIONS_MANUAL_SESSIONS.
#
# Uses fd when available; falls back to find.
# Controlled by TMUX_SESSIONS_PROJECTS_DIRS and TMUX_SESSIONS_MAX_DEPTH.
list_git_projects() {
  local _max_depth="${TMUX_SESSIONS_MAX_DEPTH:-6}"
  local _dirs=()
  local _d
  for _d in ${TMUX_SESSIONS_PROJECTS_DIRS:-$HOME/Projects}; do
    _d="${_d/#\~/$HOME}"
    [[ -d "$_d" ]] && _dirs+=("$_d")
  done

  [[ ${#_dirs[@]} -eq 0 ]] && return

  if command -v fd &>/dev/null; then
    fd \
      -H "^.git$" -td -tf \
      --max-depth="$_max_depth" \
      --prune \
      --format "{//}" \
      -E node_modules \
      "${_dirs[@]}"
  else
    for _d in "${_dirs[@]}"; do
      find "$_d" -maxdepth "$_max_depth" \
        \( -name "node_modules" -prune \) -o \
        \( -name ".git" -print \) 2>/dev/null \
        | sed 's|/\.git$||'
    done
  fi \
  | while IFS= read -r path; do
      printf "%s\t%s\n" "$(format_session_name "$path")" "$path"
    done
}

# ── Git worktree helpers ──────────────────────────────────────────────────────

# Return the remote to use for a repo: "origin" if configured, otherwise the
# first remote listed by git remote.  Returns empty if no remotes exist.
_resolve_remote() {
  local remotes
  remotes=$(git -C "$1" remote 2>/dev/null) || return
  [[ -z "$remotes" ]] && return
  printf '%s\n' "$remotes" | grep -qx 'origin' && echo 'origin' \
    || printf '%s\n' "$remotes" | head -1
}

# Return the name of the default remote branch (e.g. "main" or "master").
# Reads refs/remotes/<remote>/HEAD, which git sets after 'git remote set-head'.
get_default_branch() {
  local remote
  remote=$(_resolve_remote "$1")
  [[ -z "$remote" ]] && return
  git -C "$1" symbolic-ref "refs/remotes/$remote/HEAD" 2>/dev/null \
    | sed 's|.*/||'
}

# List branches available for a new worktree checkout.
# Outputs local branch names first, then remote-only branches prefixed with
# "origin/" so the user can distinguish them.
list_branches() {
  local repo_path="$1"
  local remote
  remote=$(_resolve_remote "$repo_path")
  local local_branches remote_branches remote_only

  local_branches=$(git -C "$repo_path" branch --format '%(refname:short)')
  remote_branches=$(git -C "$repo_path" branch -r --format '%(refname:short)' \
    | grep "^$remote/" \
    | grep -v "^$remote/HEAD$")

  remote_only=$(comm -23 \
    <(printf '%s\n' "$remote_branches" | sed "s|^$remote/||" | sort) \
    <(printf '%s\n' "$local_branches"  | sort) \
    | sed "s|^|$remote/|")

  { printf '%s\n' "$local_branches"; printf '%s\n' "$remote_only"; } \
    | grep -v '^$'
}

# Convert a branch name to a safe directory name.
#   /       → -   (feature/login → feature-login)
#   (space) → -
branch_to_dir() {
  local name="${1//\//-}"
  echo "${name// /-}"
}

# List the worktrees belonging to the same repo as $repo_path.
# Outputs one "path<TAB>branch" line per worktree.
list_worktrees() {
  local repo_path="$1"
  git -C "$repo_path" worktree list --porcelain | awk '
    /^worktree /  { path = $2; branch = "" }
    /^branch /    { branch = $2; sub("refs/heads/", "", branch) }
    /^detached$/  { branch = "(detached)" }
    /^$/ {
      if (path != "") {
        print path "\t" (branch ? branch : "(detached)")
        path = ""
      }
    }
    END {
      if (path != "") print path "\t" (branch ? branch : "(detached)")
    }
  '
}

# Create a git worktree under $container for the given branch or new name.
# All git output is redirected to stderr so stdout stays clean for callers.
# Returns the new (or existing) worktree path on stdout.
add_worktree() {
  local repo_path="$1"
  local container="$2"
  local branch="$3"    # existing branch (may be "origin/foo" for remote-only)
  local new_name="$4"  # new branch name (mutually exclusive with $branch)
  local remote
  remote=$(_resolve_remote "$repo_path")

  local dir_name worktree_path default_branch

  if [[ -n "$new_name" ]]; then
    dir_name=$(branch_to_dir "$new_name")
    worktree_path="$container/$dir_name"
    default_branch=$(get_default_branch "$repo_path")
    default_branch="${default_branch:-${TMUX_SESSIONS_DEFAULT_BRANCH:-main}}"
    git -C "$repo_path" worktree add \
      -b "$new_name" "$worktree_path" "$remote/${default_branch}" >&2 \
      || return 1
  else
    local local_branch="${branch#$remote/}"
    local existing_path
    existing_path=$(list_worktrees "$repo_path" \
      | awk -F'\t' -v b="$local_branch" '$2 == b { print $1; exit }')
    if [[ -n "$existing_path" ]]; then
      echo "$existing_path"
      return 0
    fi
    dir_name=$(branch_to_dir "$local_branch")
    worktree_path="$container/$dir_name"
    if [[ "$branch" == $remote/* ]]; then
      git -C "$repo_path" worktree add -b "$local_branch" "$worktree_path" "$branch" >&2 || return 1
    else
      git -C "$repo_path" worktree add "$worktree_path" "$branch" >&2 || return 1
    fi
  fi

  echo "$worktree_path"
}

# Rename a worktree: renames the git branch, moves the directory, repairs the
# worktree linkage, and opens a fresh tmux session at the new path.
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

  local new_dir new_wt_path
  new_dir=$(branch_to_dir "$new_name")
  new_wt_path="$container/$new_dir"

  if [[ -e "$new_wt_path" ]]; then
    echo "Destination already exists: $new_wt_path" >&2
    return 1
  fi

  git -C "$wt_path" branch -m "$old_branch" "$new_name" >&2 || return 1

  mv "$wt_path" "$new_wt_path" || {
    git -C "$wt_path" branch -m "$new_name" "$old_branch" >&2 2>/dev/null
    return 1
  }

  git -C "$new_wt_path" worktree repair >&2

  local old_session_id pane_root
  old_session_id=$(get_session_id "$(format_session_name "$wt_path")")
  [[ -n "$old_session_id" ]] && tmux kill-session -t "$old_session_id" 2>/dev/null

  pane_root=$(git -C "$(tmux display-message -p '#{pane_current_path}')" \
    rev-parse --show-toplevel 2>/dev/null)
  [[ "$pane_root" == "$wt_path" ]] && switch_or_create_session "$new_wt_path"
}

# Emit tab-delimited branch picker entries for fzf: [new] sentinel + all branches.
_gen_branch_picker_entries() {
  local repo_path="$1"
  local remote
  remote=$(_resolve_remote "$repo_path")
  printf "[new]\t%s%snew branch\n" "$_ICON_NEW" "$_ICON_SEP"
  list_branches "$repo_path" | while IFS= read -r branch; do
    if [[ "$branch" == $remote/* ]]; then
      printf "%s\t%s%s%s\n" "$branch" "$_ICON_REMOTE" "$_ICON_SEP" "$branch"
    else
      printf "%s\t%s%s%s\n" "$branch" "$_ICON_BRANCH" "$_ICON_SEP" "$branch"
    fi
  done
}

# Return 0 if git fetch should run (FETCH_HEAD missing or >15 min old).
# Uses --git-common-dir so the check works correctly from inside linked worktrees.
_fetch_is_stale() {
  local repo_path="$1"
  local window=900  # 15 minutes
  local git_common fetch_head mtime now
  git_common=$(git -C "$repo_path" rev-parse --git-common-dir 2>/dev/null) || return 0
  [[ "$git_common" != /* ]] && git_common="$repo_path/$git_common"
  fetch_head="$git_common/FETCH_HEAD"
  [[ -f "$fetch_head" ]] || return 0
  # GNU stat -f means --file-system (multi-line output); BSD stat -f means --format.
  # Branch on uname so the wrong flag never gets a chance to "succeed".
  case "$(uname -s)" in
    Darwin|*BSD) mtime=$(stat -f %m "$fetch_head" 2>/dev/null) ;;
    *)           mtime=$(stat -c %Y "$fetch_head" 2>/dev/null) ;;
  esac
  [[ -z "$mtime" ]] && return 0
  now=$(date +%s)
  (( now - mtime > window ))
}

# Interactively pick a branch for a new worktree.
# Returns "new:<name>" or "existing:<branch>" on stdout with exit 0.
# Exit 1 = ctrl-bs (go back), exit 2 = Esc (close all).
#
# Opens fzf with --listen so a background process can push a reload after
# git fetch --all completes.  Auto-fetches only when FETCH_HEAD is stale
# (>15 min); ctrl-f triggers a manual refresh at any time.
pick_branch() {
  local repo_path="$1"
  local _port _tmpfile _refresh_script _fetch_pid=""
  _port=$(( 51200 + RANDOM % 14335 ))
  _tmpfile=$(mktemp)
  _refresh_script="$(dirname "${BASH_SOURCE[0]}")/fetch_reload.sh"
  local _HEADER_BASE="enter:checkout  ctrl-bs:back  ctrl-f:refresh"

  trap 'rm -f "$_tmpfile"; [[ -n "$_fetch_pid" ]] && kill "$_fetch_pid" 2>/dev/null' RETURN

  _gen_branch_picker_entries "$repo_path" > "$_tmpfile"

  local _initial_header="$_HEADER_BASE"
  if _fetch_is_stale "$repo_path"; then
    "$_refresh_script" "$repo_path" "$_tmpfile" "$_port" "$_HEADER_BASE" &
    _fetch_pid=$!
    _initial_header="$_HEADER_BASE [syncing...]"
  fi

  while true; do
    local selected rc
    selected=$(
      cat "$_tmpfile" | fzf $FZF_POPUP \
          --listen "$_port" \
          --with-nth 2 \
          --delimiter $'\t' \
          --prompt "Branch > " \
          --header "$_initial_header" \
          --expect "ctrl-bs" \
          --bind "ctrl-f:change-header($_HEADER_BASE ⟳ fetching...)+execute-silent('$_refresh_script' '$repo_path' '$_tmpfile' '$_port' '$_HEADER_BASE')"
    )
    rc=$?
    _initial_header="$_HEADER_BASE"

    [[ $rc -eq 130 ]] && return 2
    [[ -z "$selected" ]] && return 2

    local key item
    key=$(printf '%s' "$selected" | head -1)
    item=$(printf '%s' "$selected" | sed -n '2p' | cut -f1)
    [[ "$key" == "ctrl-bs" ]] && return 1
    [[ -z "$item" ]] && return 2

    if [[ "$item" == "[new]" ]]; then
      local name_output name_rc name_key new_name
      name_output=$(echo "" | fzf $FZF_POPUP \
        --print-query --no-select-1 \
        --prompt "New branch name: " \
        --header "enter:create  ctrl-bs:back" \
        --expect "ctrl-bs")
      name_rc=$?
      [[ $name_rc -eq 130 ]] && return 2
      name_key=$(printf '%s' "$name_output" | sed -n '2p')
      [[ "$name_key" == "ctrl-bs" ]] && continue
      new_name=$(sanitize_name "$(printf '%s' "$name_output" | head -1)")
      [[ -z "$new_name" ]] && continue
      echo "new:${new_name}"
      return 0
    else
      echo "existing:${item}"
      return 0
    fi
  done
}
