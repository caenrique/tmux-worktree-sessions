"""Pure git helpers for tmux-worktree-sessions.

Functions in this module take all inputs as explicit parameters; the
CLI layer in ``tmux_worktree_sessions.__main__`` resolves env/args and writes
the result. Subprocess calls to real ``git`` are external state queries
and live here per the migration plan.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

WorktreeLayout = Literal["sibling", "subfolder", "ambiguous"]
ConcreteWorktreeLayout = Literal["sibling", "subfolder"]


def list_git_projects(roots: list[Path], *, max_depth: int) -> list[Path]:
    """Return paths of directories that contain ``.git`` under any root.

    Shells out to ``fd``, which is a hard runtime dependency of the
    plugin. ``fd`` matches ``.git`` as either a directory (regular
    checkout) or a file (linked worktree), prunes ``node_modules``
    subtrees, and stops descending into a found repo. ``max_depth``
    bounds how deep below each root the search descends.

    Roots that do not exist or are not directories are silently skipped.
    """
    existing = [r for r in roots if r.is_dir()]
    if not existing:
        return []
    # ``--format`` is only available in fd ≥ 10.0; Ubuntu apt still ships
    # fd 9.x. Print the matched ``.git`` entries and strip the trailing
    # component in Python so the call works on every supported fd.
    # ``--no-ignore-vcs`` is also required: fd 9.x special-cases ``.git``
    # and skips it even with ``--hidden`` unless VCS-ignore is disabled
    # (fd ≥ 10 dropped that behavior).
    cmd = [
        "fd",
        "--hidden",  # search hidden entries; .git starts with a dot
        "--no-ignore-vcs",  # fd 9.x hides .git unless VCS-ignore is off
        "^.git$",  # match exactly the basename '.git'
        "--type",
        "directory",  # match regular checkouts (.git as a dir)
        "--type",
        "file",  # also match linked worktrees (.git as a file)
        f"--max-depth={max_depth}",  # bound the descent depth
        "--prune",  # don't descend into a directory once it matches
        "--exclude",
        "node_modules",  # skip noisy dependency trees
        *(str(r) for r in existing),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    seen: set[Path] = set()
    projects: list[Path] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        path = Path(line).parent
        if path not in seen:
            seen.add(path)
            projects.append(path)
    return projects


def fetch_is_stale(mtime: float | None, *, now: float, window_secs: int = 900) -> bool:
    """Return True when a fetch should run.

    ``mtime`` is the FETCH_HEAD modification time (seconds since the epoch),
    or ``None`` when the file does not exist or its mtime cannot be read.
    A missing/unreadable mtime is treated as stale so a fresh fetch runs.
    """
    if mtime is None:
        return True
    return (now - mtime) > window_secs


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


def current_branch(path: Path) -> str | None:
    """Return ``branch --show-current`` for ``path``, or ``None``.

    Returns ``None`` for detached HEAD (git prints an empty line) and
    for paths that aren't inside a git repo (non-zero exit). Callers
    that want to distinguish those two cases can call ``toplevel``
    first.
    """
    result = _git(path, "branch", "--show-current")
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


def fetch_head_mtime(repo: Path) -> float | None:
    """Return the mtime of ``FETCH_HEAD`` for ``repo``, or ``None``.

    Resolves ``--git-common-dir`` so the lookup is correct from inside a
    linked worktree. Returns ``None`` when ``repo`` is not a git
    directory or ``FETCH_HEAD`` does not exist yet.
    """
    result = _git(repo, "rev-parse", "--git-common-dir")
    if result.returncode != 0:
        return None
    common_dir = Path(result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = repo / common_dir
    fetch_head = common_dir / "FETCH_HEAD"
    try:
        return fetch_head.stat().st_mtime
    except FileNotFoundError:
        return None


def fetch_all(repo: Path) -> bool:
    """Run ``git fetch --all --quiet`` in ``repo``; return success.

    Output is captured (not propagated) so callers can run this in the
    background without spamming the terminal. A non-zero exit is returned
    as ``False`` rather than raised — the picker treats network failures
    as non-fatal and still reloads the local branch list.
    """
    result = subprocess.run(
        ["git", "-C", str(repo), "fetch", "--all", "--quiet"],
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def worktree_remove(repo: Path, wt_path: Path | str, *, force: bool = True) -> None:
    """Run ``git worktree remove`` for ``wt_path``; errors are swallowed.

    The ``--force`` flag is on by default to match the picker's
    delete-without-prompt behaviour for a worktree that lost its
    backing branch or has untracked files.
    """
    cmd = ["git", "-C", str(repo), "worktree", "remove"]
    if force:
        cmd.append("--force")
    cmd.append(str(wt_path))
    subprocess.run(cmd, capture_output=True)


def toplevel(path: Path) -> Path | None:
    """Return ``rev-parse --show-toplevel`` for ``path``, or ``None``."""
    result = _git(path, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return Path(out) if out else None


def is_linked_worktree(path: Path) -> bool:
    """Return True when ``path`` is a linked git worktree (not the main checkout).

    git stores the per-worktree dir under ``<repo>/.git/worktrees/<name>``,
    so ``rev-parse --git-dir`` returning a path that contains a
    ``worktrees`` segment is the canonical "this is a linked worktree"
    signal. Returns False for the main checkout, plain directories, and
    anything outside a git repo.
    """
    result = _git(path, "rev-parse", "--git-dir")
    if result.returncode != 0:
        return False
    return "worktrees" in result.stdout.strip()


def main_worktree(repo: Path) -> Path | None:
    """Return the path of the main worktree (the regular checkout).

    ``git worktree list --porcelain`` always lists the main worktree
    first, so we just take the first parsed entry. Returns ``None`` when
    ``repo`` is not a git directory.
    """
    worktrees = list_worktrees(repo)
    return worktrees[0].path if worktrees else None


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
    Detached worktrees use the literal string ``"(detached)"`` so
    callers can render the column without a special case.
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


def detect_layout(repo: Path, *, worktrees_dir: str) -> WorktreeLayout:
    """Classify the worktree layout used by ``repo``.

    Returns ``"sibling"`` when every linked worktree sits next to the
    main checkout (``<wt>.parent == <main>.parent``), ``"subfolder"``
    when every linked worktree sits under ``<main>/<worktrees_dir>/``,
    and ``"ambiguous"`` when there are no linked worktrees yet or the
    existing ones don't all match a single shape. The caller is expected
    to resolve ``"ambiguous"`` to a concrete layout via the configured
    default before placing new worktrees.
    """
    worktrees = list_worktrees(repo)
    if len(worktrees) < 2:
        return "ambiguous"
    main = worktrees[0].path
    linked = [wt.path for wt in worktrees[1:]]

    sibling_parent = main.parent
    if all(wt.parent == sibling_parent for wt in linked):
        return "sibling"

    subfolder_parent = main / worktrees_dir
    if all(wt.parent == subfolder_parent for wt in linked):
        return "subfolder"

    return "ambiguous"


def worktree_container(
    main: Path,
    *,
    layout: ConcreteWorktreeLayout,
    worktrees_dir: str,
) -> Path:
    """Return the directory new worktrees should be placed under.

    For ``"sibling"`` layout this is ``<main>.parent`` (where
    sibling-layout repos already keep their checkouts). For
    ``"subfolder"`` it is ``<main>/<worktrees_dir>``. The caller owns
    ensuring the directory exists before invoking ``git worktree add``.
    """
    if layout == "sibling":
        return main.parent
    return main / worktrees_dir


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

    The interactive fzf rename prompt lives in the CLI dispatcher; this
    function only owns the post-prompt git/move/repair half.
    """
    old_branch = current_branch(wt_path)
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
