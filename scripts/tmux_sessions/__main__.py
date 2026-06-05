"""CLI dispatcher for the tmux_sessions package.

Only the four subcommands actually invoked from production are
registered here:

* ``sessions manage`` — TPM key-bind entry point.
* ``sessions display-name`` — status-bar helper (see README).
* ``sessions action ctrl-x|ctrl-r|ctrl-d`` — fzf binds spawned inside
  the ``manage`` loop.
* ``fetch-reload`` — fzf bind spawned inside ``picker.pick_branch``.

Earlier migration steps registered a much larger surface as parity
shims; once the bash callers were retired those subcommands had no
consumer outside the test suite, so they were dropped.
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


def cmd_fetch_reload(args: argparse.Namespace) -> int:
    style = os.environ.get("TMUX_SESSIONS_ICON_STYLE") or "nerd"
    icons = picker.IconSet.from_style(style)
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
        fetch_reload.fetch_and_reload(repo, tmpfile, args.port, args.header_base, icons=icons)
        os._exit(0)
    except BaseException:
        os._exit(1)


def _resolve_build_entries_config() -> dict[str, object]:
    """Pull the env-driven knobs that ``build_entries`` consumes.

    Shared between ``cmd_sessions_manage`` and the ``_action_ctrl_r``
    worktree-rename branch, which has to rebuild the picker tmpfile
    after the rename moves the row's path.
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

    Empty stdin, free-text query, ``ctrl-bs`` cancel. Returns ``None``
    on Esc, on ctrl-bs, or when sanitisation produces an empty string.
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
    """Drive the inline No/Yes fzf prompt for orphan-dir deletion."""
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


def _container_for_repo(repo_path: str) -> str:
    """Return the directory holding sibling worktrees for ``repo_path``."""
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
    ctrl-bs, or empty input).
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
    """Bump the recency score for ``name`` and switch to (or create) the session."""
    score_file_env = os.environ.get("SCORE_FILE", "")
    if score_file_env:
        half_life_days = float(os.environ.get("TMUX_SESSIONS_SCORE_HALF_LIFE") or 14)
        score.bump_in_file(
            Path(score_file_env),
            name=name,
            now=float(int(time.time())),
            half_life_secs=half_life_days * 24 * 3600,
        )
    tmux.switch_or_create(session_path, name)


def _fetch_reload_argv() -> list[str]:
    """Argv prefix for invoking the in-package fetch-reload subcommand."""
    return [sys.executable, "-m", "tmux_sessions", "fetch-reload"]


def _resolve_score_file_env() -> str:
    """Resolve ``SCORE_FILE`` with the configured fallbacks.

    ``SCORE_FILE`` wins; otherwise ``TMUX_SESSIONS_SCORES_FILE``;
    otherwise ``$HOME/.local/share/tmux-sessions/scores.tsv``.
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
    """Run the top-level session picker fzf loop."""
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
        with contextlib.suppress(FileNotFoundError):
            tmpfile.unlink()


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
    """Drive the ctrl-w (create-worktree) flow; return True to exit the loop."""
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
        # Esc here is "close all" — return True so the caller exits 0
        # instead of redrawing the parent picker.
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
