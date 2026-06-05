"""CLI dispatcher for the tmux_sessions package.

This module owns every form of implicit I/O: argparse subcommand
registration, environment-variable lookup, ``sys.stdin``/``stdout``,
config/state file reads and writes, ``time.time()``, and exit codes.
Each ``cmd_<group>_<verb>`` handler resolves these concerns once and
calls into the pure layer with explicit parameters.

Future migration steps add their own ``cmd_*`` handlers here. We keep
all CLI handlers co-located so the I/O surface is easy to scan; we'll
shard into ``cli/<group>.py`` only if this module ever gets unwieldy.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import secrets
import shlex
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from . import fetch_reload, git, picker, score, sessions, text, tmux


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tmux_sessions",
        description="tmux-sessions Python helpers",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    score_p = sub.add_parser("score", help="score storage and sorting")
    score_sub = score_p.add_subparsers(dest="score_command", metavar="<subcommand>")

    sort_p = score_sub.add_parser("sort", help="sort TSV input by score (highest first)")
    sort_p.add_argument(
        "boost_path",
        nargs="?",
        default="",
        help="path used for the path-similarity boost; empty disables",
    )
    sort_p.set_defaults(handler=cmd_score_sort)

    update_p = score_sub.add_parser(
        "update",
        help="increment the pick score for a session name",
    )
    update_p.add_argument("name", help="session name whose score to bump")
    update_p.set_defaults(handler=cmd_score_update)

    text_p = sub.add_parser("text", help="text utilities")
    text_sub = text_p.add_subparsers(dest="text_command", metavar="<subcommand>")

    strip_p = text_sub.add_parser("strip-ansi", help="strip ANSI SGR escape sequences")
    strip_p.add_argument("text", help="input string")
    strip_p.set_defaults(handler=cmd_text_strip_ansi)

    sanitize_p = text_sub.add_parser(
        "sanitize-name",
        help="trim whitespace and replace internal whitespace with dashes",
    )
    sanitize_p.add_argument("text", help="input string")
    sanitize_p.set_defaults(handler=cmd_text_sanitize_name)

    fsn_p = text_sub.add_parser(
        "format-session-name",
        help="derive a short session name from a filesystem path",
    )
    fsn_p.add_argument("path", help="filesystem path")
    fsn_p.set_defaults(handler=cmd_text_format_session_name)

    git_p = sub.add_parser("git", help="git helpers")
    git_sub = git_p.add_subparsers(dest="git_command", metavar="<subcommand>")

    branch_to_dir_p = git_sub.add_parser(
        "branch-to-dir",
        help="convert a branch name to a safe directory name",
    )
    branch_to_dir_p.add_argument("name", help="branch name")
    branch_to_dir_p.set_defaults(handler=cmd_git_branch_to_dir)

    resolve_remote_p = git_sub.add_parser(
        "resolve-remote",
        help="print 'origin' if configured, else the first listed remote",
    )
    resolve_remote_p.add_argument("repo", help="path to the git repo")
    resolve_remote_p.set_defaults(handler=cmd_git_resolve_remote)

    default_branch_p = git_sub.add_parser(
        "default-branch",
        help="print the default remote branch name (e.g. main)",
    )
    default_branch_p.add_argument("repo", help="path to the git repo")
    default_branch_p.set_defaults(handler=cmd_git_default_branch)

    list_branches_p = git_sub.add_parser(
        "list-branches",
        help="print local branches then remote-only branches with <remote>/ prefix",
    )
    list_branches_p.add_argument("repo", help="path to the git repo")
    list_branches_p.set_defaults(handler=cmd_git_list_branches)

    list_worktrees_p = git_sub.add_parser(
        "list-worktrees",
        help="print one path<TAB>branch line per worktree",
    )
    list_worktrees_p.add_argument("repo", help="path to the git repo")
    list_worktrees_p.set_defaults(handler=cmd_git_list_worktrees)

    add_worktree_p = git_sub.add_parser(
        "add-worktree",
        help="create or reuse a worktree; print its path",
    )
    add_worktree_p.add_argument("repo", help="path to the git repo")
    add_worktree_p.add_argument("container", help="directory under which to create the worktree")
    add_worktree_p.add_argument(
        "branch",
        help="existing branch (may be <remote>/<name>); empty string to create a new branch",
    )
    add_worktree_p.add_argument(
        "new_name",
        help="new branch name to create; empty string when reusing an existing branch",
    )
    add_worktree_p.set_defaults(handler=cmd_git_add_worktree)

    list_projects_p = git_sub.add_parser(
        "list-projects",
        help="emit session_name<TAB>path for each git project under the configured roots",
    )
    list_projects_p.set_defaults(handler=cmd_git_list_projects)

    fetch_is_stale_p = git_sub.add_parser(
        "fetch-is-stale",
        help="exit 0 if FETCH_HEAD is missing or older than --window seconds",
    )
    fetch_is_stale_p.add_argument("repo", help="path to the git repo")
    fetch_is_stale_p.add_argument(
        "--window", type=int, default=900, help="staleness threshold in seconds (default 900)"
    )
    fetch_is_stale_p.set_defaults(handler=cmd_git_fetch_is_stale)

    rename_worktree_p = git_sub.add_parser(
        "rename-worktree",
        help="rename a worktree's branch and move its directory; print the new path",
    )
    rename_worktree_p.add_argument("repo", help="path to the parent git repo")
    rename_worktree_p.add_argument("container", help="directory holding sibling worktrees")
    rename_worktree_p.add_argument("wt_path", help="current worktree path")
    rename_worktree_p.add_argument("new_name", help="post-prompt sanitised new branch name")
    rename_worktree_p.set_defaults(handler=cmd_git_rename_worktree)

    tmux_p = sub.add_parser("tmux", help="tmux helpers")
    tmux_sub = tmux_p.add_subparsers(dest="tmux_command", metavar="<subcommand>")

    session_id_p = tmux_sub.add_parser(
        "session-id",
        help="print the tmux session id ($N) for an exact session name",
    )
    session_id_p.add_argument("name", help="session name (dots are normalised to underscores)")
    session_id_p.set_defaults(handler=cmd_tmux_session_id)

    switch_or_create_p = tmux_sub.add_parser(
        "switch-or-create",
        help="switch to a session or create it first",
    )
    switch_or_create_p.add_argument("path", help="working directory for the session")
    switch_or_create_p.add_argument(
        "name",
        nargs="?",
        default="",
        help="session name; defaults to format-session-name(path)",
    )
    switch_or_create_p.set_defaults(handler=cmd_tmux_switch_or_create)

    picker_p = sub.add_parser("picker", help="branch/session picker helpers")
    picker_sub = picker_p.add_subparsers(dest="picker_command", metavar="<subcommand>")

    branch_entries_p = picker_sub.add_parser(
        "branch-entries",
        help="emit TSV rows for the branch picker ([new] sentinel + branches)",
    )
    branch_entries_p.add_argument("repo", help="path to the git repo")
    branch_entries_p.set_defaults(handler=cmd_picker_branch_entries)

    pick_branch_p = picker_sub.add_parser(
        "pick-branch",
        help="run the interactive fzf branch picker; print 'new:<name>' or 'existing:<branch>'",
    )
    pick_branch_p.add_argument("repo", help="path to the git repo")
    pick_branch_p.set_defaults(handler=cmd_picker_pick_branch)

    sessions_p = sub.add_parser("sessions", help="session picker helpers")
    sessions_sub = sessions_p.add_subparsers(dest="sessions_command", metavar="<subcommand>")

    sessions_list_p = sessions_sub.add_parser(
        "list-projects",
        help="emit session_name<TAB>path for git projects then manual sessions",
    )
    sessions_list_p.set_defaults(handler=cmd_sessions_list_projects)

    is_orphaned_p = sessions_sub.add_parser(
        "is-orphaned-worktree",
        help="exit 0 if path's parent contains a sibling git repo",
    )
    is_orphaned_p.add_argument("path", help="candidate worktree directory")
    is_orphaned_p.set_defaults(handler=cmd_sessions_is_orphaned_worktree)

    build_entries_p = sessions_sub.add_parser(
        "build-entries",
        help="emit the 4-column TSV the session picker consumes",
    )
    build_entries_p.set_defaults(handler=cmd_sessions_build_entries)

    action_p = sessions_sub.add_parser(
        "action",
        help="run a session-picker action (ctrl-x/ctrl-r/ctrl-d)",
    )
    action_sub = action_p.add_subparsers(dest="action_name", metavar="<name>")

    ctrl_x_p = action_sub.add_parser(
        "ctrl-x",
        help="kill a session and convert its row to a project row",
    )
    ctrl_x_p.add_argument("type", help="picker entry type: 's', 'p', or 'n'")
    ctrl_x_p.add_argument("id", help="session id (without leading $) or project path")
    ctrl_x_p.add_argument("tmpfile", help="picker entries tmpfile to mutate in place")
    ctrl_x_p.set_defaults(handler=cmd_sessions_action_ctrl_x)

    ctrl_r_p = action_sub.add_parser(
        "ctrl-r",
        help="rename a worktree (branch+dir+repair) or a tmux session",
    )
    ctrl_r_p.add_argument("type", help="picker entry type: 's', 'p', or 'n'")
    ctrl_r_p.add_argument("id", help="session id (without leading $) or project path")
    ctrl_r_p.add_argument("tmpfile", help="picker entries tmpfile to mutate in place")
    ctrl_r_p.set_defaults(handler=cmd_sessions_action_ctrl_r)

    ctrl_d_p = action_sub.add_parser(
        "ctrl-d",
        help="kill a session and/or remove its worktree; prompt on orphaned dirs",
    )
    ctrl_d_p.add_argument("type", help="picker entry type: 's', 'p', or 'n'")
    ctrl_d_p.add_argument("id", help="session id (without leading $) or project path")
    ctrl_d_p.add_argument("tmpfile", help="picker entries tmpfile to mutate in place")
    ctrl_d_p.set_defaults(handler=cmd_sessions_action_ctrl_d)

    manage_p = sessions_sub.add_parser(
        "manage",
        help="run the session-picker fzf loop (top-level entry point)",
    )
    manage_p.set_defaults(handler=cmd_sessions_manage)

    display_name_p = sessions_sub.add_parser(
        "display-name",
        help="round-trip a session name through format-session-name (status-bar helper)",
    )
    display_name_p.add_argument("path", help="session working directory")
    display_name_p.add_argument("name", help="session name as stored by tmux (dots → underscores)")
    display_name_p.set_defaults(handler=cmd_sessions_display_name)

    fetch_reload_p = sub.add_parser(
        "fetch-reload",
        help="background-fetch git, regenerate branch entries, post reload to fzf",
    )
    fetch_reload_p.add_argument("repo", help="path to the git repo")
    fetch_reload_p.add_argument("tmpfile", help="branch entries file fzf reads via reload(cat ...)")
    fetch_reload_p.add_argument("port", type=int, help="fzf --listen port to POST to")
    fetch_reload_p.add_argument("header_base", help="header text without the spinner suffix")
    fetch_reload_p.add_argument(
        "--no-fork",
        action="store_true",
        help="run synchronously without forking (used by tests)",
    )
    fetch_reload_p.set_defaults(handler=cmd_fetch_reload)

    return parser


def cmd_score_sort(args: argparse.Namespace) -> int:
    score_file = os.environ.get("SCORE_FILE", "")
    half_life_days = float(os.environ.get("TMUX_SESSIONS_SCORE_HALF_LIFE") or 14)
    path_boost = float(os.environ.get("TMUX_SESSIONS_SCORE_PATH_BOOST") or 1.0)

    if score_file:
        try:
            text = Path(score_file).read_text()
        except FileNotFoundError:
            text = ""
    else:
        text = ""

    entries = score.parse_score_table(text)
    scores = score.current_scores(
        entries,
        now=time.time(),
        half_life_secs=half_life_days * 24 * 3600,
    )
    ranked = score.sort_rows(
        sys.stdin.readlines(),
        boost_path=args.boost_path,
        scores=scores,
        path_boost=path_boost,
    )
    for line in ranked:
        sys.stdout.write(line)
        sys.stdout.write("\n")
    return 0


def cmd_score_update(args: argparse.Namespace) -> int:
    score_file = Path(os.environ.get("SCORE_FILE", ""))
    half_life_days = float(os.environ.get("TMUX_SESSIONS_SCORE_HALF_LIFE") or 14)
    half_life_secs = half_life_days * 24 * 3600
    now = float(int(time.time()))

    score_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        text_in = score_file.read_text()
    except FileNotFoundError:
        text_in = ""

    entries = score.parse_score_table(text_in)
    new_entries = score.merge_score(entries, name=args.name, now=now, half_life_secs=half_life_secs)

    tmp = score_file.with_name(score_file.name + ".tmp")
    tmp.write_text(score.format_score_table(new_entries))
    tmp.replace(score_file)
    return 0


def cmd_text_strip_ansi(args: argparse.Namespace) -> int:
    sys.stdout.write(text.strip_ansi(args.text))
    return 0


def cmd_text_sanitize_name(args: argparse.Namespace) -> int:
    sys.stdout.write(text.sanitize_name(args.text))
    return 0


def cmd_git_branch_to_dir(args: argparse.Namespace) -> int:
    sys.stdout.write(git.branch_to_dir(args.name))
    return 0


def cmd_git_resolve_remote(args: argparse.Namespace) -> int:
    remote = git.resolve_remote(Path(args.repo))
    if remote is not None:
        sys.stdout.write(remote)
        sys.stdout.write("\n")
    return 0


def cmd_git_default_branch(args: argparse.Namespace) -> int:
    branch = git.default_branch(Path(args.repo))
    if branch is not None:
        sys.stdout.write(branch)
        sys.stdout.write("\n")
    return 0


def cmd_git_list_branches(args: argparse.Namespace) -> int:
    for branch in git.list_branches(Path(args.repo)):
        sys.stdout.write(branch)
        sys.stdout.write("\n")
    return 0


def cmd_git_list_worktrees(args: argparse.Namespace) -> int:
    for wt in git.list_worktrees(Path(args.repo)):
        sys.stdout.write(f"{wt.path}\t{wt.branch}\n")
    return 0


def cmd_git_add_worktree(args: argparse.Namespace) -> int:
    fallback = os.environ.get("TMUX_SESSIONS_DEFAULT_BRANCH") or "main"
    path = git.add_worktree(
        Path(args.repo),
        Path(args.container),
        branch=args.branch or None,
        new_name=args.new_name or None,
        default_branch_fallback=fallback,
    )
    sys.stdout.write(str(path))
    sys.stdout.write("\n")
    return 0


def cmd_git_list_projects(args: argparse.Namespace) -> int:
    home = os.environ.get("HOME", "")
    raw_dirs = os.environ.get("TMUX_SESSIONS_PROJECTS_DIRS") or f"{home}/Projects"
    max_depth = int(os.environ.get("TMUX_SESSIONS_MAX_DEPTH") or 6)
    strip_prefixes = (os.environ.get("TMUX_SESSIONS_STRIP_PREFIXES") or "").split()

    roots: list[Path] = []
    for entry in raw_dirs.split():
        expanded = entry.replace("~", home, 1) if entry.startswith("~") else entry
        roots.append(Path(expanded))

    for project in git.list_git_projects(roots, max_depth=max_depth):
        name = text.format_session_name(str(project), home=home, strip_prefixes=strip_prefixes)
        sys.stdout.write(f"{name}\t{project}\n")
    return 0


def cmd_git_fetch_is_stale(args: argparse.Namespace) -> int:
    repo = Path(args.repo)
    common_dir_result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
    )
    if common_dir_result.returncode != 0:
        return 0
    common_dir = Path(common_dir_result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = repo / common_dir
    fetch_head = common_dir / "FETCH_HEAD"
    try:
        mtime: float | None = fetch_head.stat().st_mtime
    except FileNotFoundError:
        mtime = None
    stale = git.fetch_is_stale(mtime, now=time.time(), window_secs=args.window)
    return 0 if stale else 1


def cmd_git_rename_worktree(args: argparse.Namespace) -> int:
    try:
        new_path = git.rename_worktree(
            Path(args.repo),
            Path(args.container),
            Path(args.wt_path),
            new_name=args.new_name,
        )
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    sys.stdout.write(str(new_path))
    sys.stdout.write("\n")
    return 0


def cmd_tmux_session_id(args: argparse.Namespace) -> int:
    sid = tmux.session_id(args.name)
    if sid is not None:
        sys.stdout.write(sid)
        sys.stdout.write("\n")
    return 0


def cmd_tmux_switch_or_create(args: argparse.Namespace) -> int:
    name = args.name
    if not name:
        home = os.environ.get("HOME", "")
        strip_prefixes = (os.environ.get("TMUX_SESSIONS_STRIP_PREFIXES") or "").split()
        name = text.format_session_name(args.path, home=home, strip_prefixes=strip_prefixes)
    tmux.switch_or_create(Path(args.path), name)
    return 0


def cmd_picker_branch_entries(args: argparse.Namespace) -> int:
    style = os.environ.get("TMUX_SESSIONS_ICON_STYLE") or "nerd"
    icons = picker.IconSet.from_style(style)
    for line in picker.gen_branch_picker_entries(Path(args.repo), icons=icons):
        sys.stdout.write(line)
        sys.stdout.write("\n")
    return 0


def cmd_picker_pick_branch(args: argparse.Namespace) -> int:
    style = os.environ.get("TMUX_SESSIONS_ICON_STYLE") or "nerd"
    icons = picker.IconSet.from_style(style)
    # Random ephemeral port for fzf --listen, mirroring the bash range.
    listen_port = 51200 + secrets.randbelow(14336)
    choice = picker.pick_branch(
        Path(args.repo),
        icons=icons,
        fetch_reload_argv=_fetch_reload_argv(),
        listen_port=listen_port,
        now=time.time(),
    )
    if choice.kind == "back":
        return 1
    if choice.kind == "cancel":
        return 2
    sys.stdout.write(f"{choice.kind}:{choice.name}\n")
    return 0


def cmd_fetch_reload(args: argparse.Namespace) -> int:
    style = os.environ.get("TMUX_SESSIONS_ICON_STYLE") or "nerd"
    icons = picker.IconSet.from_style(style)
    repo = Path(args.repo)
    tmpfile = Path(args.tmpfile)

    if args.no_fork:
        fetch_reload.fetch_and_reload(repo, tmpfile, args.port, args.header_base, icons=icons)
        return 0

    # Fork once so fzf's execute-silent caller returns immediately while
    # we keep running. Parent exits 0; child detaches with setsid and
    # uses os._exit so atexit handlers and pytest's own cleanup never
    # run twice.
    pid = os.fork()
    if pid != 0:
        return 0
    try:
        os.setsid()
        fetch_reload.fetch_and_reload(repo, tmpfile, args.port, args.header_base, icons=icons)
        os._exit(0)
    except BaseException:
        os._exit(1)


def cmd_sessions_list_projects(args: argparse.Namespace) -> int:
    home = os.environ.get("HOME", "")
    raw_dirs = os.environ.get("TMUX_SESSIONS_PROJECTS_DIRS") or f"{home}/Projects"
    max_depth = int(os.environ.get("TMUX_SESSIONS_MAX_DEPTH") or 6)
    strip_prefixes = (os.environ.get("TMUX_SESSIONS_STRIP_PREFIXES") or "").split()
    manual_spec = os.environ.get("TMUX_SESSIONS_MANUAL_SESSIONS") or ""

    roots: list[Path] = []
    for entry in raw_dirs.split():
        expanded = entry.replace("~", home, 1) if entry.startswith("~") else entry
        roots.append(Path(expanded))

    for name, path in sessions.list_projects(
        roots,
        max_depth=max_depth,
        home=home,
        strip_prefixes=strip_prefixes,
        manual_spec=manual_spec,
    ):
        sys.stdout.write(f"{name}\t{path}\n")
    return 0


def cmd_sessions_is_orphaned_worktree(args: argparse.Namespace) -> int:
    path = Path(args.path)
    return 0 if sessions.is_orphaned_worktree(path, container=path.parent) else 1


def cmd_sessions_build_entries(args: argparse.Namespace) -> int:
    style = os.environ.get("TMUX_SESSIONS_ICON_STYLE") or "nerd"
    icons = picker.IconSet.from_style(style)
    config = _resolve_build_entries_config()
    for line in sessions.build_entries(icons=icons, **config):  # type: ignore[arg-type]
        sys.stdout.write(line)
        sys.stdout.write("\n")
    return 0


def _resolve_build_entries_config() -> dict[str, object]:
    """Pull the env-driven knobs that ``build_entries`` consumes.

    Shared between ``cmd_sessions_build_entries`` and the
    ``_action_ctrl_r`` worktree-rename branch, which has to rebuild the
    picker tmpfile after the rename moves the row's path.
    """
    home = os.environ.get("HOME", "")
    raw_dirs = os.environ.get("TMUX_SESSIONS_PROJECTS_DIRS") or f"{home}/Projects"
    max_depth = int(os.environ.get("TMUX_SESSIONS_MAX_DEPTH") or 6)
    strip_prefixes = (os.environ.get("TMUX_SESSIONS_STRIP_PREFIXES") or "").split()
    manual_spec = os.environ.get("TMUX_SESSIONS_MANUAL_SESSIONS") or ""
    half_life_days = float(os.environ.get("TMUX_SESSIONS_SCORE_HALF_LIFE") or 14)
    path_boost = float(os.environ.get("TMUX_SESSIONS_SCORE_PATH_BOOST") or 1.0)
    score_file = os.environ.get("SCORE_FILE", "")

    roots: list[Path] = []
    for entry in raw_dirs.split():
        expanded = entry.replace("~", home, 1) if entry.startswith("~") else entry
        roots.append(Path(expanded))

    if score_file:
        try:
            score_text = Path(score_file).read_text()
        except FileNotFoundError:
            score_text = ""
    else:
        score_text = ""
    score_entries = score.parse_score_table(score_text)

    return {
        "home": home,
        "strip_prefixes": strip_prefixes,
        "projects_roots": roots,
        "max_depth": max_depth,
        "manual_spec": manual_spec,
        "score_entries": score_entries,
        "now": time.time(),
        "half_life_secs": half_life_days * 24 * 3600,
        "path_boost": path_boost,
    }


def _prompt_rename(initial: str) -> str | None:
    """Drive the inline fzf rename prompt; return sanitised name or None.

    Mirrors the bash ``echo "" | fzf $FZF_INLINE --print-query --query
    "$initial" --expect ctrl-bs`` invocation: empty stdin, free-text
    query, optional ``ctrl-bs`` cancel. Returns ``None`` on Esc, on
    ctrl-bs, or when sanitisation produces an empty string.
    """
    result = subprocess.run(
        [
            "fzf",
            *picker.FZF_INLINE_FLAGS,
            "--print-query",
            "--no-select-1",
            "--query",
            initial,
            "--prompt",
            "Rename to: ",
            "--header",
            "enter:rename  ctrl-bs:cancel",
            "--expect",
            "ctrl-bs",
        ],
        input="",
        capture_output=True,
        text=True,
    )
    if result.returncode == 130:
        return None
    out_lines = result.stdout.split("\n")
    query = out_lines[0] if out_lines else ""
    key = out_lines[1] if len(out_lines) > 1 else ""
    if key == "ctrl-bs":
        return None
    sanitised = text.sanitize_name(query)
    return sanitised or None


def cmd_sessions_action_ctrl_x(args: argparse.Namespace) -> int:
    if args.type != "s":
        return 0
    style = os.environ.get("TMUX_SESSIONS_ICON_STYLE") or "nerd"
    icons = picker.IconSet.from_style(style)
    tmux_id = f"${args.id}"
    sess_path_result = subprocess.run(
        ["tmux", "display-message", "-p", "-t", tmux_id, "#{session_path}"],
        capture_output=True,
        text=True,
    )
    sess_path = sess_path_result.stdout.strip()
    subprocess.run(["tmux", "kill-session", "-t", tmux_id], capture_output=True)

    tmpfile = Path(args.tmpfile)
    lines = tmpfile.read_text().splitlines() if tmpfile.exists() else []
    new_lines = sessions.apply_ctrl_x(lines, sid=args.id, sess_path=sess_path, icons=icons)
    tmpfile.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))
    return 0


def cmd_sessions_action_ctrl_r(args: argparse.Namespace) -> int:
    if args.type == "s":
        tmux_id = f"${args.id}"
        target_path_result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", tmux_id, "#{session_path}"],
            capture_output=True,
            text=True,
        )
        target_path = target_path_result.stdout.strip()
    elif args.type == "p":
        target_path = args.id
    else:
        return 0

    git_dir_result = subprocess.run(
        ["git", "-C", target_path, "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
    )
    git_dir = git_dir_result.stdout.strip() if git_dir_result.returncode == 0 else ""

    style = os.environ.get("TMUX_SESSIONS_ICON_STYLE") or "nerd"
    icons = picker.IconSet.from_style(style)
    tmpfile = Path(args.tmpfile)

    if "worktrees" in git_dir:
        porcelain = subprocess.run(
            ["git", "-C", target_path, "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
        )
        main_wt = ""
        for porcelain_line in porcelain.stdout.splitlines():
            if porcelain_line.startswith("worktree "):
                main_wt = porcelain_line[len("worktree ") :]
                break
        if not main_wt:
            return 0
        container = str(Path(main_wt).parent)

        old_branch_result = subprocess.run(
            ["git", "-C", target_path, "branch", "--show-current"],
            capture_output=True,
            text=True,
        )
        old_branch = old_branch_result.stdout.strip()
        if not old_branch:
            sys.stderr.write("Cannot rename: worktree is in detached HEAD state\n")
            return 1
        new_name = _prompt_rename(old_branch)
        if not new_name or new_name == old_branch:
            return 0
        try:
            git.rename_worktree(
                Path(main_wt),
                Path(container),
                Path(target_path),
                new_name=new_name,
            )
        except RuntimeError as exc:
            sys.stderr.write(f"{exc}\n")
            return 1
        config = _resolve_build_entries_config()
        rebuilt = list(sessions.build_entries(icons=icons, **config))  # type: ignore[arg-type]
        tmpfile.write_text("\n".join(rebuilt) + ("\n" if rebuilt else ""))
        return 0

    if args.type == "s":
        lines = tmpfile.read_text().splitlines() if tmpfile.exists() else []
        clean_name = ""
        for line in lines:
            fields = line.split("\t")
            if len(fields) >= 3 and fields[0] == "s" and fields[1] == args.id:
                clean_name = fields[2]
                break
        new_name = _prompt_rename(clean_name)
        if not new_name or new_name == clean_name:
            return 0
        tmux_id = f"${args.id}"
        subprocess.run(
            ["tmux", "rename-session", "-t", tmux_id, new_name],
            capture_output=True,
        )
        new_lines = sessions.apply_ctrl_r_session_rename(lines, sid=args.id, new_name=new_name, icons=icons)
        tmpfile.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))
        return 0

    subprocess.run(
        ["tmux", "display-message", "-d", "2000", "ctrl-r: not a linked worktree"],
        capture_output=True,
    )
    return 0


def _git_dir(path: str) -> str:
    result = subprocess.run(
        ["git", "-C", path, "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_toplevel(path: str) -> str:
    result = subprocess.run(
        ["git", "-C", path, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _confirm_orphan_delete(wt_path: str) -> bool:
    """Drive the inline No/Yes fzf prompt for orphan-dir deletion.

    Mirrors the bash ``printf 'No\\nYes' | fzf $FZF_INLINE --no-sort
    --prompt "Delete $(basename "$wt_path")? "`` invocation.
    """
    result = subprocess.run(
        [
            "fzf",
            *picker.FZF_INLINE_FLAGS,
            "--no-sort",
            "--prompt",
            f"Delete {Path(wt_path).name}? ",
            "--header",
            "directory is not git-linked — delete anyway?",
        ],
        input="No\nYes",
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "Yes"


def cmd_sessions_action_ctrl_d(args: argparse.Namespace) -> int:
    tmpfile = Path(args.tmpfile)

    if args.type == "s":
        tmux_id = f"${args.id}"
        sess_path_result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", tmux_id, "#{session_path}"],
            capture_output=True,
            text=True,
        )
        sess_path = sess_path_result.stdout.strip()
        subprocess.run(["tmux", "kill-session", "-t", tmux_id], capture_output=True)

        lines = tmpfile.read_text().splitlines() if tmpfile.exists() else []
        new_lines = sessions.remove_session_row(lines, sid=args.id)
        tmpfile.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))

        git_dir = _git_dir(sess_path)
        if "worktrees" in git_dir:
            wt_repo = _git_toplevel(sess_path)
            if wt_repo:
                subprocess.run(
                    ["git", "-C", wt_repo, "worktree", "remove", "--force", sess_path],
                    capture_output=True,
                )
        return 0

    if args.type == "p":
        wt_path = args.id
        git_dir = _git_dir(wt_path)
        if "worktrees" not in git_dir:
            if sessions.is_orphaned_worktree(Path(wt_path), container=Path(wt_path).parent):
                if not _confirm_orphan_delete(wt_path):
                    return 0
                lines = tmpfile.read_text().splitlines() if tmpfile.exists() else []
                new_lines = sessions.remove_project_row(lines, path=wt_path)
                tmpfile.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))
                subprocess.run(["rm", "-rf", wt_path], capture_output=True)
            else:
                subprocess.run(
                    ["tmux", "display-message", "-d", "2000", "ctrl-d: not a linked worktree"],
                    capture_output=True,
                )
            return 0

        wt_repo = _git_toplevel(wt_path)
        if not wt_repo:
            return 0
        lines = tmpfile.read_text().splitlines() if tmpfile.exists() else []
        new_lines = sessions.remove_project_row(lines, path=wt_path)
        tmpfile.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))
        subprocess.run(
            ["git", "-C", wt_repo, "worktree", "remove", "--force", wt_path],
            capture_output=True,
        )
        return 0

    return 0


def cmd_sessions_display_name(args: argparse.Namespace) -> int:
    """Round-trip ``args.name`` through ``format-session-name``.

    tmux replaces dots with underscores when storing session names. The
    status bar uses this command to recover the original (dotted) form
    when it round-trips, falling back to the stored name when the user
    renamed the session by hand.
    """
    home = os.environ.get("HOME", "")
    strip_prefixes = (os.environ.get("TMUX_SESSIONS_STRIP_PREFIXES") or "").split()
    derived = text.format_session_name(args.path, home=home, strip_prefixes=strip_prefixes)
    sys.stdout.write(derived if derived.replace(".", "_") == args.name else args.name)
    return 0


def _read_lines(path: Path) -> list[str]:
    return path.read_text().splitlines() if path.exists() else []


def _container_for_repo(repo_path: str) -> str:
    """Return the directory holding sibling worktrees for ``repo_path``.

    Mirrors the bash one-liner ``git worktree list --porcelain | awk
    '/^worktree /{print $2; exit}' | xargs dirname``: the first
    ``worktree`` line points at the main checkout, whose parent is the
    container shared with linked worktrees.
    """
    result = subprocess.run(
        ["git", "-C", repo_path, "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            return str(Path(line[len("worktree ") :]).parent)
    return ""


def _prompt_new_session_name() -> str:
    """Drive the inline fzf prompt for the new-session sentinel.

    Returns the sanitised name, or ``""`` when the user cancels (Esc,
    ctrl-bs, or empty input). Mirrors the bash ``echo "" | fzf $FZF_POPUP
    --print-query --no-select-1 --prompt 'Session name: '`` invocation.
    """
    result = subprocess.run(
        [
            "fzf",
            *picker.FZF_POPUP_FLAGS,
            "--print-query",
            "--no-select-1",
            "--prompt",
            "Session name: ",
            "--header",
            "enter:create  ctrl-bs:cancel",
            "--expect",
            "ctrl-bs",
        ],
        input="",
        capture_output=True,
        text=True,
    )
    if result.returncode == 130:
        return ""
    out_lines = result.stdout.split("\n")
    query = out_lines[0] if out_lines else ""
    key = out_lines[1] if len(out_lines) > 1 else ""
    if key == "ctrl-bs":
        return ""
    return text.sanitize_name(query)


def _bump_score_and_switch(name: str, session_path: Path) -> None:
    """Bump the recency score for ``name`` and switch to (or create) the session.

    Resolves env knobs the same way ``cmd_score_update`` and
    ``cmd_tmux_switch_or_create`` do so the behaviour is identical to
    the ``update_score`` + ``switch_or_create_session`` pair the bash
    main loop ran in sequence.
    """
    score_file = Path(os.environ.get("SCORE_FILE", ""))
    half_life_days = float(os.environ.get("TMUX_SESSIONS_SCORE_HALF_LIFE") or 14)
    half_life_secs = half_life_days * 24 * 3600
    now = float(int(time.time()))

    if score_file:
        score_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            text_in = score_file.read_text()
        except FileNotFoundError:
            text_in = ""
        entries = score.parse_score_table(text_in)
        new_entries = score.merge_score(entries, name=name, now=now, half_life_secs=half_life_secs)
        tmp = score_file.with_name(score_file.name + ".tmp")
        tmp.write_text(score.format_score_table(new_entries))
        tmp.replace(score_file)

    tmux.switch_or_create(session_path, name)


def _fetch_reload_argv() -> list[str]:
    """Argv prefix for invoking the in-package fetch-reload subcommand.

    Re-uses the running interpreter so the picker drives the same Python
    used to launch the dispatcher (matters when the user invokes via a
    venv or alternative ``python3``).
    """
    return [sys.executable, "-m", "tmux_sessions", "fetch-reload"]


def _resolve_score_file_env() -> str:
    """Match the bash ``SCORE_FILE`` derivation in ``common.sh``.

    The bash side falls back to ``TMUX_SESSIONS_SCORES_FILE`` then to
    ``$HOME/.local/share/tmux-sessions/scores.tsv``. The Python
    sub-handlers expect ``SCORE_FILE`` to be set in the env they
    inherit, so we resolve and re-export it here.
    """
    explicit = os.environ.get("SCORE_FILE")
    if explicit:
        return explicit
    configured = os.environ.get("TMUX_SESSIONS_SCORES_FILE")
    if configured:
        return configured
    home = os.environ.get("HOME", "")
    return f"{home}/.local/share/tmux-sessions/scores.tsv"


def cmd_sessions_manage(args: argparse.Namespace) -> int:
    """Run the top-level session picker fzf loop.

    Mirrors the bash ``manage_sessions`` function in ``sessions.sh``:
    seed a tmpfile via ``build_entries``, drive fzf with the same flags
    and bindings (binds invoke ``python3 -m tmux_sessions sessions
    action ...`` instead of the legacy ``$self --action ...`` shim), and
    dispatch on the chosen key. Returns 0 once the loop exits.
    """
    score_file = _resolve_score_file_env()
    os.environ["SCORE_FILE"] = score_file

    style = os.environ.get("TMUX_SESSIONS_ICON_STYLE") or "nerd"
    icons = picker.IconSet.from_style(style)

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".entries") as initial:
        tmpfile = Path(initial.name)
        config = _resolve_build_entries_config()
        for line in sessions.build_entries(icons=icons, **config):  # type: ignore[arg-type]
            initial.write(line + "\n")

    try:
        return _manage_loop(tmpfile, icons=icons)
    finally:
        for path in (tmpfile, tmpfile.with_name(tmpfile.name + ".new")):
            with contextlib.suppress(FileNotFoundError):
                path.unlink()


def _manage_loop(tmpfile: Path, *, icons: picker.IconSet) -> int:
    # Action binds re-invoke the dispatcher itself; using
    # ``sys.executable`` keeps the venv's interpreter active in the
    # subshell fzf spawns. The inline {1}/{2}/{n} placeholders are
    # interpolated by fzf at runtime; the rest of the command line is
    # escaped so paths with spaces survive fzf's shell-style execute().
    action_cmd_prefix = f"{shlex.quote(sys.executable)} -m tmux_sessions sessions action "
    quoted_tmpfile = shlex.quote(str(tmpfile))
    bind_ctrl_d = (
        f"ctrl-d:execute({action_cmd_prefix}ctrl-d {{1}} {{2}} {quoted_tmpfile})"
        f"+reload(cat {quoted_tmpfile})+pos({{n}})"
    )
    bind_ctrl_x = (
        f"ctrl-x:execute-silent({action_cmd_prefix}ctrl-x {{1}} {{2}} {quoted_tmpfile})"
        f"+reload(cat {quoted_tmpfile})+pos({{n}})"
    )
    bind_ctrl_r = (
        f"ctrl-r:execute({action_cmd_prefix}ctrl-r {{1}} {{2}} {quoted_tmpfile})"
        f"+reload(cat {quoted_tmpfile})+pos({{n}})"
    )

    while True:
        with tmpfile.open("rb") as input_f:
            result = subprocess.run(
                [
                    "fzf",
                    *picker.FZF_POPUP_FLAGS,
                    "--ansi",
                    "--with-nth",
                    "4",
                    "--nth",
                    "3",
                    "--tiebreak=index",
                    "--delimiter",
                    "\t",
                    "--prompt",
                    "Sessions > ",
                    "--expect",
                    "ctrl-w,ctrl-bs",
                    "--header",
                    (
                        "enter:open ctrl-bs:back ?:preview ctrl-x:delete-session "
                        "ctrl-r:rename ctrl-w:worktree ctrl-d:remove-worktree"
                    ),
                    "--preview",
                    ("[ '{1}' = s ] && tmux capture-pane -e -p -t '\\$'{2} 2>/dev/null || ls '{2}' 2>/dev/null"),
                    "--preview-window",
                    "down:50%:border-top:nofollow:hidden",
                    "--bind",
                    "?:toggle-preview",
                    "--bind",
                    bind_ctrl_d,
                    "--bind",
                    bind_ctrl_x,
                    "--bind",
                    bind_ctrl_r,
                ],
                stdin=input_f,
                capture_output=True,
                text=True,
            )

        if result.returncode == 130:
            return 0
        if not result.stdout:
            return 0

        out_lines = result.stdout.split("\n")
        key = out_lines[0] if out_lines else ""
        line = out_lines[1] if len(out_lines) > 1 else ""

        if key == "ctrl-bs":
            return 0

        fields = line.split("\t")
        row_type = fields[0] if fields else ""
        key2 = fields[1] if len(fields) > 1 else ""
        search = fields[2] if len(fields) > 2 else ""

        if key == "ctrl-w":
            if _handle_ctrl_w(row_type=row_type, key2=key2, icons=icons):
                return 0
            continue

        if row_type == "n":
            new_name = _prompt_new_session_name()
            if not new_name:
                continue
            home = os.environ.get("HOME", "")
            _bump_score_and_switch(new_name, Path(home))
            return 0

        if row_type == "p":
            _bump_score_and_switch(search, Path(key2))
            return 0

        if row_type == "s":
            subprocess.run(["tmux", "switch-client", "-t", f"${key2}"], capture_output=True)
            return 0


def _handle_ctrl_w(*, row_type: str, key2: str, icons: picker.IconSet) -> bool:
    """Drive the ctrl-w (create-worktree) flow; return True to exit the loop.

    Returns False to continue the picker loop (Esc-to-back from the
    branch picker, or no repo resolved). Returns True after a successful
    worktree creation + session switch so the parent loop can exit 0.
    """
    if row_type == "p":
        repo_path = _git_toplevel(key2)
    elif row_type == "s":
        sess_path_result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", f"${key2}", "#{session_path}"],
            capture_output=True,
            text=True,
        )
        sess_path = sess_path_result.stdout.strip()
        repo_path = _git_toplevel(sess_path) if sess_path else ""
    else:
        return False

    if not repo_path:
        return False

    container = _container_for_repo(repo_path)
    if not container:
        return False

    listen_port = 51200 + secrets.randbelow(14336)
    choice = picker.pick_branch(
        Path(repo_path),
        icons=icons,
        fetch_reload_argv=_fetch_reload_argv(),
        listen_port=listen_port,
        now=time.time(),
    )
    if choice.kind == "cancel":
        # Bash treats Esc here as "close all" — return True so the
        # caller exits 0 instead of redrawing the parent picker.
        return True
    if choice.kind == "back":
        return False

    fallback = os.environ.get("TMUX_SESSIONS_DEFAULT_BRANCH") or "main"
    try:
        if choice.kind == "new":
            wt_path = git.add_worktree(
                Path(repo_path),
                Path(container),
                branch=None,
                new_name=choice.name,
                default_branch_fallback=fallback,
            )
        else:  # "existing"
            wt_path = git.add_worktree(
                Path(repo_path),
                Path(container),
                branch=choice.name,
                new_name=None,
                default_branch_fallback=fallback,
            )
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return False

    home = os.environ.get("HOME", "")
    strip_prefixes = (os.environ.get("TMUX_SESSIONS_STRIP_PREFIXES") or "").split()
    name = text.format_session_name(str(wt_path), home=home, strip_prefixes=strip_prefixes)
    _bump_score_and_switch(name, wt_path)
    return True


def cmd_text_format_session_name(args: argparse.Namespace) -> int:
    home = os.environ.get("HOME", "")
    strip_prefixes = (os.environ.get("TMUX_SESSIONS_STRIP_PREFIXES") or "").split()
    sys.stdout.write(text.format_session_name(args.path, home=home, strip_prefixes=strip_prefixes))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_usage(sys.stderr)
        return 1
    return handler(args)  # type: ignore[no-any-return]


if __name__ == "__main__":
    sys.exit(main())
