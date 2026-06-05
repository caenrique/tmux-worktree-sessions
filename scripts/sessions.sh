#!/usr/bin/env bash
# Session manager invoked by the tmux-sessions key binding.
# Shows a unified list: running sessions (green, sorted by recency) at the top,
# followed by projects without a session.  All actions are in a single fzf picker.
#   Enter     — switch to session / open project as new session
#   Ctrl-W    — open branch picker to create a worktree for the row's repo
#   Ctrl-D    — kill session + delete worktree; orphaned project dirs prompt to confirm
#   Ctrl-X    — kill session only; entry becomes a project row
#   Ctrl-R    — rename worktree (branch + dir + repair) if linked; session name otherwise
#   Ctrl-BS   — close picker

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

# Emit the unified 4-field TSV list consumed by manage_sessions.
# Format: type<TAB>key<TAB>search<TAB>display
#   - search:  clean fzf-matchable text (no icons, no colours, no
#              "(current)"/"(previous)" suffix). Sessions land here as their
#              bare display name so fzf's path scheme doesn't penalise the
#              decorated form. Projects land here as their format_session_name
#              path so the path scheme keeps boosting e.g. "playback-service"
#              over neighbours under "playback-services/".
#   - display: the rendered row (icon + colour + suffix); fzf is told to
#              show this column via --with-nth 4.
#
#   s <TAB> stripped_id <TAB> session_name <TAB> <green>icon session_name [(current)|(previous)]<reset>
#   p <TAB> path        <TAB> display_name <TAB> icon display_name
#   n <TAB>             <TAB> new session  <TAB> icon new session
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

# Return 0 if path looks like an orphaned worktree directory: its parent
# contains at least one other directory that is a git repo (.git present).
_is_orphaned_worktree_dir() {
  _tmux_sessions_py sessions is-orphaned-worktree "$1"
}

# ctrl-d: kill session + remove its worktree if applicable (session rows);
#         delete a linked worktree with no session (project rows);
#         prompt to delete if dir looks like an orphaned worktree.
_action_ctrl_d() {
  local type="$1" id="$2" tmpfile="$3"

  if [[ "$type" == "s" ]]; then
    local tmux_id="\$$id"
    local sess_path
    sess_path=$(tmux display-message -p -t "$tmux_id" '#{session_path}' 2>/dev/null)
    tmux kill-session -t "$tmux_id" 2>/dev/null
    local git_dir
    git_dir=$(git -C "$sess_path" rev-parse --git-dir 2>/dev/null)
    grep -v $'^s\t'"$id"$'\t' "$tmpfile" > "${tmpfile}.new" && mv "${tmpfile}.new" "$tmpfile"
    if [[ "$git_dir" == *"worktrees"* ]]; then
      local wt_repo
      wt_repo=$(git -C "$sess_path" rev-parse --show-toplevel 2>/dev/null)
      [[ -n "$wt_repo" ]] && git -C "$wt_repo" worktree remove --force "$sess_path" >&2 &
    fi

  elif [[ "$type" == "p" ]]; then
    local wt_path="$id"
    local git_dir
    git_dir=$(git -C "$wt_path" rev-parse --git-dir 2>/dev/null)
    if [[ "$git_dir" != *"worktrees"* ]]; then
      if _is_orphaned_worktree_dir "$wt_path"; then
        local answer
        answer=$(printf 'No\nYes' | fzf $FZF_INLINE \
          --no-sort \
          --prompt "Delete $(basename "$wt_path")? " \
          --header "directory is not git-linked — delete anyway?")
        [[ "$answer" != "Yes" ]] && return
        grep -v $'^p\t'"$(printf '%s' "$wt_path" | sed 's|[/\&]|\\&|g')"$'\t' \
          "$tmpfile" > "${tmpfile}.new" && mv "${tmpfile}.new" "$tmpfile"
        rm -rf "$wt_path" &
      else
        tmux display-message -d 2000 "ctrl-d: not a linked worktree"
      fi
      return
    fi
    local wt_repo
    wt_repo=$(git -C "$wt_path" rev-parse --show-toplevel 2>/dev/null)
    [[ -z "$wt_repo" ]] && return
    grep -v $'^p\t'"$(printf '%s' "$wt_path" | sed 's|[/\&]|\\&|g')"$'\t' \
      "$tmpfile" > "${tmpfile}.new" && mv "${tmpfile}.new" "$tmpfile"
    git -C "$wt_repo" worktree remove --force "$wt_path" >&2 &
  fi
}

# ctrl-x: kill session only; convert the entry to a project row in place.
_action_ctrl_x() {
  TMUX_SESSIONS_ICON_STYLE="$_ICON_STYLE" \
    _tmux_sessions_py sessions action ctrl-x "$1" "$2" "$3"
}

