from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import score


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tmux_sessions",
        description="tmux-sessions Python helpers",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    score_parser = subparsers.add_parser("score", help="score storage and sorting")
    score_subs = score_parser.add_subparsers(dest="score_command", metavar="<subcommand>")

    sort_parser = score_subs.add_parser("sort", help="sort TSV input by score (highest first)")
    sort_parser.add_argument(
        "boost_path",
        nargs="?",
        default="",
        help="path used for the path-similarity boost; empty disables",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "score" and args.score_command == "sort":
        return score.run_sort(args.boost_path)

    parser.print_usage(sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
