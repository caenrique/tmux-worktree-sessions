"""Pure git helpers for tmux-sessions.

Functions in this module take all inputs as explicit parameters; the
CLI layer in ``tmux_sessions.__main__`` resolves env/args and writes
the result. Subprocess calls to real ``git`` are external state queries
and live here per the migration plan.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def branch_to_dir(name: str) -> str:
    """Convert a branch name to a safe directory name.

    Both ``/`` and space become ``-`` so a branch like ``feature/login``
    can be the basename of a worktree directory.
    """
    return name.replace("/", "-").replace(" ", "-")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )


def resolve_remote(repo: Path) -> str | None:
    """Return ``origin`` if configured, otherwise the first listed remote.

    ``None`` is returned when the repo has no remotes or ``git remote``
    fails (e.g. ``repo`` is not a git directory).
    """
    result = _git(repo, "remote")
    if result.returncode != 0:
        return None
    remotes = [line for line in result.stdout.splitlines() if line]
    if not remotes:
        return None
    if "origin" in remotes:
        return "origin"
    return remotes[0]


def default_branch(repo: Path) -> str | None:
    """Return the default remote branch name (e.g. ``main``).

    Reads ``refs/remotes/<remote>/HEAD``, which git sets after
    ``git remote set-head``. Returns ``None`` if no remote is
    configured or the remote HEAD is unset.
    """
    remote = resolve_remote(repo)
    if remote is None:
        return None
    result = _git(repo, "symbolic-ref", f"refs/remotes/{remote}/HEAD")
    if result.returncode != 0:
        return None
    ref = result.stdout.strip()
    if not ref:
        return None
    return ref.rsplit("/", 1)[-1]
