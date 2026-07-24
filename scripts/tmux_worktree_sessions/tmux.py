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


@dataclass(frozen=True)
class Pane:
    pane_id: str
    index: int
    command: str
    path: Path
    active: bool
    title: str


@dataclass(frozen=True)
class Window:
    window_id: str
    index: int
    name: str
    active: bool
    panes: tuple[Pane, ...]


@dataclass(frozen=True)
class Agent:
    """One foreground AI-agent process discovered in a tmux pane."""

    name: str
    session_id: str
    window_id: str
    window_index: int
    pane_id: str
    pane_index: int
    path: Path
    status: str
    detail: str


_AGENT_NAMES = {
    "aider": "Aider",
    "amp": "Amp",
    "claude": "Claude",
    "claude-code": "Claude",
    "codex": "Codex",
    "copilot": "Copilot",
    "cursor-agent": "Cursor",
    "gemini": "Gemini",
    "gemini-cli": "Gemini",
    "goose": "Goose",
    "opencode": "OpenCode",
}


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


def session_name(target: str) -> str:
    """Return ``#{session_name}`` for one stable session target."""
    return _display_message("#{session_name}", target=target)


def current_session_id() -> str:
    """Return the bare session id for the current client, or empty string."""
    raw_id = _display_message("#{session_id}")
    return raw_id[1:] if raw_id.startswith("$") else raw_id


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


def list_session_windows(target: str) -> list[Window]:
    """Return windows and panes for one session, ordered by tmux index."""
    fmt = "\t".join(
        (
            "#{window_id}",
            "#{window_index}",
            "#{window_name}",
            "#{window_active}",
            "#{pane_id}",
            "#{pane_index}",
            "#{pane_current_command}",
            "#{pane_current_path}",
            "#{pane_active}",
            "#{pane_title}",
        )
    )
    result = subprocess.run(
        ["tmux", "list-panes", "-s", "-t", target, "-F", fmt],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    grouped: dict[str, tuple[int, str, bool, list[Pane]]] = {}
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) < 10:
            continue
        try:
            window_index = int(fields[1])
            pane_index = int(fields[5])
        except ValueError:
            continue
        pane = Pane(
            pane_id=fields[4],
            index=pane_index,
            command=fields[6],
            path=Path(fields[7]),
            active=fields[8] == "1",
            title=fields[9],
        )
        grouped.setdefault(
            fields[0],
            (window_index, fields[2], fields[3] == "1", []),
        )[3].append(pane)
    return [
        Window(
            window_id,
            index,
            name,
            active,
            tuple(sorted(panes, key=lambda pane: pane.index)),
        )
        for window_id, (index, name, active, panes) in sorted(grouped.items(), key=lambda item: item[1][0])
    ]


def agent_name(command: str) -> str | None:
    """Return the display name for a supported foreground agent command."""
    executable = Path(command).name.casefold()
    direct = _AGENT_NAMES.get(executable)
    if direct is not None:
        return direct
    for prefix in ("claude", "codex", "gemini", "opencode"):
        if executable.startswith(f"{prefix}-"):
            return _AGENT_NAMES[prefix]
    return None


