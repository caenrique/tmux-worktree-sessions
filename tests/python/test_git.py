"""Pure-layer tests mirroring the bats `branch_to_dir` cases."""

from __future__ import annotations

from tmux_sessions.git import branch_to_dir


def test_branch_to_dir_replaces_slashes_with_dashes() -> None:
    assert branch_to_dir("feature/login") == "feature-login"


def test_branch_to_dir_replaces_spaces_with_dashes() -> None:
    assert branch_to_dir("with spaces") == "with-spaces"
