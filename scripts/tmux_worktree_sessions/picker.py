"""Picker UIs for tmux-worktree-sessions.

This module owns every interactive flow the user can land in:

* :func:`run_session_picker` — top-level session picker fzf loop.
* :func:`open_worktree_picker` — branch picker driver (used by both the
  session-picker ctrl-w handler and the standalone worktree command).
* :func:`pick_branch` — single-shot branch picker (returns a
  :class:`BranchChoice`).
* :func:`prompt_rename`, :func:`prompt_new_session_name`,
  :func:`confirm_orphan_delete` — small inline UIs reused across the
  CLI handlers.

Each function has a single responsibility; the multi-step flows
compose them. Pure pieces (entry generation, layout resolution) sit
next to their UI consumers so a reader navigating the file sees the
whole picker logic in one place.
"""

from __future__ import annotations

import contextlib
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import fzf, git, score, sessions, text, tmux
from .icons import IconSet

if TYPE_CHECKING:
    from .config import Config

# Truecolor SGR matching the fzf header colour (#6c7086) so the
# worktree-path suffix in the branch picker reads as a secondary detail
# next to the bright branch name. ``--ansi`` must be on for the picker
# to interpret these.
GRAY = "\033[38;2;108;112;134m"
# Catppuccin "green" — same hue the session picker uses for active
# sessions. Reusing it for branches whose worktree is open as a session
# keeps the visual cue consistent across both pickers.
GREEN = "\033[38;2;166;227;161m"
# Bold for branches with a worktree but no session — makes the row
# brighter than the default-rendered plain-branch rows without picking
# a hue that competes with the session green.
BOLD = "\033[1m"
RESET = "\033[0m"

_BRANCH_HEADER = "enter:checkout  ctrl-bs:back  ctrl-f:refresh"
_NEW_NAME_HEADER = "enter:create  ctrl-bs:back"
_SESSION_HEADER = (
    "enter:open ctrl-bs:back ?:preview ctrl-x:delete-session ctrl-r:rename ctrl-w:worktree ctrl-d:remove-worktree"
)
_RENAME_HEADER = "enter:rename  ctrl-bs:cancel"
_NEW_SESSION_HEADER = "enter:create  ctrl-bs:cancel"
_ORPHAN_DELETE_HEADER = "directory is not git-linked — delete anyway?"

# Listen-port range fzf binds to during the branch picker. Avoids the
# 0–51199 well-known range and stays under the ephemeral ceiling.
_LISTEN_PORT_BASE = 51200
_LISTEN_PORT_RANGE = 14336


__all__ = [
    "BranchChoice",
    "BOLD",
    "GRAY",
    "GREEN",
    "RESET",
    "build_session_entries_iter",
    "bump_score_and_switch",
    "confirm_orphan_delete",
    "fetch_reload_argv",
    "gen_branch_picker_entries",
    "open_worktree_picker",
    "pick_branch",
    "picker_action_ctrl_d",
    "picker_action_ctrl_r",
    "picker_action_ctrl_x",
    "prompt_new_session_name",
    "prompt_rename",
    "resolve_worktree_container",
    "run_session_picker",
]


@dataclass(frozen=True)
class BranchChoice:
    """Outcome of :func:`pick_branch`.

    ``kind`` is one of ``"new"``, ``"existing"``, ``"back"``, or
    ``"cancel"``. ``name`` carries the branch name for the first two
    kinds; it is empty for ``back`` / ``cancel``.
    """

    kind: str
    name: str = ""


# ---------------------------------------------------------------------------
# Inline prompts
# ---------------------------------------------------------------------------


def prompt_rename(initial: str) -> str | None:
    """Drive the inline fzf rename prompt; return sanitised name or None.

    Returns ``None`` on Esc, on ctrl-bs, or when sanitisation produces
    an empty string.
    """
    result = fzf.prompt(
        prompt_label="Rename to: ",
        header=_RENAME_HEADER,
        initial=initial,
        popup=False,
    )
    if result.cancelled:
        return None
    return text.sanitize_name(result.query) or None


