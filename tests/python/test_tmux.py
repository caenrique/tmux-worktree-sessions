"""Tests for :mod:`tmux_worktree_sessions.tmux`.

Covers ``session_id``, ``switch_or_create``, and the thin API helpers
(``session_path``, ``kill_session``, ``rename_session``, ``switch_client``,
``flash_message``). The tmux stub at ``tests/python/_stubs/tmux`` is
loaded via the ``tmux_stub`` fixture.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tmux_worktree_sessions.tmux import (
    Session,
    agent_name,
    capture_pane,
    flash_message,
    kill_session,
    list_agents,
    list_session_windows,
    previous_attached_session,
    refresh_status,
    rename_session,
    select_pane,
    select_window,
    session_id,
    session_path,
    set_session_option,
    switch_client,
    switch_or_create,
    switch_to_previous_attached_session,
)

from .conftest import TmuxStub


def test_session_id_returns_matching_id(tmux_stub: Callable[..., TmuxStub]) -> None:
    tmux_stub(sessions="alpha\t$1\t/tmp/alpha\nbeta\t$2\t/tmp/beta")
    assert session_id("beta") == "$2"


def test_session_id_returns_none_when_no_match(tmux_stub: Callable[..., TmuxStub]) -> None:
    tmux_stub(sessions="alpha\t$1\t/tmp/alpha")
    assert session_id("ghost") is None


def test_session_id_treats_dot_as_underscore(tmux_stub: Callable[..., TmuxStub]) -> None:
    tmux_stub(sessions="foo_bar\t$7\t/tmp/foo")
    assert session_id("foo.bar") == "$7"


def test_switch_or_create_uses_existing_session_id(
    tmux_stub: Callable[..., TmuxStub],
) -> None:
    stub = tmux_stub(sessions="alpha\t$5\t/tmp/alpha")
    switch_or_create(Path("/tmp/alpha"), "alpha")
    invocations = stub.invocations()
    assert ["tmux", "switch-client", "-t", "$5"] in invocations
    assert not any(call[1:2] == ["new-session"] for call in invocations)


def test_switch_or_create_creates_new_session_when_unknown(
    tmux_stub: Callable[..., TmuxStub],
) -> None:
    stub = tmux_stub(sessions="", new_id="$42")
    switch_or_create(Path("/tmp/fresh"), "fresh")
    invocations = stub.invocations()
    assert any(call[1:6] == ["new-session", "-c", "/tmp/fresh", "-s", "fresh"] for call in invocations)
    assert ["tmux", "switch-client", "-t", "$42"] in invocations


def test_session_path_returns_session_dir(tmux_stub: Callable[..., TmuxStub]) -> None:
    tmux_stub(sessions="alpha\t$3\t/tmp/alpha")
    assert session_path("$3") == "/tmp/alpha"


def test_session_path_unknown_target_returns_empty(tmux_stub: Callable[..., TmuxStub]) -> None:
    tmux_stub(sessions="")
    assert session_path("$99") == ""


def test_kill_session_invokes_tmux(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    kill_session("$5")
    assert ["tmux", "kill-session", "-t", "$5"] in stub.invocations()


def test_rename_session_invokes_tmux(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    rename_session("$5", "fresh")
    assert ["tmux", "rename-session", "-t", "$5", "fresh"] in stub.invocations()


def test_set_session_option_targets_one_session(
    tmux_stub: Callable[..., TmuxStub],
) -> None:
    stub = tmux_stub()
    set_session_option("$5", "@tws-session-name", "github.com/project")
    assert [
        "tmux",
        "set-option",
        "-q",
        "-t",
        "$5",
        "@tws-session-name",
        "github.com/project",
    ] in stub.invocations()


def test_refresh_status_requests_immediate_status_redraw(
    tmux_stub: Callable[..., TmuxStub],
) -> None:
    stub = tmux_stub()
    refresh_status()
    assert ["tmux", "refresh-client", "-S"] in stub.invocations()


def test_switch_client_invokes_tmux(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    switch_client("$7")
    assert ["tmux", "switch-client", "-t", "$7"] in stub.invocations()


def test_previous_attached_session_skips_deleted_last_session() -> None:
    sessions = [
        Session("1", "a", Path("/a"), 100),
        Session("3", "c", Path("/c"), 300),
    ]

    target = previous_attached_session(sessions, "$3")

    assert target is not None
    assert target.name == "a"


def test_switch_to_previous_attached_session_uses_live_attach_order(
    tmux_stub: Callable[..., TmuxStub],
) -> None:
    stub = tmux_stub(
        sessions="a\t$1\t/a\t100\nc\t$3\t/c\t300",
        current_id="$3",
    )

    assert switch_to_previous_attached_session()
    assert ["tmux", "switch-client", "-t", "$1"] in stub.invocations()


def test_switch_to_previous_attached_session_is_quiet_when_no_other_session(
    tmux_stub: Callable[..., TmuxStub],
) -> None:
    stub = tmux_stub(sessions="a\t$1\t/a\t100", current_id="$1")

    assert not switch_to_previous_attached_session()
    assert not any(call[1:2] == ["switch-client"] for call in stub.invocations())


def test_flash_message_uses_default_duration(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    flash_message("hello")
    assert ["tmux", "display-message", "-d", "2000", "hello"] in stub.invocations()


def test_flash_message_honours_custom_duration(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    flash_message("hello", duration_ms=500)
    assert ["tmux", "display-message", "-d", "500", "hello"] in stub.invocations()


def test_list_session_windows_parses_stable_window_and_pane_ids(
    tmux_stub: Callable[..., TmuxStub],
) -> None:
    tmux_stub(
        panes=(
            "@2\t2\tserver\t0\t%3\t1\tcargo\t/repo\t1\tserver\n"
            "@1\t1\teditor\t1\t%2\t2\tfish\t/repo\t0\ttests\n"
            "@1\t1\teditor\t1\t%1\t1\tnvim\t/repo\t1\tcode"
        )
    )

    windows = list_session_windows("$3")

    assert [window.window_id for window in windows] == ["@1", "@2"]
    assert [pane.pane_id for pane in windows[0].panes] == ["%1", "%2"]
    assert windows[0].active


def test_select_window_and_pane_use_stable_targets(
    tmux_stub: Callable[..., TmuxStub],
) -> None:
    stub = tmux_stub()

    select_window("@4")
    select_pane("%9")

    assert ["tmux", "select-window", "-t", "@4"] in stub.invocations()
    assert ["tmux", "select-pane", "-t", "%9"] in stub.invocations()


def test_agent_name_recognizes_supported_agent_commands() -> None:
    assert agent_name("codex") == "Codex"
    assert agent_name("/opt/bin/claude-code") == "Claude"
    assert agent_name("gemini-cli-v2") == "Gemini"
    assert agent_name("nvim") is None


def test_list_agents_returns_foreground_agents_grouped_by_session(
    tmux_stub: Callable[..., TmuxStub],
) -> None:
    tmux_stub(
        agents=(
            "$3\t@2\t2\t%5\t1\tnode\t\tWaiting for permission\t501\t/repo\n"
            "$3\t@1\t1\t%2\t2\tfish\t\tready\t500\t/repo\n"
            "$4\t@3\t1\t%8\t1\tnvim\t\tcode\t600\t/other"
        ),
        processes="700 500 /usr/local/bin/codex\n701 501 /usr/local/bin/claude",
    )

    agents = list_agents()

    assert [(agent.name, agent.session_id, agent.pane_id) for agent in agents] == [
        ("Codex", "3", "%2"),
        ("Claude", "3", "%5"),
    ]
    assert [agent.status for agent in agents] == ["idle", "response"]


def test_capture_pane_resolves_and_captures_exact_pane(
    monkeypatch: object,
) -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout: str | bytes

        def __init__(self, stdout: str | bytes) -> None:
            self.stdout = stdout

    def fake_run(args: list[str], **_kwargs: object) -> Result:
        calls.append(args)
        if args[1] == "display-message":
            return Result("%9\n")
        return Result(b"pane nine")

    monkeypatch.setattr("tmux_worktree_sessions.tmux.subprocess.run", fake_run)  # type: ignore[attr-defined]

    assert capture_pane("@4") == b"pane nine"
    assert calls[-1] == ["tmux", "capture-pane", "-e", "-p", "-t", "%9"]
