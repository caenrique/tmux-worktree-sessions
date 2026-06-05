"""Tests for :mod:`tmux_worktree_sessions.tmux`.

Covers ``session_id`` and ``switch_or_create``. The tmux stub at
``tests/python/_stubs/tmux`` is loaded via the ``tmux_stub`` fixture.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tmux_worktree_sessions.tmux import session_id, switch_or_create

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
