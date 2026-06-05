#!/usr/bin/env bash
# Background fetch + fzf reload helper invoked by pick_branch.
# Args: $1=repo_path  $2=tmpfile  $3=fzf_port  $4=header_base
#
# Forking happens inside the Python CLI (cmd_fetch_reload) so callers
# (fzf's execute-silent) return at once while the work continues.

source "$(dirname "$0")/common.sh"

_tmux_sessions_py fetch-reload "$@"
