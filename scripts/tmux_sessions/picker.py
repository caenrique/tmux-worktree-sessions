"""Picker entry generation for tmux-sessions.

Pure helpers that build the TSV rows fzf consumes plus the interactive
``pick_branch`` loop that drives fzf itself. Subprocess calls into real
``git`` happen via :mod:`tmux_sessions.git`; this module owns the
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

# Shared fzf style flags. Mirror the FZF_INLINE / FZF_POPUP shell
# variables in scripts/common.sh so behaviour is identical when invoked
# from Python or from the bash shims.
FZF_INLINE_FLAGS: tuple[str, ...] = (
    "--reverse",
    "--no-scrollbar",
    "--no-info",
    "--no-separator",
    "--no-border",
    "--color",
    "header:#6c7086",
)
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
    ``none`` style — matching the bash ``_ICON_SEP="${_ICON_SESSION:+ }"``
    derivation so ``f"{icon}{sep}{label}"`` doesn't leave a stray space
    when the user disabled icons.
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
        # default: nerd
        return cls(
            session=" ",
            project=" ",
            branch=" ",
            remote=" ",
            new=" ",
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


def gen_branch_picker_entries(repo: Path, *, icons: IconSet) -> Iterator[str]:
    """Yield TSV lines for the branch picker.

    First line is the ``[new]`` sentinel, then one line per branch
    returned by :func:`tmux_sessions.git.list_branches`. Branches whose
    name starts with ``<remote>/`` get the remote icon; the rest get the
    branch icon. When the repo has no remote, every branch falls through
    to the local icon (matching the bash behaviour).
    """
    remote = git.resolve_remote(repo)
    yield f"[new]\t{icons.new}{icons.sep}new branch"
    remote_prefix = f"{remote}/" if remote else None
    for branch in git.list_branches(repo):
        is_remote = remote_prefix is not None and branch.startswith(remote_prefix)
        icon = icons.remote if is_remote else icons.branch
        yield f"{branch}\t{icon}{icons.sep}{branch}"


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
        for line in gen_branch_picker_entries(repo, icons=icons):
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
