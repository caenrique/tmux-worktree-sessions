"""CLI dispatcher for the tmux_worktree_sessions package.

The CLI surface is split into two clearly separated tiers:

User-facing — bound from the tmux config or invoked from the status bar:

* ``sessions manage`` — TPM key-bind entry point.
* ``sessions previous`` — switch to the previous live session by attach time.
* ``sessions display-name`` — status-bar helper (see README).
* ``worktree manage`` — standalone branch picker for the current pane.

Internal hatches — never typed by the user; spawned by fzf binds inside
the running picker so it can call back into itself. Grouped under the
``_internal`` subcommand (hidden from ``--help``) so the boundary stays
obvious:

* ``_internal session-action <key>`` — ctrl-x/ctrl-r binds spawned
  inside the session-picker ``manage`` loop.
* ``_internal branch-action <key>`` — ctrl-x bind spawned inside the
  branch picker (``picker.pick_branch``).
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

from . import fetch_reload, git, picker, session_tree, sessions, text, tmux
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

    previous_p = sessions_sub.add_parser(
        "previous",
        help="switch to the most recently attached other live session",
    )
    previous_p.set_defaults(handler=cmd_sessions_previous)

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
    action_p.add_argument("key", choices=("ctrl-x", "ctrl-r"), help="action key")
    action_p.add_argument("type", help="picker entry type: 's', 'p', or 'n'")
    action_p.add_argument("id", help="session id (without leading $) or project path")
    action_p.add_argument("tmpfile", help="top-level picker entries tmpfile to mutate in place")
    action_p.add_argument("session", nargs="?", default="", help="containing session id for tree rows")
    action_p.add_argument("window", nargs="?", default="", help="containing window id for pane rows")
    action_p.add_argument("viewfile", nargs="?", help="rendered tree entries file")
    action_p.add_argument("statefile", nargs="?", help="tree expansion state file")
    action_p.set_defaults(handler=cmd_internal_session_action)

    tree_p = internal_sub.add_parser("tree-expand")
    tree_p.add_argument("action", choices=("expand", "collapse"))
    tree_p.add_argument("type", help="selected tree row type")
    tree_p.add_argument("id", help="selected stable row id")
    tree_p.add_argument("session", help="containing session id")
    tree_p.add_argument("rootfile", help="top-level picker entries file")
    tree_p.add_argument("viewfile", help="rendered tree entries file")
    tree_p.add_argument("statefile", help="tree expansion state file")
    tree_p.set_defaults(handler=cmd_internal_tree_expand)

    preview_p = internal_sub.add_parser("preview")
    preview_p.add_argument("target", help="stable tmux session, window, or pane target")
    preview_p.set_defaults(handler=cmd_internal_preview)

    sync_name_p = internal_sub.add_parser("sync-session-name")
    sync_name_p.add_argument("target", help="session id to refresh")
    sync_name_p.set_defaults(handler=cmd_internal_sync_session_name)

    branch_p = internal_sub.add_parser("branch-action")
    branch_p.add_argument("key", choices=("ctrl-x",), help="action key")
    branch_p.add_argument("repo", help="path to the git repo whose branches are being picked")
    branch_p.add_argument("branch", help="branch name selected in the picker (column 1 of the row)")
    branch_p.add_argument("tmpfile", help="picker entries tmpfile to mutate in place")
    branch_p.set_defaults(handler=cmd_internal_branch_action)

    fetch_p = internal_sub.add_parser("fetch-reload")
    fetch_p.add_argument("repo", help="path to the git repo")
    fetch_p.add_argument("tmpfile", help="branch entries file fzf reads via reload(cat ...)")
    fetch_p.add_argument("statefile", help="current branch-picker view: all or pull requests")
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

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".roots") as initial, tempfile.NamedTemporaryFile(
        "w", delete=False, suffix=".entries"
    ) as view, tempfile.NamedTemporaryFile("w", delete=False, suffix=".tree-state") as state:
        rootfile = Path(initial.name)
        viewfile = Path(view.name)
        statefile = Path(state.name)
        for line in picker.build_session_entries_iter(cfg):
            initial.write(line + "\n")
    session_tree.save_state(statefile, session_tree.TreeState())
    session_tree.refresh_view(rootfile, viewfile, statefile)

    try:
        return picker.run_session_picker(
            viewfile,
            cfg=cfg,
            rootfile=rootfile,
            statefile=statefile,
        )
    finally:
        for path in (rootfile, viewfile, statefile, statefile.with_name(f"{statefile.name}.agents")):
            with contextlib.suppress(FileNotFoundError):
                path.unlink()


def cmd_sessions_previous(args: argparse.Namespace) -> int:
    """Switch to the most recently attached other live tmux session."""
    tmux.switch_to_previous_attached_session()
    return 0


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
}


def cmd_internal_session_action(args: argparse.Namespace) -> int:
    return _PICKER_ACTIONS[args.key](
        row_type=args.type,
        row_id=args.id,
        tmpfile=Path(args.tmpfile),
        session_id=args.session,
        window_id=args.window,
        viewfile=Path(args.viewfile) if args.viewfile else None,
        statefile=Path(args.statefile) if args.statefile else None,
        cfg=Config.from_env(),
    )


def cmd_internal_tree_expand(args: argparse.Namespace) -> int:
    session_tree.set_expanded(
        action=args.action,
        row_type=args.type,
        row_id=args.id,
        session_id=args.session,
        rootfile=Path(args.rootfile),
        viewfile=Path(args.viewfile),
        statefile=Path(args.statefile),
    )
    return 0


def cmd_internal_preview(args: argparse.Namespace) -> int:
    sys.stdout.buffer.write(tmux.capture_pane(args.target))
    return 0


def cmd_internal_sync_session_name(args: argparse.Namespace) -> int:
    """Refresh ``@tws-session-name`` for one newly attached session."""
    target = args.target if args.target.startswith("$") else f"${args.target}"
    cfg = Config.from_env()
    name = tmux.session_name(target)
    path = tmux.session_path(target)
    if not name or not path:
        return 0
    display_name = sessions.format_session_display(
        Path(path),
        name,
        home=cfg.home,
        strip_prefixes=cfg.strip_prefixes,
    )
    tmux.set_session_option(target, "@tws-session-name", display_name)
    tmux.refresh_status()
    return 0


def cmd_internal_branch_action(args: argparse.Namespace) -> int:
    cfg = Config.from_env()
    # Only ctrl-x is wired up today; the choices= guard above means we
    # never reach this dispatcher with anything else.
    return picker.branch_action_ctrl_x(
        repo=Path(args.repo),
        branch=args.branch,
        tmpfile=Path(args.tmpfile),
        icons=cfg.icons,
        home=cfg.home,
        strip_prefixes=cfg.strip_prefixes,
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
            Path(args.statefile),
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
