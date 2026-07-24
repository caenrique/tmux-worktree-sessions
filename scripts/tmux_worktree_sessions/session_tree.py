"""Lazy session/window/pane tree projection for the fzf picker.

The top-level picker rows remain the existing four-column protocol.  This
module projects those rows into an eight-column fzf view and persists only
the stable IDs of expanded sessions and windows.  Topology is queried lazily:
collapsed startup performs no ``list-panes`` calls.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from . import tmux

TopologyLoader = Callable[[str], list[tmux.Window]]
AgentLoader = Callable[[], list[tmux.Agent]]

_RESET = "\033[0m"
WORKING_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_STATUS_STYLE = {
    "working": ("\033[32m", WORKING_SPINNER_FRAMES[0]),
    "response": ("\033[33m", "◐"),
    "idle": ("\033[36m", "○"),
    "waiting": ("\033[34m", "◌"),
}


@dataclass
class TreeState:
    expanded_sessions: set[str] = field(default_factory=set)
    expanded_windows: set[str] = field(default_factory=set)


def _agents_path(statefile: Path) -> Path:
    return statefile.with_name(f"{statefile.name}.agents")


def load_agents(statefile: Path) -> list[tmux.Agent]:
    try:
        payload = json.loads(_agents_path(statefile).read_text())
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return []
    if not isinstance(payload, list):
        return []
    agents: list[tmux.Agent] = []
    for value in payload:
        if not isinstance(value, dict):
            continue
        try:
            agents.append(
                tmux.Agent(
                    name=str(value["name"]),
                    session_id=str(value["session_id"]),
                    window_id=str(value["window_id"]),
                    window_index=int(value["window_index"]),
                    pane_id=str(value["pane_id"]),
                    pane_index=int(value["pane_index"]),
                    path=Path(str(value["path"])),
                    status=str(value["status"]),
                    detail=str(value["detail"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return agents


def save_agents(statefile: Path, agents: list[tmux.Agent]) -> None:
    payload = [
        {
            "name": agent.name,
            "session_id": agent.session_id,
            "window_id": agent.window_id,
            "window_index": agent.window_index,
            "pane_id": agent.pane_id,
            "pane_index": agent.pane_index,
            "path": str(agent.path),
            "status": agent.status,
            "detail": agent.detail,
        }
        for agent in agents
    ]
    _atomic_write(_agents_path(statefile), json.dumps(payload, separators=(",", ":")) + "\n")


def load_state(path: Path) -> TreeState:
    try:
        payload = json.loads(path.read_text())
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return TreeState()
    sessions = payload.get("expanded_sessions", [])
    windows = payload.get("expanded_windows", [])
    if not isinstance(sessions, list) or not isinstance(windows, list):
        return TreeState()
    return TreeState(
        expanded_sessions={str(value) for value in sessions},
        expanded_windows={str(value) for value in windows},
    )


def save_state(path: Path, state: TreeState) -> None:
    payload = {
        "expanded_sessions": sorted(state.expanded_sessions),
        "expanded_windows": sorted(state.expanded_windows),
    }
    _atomic_write(path, json.dumps(payload, separators=(",", ":")) + "\n")


def render_tree_lines(
    root_lines: Iterable[str],
    state: TreeState,
    *,
    topology_loader: TopologyLoader = tmux.list_session_windows,
    agent_loader: AgentLoader = tmux.list_agents,
) -> list[str]:
    """Return the fzf view for top-level rows and the requested subtrees."""
    rendered: list[str] = []
    agents_by_session: dict[str, list[tmux.Agent]] = {}
    for agent in agent_loader():
        agents_by_session.setdefault(agent.session_id, []).append(agent)
    for line in root_lines:
        fields = line.split("\t")
        if len(fields) < 4:
            continue
        kind, row_id, search, display = fields[:4]
        if kind != "s":
            preview_target = row_id if kind == "p" else ""
            rendered.append(_row(kind, row_id, search, display, preview_target=preview_target))
            continue

        sid = row_id
        agents = agents_by_session.get(sid, [])
        badge = _agent_badge(agents)
        if sid not in state.expanded_sessions:
            rendered.append(
                _row(
                    "s",
                    sid,
                    search,
                    f"▸ {display}{badge}",
                    session_id=sid,
                    preview_target=f"${sid}",
                )
            )
            continue

        windows = topology_loader(f"${sid}")
        pane_count = sum(len(window.panes) for window in windows)
        rendered.append(
            _row(
                "s",
                sid,
                search,
                f"▾ {display}  · {_count(len(windows), 'window')} · {_count(pane_count, 'pane')}{badge}",
                session_id=sid,
                preview_target=f"${sid}",
            )
        )
        for agent in agents:
            agent_search = _clean(
                f"{search} {agent.name} agent window {agent.window_index} pane {agent.pane_index} {agent.path}"
            )
            rendered.append(
                _row(
                    "a",
                    agent.pane_id,
                    agent_search,
                    (
                        f"    {_status_label(agent.status)} {agent.name}"
                        f"  {agent.status} · {agent.detail} · %{agent.pane_id.lstrip('%')}"
                    ),
                    session_id=sid,
                    window_id=agent.window_id,
                    preview_target=agent.pane_id,
                )
            )
        for window in windows:
            expanded = window.window_id in state.expanded_windows
            fold = "▾" if expanded else "▸"
            active = " ●" if window.active else ""
            window_search = _clean(f"{search} {window.name} window {window.index}")
            rendered.append(
                _row(
                    "w",
                    window.window_id,
                    window_search,
                    f"    {fold} window {window.index}: {window.name}{active}  · {_count(len(window.panes), 'pane')}",
                    session_id=sid,
                    window_id=window.window_id,
                    preview_target=window.window_id,
                )
            )
            if not expanded:
                continue
            for pane in window.panes:
                marker = "●" if pane.active else " "
                pane_search = _clean(f"{search} {window.name} {pane.command} {pane.title} {pane.path}")
                rendered.append(
                    _row(
                        "t",
                        pane.pane_id,
                        pane_search,
                        f"        {marker} pane {pane.index}: {pane.command}  {pane.path}",
                        session_id=sid,
                        window_id=window.window_id,
                        preview_target=pane.pane_id,
                    )
                )
    return rendered


def refresh_view(
    rootfile: Path,
    viewfile: Path,
    statefile: Path,
    *,
    topology_loader: TopologyLoader = tmux.list_session_windows,
    agent_loader: AgentLoader | None = None,
) -> None:
    root_lines = rootfile.read_text().splitlines() if rootfile.exists() else []
    agents = load_agents(statefile) if agent_loader is None else agent_loader()
    lines = render_tree_lines(
        root_lines,
        load_state(statefile),
        topology_loader=topology_loader,
        agent_loader=lambda: agents,
    )
    _atomic_write(viewfile, "\n".join(lines) + ("\n" if lines else ""))


def set_expanded(
    *,
    action: str,
    row_type: str,
    row_id: str,
    session_id: str,
    rootfile: Path,
    viewfile: Path,
    statefile: Path,
) -> None:
    state = load_state(statefile)
    if row_type == "s":
        _set_membership(state.expanded_sessions, row_id, expanded=action == "expand")
    elif row_type == "w" and session_id in state.expanded_sessions:
        _set_membership(state.expanded_windows, row_id, expanded=action == "expand")
    else:
        return
    save_state(statefile, state)
    refresh_view(rootfile, viewfile, statefile)


def forget_session(statefile: Path, sid: str) -> None:
    state = load_state(statefile)
    state.expanded_sessions.discard(sid)
    save_state(statefile, state)


def _row(
    kind: str,
    row_id: str,
    search: str,
    display: str,
    *,
    session_id: str = "",
    window_id: str = "",
    preview_target: str = "",
) -> str:
    return "\t".join(
        (
            _clean(kind),
            _clean(row_id),
            _clean(search),
            _clean(display),
            _clean(session_id),
            _clean(window_id),
            _clean(preview_target),
            "",
        )
    )


def _clean(value: object) -> str:
    return str(value).replace("\t", " ").replace("\n", " ")


def _count(value: int, unit: str) -> str:
    return f"{value} {unit if value == 1 else f'{unit}s'}"


def _set_membership(values: set[str], value: str, *, expanded: bool) -> None:
    if expanded:
        values.add(value)
    else:
        values.discard(value)


def _agent_badge(agents: list[tmux.Agent]) -> str:
    if not agents:
        return ""
    badges = [f"[{_status_label(agent.status)} {agent.name} {agent.status}]" for agent in agents]
    return f"  {' '.join(badges)}"


def _status_label(status: str) -> str:
    color, glyph = _STATUS_STYLE.get(status, ("", "○"))
    return f"{color}{glyph}{_RESET}"


def set_working_spinner_frame(viewfile: Path, frame: str) -> None:
    """Replace every rendered working-agent spinner with ``frame`` atomically."""
    value = viewfile.read_text()
    translation = str.maketrans({spinner: frame for spinner in WORKING_SPINNER_FRAMES})
    _atomic_write(viewfile, value.translate(translation))


def _atomic_write(path: Path, value: str) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value)
    temporary.replace(path)
