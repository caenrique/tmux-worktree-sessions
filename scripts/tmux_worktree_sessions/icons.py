"""Icon set used by every picker row.

Hosts the :class:`IconSet` dataclass plus its style-name factory. Lives
in its own module so :mod:`tmux_worktree_sessions.config` (which holds
the resolved ``IconSet``) and :mod:`tmux_worktree_sessions.picker`
(which renders rows) can both import it without a circular dependency.
"""

from __future__ import annotations

from dataclasses import dataclass


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
                new="✨",
            )
        # default: nerd. Written as \\uXXXX escapes — the literal glyphs
        # were silently flattened to plain spaces during the bash → Python
        # migration (scripts/common.sh in commit 2e40556 had them inline).
        return cls(
            session="",
            project="",
            branch="",
            remote="",
            new="",
        )
