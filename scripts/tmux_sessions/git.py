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


def add_worktree(
    repo: Path,
    container: Path,
    *,
    branch: str | None,
    new_name: str | None,
    default_branch_fallback: str,
) -> Path:
    """Create or reuse a worktree under ``container``.

    Exactly one of ``branch`` (existing branch, possibly remote-prefixed
    like ``origin/foo``) or ``new_name`` (a brand-new branch off the
    default branch) should be supplied. Returns the worktree path.

    When ``new_name`` is set, the new branch is created from
    ``<remote>/<default>`` if the repo has a remote, falling back to
    ``default_branch_fallback`` (usually ``main``) when the remote
    HEAD is unset. When ``branch`` is set and a worktree already has
    that branch checked out, the existing path is returned unchanged.
    Remote-only branches (``<remote>/foo``) are checked out as a new
    local branch ``foo`` that tracks the remote.

    Git's progress messages stream to the caller's stderr; git's
    stdout is dropped so the returned path stays clean.
    """
    remote = resolve_remote(repo)

    if new_name:
        dir_name = branch_to_dir(new_name)
        worktree_path = container / dir_name
        resolved_default = default_branch(repo) or default_branch_fallback
        base_ref = f"{remote}/{resolved_default}" if remote is not None else resolved_default
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "worktree",
                "add",
                "-b",
                new_name,
                str(worktree_path),
                base_ref,
            ],
            stdout=subprocess.DEVNULL,
            check=True,
        )
        return worktree_path

    if branch is None:
        raise ValueError("add_worktree requires either branch or new_name")

    if remote is not None and branch.startswith(f"{remote}/"):
        local_branch = branch[len(remote) + 1 :]
        is_remote_only = True
    else:
        local_branch = branch
        is_remote_only = False

    for wt in list_worktrees(repo):
        if wt.branch == local_branch:
            return wt.path

    dir_name = branch_to_dir(local_branch)
    worktree_path = container / dir_name
    if is_remote_only:
        cmd = [
            "git",
            "-C",
            str(repo),
            "worktree",
            "add",
            "-b",
            local_branch,
            str(worktree_path),
            branch,
        ]
    else:
        cmd = ["git", "-C", str(repo), "worktree", "add", str(worktree_path), branch]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, check=True)
    return worktree_path


def rename_worktree(
    repo: Path,
    container: Path,
    wt_path: Path,
    *,
    new_name: str,
) -> Path:
    """Rename a worktree's branch, move the directory, and repair linkage.

    Returns the new worktree path. Raises ``RuntimeError`` for the user-
    facing failure modes (detached HEAD, destination exists, branch
    rename or filesystem move failed) so the CLI can map them to
    ``stderr`` plus exit 1.

    The interactive fzf prompt that picks ``new_name`` lives in bash;
    this function only owns the post-prompt git/move/repair half of
    the operation.
    """
    show = subprocess.run(
        ["git", "-C", str(wt_path), "branch", "--show-current"],
        capture_output=True,
        text=True,
    )
    old_branch = show.stdout.strip() if show.returncode == 0 else ""
    if not old_branch:
        raise RuntimeError("Cannot rename: worktree is in detached HEAD state")

    new_dir = branch_to_dir(new_name)
    new_wt_path = container / new_dir
    if new_wt_path.exists():
        raise RuntimeError(f"Destination already exists: {new_wt_path}")

    rename_rc = subprocess.run(
        ["git", "-C", str(wt_path), "branch", "-m", old_branch, new_name],
        stdout=subprocess.DEVNULL,
    ).returncode
    if rename_rc != 0:
        raise RuntimeError(f"git branch -m {old_branch} {new_name} failed")

    try:
        wt_path.rename(new_wt_path)
    except OSError as exc:
        subprocess.run(
            ["git", "-C", str(wt_path), "branch", "-m", new_name, old_branch],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        raise RuntimeError(f"mv {wt_path} -> {new_wt_path} failed: {exc}") from exc

    subprocess.run(
        ["git", "-C", str(new_wt_path), "worktree", "repair"],
        stdout=subprocess.DEVNULL,
    )
    return new_wt_path
