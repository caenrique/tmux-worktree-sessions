"""CLI dispatcher for the tmux_worktree_sessions package.

The CLI surface is split into two clearly separated tiers:

User-facing — bound from the tmux config or invoked from the status bar:

* ``sessions manage`` — TPM key-bind entry point.
* ``sessions display-name`` — status-bar helper (see README).
* ``worktree manage`` — standalone branch picker for the current pane.

Internal hatches — never typed by the user; spawned by fzf binds inside
the running picker so it can call back into itself. Grouped under the
``_internal`` subcommand (hidden from ``--help``) so the boundary stays
obvious:

* ``_internal session-action <key>`` — ctrl-x/ctrl-r/ctrl-d binds spawned
  inside the session-picker ``manage`` loop.
* ``_internal fetch-reload`` — bind spawned inside the branch picker
  (``picker.pick_branch``) to background-fetch and reload entries.

The ``__main__`` module owns argparse plumbing and the thin glue between
argparse and the picker UIs. Picker drivers and the action logic live in
:mod:`tmux_worktree_sessions.picker`; resolved env-config lives in
:mod:`tmux_worktree_sessions.config`.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from . import fetch_reload, git, picker, text, tmux
from .config import Config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tmux_worktree_sessions",
        description="tmux-worktree-sessions Python helpers",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    _add_user_subcommands(sub)
    _add_internal_subcommands(sub)
    return parser


# ---------------------------------------------------------------------------
# User-facing subcommands
#
# Bound from the user's tmux config or status bar; stable surface.
# ---------------------------------------------------------------------------


def _add_user_subcommands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    sessions_p = sub.add_parser("sessions", help="session picker helpers")
    sessions_sub = sessions_p.add_subparsers(dest="sessions_command", metavar="<subcommand>")

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

    worktree_p = sub.add_parser("worktree", help="worktree picker helpers")
    worktree_sub = worktree_p.add_subparsers(dest="worktree_command", metavar="<subcommand>")
    worktree_manage_p = worktree_sub.add_parser(
        "manage",
        help="open the branch picker for the current pane's repo (top-level entry point)",
    )
    worktree_manage_p.set_defaults(handler=cmd_worktree_manage)


# ---------------------------------------------------------------------------
# Internal subcommands (``_internal ...``)
#
# Spawned only by fzf binds inside the running pickers — the picker
# uses these to call back into itself. Hidden from ``--help`` and not
# part of the user-facing CLI contract; rename freely as long as the
# call sites in ``picker.py`` are updated in lockstep.
# ---------------------------------------------------------------------------


def _add_internal_subcommands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    # Omitting ``help=`` keeps ``_internal`` out of the user-facing
    # ``--help`` listing — ``add_parser`` only registers a choice action
    # when ``help`` is set, while the parser itself remains fully callable.
    # (``help=argparse.SUPPRESS`` would still leak a ``==SUPPRESS==`` row.)
    internal_p = sub.add_parser("_internal")
    internal_sub = internal_p.add_subparsers(dest="internal_command", metavar="<subcommand>")

    action_p = internal_sub.add_parser("session-action")
    action_p.add_argument("key", choices=("ctrl-x", "ctrl-r", "ctrl-d"), help="action key")
    action_p.add_argument("type", help="picker entry type: 's', 'p', or 'n'")
    action_p.add_argument("id", help="session id (without leading $) or project path")
    action_p.add_argument("tmpfile", help="picker entries tmpfile to mutate in place")
    action_p.set_defaults(handler=cmd_internal_session_action)

    fetch_p = internal_sub.add_parser("fetch-reload")
    fetch_p.add_argument("repo", help="path to the git repo")
    fetch_p.add_argument("tmpfile", help="branch entries file fzf reads via reload(cat ...)")
    fetch_p.add_argument("port", type=int, help="fzf --listen port to POST to")
    fetch_p.add_argument("header_base", help="header text without the spinner suffix")
    fetch_p.set_defaults(handler=cmd_internal_fetch_reload)


# ---------------------------------------------------------------------------
# User-facing command handlers
# ---------------------------------------------------------------------------


def cmd_sessions_manage(args: argparse.Namespace) -> int:
    """Run the top-level session picker fzf loop."""
    cfg = Config.from_env()
    # Children spawned by fzf binds re-resolve via Config.from_env(), so
    # propagate the resolved score-file path through SCORE_FILE in case
    # only TWS_SCORES_FILE was set at parent entry.
    os.environ["SCORE_FILE"] = str(cfg.score_file)

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".entries") as initial:
        tmpfile = Path(initial.name)
        for line in picker.build_session_entries_iter(cfg):
            initial.write(line + "\n")

    try:
        return picker.run_session_picker(tmpfile, cfg=cfg)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmpfile.unlink()


def cmd_sessions_display_name(args: argparse.Namespace) -> int:
    """Round-trip ``args.name`` through ``format-session-name``.

    tmux replaces dots with underscores when storing session names. The
    status bar uses this command to recover the original (dotted) form
    when it round-trips, falling back to the stored name when the user
    renamed the session by hand.
    """
    cfg = Config.from_env()
    derived = text.format_session_name(args.path, home=cfg.home, strip_prefixes=cfg.strip_prefixes)
    sys.stdout.write(derived if derived.replace(".", "_") == args.name else args.name)
    return 0


def cmd_worktree_manage(args: argparse.Namespace) -> int:
    """Open the branch picker for the current pane's git repo.

    Top-level entry point bound to a separate tmux key (default
    ``C-S-w``); skips the session picker so creating a new worktree for
    the repo you're already in is one keystroke instead of three. Shows
    a tmux flash message when the pane isn't inside a git repo.
    """
    cfg = Config.from_env()
    os.environ["SCORE_FILE"] = str(cfg.score_file)
    pane_path = tmux.pane_current_path()
    if not pane_path:
        return 0
    repo_path = git.toplevel(Path(pane_path))
    if repo_path is None:
        tmux.flash_message("worktree: not a git repo")
        return 0
    picker.open_worktree_picker(repo_path, cfg=cfg)
    return 0


# ---------------------------------------------------------------------------
# Internal command handlers (``_internal ...``)
#
# Spawned only by fzf binds inside the running pickers. Both handlers
# are thin glue over the picker module's public API.
# ---------------------------------------------------------------------------


_PICKER_ACTIONS: dict[str, Callable[..., int]] = {
    "ctrl-x": picker.picker_action_ctrl_x,
    "ctrl-r": picker.picker_action_ctrl_r,
    "ctrl-d": picker.picker_action_ctrl_d,
}


def cmd_internal_session_action(args: argparse.Namespace) -> int:
    return _PICKER_ACTIONS[args.key](
        row_type=args.type,
        row_id=args.id,
        tmpfile=Path(args.tmpfile),
        cfg=Config.from_env(),
    )


def cmd_internal_fetch_reload(args: argparse.Namespace) -> int:
    cfg = Config.from_env()
    repo = Path(args.repo)
    tmpfile = Path(args.tmpfile)

    # Fork once so fzf's execute-silent caller returns immediately while
    # we keep running. Parent exits 0; child detaches with setsid and
    # uses os._exit so atexit handlers and pytest's own cleanup never
    # run twice.
    pid = os.fork()
    if pid != 0:
        return 0
    try:
        os.setsid()
        session_paths = frozenset(s.path for s in tmux.list_sessions())
        fetch_reload.fetch_and_reload(
            repo,
            tmpfile,
            args.port,
            args.header_base,
            icons=cfg.icons,
            home=cfg.home,
            strip_prefixes=cfg.strip_prefixes,
            session_paths=session_paths,
        )
        os._exit(0)
    except BaseException:
        os._exit(1)


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
