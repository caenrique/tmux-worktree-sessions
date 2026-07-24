"""Tests for optional pull-request discovery through ``gh``."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pytest
from tmux_worktree_sessions.pull_requests import is_available, list_open

from .conftest import GhStub


def test_is_available_with_gh_on_path(gh_stub: GhStub) -> None:
    assert is_available() is True


def test_list_open_parses_metadata(
    make_repo: Callable[..., Path],
    gh_stub: GhStub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = make_repo("r")
    monkeypatch.setenv(
        "GH_STUB_OUTPUT",
        json.dumps(
            [
                {
                    "headRefName": "feature",
                    "title": "Improve picker",
                    "author": {"login": "octocat"},
                    "createdAt": "2026-07-20T12:00:00Z",
                }
            ]
        ),
    )
    now = datetime(2026, 7, 24, 12, tzinfo=timezone.utc).timestamp()

    result = list_open(repo, now=now)

    assert result["feature"].title == "Improve picker"
    assert result["feature"].author == "octocat"
    assert result["feature"].days_open == 4
    assert gh_stub.invocations()[0][1:4] == ["pr", "list", "--state"]


def test_list_open_returns_empty_on_gh_failure(
    make_repo: Callable[..., Path],
    gh_stub: GhStub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_STUB_EXIT_CODE", "1")
    assert list_open(make_repo("r"), now=0.0) == {}
