from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from tmux_worktree_sessions import session_tree, tmux
from tmux_worktree_sessions.__main__ import main

from .conftest import TmuxStub


def _topology(_target: str) -> list[tmux.Window]:
    return [
        tmux.Window(
            "@1",
            1,
            "editor",
            True,
            (
                tmux.Pane("%1", 1, "nvim", Path("/repo"), True, "code"),
                tmux.Pane("%2", 2, "fish", Path("/repo"), False, "tests"),
            ),
        ),
        tmux.Window(
            "@2",
            2,
            "server",
            False,
            (tmux.Pane("%3", 1, "cargo", Path("/repo"), True, "server"),),
        ),
    ]


def test_collapsed_tree_does_not_load_topology() -> None:
    calls: list[str] = []

    lines = session_tree.render_tree_lines(
        ["s\t3\trepo\t* repo", "p\t/other\tother\t. other"],
        session_tree.TreeState(),
        topology_loader=lambda target: calls.append(target) or [],
        agent_loader=lambda: [],
    )

    assert calls == []
    assert lines[0].split("\t")[3] == "▸ * repo"
    assert lines[0].split("\t")[6] == "$3"
    assert lines[1].split("\t")[3] == ". other"


def test_expanded_session_lists_windows_but_not_panes() -> None:
    state = session_tree.TreeState(expanded_sessions={"3"})

    lines = session_tree.render_tree_lines(
        ["s\t3\trepo\t* repo"],
        state,
        topology_loader=_topology,
        agent_loader=lambda: [],
    )

    fields = [line.split("\t") for line in lines]
    assert [row[0] for row in fields] == ["s", "w", "w"]
    assert "2 windows" in fields[0][3]
    assert "3 panes" in fields[0][3]
    assert fields[1][1] == "@1"
    assert fields[1][4:7] == ["3", "@1", "@1"]


def test_expanded_window_lists_exact_pane_targets() -> None:
    state = session_tree.TreeState(
        expanded_sessions={"3"},
        expanded_windows={"@1"},
    )

    lines = session_tree.render_tree_lines(
        ["s\t3\trepo\t* repo"],
        state,
        topology_loader=_topology,
        agent_loader=lambda: [],
    )

    fields = [line.split("\t") for line in lines]
    assert [row[0] for row in fields] == ["s", "w", "t", "t", "w"]
    assert fields[2][1] == "%1"
    assert fields[2][4:7] == ["3", "@1", "%1"]
    assert "nvim" in fields[2][3]


def test_toggle_persists_stable_ids_and_rewrites_view(tmp_path: Path) -> None:
    rootfile = tmp_path / "roots"
    viewfile = tmp_path / "view"
    statefile = tmp_path / "state"
    rootfile.write_text("s\t3\trepo\t* repo\n")
    session_tree.save_state(statefile, session_tree.TreeState())

    session_tree.set_expanded(
        action="expand",
        row_type="s",
        row_id="3",
        session_id="3",
        rootfile=rootfile,
        viewfile=viewfile,
        statefile=statefile,
    )

    state = session_tree.load_state(statefile)
    assert state.expanded_sessions == {"3"}
    assert viewfile.read_text().startswith("s\t3\trepo\t▾ ")


def test_internal_expand_loads_topology_and_expands_window(
    cli_env: Path,
    tmp_path: Path,
    tmux_stub: Callable[..., TmuxStub],
) -> None:
    rootfile = tmp_path / "roots"
    viewfile = tmp_path / "view"
    statefile = tmp_path / "state"
    rootfile.write_text("s\t3\trepo\t* repo\n")
    session_tree.save_state(statefile, session_tree.TreeState())
    tmux_stub(panes=("@4\t1\teditor\t1\t%8\t1\tnvim\t/repo\t1\tcode\n@4\t1\teditor\t1\t%9\t2\tfish\t/repo\t0\ttests"))

    assert (
        main(
            [
                "_internal",
                "tree-expand",
                "expand",
                "s",
                "3",
                "3",
                str(rootfile),
                str(viewfile),
                str(statefile),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "_internal",
                "tree-expand",
                "expand",
                "w",
                "@4",
                "3",
                str(rootfile),
                str(viewfile),
                str(statefile),
            ]
        )
        == 0
    )

    fields = [line.split("\t") for line in viewfile.read_text().splitlines()]
    assert [row[0] for row in fields] == ["s", "w", "t", "t"]
    assert fields[2][1] == "%8"


def test_agent_badge_and_rows_are_rendered_for_expanded_session() -> None:
    agents = [
        tmux.Agent("Codex", "3", "@1", 1, "%2", 2, Path("/repo"), "working", "editing"),
        tmux.Agent("Claude", "3", "@2", 2, "%3", 1, Path("/repo"), "response", "approval"),
    ]

    collapsed = session_tree.render_tree_lines(
        ["s\t3\trepo\t* repo"],
        session_tree.TreeState(),
        topology_loader=_topology,
        agent_loader=lambda: agents,
    )
    display = collapsed[0].split("\t")[3]
    assert "[\x1b[32m⠋\x1b[0m Codex working]" in display
    assert "[\x1b[33m◐\x1b[0m Claude response]" in display

    expanded = session_tree.render_tree_lines(
        ["s\t3\trepo\t* repo"],
        session_tree.TreeState(expanded_sessions={"3"}),
        topology_loader=_topology,
        agent_loader=lambda: agents,
    )
    fields = [line.split("\t") for line in expanded]
    assert [row[0] for row in fields[:3]] == ["s", "a", "a"]
    assert fields[1][1] == "%2"
    assert fields[1][4:7] == ["3", "@1", "%2"]
    assert "\x1b[32m⠋\x1b[0m Codex  working · editing · %2" in fields[1][3]


def test_agent_snapshot_round_trips_separately_from_expansion_state(tmp_path: Path) -> None:
    statefile = tmp_path / "state"
    agent = tmux.Agent(
        "Codex",
        "3",
        "@1",
        1,
        "%2",
        2,
        Path("/repo"),
        "working",
        "editing",
    )

    session_tree.save_state(statefile, session_tree.TreeState(expanded_sessions={"3"}))
    session_tree.save_agents(statefile, [agent])

    assert session_tree.load_agents(statefile) == [agent]
    assert session_tree.load_state(statefile).expanded_sessions == {"3"}


def test_refresh_view_uses_cached_agents_without_process_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rootfile = tmp_path / "roots"
    viewfile = tmp_path / "view"
    statefile = tmp_path / "state"
    rootfile.write_text("s\t3\trepo\t* repo\n")
    session_tree.save_state(statefile, session_tree.TreeState())
    agent = tmux.Agent(
        "Codex",
        "3",
        "@1",
        1,
        "%2",
        2,
        Path("/repo"),
        "working",
        "editing",
    )
    session_tree.save_agents(statefile, [agent])
    monkeypatch.setattr(
        tmux,
        "list_agents",
        lambda: (_ for _ in ()).throw(AssertionError("synchronous agent scan")),
    )

    session_tree.refresh_view(rootfile, viewfile, statefile)

    assert "Codex working" in viewfile.read_text()


def test_working_spinner_frame_updates_badge_and_agent_row(tmp_path: Path) -> None:
    viewfile = tmp_path / "view"
    viewfile.write_text("[\x1b[32m⠋\x1b[0m Codex working]\n    \x1b[32m⠋\x1b[0m Codex\n")

    session_tree.set_working_spinner_frame(viewfile, "⠙")

    rendered = viewfile.read_text()
    assert rendered.count("⠙") == 2
    assert "⠋" not in rendered