def prompt_new_session_name() -> str:
    """Drive the popup fzf prompt for the new-session sentinel.

    Returns the sanitised name, or ``""`` when the user cancels (Esc,
    ctrl-bs, or empty input).
    """
    result = fzf.prompt(
        prompt_label="Session name: ",
        header=_NEW_SESSION_HEADER,
    )
    if result.cancelled:
        return ""
    return text.sanitize_name(result.query)


def confirm_orphan_delete(wt_path: str) -> bool:
    """Drive the inline No/Yes fzf prompt for orphan-dir deletion."""
    return fzf.confirm(
        prompt_label=f"Delete {Path(wt_path).name}? ",
        header=_ORPHAN_DELETE_HEADER,
    )


# ---------------------------------------------------------------------------
# Branch picker entry generation (pure)
# ---------------------------------------------------------------------------


def gen_branch_picker_entries(
    repo: Path,
    *,
    icons: IconSet,
    home: str = "",
    strip_prefixes: list[str] | None = None,
    session_paths: frozenset[Path] = frozenset(),
) -> Iterator[str]:
    """Yield TSV lines for the branch picker.

    First line is the ``[new]`` sentinel. Branches are then grouped to
    surface what the user is most likely to act on:

    1. Branches whose worktree is currently open as a tmux session —
       icon+name rendered in catppuccin green (matches the active-
       session colour in the session picker).
    2. Branches with an associated worktree but no open session —
       icon+name rendered bold so the row reads brighter than plain
       branches without claiming a distinct hue.
    3. Other local branches (no worktree) — default rendering.
    4. Remote-only branches (``<remote>/...``) — default rendering.

    Branches with a worktree get the worktree path appended in dark
    gray, formatted via :func:`text.format_session_name`. Within each
    group, ``git.list_branches`` order is preserved (alphabetical for
    locals, sorted for remotes). The picker must be invoked with
    ``--ansi`` for the SGR codes to render.
    """
    prefixes = strip_prefixes or []
    remote = git.resolve_remote(repo)
    yield f"[new]\t{icons.new}{icons.sep}new branch"

    branch_paths: dict[str, Path] = {wt.branch: wt.path for wt in git.list_worktrees(repo)}
    remote_prefix = f"{remote}/" if remote else None

    sessions_bucket: list[str] = []
    worktrees_bucket: list[str] = []
    locals_bucket: list[str] = []
    remotes_bucket: list[str] = []

    for branch in git.list_branches(repo):
        line, has_session, has_worktree, is_remote = _format_branch_row(
            branch,
            branch_paths=branch_paths,
            remote_prefix=remote_prefix,
            session_paths=session_paths,
            icons=icons,
            home=home,
            prefixes=prefixes,
        )
        if has_session:
            sessions_bucket.append(line)
        elif has_worktree:
            worktrees_bucket.append(line)
        elif is_remote:
            remotes_bucket.append(line)
        else:
            locals_bucket.append(line)

    yield from sessions_bucket
    yield from worktrees_bucket
    yield from locals_bucket
    yield from remotes_bucket


def _format_branch_row(
    branch: str,
    *,
    branch_paths: dict[str, Path],
    remote_prefix: str | None,
    session_paths: frozenset[Path],
    icons: IconSet,
    home: str,
    prefixes: list[str],
) -> tuple[str, bool, bool, bool]:
    """Format one branch row plus the booleans that pick its bucket."""
    is_remote = remote_prefix is not None and branch.startswith(remote_prefix)
    icon = icons.remote if is_remote else icons.branch
    wt_path = branch_paths.get(branch)
    has_session = wt_path is not None and wt_path in session_paths
    has_worktree = wt_path is not None and not has_session

    if has_session:
        label_open, label_close = GREEN, RESET
    elif has_worktree:
        label_open, label_close = BOLD, RESET
    else:
        label_open, label_close = "", ""

    suffix = ""
    if wt_path is not None:
        display_path = text.format_session_name(str(wt_path), home=home, strip_prefixes=prefixes)
        suffix = f" {GRAY}{display_path}{RESET}"
    line = f"{branch}\t{label_open}{icon}{icons.sep}{branch}{label_close}{suffix}"
    return line, has_session, has_worktree, is_remote


