"""Picker entry generation for tmux-sessions.

Pure helpers that build the TSV rows fzf consumes. Subprocess calls into
real ``git`` happen via :mod:`tmux_sessions.git`; this module owns the
icon/format logic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from . import git


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
            session=" ",
            project=" ",
            branch=" ",
            remote=" ",
            new=" ",
        )


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
