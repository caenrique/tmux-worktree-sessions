"""Tests for the ``tmux-worktree-sessions.tmux`` TPM entry point.

The entry point reads ``@tws-*`` options via ``tmux show-option``
and registers a ``bind-key`` that invokes the Python dispatcher. These
tests stub tmux to canned option responses, run the script, and assert
on the recorded ``bind-key`` invocation row in ``TMUX_STUB_LOG``.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from .conftest import TmuxStub

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TMUX_TPM_ENTRY = _REPO_ROOT / "tmux-worktree-sessions.tmux"


def _run_tpm_entry(
    tmux_stub: TmuxStub,
    *,
    options: str,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["TMUX_STUB_LOG"] = str(tmux_stub.log)
    env["TMUX_STUB_OPTIONS"] = options
    return subprocess.run(
        ["bash", str(_TMUX_TPM_ENTRY)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _bind_key_row(tmux_stub: TmuxStub, key: str | None = None) -> str:
    """Return a tab-joined bind-key invocation row.

    With ``key=None`` returns the first bind-key invocation (back-compat
    for the existing session-key tests). With ``key`` set, returns the
    invocation that binds that key combo. ``-n`` lives at fields[2] in
    the recorded TSV row, so the key combo is at fields[3].
    """
    for fields in tmux_stub.invocations():
        if len(fields) >= 2 and fields[1] == "bind-key":
            if key is None:
                return "\t".join(fields)
            if len(fields) >= 4 and fields[3] == key:
                return "\t".join(fields)
    raise AssertionError(f"no bind-key invocation recorded for key={key!r}")


def test_binds_default_key(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    _run_tpm_entry(stub, options="")
    row = _bind_key_row(stub)
    assert "\tC-S-s\t" in row


def test_honours_custom_key(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    _run_tpm_entry(stub, options="@tws-key=M-x")
    row = _bind_key_row(stub)
    assert "\tM-x\t" in row


def test_expands_home_in_projects_dir(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    _run_tpm_entry(stub, options="@tws-projects-dir=$HOME/MyProjects")
    row = _bind_key_row(stub)
    home = os.environ["HOME"]
    assert f"TWS_PROJECTS_DIRS='{home}/MyProjects'" in row
    assert "$HOME/MyProjects" not in row


def test_expands_home_in_strip_prefixes(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    _run_tpm_entry(stub, options="@tws-strip-prefixes=$HOME/Projects $HOME/work")
    row = _bind_key_row(stub)
    home = os.environ["HOME"]
    assert f"TWS_STRIP_PREFIXES='{home}/Projects {home}/work'" in row


def test_forwards_numeric_option_values(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    _run_tpm_entry(
        stub,
        options=("@tws-max-depth=8\n@tws-score-half-life=30\n@tws-score-path-boost=2.5"),
    )
    row = _bind_key_row(stub)
    assert "TWS_MAX_DEPTH='8'" in row
    assert "TWS_SCORE_HALF_LIFE='30'" in row
    assert "TWS_SCORE_PATH_BOOST='2.5'" in row


def test_invokes_python_dispatcher(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    _run_tpm_entry(stub, options="")
    row = _bind_key_row(stub)
    assert f"PYTHONPATH='{_REPO_ROOT}/scripts'" in row
    assert "python3 -m tmux_worktree_sessions sessions manage" in row


def test_forwards_default_worktrees_dir(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    _run_tpm_entry(stub, options="")
    row = _bind_key_row(stub)
    assert "TWS_WORKTREES_DIR='.worktrees'" in row


def test_forwards_worktrees_dir_override(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    _run_tpm_entry(stub, options="@tws-worktrees-dir=trees")
    row = _bind_key_row(stub)
    assert "TWS_WORKTREES_DIR='trees'" in row


def test_forwards_default_worktree_layout_default(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    _run_tpm_entry(stub, options="")
    row = _bind_key_row(stub)
    assert "TWS_DEFAULT_WORKTREE_LAYOUT='subfolder'" in row


def test_forwards_default_worktree_layout_override(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    _run_tpm_entry(stub, options="@tws-default-worktree-layout=sibling")
    row = _bind_key_row(stub)
    assert "TWS_DEFAULT_WORKTREE_LAYOUT='sibling'" in row


def test_binds_default_worktree_key(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    _run_tpm_entry(stub, options="")
    row = _bind_key_row(stub, key="C-S-w")
    assert "python3 -m tmux_worktree_sessions worktree manage" in row


def test_honours_custom_worktree_key(tmux_stub: Callable[..., TmuxStub]) -> None:
    stub = tmux_stub()
    _run_tpm_entry(stub, options="@tws-worktree-key=M-w")
    row = _bind_key_row(stub, key="M-w")
    assert "python3 -m tmux_worktree_sessions worktree manage" in row


def test_worktree_bind_carries_same_env_block(tmux_stub: Callable[..., TmuxStub]) -> None:
    """Both bind-keys should share the env block, so configuration set for
    the session picker also reaches the standalone worktree picker."""
    stub = tmux_stub()
    _run_tpm_entry(
        stub,
        options="@tws-projects-dir=$HOME/MyProjects\n@tws-worktrees-dir=trees",
    )
    sessions_row = _bind_key_row(stub, key="C-S-s")
    worktree_row = _bind_key_row(stub, key="C-S-w")
    home = os.environ["HOME"]
    for row in (sessions_row, worktree_row):
        assert f"TWS_PROJECTS_DIRS='{home}/MyProjects'" in row
        assert "TWS_WORKTREES_DIR='trees'" in row


def _set_option_row(tmux_stub: TmuxStub, option: str) -> str | None:
    """Return the last ``set-option ... <option> <value>`` invocation, or None."""
    for fields in reversed(tmux_stub.invocations()):
        if len(fields) >= 4 and fields[1] == "set-option" and option in fields:
            return "\t".join(fields)
    return None


def test_substitutes_session_display_name_in_status_left(
    tmux_stub: Callable[..., TmuxStub],
) -> None:
    stub = tmux_stub()
    _run_tpm_entry(stub, options="status-left=#{session_display_name} | %H:%M")
    row = _set_option_row(stub, "status-left")
    assert row is not None, "expected set-option for status-left"
    assert "#{session_display_name}" not in row
    assert "#(" in row
    assert "tmux_worktree_sessions sessions display-name" in row
    assert "| %H:%M" in row


def test_substitutes_session_display_name_in_status_right(
    tmux_stub: Callable[..., TmuxStub],
) -> None:
    stub = tmux_stub()
    _run_tpm_entry(stub, options="status-right=foo #{session_display_name} bar")
    row = _set_option_row(stub, "status-right")
    assert row is not None, "expected set-option for status-right"
    assert "#{session_display_name}" not in row
    assert "tmux_worktree_sessions sessions display-name" in row


def test_does_not_touch_status_options_without_placeholder(
    tmux_stub: Callable[..., TmuxStub],
) -> None:
    stub = tmux_stub()
    _run_tpm_entry(stub, options="status-left=plain | %H:%M\nstatus-right=plain")
    assert _set_option_row(stub, "status-left") is None
    assert _set_option_row(stub, "status-right") is None


def test_substituted_command_carries_plugin_pythonpath(
    tmux_stub: Callable[..., TmuxStub],
) -> None:
    stub = tmux_stub()
    _run_tpm_entry(stub, options="status-left=#{session_display_name}")
    row = _set_option_row(stub, "status-left")
    assert row is not None
    assert f"PYTHONPATH='{_REPO_ROOT}/scripts'" in row


def test_substituted_command_carries_strip_prefixes(
    tmux_stub: Callable[..., TmuxStub],
) -> None:
    stub = tmux_stub()
    home = os.environ["HOME"]
    _run_tpm_entry(
        stub,
        options=("status-left=#{session_display_name}\n@tws-strip-prefixes=$HOME/Projects"),
    )
    row = _set_option_row(stub, "status-left")
    assert row is not None
    assert f"TWS_STRIP_PREFIXES='{home}/Projects'" in row


@pytest.fixture(autouse=True)
def _clean_stub_log_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop stale TMUX_STUB_* leakage from the parent shell."""
    for key in (
        "TMUX_STUB_SESSIONS",
        "TMUX_STUB_CURRENT",
        "TMUX_STUB_PREV",
        "TMUX_STUB_PANE_PATH",
        "TMUX_STUB_NEW_ID",
        "TMUX_STUB_OPTIONS",
    ):
        monkeypatch.delenv(key, raising=False)