# ---------------------------------------------------------------------------
# Branch picker UI
# ---------------------------------------------------------------------------


def fetch_reload_argv() -> list[str]:
    """Argv prefix for invoking the in-package fetch-reload subcommand.

    Used both by :func:`pick_branch` (initial sync) and the ``ctrl-f``
    rebind. Centralised here so the venv interpreter is shared by every
    spawn site. Targets the internal ``_internal fetch-reload`` hatch —
    the picker calling back into itself.
    """
    return [sys.executable, "-m", "tmux_worktree_sessions", "_internal", "fetch-reload"]


def _seed_branch_tmpfile(
    repo: Path,
    *,
    icons: IconSet,
    home: str,
    strip_prefixes: list[str] | None,
    session_paths: frozenset[Path],
) -> Path:
    """Write the initial branch-picker entries to a fresh tempfile.

    The tempfile is the IPC channel between the picker and the
    background fetch helper — both write to the same path so the
    picker's ``reload(cat ...)`` always pulls the latest list.
    """
    with tempfile.NamedTemporaryFile("w", delete=False) as initial:
        path = Path(initial.name)
        for line in gen_branch_picker_entries(
            repo,
            icons=icons,
            home=home,
            strip_prefixes=strip_prefixes,
            session_paths=session_paths,
        ):
            initial.write(line + "\n")
    return path


def _maybe_start_background_fetch(
    repo: Path,
    *,
    tmpfile: Path,
    listen_port: int,
    fetch_argv: list[str],
    now: float,
    fetch_window_secs: int,
) -> tuple[subprocess.Popen[bytes] | None, str]:
    """Spawn the detached fetch helper if FETCH_HEAD is older than the window.

    Returns ``(process, header)``: the process is ``None`` when no fetch
    was needed; the header string is suffixed with ``[syncing...]``
    while a fetch is running so the user sees something is happening.
    """
    mtime = git.fetch_head_mtime(repo)
    if not git.fetch_is_stale(mtime, now=now, window_secs=fetch_window_secs):
        return None, _BRANCH_HEADER
    proc = subprocess.Popen(
        [
            *fetch_argv,
            str(repo),
            str(tmpfile),
            str(listen_port),
            _BRANCH_HEADER,
        ],
        start_new_session=True,
    )
    return proc, f"{_BRANCH_HEADER} [syncing...]"


def _build_ctrl_f_bind(
    fetch_argv: list[str],
    repo: Path,
    tmpfile: Path,
    listen_port: int,
) -> str:
    """Compose the ``ctrl-f`` bind that re-runs fetch-reload on demand."""
    args = " ".join(
        shlex.quote(s)
        for s in (
            *fetch_argv,
            str(repo),
            str(tmpfile),
            str(listen_port),
            _BRANCH_HEADER,
        )
    )
    return f"ctrl-f:change-header({_BRANCH_HEADER} ⟳ fetching...)+execute-silent({args})"


def _branch_pick_round(
    *,
    tmpfile: Path,
    initial_header: str,
    listen_port: int,
    ctrl_f_bind: str,
) -> fzf.PickerSelection:
    """Run one fzf round of the branch picker reading from ``tmpfile``."""
    branch_picker = fzf.Picker(
        prompt_label="Branch > ",
        header=initial_header,
        with_nth="2",
        expect="ctrl-bs",
        listen_port=listen_port,
    ).bind(ctrl_f_bind)
    with tmpfile.open("rb") as input_f:
        return branch_picker.run(stdin=input_f)


