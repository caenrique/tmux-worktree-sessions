"""tmux subprocess wrappers for tmux-worktree-sessions.

Functions in this module shell out to a real ``tmux`` process and take
all inputs as explicit parameters. Per the migration plan, subprocess
calls are external state queries and live in the pure layer; the CLI
layer in :mod:`tmux_worktree_sessions.__main__` is a one-line passthrough that
only resolves env-driven defaults.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Session:
    """One row from ``tmux ls``: id, name, working dir, last-attached ts.

    ``sid`` is the bare session id with the leading ``$`` stripped so
    callers can treat it as a TSV column without re-escaping. ``last_attached``
    is 0 for sessions that have never been attached, matching how tmux
    reports them via ``#{session_last_attached}``.
    """

    sid: str
    name: str
    path: Path
    last_attached: int


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


def list_sessions() -> list[Session]:
    """Return every running tmux session as a :class:`Session` row.

    The ``$`` prefix on ``session_id`` is stripped so callers can use the
    bare id as a TSV column. Order matches tmux's output (insertion
    order); callers that need recency sorting do so themselves.
    """
    result = subprocess.run(
        [
            "tmux",
            "ls",
            "-F",
            "#{session_last_attached}\t#{session_id}\t#{session_name}\t#{session_path}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    out: list[Session] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        last_attached_raw, raw_id, name, sess_path = parts[0], parts[1], parts[2], parts[3]
        if not raw_id or not name:
            continue
        try:
            last_attached = int(last_attached_raw or "0")
        except ValueError:
            last_attached = 0
        sid = raw_id[1:] if raw_id.startswith("$") else raw_id
        out.append(Session(sid=sid, name=name, path=Path(sess_path), last_attached=last_attached))
    return out


def current_session_name() -> str:
    """Return ``#{session_name}`` for the current client, or empty string."""
    return _display_message("#{session_name}")


def previous_session_name() -> str:
    """Return ``#{client_last_session}`` for the current client, or empty string."""
    return _display_message("#{client_last_session}")


def pane_current_path() -> str:
    """Return ``#{pane_current_path}`` for the current client, or empty string."""
    return _display_message("#{pane_current_path}")


def session_path(target: str) -> str:
    """Return ``#{session_path}`` for ``target`` (e.g. ``"$3"``).

    Returns the empty string when the lookup fails — typically because
    the session id is unknown or tmux is not running.
    """
    return _display_message("#{session_path}", target=target)


def _display_message(fmt: str, *, target: str | None = None) -> str:
    cmd = ["tmux", "display-message", "-p"]
    if target is not None:
        cmd.extend(["-t", target])
    cmd.append(fmt)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    return result.stdout.rstrip("\n")


def kill_session(target: str) -> None:
    """Kill the session ``target`` (id like ``"$3"``); errors are swallowed."""
    subprocess.run(["tmux", "kill-session", "-t", target], capture_output=True)


def rename_session(target: str, new_name: str) -> None:
    """Rename ``target`` to ``new_name``; errors are swallowed."""
    subprocess.run(
        ["tmux", "rename-session", "-t", target, new_name],
        capture_output=True,
    )


def switch_client(target: str) -> None:
    """Switch the current client to ``target``; errors are swallowed.

    Bare counterpart to :func:`switch_or_create` — used when the caller
    already has a tmux session id (with leading ``$``) and just wants to
    attach without conditional creation.
    """
    subprocess.run(["tmux", "switch-client", "-t", target], capture_output=True)


def flash_message(message: str, *, duration_ms: int = 2000) -> None:
    """Show a transient ``display-message`` banner; errors are swallowed."""
    subprocess.run(
        ["tmux", "display-message", "-d", str(duration_ms), message],
        capture_output=True,
    )


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
