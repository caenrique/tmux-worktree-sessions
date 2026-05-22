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

from tmux_sessions.git import branch_to_dir, default_branch, resolve_remote


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
