"""Picker entry generation for tmux-worktree-sessions.

Pure helpers that build the TSV rows fzf consumes plus the interactive
``pick_branch`` loop that drives fzf itself. Subprocess calls into real
``git`` happen via :mod:`tmux_worktree_sessions.git`; this module owns the
icon/format logic and the fzf orchestration.
"""

from __future__ import annotations

import contextlib
import shlex
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from . import git, text

# Shared fzf style flags. ``FZF_INLINE_FLAGS`` is the base style used
# for inline prompts (rename, confirm); ``FZF_POPUP_FLAGS`` adds the
# ``--tmux`` popup flag and ``--scheme=path`` for top-level pickers.
FZF_INLINE_FLAGS: tuple[str, ...] = (
    "--reverse",
    "--no-scrollbar",
    "--no-info",
    "--no-separator",
    "--no-border",
    "--color",
    "header:#6c7086",
)

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
FZF_POPUP_FLAGS: tuple[str, ...] = (
    "--tmux",
    "bottom,100%,100%",
    "--scheme=path",
    *FZF_INLINE_FLAGS,
)

_BRANCH_HEADER = "enter:checkout  ctrl-bs:back  ctrl-f:refresh"
_NEW_NAME_HEADER = "enter:create  ctrl-bs:back"


@dataclass(frozen=True)
class IconSet:
    """Five icons used across picker lists, plus a derived separator.

    ``sep`` is a single space when icons are non-empty and empty in
    ``none`` style, so ``f"{icon}{sep}{label}"`` doesn't leave a stray
    space when the user disabled icons.
    """

    session: str
    project: str
    branch: str
    remote: str
    new: str

    @property
    def sep(self) -> str:
        return " " if self.session else ""

    @classmethod
    def from_style(cls, style: str) -> IconSet:
        if style == "none":
            return cls(session="", project="", branch="", remote="", new="")
        if style == "ascii":
            return cls(session="*", project=".", branch="-", remote="@", new="+")
        if style == "emoji":
            return cls(
                session="🖥",
                project="📦",
                branch="🌱",
                remote="☁️",
                new="＋",
            )
        # default: nerd. Written as \\uXXXX escapes — the literal glyphs
        # were silently flattened to plain spaces during the bash → Python
        # migration (scripts/common.sh in commit 2e40556 had them inline).
        return cls(
            session="\ue5ff",
            project="\uf114",
            branch="\uf418",
            remote="\uf0ed",
            new="\uf44d",
        )


@dataclass(frozen=True)
class BranchChoice:
    """Outcome of :func:`pick_branch`.

    ``kind`` is one of ``"new"``, ``"existing"``, ``"back"``, or
    ``"cancel"``. ``name`` carries the branch name for the first two
    kinds; it is empty for ``back`` / ``cancel``.
    """

    kind: str
    name: str = ""


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


