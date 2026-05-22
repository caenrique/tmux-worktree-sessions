"""Pure-layer tests for :mod:`tmux_sessions.git`.

Mirrors the bats coverage in ``tests/common.bats`` for ``branch_to_dir``,
``_resolve_remote``, and ``get_default_branch``. The remote/HEAD cases
spin up real git repos via the ``make_repo`` fixture in ``conftest.py``
because ``resolve_remote``/``default_branch`` shell out to real ``git``.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from tmux_sessions.git import (
    add_worktree,
    branch_to_dir,
    default_branch,
    fetch_is_stale,
    list_branches,
    list_worktrees,
    rename_worktree,
    resolve_remote,
)


def test_fetch_is_stale_missing_mtime_is_stale() -> None:
    assert fetch_is_stale(None, now=1_000_000.0) is True


def test_fetch_is_stale_fresh_is_not_stale() -> None:
    now = 1_000_000.0
    assert fetch_is_stale(now - 60.0, now=now) is False


def test_fetch_is_stale_older_than_window_is_stale() -> None:
    now = 1_000_000.0
    assert fetch_is_stale(now - 901.0, now=now) is True


def test_fetch_is_stale_custom_window() -> None:
    now = 1_000_000.0
    assert fetch_is_stale(now - 30.0, now=now, window_secs=10) is True
    assert fetch_is_stale(now - 5.0, now=now, window_secs=10) is False


def test_branch_to_dir_replaces_slashes_with_dashes() -> None:
    assert branch_to_dir("feature/login") == "feature-login"


def test_branch_to_dir_replaces_spaces_with_dashes() -> None:
    assert branch_to_dir("with spaces") == "with-spaces"


def test_resolve_remote_returns_origin_when_configured(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r", with_remote=True)
    assert resolve_remote(repo) == "origin"


def test_resolve_remote_falls_back_to_first_remote_when_origin_absent(
    make_repo: Callable[..., Path], tmp_path: Path
) -> None:
    repo = make_repo("r")
    upstream = tmp_path / "upstream.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(upstream)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "upstream", str(upstream)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert resolve_remote(repo) == "upstream"


def test_resolve_remote_returns_none_when_no_remotes(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r")
    assert resolve_remote(repo) is None


def test_default_branch_returns_remote_head(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r", with_remote=True)
    assert default_branch(repo) == "main"


def test_default_branch_returns_none_when_remote_head_unset(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r")
    assert default_branch(repo) is None


def test_list_branches_local_plus_remote_only_with_origin_prefix(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r", branches=("main", "feature"), with_remote=True)
    main_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "update-ref",
            "refs/remotes/origin/server-only",
            main_sha,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    branches = list_branches(repo)

    assert "main" in branches
    assert "feature" in branches
    assert "origin/server-only" in branches


def test_list_branches_local_tracking_remote_not_duplicated(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r", with_remote=True)
    branches = list_branches(repo)
    assert branches.count("main") == 1


def test_list_branches_no_remote_returns_only_local(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r", branches=("main", "feature"))
    branches = list_branches(repo)
    assert "main" in branches
    assert "feature" in branches
    assert not any(b.startswith("origin/") for b in branches)


def test_list_worktrees_main_only(make_repo: Callable[..., Path]) -> None:
    repo = make_repo("r")
    worktrees = list_worktrees(repo)
    assert len(worktrees) == 1
    assert worktrees[0].branch == "main"
    assert worktrees[0].path == repo


def test_list_worktrees_lists_multiple(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    repo = make_repo("r")
    feature_path = tmp_path / "feature"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feature", str(feature_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    branches = {wt.branch for wt in list_worktrees(repo)}
    assert "main" in branches
    assert "feature" in branches


def test_add_worktree_creates_new_branch_from_remote_default(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    repo = make_repo("r", with_remote=True)
    container = tmp_path / "container"
    container.mkdir()

    path = add_worktree(
        repo,
        container,
        branch=None,
        new_name="shiny",
        default_branch_fallback="main",
    )

    assert path == container / "shiny"
    assert path.is_dir()
    head = subprocess.run(
        ["git", "-C", str(path), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head == "shiny"


def test_add_worktree_checks_out_existing_local_branch(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    repo = make_repo("r", branches=("main", "feature"), with_remote=True)
    container = tmp_path / "container"
    container.mkdir()

    path = add_worktree(
        repo,
        container,
        branch="feature",
        new_name=None,
        default_branch_fallback="main",
    )

    assert path == container / "feature"
    assert path.is_dir()


def test_add_worktree_returns_existing_path_when_branch_already_checked_out(
    make_repo: Callable[..., Path], tmp_path: Path
) -> None:
    repo = make_repo("r", branches=("main", "feature"), with_remote=True)
    container = tmp_path / "container"
    container.mkdir()
    existing = container / "feature"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", str(existing), "feature"],
        check=True,
        capture_output=True,
        text=True,
    )

    path = add_worktree(
        repo,
        container,
        branch="feature",
        new_name=None,
        default_branch_fallback="main",
    )

    assert path == existing


def test_add_worktree_remote_only_creates_tracking_branch(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    repo = make_repo("r", with_remote=True)
    main_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "update-ref",
            "refs/remotes/origin/remote-only",
            main_sha,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    container = tmp_path / "container"
    container.mkdir()

    path = add_worktree(
        repo,
        container,
        branch="origin/remote-only",
        new_name=None,
        default_branch_fallback="main",
    )

    assert path == container / "remote-only"
    head = subprocess.run(
        ["git", "-C", str(path), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head == "remote-only"


def test_list_worktrees_marks_detached_head(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    repo = make_repo("r")
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    det_path = tmp_path / "det"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(det_path), sha],
        check=True,
        capture_output=True,
        text=True,
    )
    branches = [wt.branch for wt in list_worktrees(repo)]
    assert "(detached)" in branches


def test_rename_worktree_renames_branch_moves_dir_and_repairs(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    repo = make_repo("r", branches=("main", "feature"))
    container = tmp_path
    feature_path = container / "feature"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", str(feature_path), "feature"],
        check=True,
        capture_output=True,
        text=True,
    )

    new_path = rename_worktree(repo, container, feature_path, new_name="renamed-feature")

    assert new_path == container / "renamed-feature"
    assert new_path.is_dir()
    assert not feature_path.exists()
    head = subprocess.run(
        ["git", "-C", str(new_path), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head == "renamed-feature"


def test_rename_worktree_detached_head_raises(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    repo = make_repo("r")
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    det_path = tmp_path / "det"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(det_path), sha],
        check=True,
        capture_output=True,
        text=True,
    )

    with pytest.raises(RuntimeError, match="detached HEAD"):
        rename_worktree(repo, tmp_path, det_path, new_name="anything")


def test_rename_worktree_destination_exists_raises(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    repo = make_repo("r", branches=("main", "feature"))
    container = tmp_path
    feature_path = container / "feature"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", str(feature_path), "feature"],
        check=True,
        capture_output=True,
        text=True,
    )
    blocker = container / "renamed"
    blocker.mkdir()

    with pytest.raises(RuntimeError, match="Destination already exists"):
        rename_worktree(repo, container, feature_path, new_name="renamed")

    assert feature_path.is_dir()  # rollback: original worktree untouched