# ctrl-r: rename worktree (branch + dir + repair) when on a linked worktree;
#         rename tmux session only otherwise.
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
  local tmpfile
  tmpfile=$(mktemp)
  # shellcheck disable=SC2064  # tmpfile is local; expand now or it's gone at EXIT.
  trap "rm -f '$tmpfile' '${tmpfile}.new'" EXIT
  build_entries > "$tmpfile"

  local self="${BASH_SOURCE[0]}"

  while true; do
    local output fzf_rc
    output=$(
      cat "$tmpfile" \
      | fzf $FZF_POPUP \
          --ansi \
          --with-nth 4 \
          --nth 3 \
          --tiebreak=index \
          --delimiter $'\t' \
          --prompt "Sessions > " \
          --expect "ctrl-w,ctrl-bs" \
          --header "enter:open ctrl-bs:back ?:preview ctrl-x:delete-session ctrl-r:rename ctrl-w:worktree ctrl-d:remove-worktree" \
          --preview "[ '{1}' = s ] \
                     && tmux capture-pane -e -p -t '\$'{2} 2>/dev/null \
                     || ls '{2}' 2>/dev/null" \
          --preview-window "down:50%:border-top:nofollow:hidden" \
          --bind "?:toggle-preview" \
          --bind "ctrl-d:execute('$self' --action ctrl-d {1} {2} '$tmpfile')+reload(cat '$tmpfile')+pos({n})" \
          --bind "ctrl-x:execute-silent('$self' --action ctrl-x {1} {2} '$tmpfile')+reload(cat '$tmpfile')+pos({n})" \
          --bind "ctrl-r:execute('$self' --action ctrl-r {1} {2} '$tmpfile')+reload(cat '$tmpfile')+pos({n})"
    )
    fzf_rc=$?

    [[ $fzf_rc -eq 130 ]] && return 0  # Esc → close
    [[ -z "$output" ]]    && return 0

    local key line type key2 search
    key=$(printf '%s' "$output" | head -1)
    line=$(printf '%s' "$output" | sed -n '2p')
    type=$(printf '%s' "$line" | cut -f1)
    key2=$(printf '%s' "$line" | cut -f2)
    search=$(printf '%s' "$line" | cut -f3)

    [[ "$key" == "ctrl-bs" ]] && return 0

    # ── ctrl-w: create a worktree ─────────────────────────────────────────────
    if [[ "$key" == "ctrl-w" ]]; then
      local repo_path
      if [[ "$type" == "p" ]]; then
        repo_path=$(git -C "$key2" rev-parse --show-toplevel 2>/dev/null)
      else
        local tmux_id="\$${key2}"
        local sess_path
        sess_path=$(tmux display-message -p -t "$tmux_id" '#{session_path}' 2>/dev/null)
        repo_path=$(git -C "$sess_path" rev-parse --show-toplevel 2>/dev/null)
      fi
      if [[ -n "$repo_path" ]]; then
        local container result wt_path pick_rc
        container=$(git -C "$repo_path" worktree list --porcelain \
          | awk '/^worktree /{print $2; exit}' \
          | xargs dirname)
        result=$(pick_branch "$repo_path")
        pick_rc=$?
        [[ $pick_rc -eq 2 ]] && return 0  # Esc → close all
        if [[ $pick_rc -eq 0 ]]; then
          if [[ "$result" == new:* ]]; then
            wt_path=$(add_worktree "$repo_path" "$container" "" "${result#new:}") || continue
          else
            wt_path=$(add_worktree "$repo_path" "$container" "${result#existing:}" "") || continue
          fi
          update_score "$(format_session_name "$wt_path")"
          switch_or_create_session "$wt_path"
          return 0
        fi
      fi
      continue
    fi

    # ── New session sentinel: Enter ───────────────────────────────────────────
    if [[ "$type" == "n" ]]; then
      local name_output name_key new_name
      name_output=$(echo "" | fzf $FZF_POPUP \
        --print-query --no-select-1 \
        --prompt "Session name: " \
        --header "enter:create  ctrl-bs:cancel" \
        --expect "ctrl-bs")
      local name_rc=$?
      [[ $name_rc -eq 130 ]] && continue
      name_key=$(printf '%s' "$name_output" | sed -n '2p')
      [[ "$name_key" == "ctrl-bs" ]] && continue
      new_name=$(sanitize_name "$(printf '%s' "$name_output" | head -1)")
      [[ -z "$new_name" ]] && continue
      update_score "$new_name"
      switch_or_create_session "$HOME" "$new_name"
      return 0
    fi

    # ── Project row: Enter ────────────────────────────────────────────────────
    if [[ "$type" == "p" ]]; then
      update_score "$search"
      switch_or_create_session "$key2" "$search"
      return 0

    # ── Session row: Enter ────────────────────────────────────────────────────
    else
      local tmux_id="\$${key2}"
      tmux switch-client -t "$tmux_id"
      return 0
    fi
  done
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
  # For use in the tmux status bar to restore dots that tmux converted to underscores.
  if [[ "${1:-}" == --display-name ]]; then
    derived=$(format_session_name "$2")
    [[ "${derived//./_}" == "$3" ]] && printf '%s' "$derived" || printf '%s' "$3"
    exit
  fi

  manage_sessions
fi
