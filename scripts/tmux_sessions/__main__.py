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

from . import score, text


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


def cmd_text_strip_ansi(args: argparse.Namespace) -> int:
    sys.stdout.write(text.strip_ansi(args.text))
    return 0


def cmd_text_sanitize_name(args: argparse.Namespace) -> int:
    sys.stdout.write(text.sanitize_name(args.text))
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
