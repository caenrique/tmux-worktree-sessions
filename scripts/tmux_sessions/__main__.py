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
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from . import git, picker, score, text, tmux


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
