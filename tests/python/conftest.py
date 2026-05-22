"""Shared pytest fixtures for the tmux_sessions Python tests.

``make_repo`` mirrors the bats ``mkrepo`` helper in
``tests/helpers/git_fixtures.bash``: it spins up a real git repo (with
optional sibling bare ``origin``) under a tmpdir so subprocess-based
helpers in :mod:`tmux_sessions.git` can be exercised end-to-end.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[..., Path]:
    """Return a factory that creates a real git repo under ``tmp_path``.

    Defaults match ``mkrepo`` in ``tests/helpers/git_fixtures.bash``: a
    ``main`` branch with one initial commit. Pass ``with_remote=True``
    to also create a sibling bare ``origin`` and run
    ``git remote set-head origin main``.
    """

    def _factory(
        name: str = "r",
        *,
        branches: Iterable[str] = ("main",),
        with_remote: bool = False,
        with_initial_commit: bool = True,
    ) -> Path:
        repo = tmp_path / name
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test")
        _git(repo, "config", "commit.gpgsign", "false")

        if with_initial_commit:
            (repo / "README").write_text("")
            _git(repo, "add", "README")
            _git(repo, "commit", "-q", "-m", "init")

        for b in branches:
            if b == "main":
                continue
            _git(repo, "branch", b)

        if with_remote and with_initial_commit:
            origin = tmp_path / f"{name}.git"
            subprocess.run(
                ["git", "init", "-q", "--bare", "-b", "main", str(origin)],
                check=True,
                capture_output=True,
                text=True,
            )
            _git(repo, "remote", "add", "origin", str(origin))
            _git(repo, "push", "-q", "--all", "origin")
            _git(repo, "remote", "set-head", "origin", "main")

        return repo

    return _factory
