"""Resolved env-driven configuration for tmux-worktree-sessions.

The picker UIs and the action subcommands both read the same ``@tws-*``
tmux options. Owning that schema here (rather than splitting it between
``__main__`` and ``picker``) keeps the env keys, defaults, and types in
one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import git
from .icons import IconSet


@dataclass(frozen=True)
class Config:
    """Env-driven knobs the picker and its action handlers consume.

    Resolved once per process — the parent ``manage`` loop and each
    action subprocess fzf spawns each call ``Config.from_env()`` at
    entry. ``score_file`` is always resolved to a path (never ``None``)
    so the bump path doesn't branch on configured-or-not.
    """

    home: str
    projects_roots: list[Path]
    max_depth: int
    strip_prefixes: list[str]
    manual_spec: str
    half_life_secs: float
    path_boost: float
    score_file: Path
    icons: IconSet
    default_branch_fallback: str
    worktrees_dir: str
    default_layout: git.ConcreteWorktreeLayout

    @classmethod
    def from_env(cls) -> Config:
        home = os.environ.get("HOME", "")
        return cls(
            home=home,
            projects_roots=_parse_projects_roots(home),
            max_depth=int(os.environ.get("TWS_MAX_DEPTH") or 6),
            strip_prefixes=(os.environ.get("TWS_STRIP_PREFIXES") or "").split(),
            manual_spec=os.environ.get("TWS_MANUAL_SESSIONS") or "",
            half_life_secs=_parse_half_life_secs(),
            path_boost=float(os.environ.get("TWS_SCORE_PATH_BOOST") or 1.0),
            score_file=_parse_score_file(home),
            icons=IconSet.from_style(os.environ.get("TWS_ICON_STYLE") or "nerd"),
            default_branch_fallback=os.environ.get("TWS_DEFAULT_BRANCH") or "main",
            worktrees_dir=os.environ.get("TWS_WORKTREES_DIR") or ".worktrees",
            default_layout=_parse_default_layout(),
        )


def _parse_projects_roots(home: str) -> list[Path]:
    raw_dirs = os.environ.get("TWS_PROJECTS_DIRS") or f"{home}/Projects"
    roots: list[Path] = []
    for entry in raw_dirs.split():
        expanded = entry.replace("~", home, 1) if entry.startswith("~") else entry
        roots.append(Path(expanded))
    return roots


def _parse_score_file(home: str) -> Path:
    score_file_str = (
        os.environ.get("SCORE_FILE") or os.environ.get("TWS_SCORES_FILE") or f"{home}/.local/share/tws/scores.tsv"
    )
    return Path(score_file_str)


def _parse_half_life_secs() -> float:
    half_life_days = float(os.environ.get("TWS_SCORE_HALF_LIFE") or 14)
    return half_life_days * 24 * 3600


def _parse_default_layout() -> git.ConcreteWorktreeLayout:
    raw_layout = os.environ.get("TWS_DEFAULT_WORKTREE_LAYOUT") or "subfolder"
    return "sibling" if raw_layout == "sibling" else "subfolder"