def _prompt_new_branch_name() -> BranchChoice | None:
    """Inline prompt for the [new] sentinel; encode the branch-picker semantics.

    Returns:
        * ``BranchChoice("cancel")`` when the user pressed Esc.
        * ``None`` when the user pressed ctrl-bs (caller should re-open
          the branch list).
        * ``BranchChoice("new", name)`` on success.
    """
    name_result = fzf.prompt(
        prompt_label="New branch name: ",
        header=_NEW_NAME_HEADER,
    )
    # Esc on the name prompt aborts the whole flow; ctrl-bs is "go back"
    # and re-opens the branch list.
    if name_result.cancelled and not name_result.cancel_key:
        return BranchChoice(kind="cancel")
    if name_result.cancelled:
        return None
    new_name = text.sanitize_name(name_result.query)
    if not new_name:
        return None
    return BranchChoice(kind="new", name=new_name)


def pick_branch(
    repo: Path,
    *,
    icons: IconSet,
    fetch_reload_argv: list[str],
    listen_port: int,
    now: float,
    fetch_window_secs: int = 900,
    home: str = "",
    strip_prefixes: list[str] | None = None,
    session_paths: frozenset[Path] = frozenset(),
) -> BranchChoice:
    """Drive the fzf branch picker; return the user's selection.

    The picker writes its entries to a temp file so the background
    fetch helper invoked via ``fetch_reload_argv`` can rewrite them in
    place and post a ``reload`` to fzf's listen port.
    """
    tmpfile = _seed_branch_tmpfile(
        repo,
        icons=icons,
        home=home,
        strip_prefixes=strip_prefixes,
        session_paths=session_paths,
    )
    fetch_proc, initial_header = _maybe_start_background_fetch(
        repo,
        tmpfile=tmpfile,
        listen_port=listen_port,
        fetch_argv=fetch_reload_argv,
        now=now,
        fetch_window_secs=fetch_window_secs,
    )
    ctrl_f_bind = _build_ctrl_f_bind(fetch_reload_argv, repo, tmpfile, listen_port)

    try:
        while True:
            selection = _branch_pick_round(
                tmpfile=tmpfile,
                initial_header=initial_header,
                listen_port=listen_port,
                ctrl_f_bind=ctrl_f_bind,
            )
            initial_header = _BRANCH_HEADER

            if selection.cancelled:
                return BranchChoice(kind="cancel")
            if selection.key == "ctrl-bs":
                return BranchChoice(kind="back")
            item = selection.line.split("\t", 1)[0] if selection.line else ""
            if not item:
                return BranchChoice(kind="cancel")

            if item != "[new]":
                return BranchChoice(kind="existing", name=item)

            outcome = _prompt_new_branch_name()
            if outcome is not None:
                return outcome
            # ctrl-bs / empty → loop back to the branch list.
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmpfile.unlink()
        if fetch_proc is not None and fetch_proc.poll() is None:
            with contextlib.suppress(OSError):
                fetch_proc.terminate()


# ---------------------------------------------------------------------------
# Glue helpers: layout resolution + score-then-switch
# ---------------------------------------------------------------------------


def resolve_worktree_container(repo: Path, main_wt: Path, *, cfg: Config) -> Path:
    """Pick the right container for new/renamed worktrees of ``repo``.

    Detects the existing layout from the repo's worktrees and falls back
    to ``cfg.default_layout`` when the repo has no linked worktrees yet
    (or its existing ones don't fit a single shape). The returned
    directory is created with ``parents=True`` so subfolder layouts work
    on the very first worktree.
    """
    detected = git.detect_layout(repo, worktrees_dir=cfg.worktrees_dir)
    layout: git.ConcreteWorktreeLayout = cfg.default_layout if detected == "ambiguous" else detected
    container = git.worktree_container(main_wt, layout=layout, worktrees_dir=cfg.worktrees_dir)
    container.mkdir(parents=True, exist_ok=True)
    return container