def list_agents() -> list[Agent]:
    """Return AI agents detected from pane metadata and process descendants."""
    fmt = "\t".join(
        (
            "#{session_id}",
            "#{window_id}",
            "#{window_index}",
            "#{pane_id}",
            "#{pane_index}",
            "#{pane_current_command}",
            "#{pane_start_command}",
            "#{pane_title}",
            "#{pane_pid}",
            "#{pane_current_path}",
        )
    )
    try:
        result = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", fmt],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except subprocess.TimeoutExpired:
        return []
    if result.returncode != 0:
        return []
    rows = [line.split("\t") for line in result.stdout.splitlines()]
    pane_pids = {int(fields[8]) for fields in rows if len(fields) >= 10 and fields[8].isdigit()}
    process_commands = _process_commands(pane_pids)
    agents: list[Agent] = []
    for fields in rows:
        if len(fields) < 10:
            continue
        pane_pid = int(fields[8]) if fields[8].isdigit() else 0
        descendants = process_commands.get(pane_pid, "")
        haystack = f"{fields[5]} {fields[6]} {fields[7]} {descendants}".casefold()
        spinner = any(value in fields[7] for value in "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
        name = _agent_name_from_metadata(haystack, command=fields[5], spinner=spinner)
        if name is None:
            continue
        status = _agent_status(haystack, spinner=spinner)
        try:
            window_index = int(fields[2])
            pane_index = int(fields[4])
        except ValueError:
            continue
        raw_session_id = fields[0]
        agents.append(
            Agent(
                name=name,
                session_id=raw_session_id[1:] if raw_session_id.startswith("$") else raw_session_id,
                window_id=fields[1],
                window_index=window_index,
                pane_id=fields[3],
                pane_index=pane_index,
                path=Path(fields[9]),
                status=status,
                detail=fields[7] or fields[5],
            )
        )
    return sorted(agents, key=lambda agent: (agent.session_id, agent.window_index, agent.pane_index))


def _agent_name_from_metadata(haystack: str, *, command: str, spinner: bool) -> str | None:
    for needle, name in _AGENT_NAMES.items():
        if needle in haystack:
            return name
    if command.casefold() == "node" and spinner:
        return "Codex"
    return None


def _agent_status(haystack: str, *, spinner: bool) -> str:
    if any(token in haystack for token in ("action required", "approval", "permission")):
        return "response"
    if spinner or "working" in haystack:
        return "working"
    if "idle" in haystack or "ready" in haystack:
        return "idle"
    return "waiting"


def _process_commands(roots: set[int]) -> dict[int, str]:
    if not roots:
        return {}
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,command="],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except subprocess.TimeoutExpired:
        return {}
    if result.returncode != 0:
        return {}
    parents: dict[int, int] = {}
    commands: dict[int, str] = {}
    for line in result.stdout.splitlines():
        fields = line.strip().split(maxsplit=2)
        if len(fields) < 3:
            continue
        try:
            pid, parent = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        parents[pid] = parent
        commands[pid] = fields[2]
    grouped: dict[int, list[str]] = {root: [] for root in roots}
    for pid, command in commands.items():
        ancestor = pid
        visited: set[int] = set()
        while ancestor in parents and ancestor not in visited:
            visited.add(ancestor)
            ancestor = parents[ancestor]
            if ancestor in roots:
                grouped[ancestor].append(command)
                break
    return {root: " ".join(values) for root, values in grouped.items()}


def capture_pane(target: str) -> bytes:
    """Capture the exact pane resolved by ``target``.

    Resolving ``#{pane_id}`` first prevents a window/session target from
    drifting to the picker's active pane between fzf refreshes.
    """
    pane_id = _display_message("#{pane_id}", target=target)
    if not pane_id:
        return b""
    result = subprocess.run(
        ["tmux", "capture-pane", "-e", "-p", "-t", pane_id],
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else b""


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


def kill_window(target: str) -> None:
    subprocess.run(["tmux", "kill-window", "-t", target], capture_output=True)


def kill_pane(target: str) -> None:
    subprocess.run(["tmux", "kill-pane", "-t", target], capture_output=True)


def rename_session(target: str, new_name: str) -> None:
    """Rename ``target`` to ``new_name``; errors are swallowed."""
    subprocess.run(
        ["tmux", "rename-session", "-t", target, new_name],
        capture_output=True,
    )


def set_session_option(target: str, option: str, value: str) -> None:
    """Set a session-scoped tmux user option for ``target``."""
    subprocess.run(
        ["tmux", "set-option", "-q", "-t", target, option, value],
        capture_output=True,
    )


def refresh_status() -> None:
    """Request an immediate redraw of the current client's status line."""
    subprocess.run(["tmux", "refresh-client", "-S"], capture_output=True)


def switch_client(target: str) -> None:
    """Switch the current client to ``target``; errors are swallowed.

    Bare counterpart to :func:`switch_or_create` — used when the caller
    already has a tmux session id (with leading ``$``) and just wants to
    attach without conditional creation.
    """
    subprocess.run(["tmux", "switch-client", "-t", target], capture_output=True)


def previous_attached_session(
    sessions: list[Session],
    current_id: str,
) -> Session | None:
    """Return the most recently attached live session before ``current_id``.

    Unlike ``switch-client -l``, this derives the target from the live
    sessions' ``session_last_attached`` timestamps. If tmux's remembered
    last session was deleted, the next-most-recent live session remains
    selectable.
    """
    normalized_current = current_id[1:] if current_id.startswith("$") else current_id
    if not normalized_current:
        return None
    candidates = [session for session in sessions if session.sid != normalized_current]
    return max(candidates, key=lambda session: session.last_attached, default=None)


def switch_to_previous_attached_session() -> bool:
    """Switch to the most recently attached other live session.

    Returns ``False`` without asking tmux to switch when there is no current
    session or no other live session, avoiding tmux's noisy
    ``no last session`` error.
    """
    target = previous_attached_session(list_sessions(), current_session_id())
    if target is None:
        return False
    switch_client(f"${target.sid}")
    return True


def select_window(target: str) -> None:
    subprocess.run(["tmux", "select-window", "-t", target], capture_output=True)


def select_pane(target: str) -> None:
    subprocess.run(["tmux", "select-pane", "-t", target], capture_output=True)


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
