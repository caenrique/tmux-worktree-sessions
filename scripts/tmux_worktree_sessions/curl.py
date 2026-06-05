"""curl subprocess wrappers for tmux-worktree-sessions.

Mirrors :mod:`tmux_worktree_sessions.git` / :mod:`tmux_worktree_sessions.tmux`:
the only place in the codebase that should spawn a ``curl`` process.

Why curl, not :mod:`urllib.request`: ``curl`` is already a documented
runtime dependency of the plugin and the test stub captures every POST
verbatim, so the wire output is exercised end-to-end without any
HTTP-level mocking.
"""

from __future__ import annotations

import subprocess


def post(port: int, body: str, *, max_time: float, host: str = "localhost") -> None:
    """POST ``body`` to ``host:port``; errors are silent.

    Used by the branch picker's spinner thread and final reload to talk
    to fzf's ``--listen`` HTTP endpoint. Failures are intentionally
    swallowed — a missed spinner frame or a torn-down listener never
    propagates back to the caller.
    """
    subprocess.run(
        [
            "curl",
            "-s",
            "--max-time",
            str(max_time),
            "-XPOST",
            f"{host}:{port}",
            "-d",
            body,
        ],
        check=False,
        capture_output=True,
    )