def bump_score_and_switch(name: str, session_path: Path, *, cfg: Config) -> None:
    """Bump the recency score for ``name`` and switch to (or create) the session."""
    score.bump_in_file(
        cfg.score_file,
        name=name,
        now=float(int(time.time())),
        half_life_secs=cfg.half_life_secs,
    )
    tmux.switch_or_create(session_path, name)


# ---------------------------------------------------------------------------
# Worktree picker driver (branch picker + add_worktree + switch)
# ---------------------------------------------------------------------------


def open_worktree_picker(repo_path: Path, *, cfg: Config) -> bool:
    """Drive the branch picker for ``repo_path``; return True to exit a parent loop.

    Shared between the session-picker ctrl-w handler and the standalone
    ``worktree manage`` entry point. Returns True when the user picked a
    branch or pressed Esc, False when they pressed Ctrl-Backspace (which
    only matters when there IS a parent picker to redraw).
    """
    main_wt = git.main_worktree(repo_path)
    if main_wt is None:
        return False
    container = resolve_worktree_container(repo_path, main_wt, cfg=cfg)

    choice = _open_branch_picker_for_repo(repo_path, cfg=cfg)
    if choice.kind == "cancel":
        # Esc here is "close all" — return True so the caller exits 0
        # instead of redrawing the parent picker.
        return True
    if choice.kind == "back":
        return False

    wt_path = _add_worktree_for_choice(repo_path, container, choice, cfg=cfg)
    if wt_path is None:
        return False

    name = text.format_session_name(str(wt_path), home=cfg.home, strip_prefixes=cfg.strip_prefixes)
    bump_score_and_switch(name, wt_path, cfg=cfg)
    return True


def _open_branch_picker_for_repo(repo_path: Path, *, cfg: Config) -> BranchChoice:
    """Wire ``pick_branch`` to the resolved Config + tmux session list."""
    listen_port = _LISTEN_PORT_BASE + secrets.randbelow(_LISTEN_PORT_RANGE)
    session_paths = frozenset(s.path for s in tmux.list_sessions())
    return pick_branch(
        repo_path,
        icons=cfg.icons,
        fetch_reload_argv=fetch_reload_argv(),
        listen_port=listen_port,
        now=time.time(),
        home=cfg.home,
        strip_prefixes=cfg.strip_prefixes,
        session_paths=session_paths,
    )


def _add_worktree_for_choice(
    repo_path: Path,
    container: Path,
    choice: BranchChoice,
    *,
    cfg: Config,
) -> Path | None:
    """Add a worktree for the user's branch selection; print errors and return None."""
    try:
        if choice.kind == "new":
            return git.add_worktree(
                repo_path,
                container,
                branch=None,
                new_name=choice.name,
                default_branch_fallback=cfg.default_branch_fallback,
            )
        return git.add_worktree(
            repo_path,
            container,
            branch=choice.name,
            new_name=None,
            default_branch_fallback=cfg.default_branch_fallback,
        )
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return None


# ---------------------------------------------------------------------------
# Session picker driver
# ---------------------------------------------------------------------------


def run_session_picker(tmpfile: Path, *, cfg: Config) -> int:
    """Run the top-level session picker fzf loop until the user commits.

    Reads picker rows from ``tmpfile`` and acts on each user selection
    (open, switch, ctrl-w to open a worktree, etc.). Returns the exit
    code the CLI handler should propagate.
    """
    picker_obj = _build_session_picker(tmpfile)

    while True:
        with tmpfile.open("rb") as input_f:
            selection = picker_obj.run(stdin=input_f)

        if selection.cancelled or selection.key == "ctrl-bs":
            return 0

        if _dispatch_session_selection(selection, cfg=cfg):
            return 0
        # Selection didn't terminate the loop — re-prompt.


