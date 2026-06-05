"""CLI dispatcher for the tmux_worktree_sessions package.

Only the subcommands actually invoked from production are registered
here:

* ``sessions manage`` — TPM key-bind entry point.
* ``sessions display-name`` — status-bar helper (see README).
* ``sessions action ctrl-x|ctrl-r|ctrl-d`` — fzf binds spawned inside
  the ``manage`` loop.
* ``worktree manage`` — standalone branch picker for the current pane.
* ``fetch-reload`` — fzf bind spawned inside ``picker.pick_branch``.

The ``__main__`` module owns argparse plumbing and the thin glue
between argparse and the picker UIs. Picker drivers live in
:mod:`tmux_worktree_sessions.picker`; resolved env-config lives in
:mod:`tmux_worktree_sessions.config`.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from pathlib import Path

from . import fetch_reload, git, picker, score, sessions, text, tmux
from .config import Config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tmux_worktree_sessions",
        description="tmux-worktree-sessions Python helpers",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sessions_p = sub.add_parser("sessions", help="session picker helpers")
    sessions_sub = sessions_p.add_subparsers(dest="sessions_command", metavar="<subcommand>")

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

    worktree_p = sub.add_parser("worktree", help="worktree picker helpers")
    worktree_sub = worktree_p.add_subparsers(dest="worktree_command", metavar="<subcommand>")
    worktree_manage_p = worktree_sub.add_parser(
        "manage",
        help="open the branch picker for the current pane's repo (top-level entry point)",
    )
    worktree_manage_p.set_defaults(handler=cmd_worktree_manage)

    fetch_reload_p = sub.add_parser(
        "fetch-reload",
        help="background-fetch git, regenerate branch entries, post reload to fzf",
    )
    fetch_reload_p.add_argument("repo", help="path to the git repo")
    fetch_reload_p.add_argument("tmpfile", help="branch entries file fzf reads via reload(cat ...)")
    fetch_reload_p.add_argument("port", type=int, help="fzf --listen port to POST to")
    fetch_reload_p.add_argument("header_base", help="header text without the spinner suffix")
    fetch_reload_p.set_defaults(handler=cmd_fetch_reload)

    return parser


def _read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text()
    except FileNotFoundError:
        return ""


def _build_entries_iter(cfg: Config) -> Iterator[str]:
    """Drive ``sessions.build_entries`` from a resolved ``Config``.

    Reads the score file fresh on every call — picker actions can leave
    it out of date with the in-memory tmpfile.
    """
    score_entries = score.parse_score_table(_read_text_or_empty(cfg.score_file))
    return sessions.build_entries(
        home=cfg.home,
        strip_prefixes=cfg.strip_prefixes,
        projects_roots=cfg.projects_roots,
        max_depth=cfg.max_depth,
        manual_spec=cfg.manual_spec,
        icons=cfg.icons,
        score_entries=score_entries,
        now=time.time(),
        half_life_secs=cfg.half_life_secs,
        path_boost=cfg.path_boost,
        worktrees_dir=cfg.worktrees_dir,
    )


def cmd_fetch_reload(args: argparse.Namespace) -> int:
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


def cmd_sessions_action_ctrl_x(args: argparse.Namespace) -> int:
    if args.type != "s":
        return 0
    cfg = Config.from_env()
    tmux_id = f"${args.id}"
    sess_path = tmux.session_path(tmux_id)
    tmux.kill_session(tmux_id)

    tmpfile = Path(args.tmpfile)
    lines = tmpfile.read_text().splitlines() if tmpfile.exists() else []
    new_lines = sessions.apply_ctrl_x(lines, sid=args.id, sess_path=sess_path, icons=cfg.icons)
    tmpfile.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))
    return 0


def cmd_sessions_action_ctrl_r(args: argparse.Namespace) -> int:
    target_path = _resolve_action_target(args.type, args.id)
    if target_path is None:
        return 0

    cfg = Config.from_env()
    tmpfile = Path(args.tmpfile)
    target = Path(target_path)

    if git.is_linked_worktree(target):
        return _rename_worktree_action(target, target_path, tmpfile, cfg=cfg)

    if args.type == "s":
        return _rename_session_action(args.id, tmpfile, cfg=cfg)

    tmux.flash_message("ctrl-r: not a linked worktree")
    return 0


def _resolve_action_target(row_type: str, row_id: str) -> str | None:
    """Return the filesystem target of a ctrl-r/ctrl-d action row, or None."""
    if row_type == "s":
        return tmux.session_path(f"${row_id}")
    if row_type == "p":
        return row_id
    return None


def _rename_worktree_action(target: Path, target_path: str, tmpfile: Path, *, cfg: Config) -> int:
    """Branch+directory rename for a linked worktree row; rebuild tmpfile on success."""
    main_wt = git.main_worktree(target)
    if main_wt is None:
        return 0
    container = picker.resolve_worktree_container(main_wt, main_wt, cfg=cfg)

    old_branch = git.current_branch(target)
    if not old_branch:
        sys.stderr.write("Cannot rename: worktree is in detached HEAD state\n")
        return 1
    new_name = picker.prompt_rename(old_branch)
    if not new_name or new_name == old_branch:
        return 0
    try:
        git.rename_worktree(main_wt, container, target, new_name=new_name)
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    rebuilt = list(_build_entries_iter(cfg))
    tmpfile.write_text("\n".join(rebuilt) + ("\n" if rebuilt else ""))
    return 0


def _rename_session_action(sid: str, tmpfile: Path, *, cfg: Config) -> int:
    """Tmux ``rename-session`` for a session row; rewrite the tmpfile row in place."""
    lines = tmpfile.read_text().splitlines() if tmpfile.exists() else []
    clean_name = _find_session_clean_name(lines, sid)
    new_name = picker.prompt_rename(clean_name)
    if not new_name or new_name == clean_name:
        return 0
    tmux.rename_session(f"${sid}", new_name)
    new_lines = sessions.apply_ctrl_r_session_rename(lines, sid=sid, new_name=new_name, icons=cfg.icons)
    tmpfile.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))
    return 0


def _find_session_clean_name(lines: list[str], sid: str) -> str:
    """Pull the search column off the matching ``s\\t<sid>`` row, or empty string."""
    for line in lines:
        fields = line.split("\t")
        if len(fields) >= 3 and fields[0] == "s" and fields[1] == sid:
            return fields[2]
    return ""


def cmd_sessions_action_ctrl_d(args: argparse.Namespace) -> int:
    tmpfile = Path(args.tmpfile)

    if args.type == "s":
        return _ctrl_d_session_row(args.id, tmpfile)
    if args.type == "p":
        return _ctrl_d_project_row(args.id, tmpfile)
    return 0


def _ctrl_d_session_row(sid: str, tmpfile: Path) -> int:
    """Kill the tmux session, drop its row, and remove its worktree if linked."""
    tmux_id = f"${sid}"
    sess_path = tmux.session_path(tmux_id)
    tmux.kill_session(tmux_id)

    lines = tmpfile.read_text().splitlines() if tmpfile.exists() else []
    new_lines = sessions.remove_session_row(lines, sid=sid)
    tmpfile.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))

    sess = Path(sess_path)
    if git.is_linked_worktree(sess):
        wt_repo = git.toplevel(sess)
        if wt_repo is not None:
            git.worktree_remove(wt_repo, sess_path)
    return 0


def _ctrl_d_project_row(wt_path: str, tmpfile: Path) -> int:
    """Drop the project row; remove its worktree (or an orphan dir after confirm)."""
    wt = Path(wt_path)
    if not git.is_linked_worktree(wt):
        return _ctrl_d_orphan_or_flash(wt, wt_path, tmpfile)

    wt_repo = git.toplevel(wt)
    if wt_repo is None:
        return 0
    _drop_project_row(tmpfile, wt_path)
    git.worktree_remove(wt_repo, wt_path)
    return 0


def _ctrl_d_orphan_or_flash(wt: Path, wt_path: str, tmpfile: Path) -> int:
    """Either confirm-and-rmtree an orphan worktree, or flash an error."""
    if not sessions.is_orphaned_worktree(wt, container=wt.parent):
        tmux.flash_message("ctrl-d: not a linked worktree")
        return 0
    if not picker.confirm_orphan_delete(wt_path):
        return 0
    _drop_project_row(tmpfile, wt_path)
    shutil.rmtree(wt_path, ignore_errors=True)
    return 0


def _drop_project_row(tmpfile: Path, wt_path: str) -> None:
    """Rewrite ``tmpfile`` with the project row for ``wt_path`` removed."""
    lines = tmpfile.read_text().splitlines() if tmpfile.exists() else []
    new_lines = sessions.remove_project_row(lines, path=wt_path)
    tmpfile.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))


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


def cmd_sessions_manage(args: argparse.Namespace) -> int:
    """Run the top-level session picker fzf loop."""
    cfg = Config.from_env()
    # Children spawned by fzf binds re-resolve via Config.from_env(), so
    # propagate the resolved score-file path through SCORE_FILE in case
    # only TWS_SCORES_FILE was set at parent entry.
    os.environ["SCORE_FILE"] = str(cfg.score_file)

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".entries") as initial:
        tmpfile = Path(initial.name)
        for line in _build_entries_iter(cfg):
            initial.write(line + "\n")

    try:
        return picker.run_session_picker(tmpfile, cfg=cfg)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmpfile.unlink()


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
