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
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from . import git, score, text


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