def _build_session_picker(tmpfile: Path) -> fzf.Picker:
    """Construct the session picker with all action key binds wired up."""
    bind_d, bind_x, bind_r = _build_session_action_binds(tmpfile)
    # Preview target is `'$'{2}`, not `'\$'{2}`: inside single quotes
    # the backslash survives literally, and tmux rejects `\$<sid>` with
    # "can't find pane".
    preview_cmd = "[ '{1}' = s ] && tmux capture-pane -e -p -t '$'{2} 2>/dev/null || ls '{2}' 2>/dev/null"
    # No ``--nth`` is set on the picker: fzf indexes ``--nth`` into the
    # post-``--with-nth`` view, so any value finds nothing once
    # ``--with-nth 4`` collapses each row to a single field. We rely on
    # ``--ansi`` stripping SGR codes from field 4 before matching.
    return (
        fzf.Picker(
            prompt_label="Sessions > ",
            header=_SESSION_HEADER,
            with_nth="4",
            expect="ctrl-w,ctrl-bs",
            preview=preview_cmd,
            preview_window="down:50%:border-top:nofollow:hidden",
            extra_flags=("--tiebreak=index",),
        )
        .bind("?:toggle-preview")
        .bind(bind_d)
        .bind(bind_x)
        .bind(bind_r)
    )


def _build_session_action_binds(tmpfile: Path) -> tuple[str, str, str]:
    """Build the ctrl-d / ctrl-x / ctrl-r binds that re-invoke the dispatcher.

    Each bind shells out to ``python3 -m tmux_worktree_sessions _internal
    session-action <key>`` — the internal hatch the picker uses to call
    back into itself. ``sys.executable`` keeps the venv's interpreter
    active in the subshell fzf spawns. The inline ``{1}/{2}/{n}``
    placeholders are interpolated by fzf at runtime; the rest of the
    command line is escaped so paths with spaces survive fzf's
    shell-style ``execute()``.
    """
    action_cmd_prefix = (
        f"{shlex.quote(sys.executable)} -m tmux_worktree_sessions _internal session-action "
    )
    quoted_tmpfile = shlex.quote(str(tmpfile))

    def _bind(key: str, exec_form: str) -> str:
        return (
            f"{key}:{exec_form}({action_cmd_prefix}{key} {{1}} {{2}} {quoted_tmpfile})"
            f"+reload(cat {quoted_tmpfile})+pos({{n}})"
        )

    return (
        _bind("ctrl-d", "execute"),
        _bind("ctrl-x", "execute-silent"),
        _bind("ctrl-r", "execute"),
    )


def _dispatch_session_selection(selection: fzf.PickerSelection, *, cfg: Config) -> bool:
    """Act on one picker selection; return True when the loop should exit."""
    fields = selection.line.split("\t")
    row_type = fields[0] if fields else ""
    key2 = fields[1] if len(fields) > 1 else ""
    search = fields[2] if len(fields) > 2 else ""

    if selection.key == "ctrl-w":
        return _handle_session_picker_ctrl_w(row_type=row_type, key2=key2, cfg=cfg)

    if row_type == "n":
        new_name = prompt_new_session_name()
        if not new_name:
            return False
        bump_score_and_switch(new_name, Path(cfg.home), cfg=cfg)
        return True

    if row_type == "p":
        bump_score_and_switch(search, Path(key2), cfg=cfg)
        return True

    if row_type == "s":
        tmux.switch_client(f"${key2}")
        return True

    return False


def _handle_session_picker_ctrl_w(*, row_type: str, key2: str, cfg: Config) -> bool:
    """Drive the ctrl-w (create-worktree) flow; return True to exit the loop."""
    repo_path = _resolve_ctrl_w_repo(row_type=row_type, key2=key2)
    if repo_path is None:
        return False
    return open_worktree_picker(repo_path, cfg=cfg)


def _resolve_ctrl_w_repo(*, row_type: str, key2: str) -> Path | None:
    """Map the picker row's type+key to a repo path, or None for invalid rows."""
    if row_type == "p":
        return git.toplevel(Path(key2))
    if row_type == "s":
        sess_path = tmux.session_path(f"${key2}")
        return git.toplevel(Path(sess_path)) if sess_path else None
    return None


