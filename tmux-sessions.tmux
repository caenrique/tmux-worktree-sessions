#!/usr/bin/env bash
# TPM entry point: reads @tmux-sessions-* options and binds the session picker key.

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_get() { tmux show-option -gqv "$1"; }

_key=$(_get @tmux-sessions-key);                    _key=${_key:-C-S-s}
_projects_dirs=$(_get @tmux-sessions-projects-dir); _projects_dirs=${_projects_dirs:-$HOME/Projects}
_scores_file=$(_get @tmux-sessions-scores-file);    _scores_file=${_scores_file:-$HOME/.local/share/tmux-sessions/scores.tsv}
_strip_prefixes=$(_get @tmux-sessions-strip-prefixes)
_manual_sessions=$(_get @tmux-sessions-manual-sessions)
_max_depth=$(_get @tmux-sessions-max-depth);         _max_depth=${_max_depth:-6}
_default_branch=$(_get @tmux-sessions-default-branch); _default_branch=${_default_branch:-main}
_half_life=$(_get @tmux-sessions-score-half-life);  _half_life=${_half_life:-14}
_path_boost=$(_get @tmux-sessions-score-path-boost); _path_boost=${_path_boost:-1.0}
_icon_style=$(_get @tmux-sessions-icon-style);       _icon_style=${_icon_style:-nerd}

# Expand literal $HOME that tmux does not expand in option values.
_projects_dirs="${_projects_dirs//\$HOME/$HOME}"
_scores_file="${_scores_file//\$HOME/$HOME}"
_strip_prefixes="${_strip_prefixes//\$HOME/$HOME}"
_manual_sessions="${_manual_sessions//\$HOME/$HOME}"

tmux bind-key -n "$_key" run-shell -b "\
  TMUX_SESSIONS_PROJECTS_DIRS='$_projects_dirs' \
  TMUX_SESSIONS_SCORES_FILE='$_scores_file' \
  TMUX_SESSIONS_STRIP_PREFIXES='$_strip_prefixes' \
  TMUX_SESSIONS_MANUAL_SESSIONS='$_manual_sessions' \
  TMUX_SESSIONS_MAX_DEPTH='$_max_depth' \
  TMUX_SESSIONS_DEFAULT_BRANCH='$_default_branch' \
  TMUX_SESSIONS_SCORE_HALF_LIFE='$_half_life' \
  TMUX_SESSIONS_SCORE_PATH_BOOST='$_path_boost' \
  TMUX_SESSIONS_ICON_STYLE='$_icon_style' \
  PYTHONPATH='$PLUGIN_DIR/scripts' \
  python3 -m tmux_sessions sessions manage"

# Status-bar widget: replace `#{session_display_name}` in status-left
# and status-right with a `#(...)` shell-command that calls
# `sessions display-name`. Single-quoted env values pass through to
# /bin/sh verbatim; double-quoted format tokens are substituted by
# tmux at status-redraw time. Substitution runs once at plugin-load,
# so users must set status-left/right before TPM's `run` line.
_widget='#{session_display_name}'
_widget_cmd="#(TMUX_SESSIONS_STRIP_PREFIXES='$_strip_prefixes' PYTHONPATH='$PLUGIN_DIR/scripts' python3 -m tmux_sessions sessions display-name \"#{session_path}\" \"#{session_name}\")"

for _option in status-left status-right; do
  _value=$(_get "$_option")
  case "$_value" in
    *"$_widget"*)
      tmux set-option -gq "$_option" "${_value//"$_widget"/$_widget_cmd}"
      ;;
  esac
done
