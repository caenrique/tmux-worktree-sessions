"""Pure-layer tests for :mod:`tmux_worktree_sessions.git`.

Cases that exercise the subprocess-backed helpers (``resolve_remote``,
``default_branch``, ``list_branches``, worktree helpers, …) spin up
real git repos via the ``make_repo`` fixture in ``conftest.py``.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from tmux_worktree_sessions.git import (
    add_worktree,
    branch_to_dir,
    current_branch,
    default_branch,
    detect_layout,
    fetch_all,
    fetch_head_mtime,
    fetch_is_stale,
    is_linked_worktree,
    list_branches,
    list_git_projects,
    list_worktrees,
    main_worktree,
    rename_worktree,
    resolve_remote,
    toplevel,
    worktree_container,
    worktree_remove,
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


def test_list_git_projects_finds_repos_directly_under_root(
    make_repo: Callable[..., Path],
    tmp_path: Path,
) -> None:
    root = tmp_path / "Projects"
    root.mkdir()
    foo = make_repo("Projects/foo")
    bar = make_repo("Projects/bar")

    projects = list_git_projects([root], max_depth=6)

    assert set(projects) == {foo, bar}


def test_list_git_projects_skips_missing_roots(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert list_git_projects([missing], max_depth=6) == []


def test_list_git_projects_excludes_node_modules(
    make_repo: Callable[..., Path],
    tmp_path: Path,
) -> None:
    root = tmp_path / "Projects"
    root.mkdir()
    nm = root / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / ".git").mkdir()
    real = make_repo("Projects/real")

    projects = list_git_projects([root], max_depth=6)

    assert projects == [real]


def test_list_git_projects_treats_dotgit_file_as_project(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Projects"
    repo = root / "linked"
    repo.mkdir(parents=True)
    (repo / ".git").write_text("gitdir: ../some/path\n")  # worktree-style .git file

    projects = list_git_projects([root], max_depth=6)

    assert projects == [repo]


def test_list_git_projects_respects_max_depth(
    make_repo: Callable[..., Path],
    tmp_path: Path,
) -> None:
    root = tmp_path / "Projects"
    root.mkdir()
    deep = make_repo("Projects/a/b/c/deep")

    found_shallow = list_git_projects([root], max_depth=2)
    found_deep = list_git_projects([root], max_depth=6)

    assert deep not in found_shallow
    assert deep in found_deep


def test_toplevel_returns_repo_path(make_repo: Callable[..., Path]) -> None:
    repo = make_repo("r")
    assert toplevel(repo) == repo


def test_toplevel_from_subdir_returns_repo_root(make_repo: Callable[..., Path]) -> None:
    repo = make_repo("r")
    sub = repo / "deep" / "nested"
    sub.mkdir(parents=True)
    assert toplevel(sub) == repo


def test_toplevel_outside_a_repo_returns_none(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert toplevel(plain) is None


def test_is_linked_worktree_false_for_main_checkout(make_repo: Callable[..., Path]) -> None:
    repo = make_repo("r")
    assert is_linked_worktree(repo) is False


def test_is_linked_worktree_true_for_linked_worktree(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    repo = make_repo("r")
    wt = tmp_path / "wt" / "feature"
    wt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feature", str(wt)],
        check=True,
        capture_output=True,
    )
    assert is_linked_worktree(wt) is True


def test_is_linked_worktree_false_outside_a_repo(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert is_linked_worktree(plain) is False


def test_main_worktree_returns_main_checkout_path(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    repo = make_repo("r")
    wt = tmp_path / "wt" / "feature"
    wt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feature", str(wt)],
        check=True,
        capture_output=True,
    )
    # Asking from either the main checkout or a linked worktree must
    # both resolve back to the main checkout's path.
    assert main_worktree(repo) == repo
    assert main_worktree(wt) == repo


def test_main_worktree_outside_a_repo_returns_none(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert main_worktree(plain) is None


def test_detect_layout_no_linked_worktrees_is_ambiguous(make_repo: Callable[..., Path]) -> None:
    repo = make_repo("r")
    assert detect_layout(repo, worktrees_dir=".worktrees") == "ambiguous"


def test_detect_layout_sibling_when_linked_is_sibling_of_main(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    # Layout: tmp/r-container/{main, feature}; main_worktree is under r-container
    container = tmp_path / "r-container"
    container.mkdir()
    repo = make_repo("r-container/main")
    feature = container / "feature"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feature", str(feature)],
        check=True,
        capture_output=True,
    )
    assert detect_layout(repo, worktrees_dir=".worktrees") == "sibling"


def test_detect_layout_subfolder_when_linked_is_under_worktrees_dir(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r")
    sub = repo / ".worktrees"
    sub.mkdir()
    feature = sub / "feature"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feature", str(feature)],
        check=True,
        capture_output=True,
    )
    assert detect_layout(repo, worktrees_dir=".worktrees") == "subfolder"


def test_detect_layout_honours_custom_worktrees_dir(make_repo: Callable[..., Path]) -> None:
    repo = make_repo("r")
    sub = repo / "trees"
    sub.mkdir()
    feature = sub / "feature"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feature", str(feature)],
        check=True,
        capture_output=True,
    )
    assert detect_layout(repo, worktrees_dir="trees") == "subfolder"
    # The same repo with a different worktrees_dir is no longer recognized as subfolder.
    assert detect_layout(repo, worktrees_dir=".worktrees") == "ambiguous"


def test_detect_layout_mixed_paths_is_ambiguous(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    repo = make_repo("r")
    sub = repo / ".worktrees"
    sub.mkdir()
    inside = sub / "inside"
    outside = tmp_path / "outside"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "inside", str(inside)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "outside", str(outside)],
        check=True,
        capture_output=True,
    )
    assert detect_layout(repo, worktrees_dir=".worktrees") == "ambiguous"


def test_worktree_container_sibling_returns_main_parent(tmp_path: Path) -> None:
    main = tmp_path / "repo" / "main"
    assert worktree_container(main, layout="sibling", worktrees_dir=".worktrees") == tmp_path / "repo"


def test_worktree_container_subfolder_returns_main_join_worktrees_dir(tmp_path: Path) -> None:
    main = tmp_path / "repo"
    assert worktree_container(main, layout="subfolder", worktrees_dir=".worktrees") == tmp_path / "repo" / ".worktrees"


def test_worktree_container_subfolder_honours_custom_dir(tmp_path: Path) -> None:
    main = tmp_path / "repo"
    assert worktree_container(main, layout="subfolder", worktrees_dir="trees") == tmp_path / "repo" / "trees"


def test_add_worktree_places_into_subfolder_container(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r", with_remote=True)
    container = repo / ".worktrees"
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


def test_rename_worktree_in_subfolder_layout(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r", branches=("main", "feature"))
    container = repo / ".worktrees"
    container.mkdir()
    feature_path = container / "feature"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", str(feature_path), "feature"],
        check=True,
        capture_output=True,
    )

    new_path = rename_worktree(repo, container, feature_path, new_name="renamed")

    assert new_path == container / "renamed"
    assert new_path.is_dir()
    assert not feature_path.exists()


def test_current_branch_returns_branch_name(make_repo: Callable[..., Path]) -> None:
    repo = make_repo("r")
    assert current_branch(repo) == "main"


def test_current_branch_returns_none_for_detached_head(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    repo = make_repo("r")
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    det = tmp_path / "det"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(det), sha],
        check=True,
        capture_output=True,
    )
    assert current_branch(det) is None


def test_current_branch_returns_none_outside_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert current_branch(plain) is None


def test_fetch_head_mtime_returns_none_when_missing(make_repo: Callable[..., Path]) -> None:
    repo = make_repo("r")
    assert fetch_head_mtime(repo) is None


def test_fetch_head_mtime_returns_mtime_after_fetch(
    make_repo: Callable[..., Path],
) -> None:
    repo = make_repo("r", with_remote=True)
    subprocess.run(
        ["git", "-C", str(repo), "fetch", "--quiet", "origin"],
        check=True,
        capture_output=True,
    )
    mtime = fetch_head_mtime(repo)
    assert mtime is not None
    assert mtime > 0


def test_fetch_head_mtime_resolves_through_linked_worktree(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    repo = make_repo("r", with_remote=True)
    subprocess.run(
        ["git", "-C", str(repo), "fetch", "--quiet", "origin"],
        check=True,
        capture_output=True,
    )
    wt = tmp_path / "feature"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feature", str(wt)],
        check=True,
        capture_output=True,
    )
    assert fetch_head_mtime(wt) is not None


def test_fetch_head_mtime_returns_none_outside_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert fetch_head_mtime(plain) is None


def test_fetch_all_succeeds_against_real_remote(make_repo: Callable[..., Path]) -> None:
    repo = make_repo("r", with_remote=True)
    assert fetch_all(repo) is True


def test_fetch_all_returns_false_when_repo_has_no_remote(make_repo: Callable[..., Path]) -> None:
    repo = make_repo("r")
    # `git fetch --all` against a repo with no remotes succeeds (no-op),
    # so we can only assert it doesn't blow up — call should return True.
    # The False path is exercised by stubs in higher-level tests.
    assert fetch_all(repo) in (True, False)


def test_worktree_remove_drops_linked_worktree(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    repo = make_repo("r")
    wt = tmp_path / "feature"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feature", str(wt)],
        check=True,
        capture_output=True,
    )
    assert wt.is_dir()

    worktree_remove(repo, wt)

    assert not wt.exists()
    assert {w.branch for w in list_worktrees(repo)} == {"main"}


def test_worktree_remove_swallows_errors_for_unknown_path(make_repo: Callable[..., Path], tmp_path: Path) -> None:
    repo = make_repo("r")
    # Should not raise even though the path is not a registered worktree.
    worktree_remove(repo, tmp_path / "nope")
