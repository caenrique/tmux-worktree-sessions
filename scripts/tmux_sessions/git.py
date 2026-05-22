"""Pure git helpers for tmux-sessions.

Functions in this module take all inputs as explicit parameters; the
CLI layer in ``tmux_sessions.__main__`` resolves env/args and writes
the result. Subprocess calls to real ``git`` are external state queries
and live here per the migration plan.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
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


def list_branches(repo: Path) -> list[str]:
    """Return local branches followed by remote-only branches.

    Remote-only branches are prefixed with ``<remote>/`` and listed
    in sorted order; the remote ``HEAD`` ref is excluded. When ``repo``
    has no remote, only local branches are returned. Local branch order
    matches ``git branch`` output (alphabetical by default).
    """
    local_result = _git(repo, "branch", "--format", "%(refname:short)")
    local = [line for line in local_result.stdout.splitlines() if line]

    remote = resolve_remote(repo)
    if remote is None:
        return local

    remote_result = _git(repo, "branch", "-r", "--format", "%(refname:short)")
    prefix = f"{remote}/"
    head_ref = f"{prefix}HEAD"
    remote_branches = [
        line for line in remote_result.stdout.splitlines() if line.startswith(prefix) and line != head_ref
    ]
    local_set = set(local)
    remote_only = sorted(r for r in remote_branches if r[len(prefix) :] not in local_set)
    return local + remote_only


@dataclass(frozen=True)
class Worktree:
    """A git worktree: filesystem path and the branch it has checked out.

    ``branch`` is the bare branch name (no ``refs/heads/`` prefix).
    Detached worktrees use the literal string ``"(detached)"``, matching
    the bash awk pipeline this dataclass replaced.
    """

    path: Path
    branch: str


def list_worktrees(repo: Path) -> list[Worktree]:
    """Parse ``git worktree list --porcelain`` into ``Worktree`` rows.

    Detached worktrees are reported with ``branch == "(detached)"`` so
    callers can render the column without a special case.
    """
    result = _git(repo, "worktree", "list", "--porcelain")
    if result.returncode != 0:
        return []

    worktrees: list[Worktree] = []
    path: str | None = None
    branch = ""

    def _flush() -> None:
        nonlocal path, branch
        if path is not None:
            worktrees.append(Worktree(Path(path), branch or "(detached)"))
            path = None
            branch = ""

    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            _flush()
            path = line[len("worktree ") :]
            branch = ""
        elif line.startswith("branch "):
            ref = line[len("branch ") :]
            heads_prefix = "refs/heads/"
            branch = ref[len(heads_prefix) :] if ref.startswith(heads_prefix) else ref
        elif line == "detached":
            branch = "(detached)"
        elif line == "":
            _flush()
    _flush()
    return worktrees
