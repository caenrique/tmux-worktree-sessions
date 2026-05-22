"""tmux subprocess wrappers for tmux-sessions.

Functions in this module shell out to a real ``tmux`` process and take
all inputs as explicit parameters. Per the migration plan, subprocess
calls are external state queries and live in the pure layer; the CLI
layer in :mod:`tmux_sessions.__main__` is a one-line passthrough that
only resolves env-driven defaults.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def session_id(name: str) -> str | None:
    """Return the tmux session id (``$N``) for an exactly-named session.

    tmux silently replaces ``.`` with ``_`` when storing session names,
    so the lookup applies the same substitution before comparing. Uses
    ``tmux ls`` with explicit format strings instead of ``tmux -t`` so
    a ``/`` in a session name is never misread as the ``session:window``
    separator. Returns ``None`` when no session matches or tmux is not
    running.
    """
    normalized = name.replace(".", "_")
    result = subprocess.run(
        ["tmux", "ls", "-F", "#{session_name}\t#{session_id}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if "\t" not in line:
            continue
        stored_name, sid = line.split("\t", 1)
        if stored_name == normalized:
            return sid
    return None


def switch_or_create(session_path: Path, name: str) -> None:
    """Switch the current client to ``name`` or create the session first.

    Targeting always uses the session id printed by ``new-session -P``
    rather than the name, so a slash inside the name cannot be misread
    as ``session:window``. Raises ``CalledProcessError`` if tmux fails;
    the caller decides how to surface that.
    """
    sid = session_id(name)
    if sid is None:
        created = subprocess.run(
            [
                "tmux",
                "new-session",
                "-c",
                str(session_path),
                "-s",
                name,
                "-d",
                "-P",
                "-F",
                "#{session_id}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        sid = created.stdout.strip()
    subprocess.run(["tmux", "switch-client", "-t", sid], check=True)