# ---------------------------------------------------------------------------
# CLI action handlers (``picker_action_*``)
#
# Reached only via the ``_internal session-action <key>`` subcommand,
# which fzf's ctrl-x / ctrl-r / ctrl-d binds inside the session picker
# spawn (see ``_build_session_action_binds``). Each one mutates the
# picker's shared entries tmpfile in place so the fzf ``reload(cat ...)``
# rebind pulls the fresh row set on return. The ``picker_action_*``
# prefix marks the functions the CLI hatch dispatches to — keep them
# grouped so the boundary stays obvious.
# ---------------------------------------------------------------------------


def _read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text()
    except FileNotFoundError:
        return ""


def build_session_entries_iter(cfg: Config) -> Iterator[str]:
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


def picker_action_ctrl_x(*, row_type: str, row_id: str, tmpfile: Path, cfg: Config) -> int:
    """Kill the tmux session and convert its row to a project row."""
    if row_type != "s":
        return 0
    tmux_id = f"${row_id}"
    sess_path = tmux.session_path(tmux_id)
    tmux.kill_session(tmux_id)

    lines = tmpfile.read_text().splitlines() if tmpfile.exists() else []
    new_lines = sessions.apply_ctrl_x(lines, sid=row_id, sess_path=sess_path, icons=cfg.icons)
    tmpfile.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))
    return 0


def picker_action_ctrl_r(*, row_type: str, row_id: str, tmpfile: Path, cfg: Config) -> int:
    """Rename a worktree (branch+dir+repair) or a tmux session in place."""
    target_path = _resolve_action_target(row_type, row_id)
    if target_path is None:
        return 0

    target = Path(target_path)
    if git.is_linked_worktree(target):
        return _rename_worktree_action(target, target_path, tmpfile, cfg=cfg)

    if row_type == "s":
        return _rename_session_action(row_id, tmpfile, cfg=cfg)

    tmux.flash_message("ctrl-r: not a linked worktree")
    return 0


def picker_action_ctrl_d(*, row_type: str, row_id: str, tmpfile: Path, cfg: Config) -> int:
    """Kill a session and/or remove its worktree; prompt on orphaned dirs."""
    del cfg  # accepted for handler symmetry; ctrl-d does not consume config
    if row_type == "s":
        return _ctrl_d_session_row(row_id, tmpfile)
    if row_type == "p":
        return _ctrl_d_project_row(row_id, tmpfile)
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
    container = resolve_worktree_container(main_wt, main_wt, cfg=cfg)

    old_branch = git.current_branch(target)
    if not old_branch:
        sys.stderr.write("Cannot rename: worktree is in detached HEAD state\n")
        return 1
    new_name = prompt_rename(old_branch)
    if not new_name or new_name == old_branch:
        return 0
    try:
        git.rename_worktree(main_wt, container, target, new_name=new_name)
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    rebuilt = list(build_session_entries_iter(cfg))
    tmpfile.write_text("\n".join(rebuilt) + ("\n" if rebuilt else ""))
    return 0


def _rename_session_action(sid: str, tmpfile: Path, *, cfg: Config) -> int:
    """Tmux ``rename-session`` for a session row; rewrite the tmpfile row in place."""
    lines = tmpfile.read_text().splitlines() if tmpfile.exists() else []
    clean_name = _find_session_clean_name(lines, sid)
    new_name = prompt_rename(clean_name)
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
    if not confirm_orphan_delete(wt_path):
        return 0
    _drop_project_row(tmpfile, wt_path)
    shutil.rmtree(wt_path, ignore_errors=True)
    return 0


def _drop_project_row(tmpfile: Path, wt_path: str) -> None:
    """Rewrite ``tmpfile`` with the project row for ``wt_path`` removed."""
    lines = tmpfile.read_text().splitlines() if tmpfile.exists() else []
    new_lines = sessions.remove_project_row(lines, path=wt_path)
    tmpfile.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))
