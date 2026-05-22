"""Pure git helpers for tmux-sessions.

Functions in this module take all inputs as explicit parameters; the
CLI layer in ``tmux_sessions.__main__`` resolves env/args and writes
the result.
"""

from __future__ import annotations


def branch_to_dir(name: str) -> str:
    """Convert a branch name to a safe directory name.

    Both ``/`` and space become ``-`` so a branch like ``feature/login``
    can be the basename of a worktree directory.
    """
    return name.replace("/", "-").replace(" ", "-")