def _fetch_head_mtime(repo: Path) -> float | None:
    """Return the mtime of FETCH_HEAD, or ``None`` if it does not exist.

    Resolves ``--git-common-dir`` so the lookup is correct from inside a
    linked worktree. A non-zero ``git`` exit (not a git directory) is
    treated as "no FETCH_HEAD" rather than an error.
    """
    common_dir_result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
    )
    if common_dir_result.returncode != 0:
        return None
    common_dir = Path(common_dir_result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = repo / common_dir
    fetch_head = common_dir / "FETCH_HEAD"
    try:
        return fetch_head.stat().st_mtime
    except FileNotFoundError:
        return None


def _build_ctrl_f_bind(
    fetch_reload_argv: list[str],
    repo: Path,
    tmpfile: Path,
    listen_port: int,
) -> str:
    args = " ".join(
        shlex.quote(s)
        for s in (
            *fetch_reload_argv,
            str(repo),
            str(tmpfile),
            str(listen_port),
            _BRANCH_HEADER,
        )
    )
    return f"ctrl-f:change-header({_BRANCH_HEADER} ⟳ fetching...)+execute-silent({args})"


def _parse_fzf_selection(stdout: str) -> tuple[str, str]:
    """Parse fzf ``--expect`` output into ``(key, item)``.

    fzf with ``--expect`` prints the key on line 1 (empty for Enter) and
    the selected line on line 2. The selected line is TSV; only the
    first column is the picker key (e.g. branch name or ``[new]``).
    """
    lines = stdout.split("\n")
    key = lines[0] if lines else ""
    item_line = lines[1] if len(lines) > 1 else ""
    item = item_line.split("\t", 1)[0] if item_line else ""
    return key, item


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
    place and post a ``reload`` to fzf's listen port. We seed the file
    once, spawn the fetch helper as a detached background process when
    ``FETCH_HEAD`` is older than ``fetch_window_secs`` seconds, and
    delegate the on-demand ``ctrl-f`` refresh to the same argv via an
    fzf ``execute-silent`` binding.
    """
    fetch_proc: subprocess.Popen[bytes] | None = None
    # NamedTemporaryFile is used here so the picker can write entries
    # once and let fetch_reload mutate them in place — the file IS the
    # IPC channel between the picker and the fetcher.
    with tempfile.NamedTemporaryFile("w", delete=False) as initial:
        tmpfile = Path(initial.name)
        for line in gen_branch_picker_entries(
            repo,
            icons=icons,
            home=home,
            strip_prefixes=strip_prefixes,
            session_paths=session_paths,
        ):
            initial.write(line + "\n")

    try:
        initial_header = _BRANCH_HEADER
        mtime = _fetch_head_mtime(repo)
        if git.fetch_is_stale(mtime, now=now, window_secs=fetch_window_secs):
            fetch_proc = subprocess.Popen(
                [
                    *fetch_reload_argv,
                    str(repo),
                    str(tmpfile),
                    str(listen_port),
                    _BRANCH_HEADER,
                ],
                start_new_session=True,
            )
            initial_header = f"{_BRANCH_HEADER} [syncing...]"

        ctrl_f_bind = _build_ctrl_f_bind(fetch_reload_argv, repo, tmpfile, listen_port)

        while True:
            with tmpfile.open("rb") as input_f:
                result = subprocess.run(
                    [
                        "fzf",
                        *FZF_POPUP_FLAGS,
                        "--ansi",
                        "--listen",
                        str(listen_port),
                        "--with-nth",
                        "2",
                        "--delimiter",
                        "\t",
                        "--prompt",
                        "Branch > ",
                        "--header",
                        initial_header,
                        "--expect",
                        "ctrl-bs",
                        "--bind",
                        ctrl_f_bind,
                    ],
                    stdin=input_f,
                    capture_output=True,
                    text=True,
                )
            initial_header = _BRANCH_HEADER

            if result.returncode == 130:
                return BranchChoice(kind="cancel")
            if not result.stdout:
                return BranchChoice(kind="cancel")

            key, item = _parse_fzf_selection(result.stdout)
            if key == "ctrl-bs":
                return BranchChoice(kind="back")
            if not item:
                return BranchChoice(kind="cancel")

            if item != "[new]":
                return BranchChoice(kind="existing", name=item)

            name_result = subprocess.run(
                [
                    "fzf",
                    *FZF_POPUP_FLAGS,
                    "--print-query",
                    "--no-select-1",
                    "--prompt",
                    "New branch name: ",
                    "--header",
                    _NEW_NAME_HEADER,
                    "--expect",
                    "ctrl-bs",
                ],
                input="",
                capture_output=True,
                text=True,
            )
            if name_result.returncode == 130:
                return BranchChoice(kind="cancel")
            name_lines = name_result.stdout.split("\n")
            query = name_lines[0] if name_lines else ""
            name_key = name_lines[1] if len(name_lines) > 1 else ""
            if name_key == "ctrl-bs":
                continue
            new_name = text.sanitize_name(query)
            if not new_name:
                continue
            return BranchChoice(kind="new", name=new_name)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmpfile.unlink()
        if fetch_proc is not None and fetch_proc.poll() is None:
            with contextlib.suppress(OSError):
                fetch_proc.terminate()
