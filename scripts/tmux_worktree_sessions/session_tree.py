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


@dataclass
class TreeState:
    expanded_sessions: set[str] = field(default_factory=set)
    expanded_windows: set[str] = field(default_factory=set)


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
) -> list[str]:
    """Return the fzf view for top-level rows and the requested subtrees."""
    rendered: list[str] = []
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
        if sid not in state.expanded_sessions:
            rendered.append(
                _row(
                    "s",
                    sid,
                    search,
                    f"▸ {display}",
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
                f"▾ {display}  · {_count(len(windows), 'window')} · {_count(pane_count, 'pane')}",
                session_id=sid,
                preview_target=f"${sid}",
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
) -> None:
    root_lines = rootfile.read_text().splitlines() if rootfile.exists() else []
    lines = render_tree_lines(root_lines, load_state(statefile), topology_loader=topology_loader)
    _atomic_write(viewfile, "\n".join(lines) + ("\n" if lines else ""))


def toggle(
    *,
    row_type: str,
    row_id: str,
    session_id: str,
    rootfile: Path,
    viewfile: Path,
    statefile: Path,
) -> None:
    state = load_state(statefile)
    if row_type == "s":
        _toggle(state.expanded_sessions, row_id)
    elif row_type == "w" and session_id in state.expanded_sessions:
        _toggle(state.expanded_windows, row_id)
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


def _toggle(values: set[str], value: str) -> None:
    if value in values:
        values.remove(value)
    else:
        values.add(value)


def _atomic_write(path: Path, value: str) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value)
    temporary.replace(path)
