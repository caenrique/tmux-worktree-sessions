"""Shared pytest fixtures for the tmux_sessions Python tests.

``make_repo`` spins up a real git repo (with optional sibling bare
``origin``) under a tmpdir so subprocess-based helpers in
:mod:`tmux_sessions.git` can be exercised end-to-end. ``tmux_stub``,
``fzf_stub``, and ``curl_stub`` prepend programmable scripts in
``_stubs/`` onto PATH so subprocess calls land on canned responses.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TMUX_STUB_DIR = Path(__file__).parent / "_stubs"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[..., Path]:
    """Return a factory that creates a real git repo under ``tmp_path``.

    Default is a ``main`` branch with one initial commit. Pass
    ``with_remote=True`` to also create a sibling bare ``origin`` and
    run ``git remote set-head origin main``.
    """

    def _factory(
        name: str = "r",
        *,
        branches: Iterable[str] = ("main",),
        with_remote: bool = False,
        with_initial_commit: bool = True,
    ) -> Path:
        repo = tmp_path / name
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test")
        _git(repo, "config", "commit.gpgsign", "false")

        if with_initial_commit:
            (repo / "README").write_text("")
            _git(repo, "add", "README")
            _git(repo, "commit", "-q", "-m", "init")

        for b in branches:
            if b == "main":
                continue
            _git(repo, "branch", b)

        if with_remote and with_initial_commit:
            origin = tmp_path / f"{name}.git"
            subprocess.run(
                ["git", "init", "-q", "--bare", "-b", "main", str(origin)],
                check=True,
                capture_output=True,
                text=True,
            )
            _git(repo, "remote", "add", "origin", str(origin))
            _git(repo, "push", "-q", "--all", "origin")
            _git(repo, "remote", "set-head", "origin", "main")

        return repo

    return _factory


@dataclass
class TmuxStub:
    """Handle to a primed tmux stub on PATH for the duration of a test."""

    log: Path

    def invocations(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [line.split("\t") for line in self.log.read_text().splitlines() if line]


@pytest.fixture
def tmux_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., TmuxStub]:
    """Prepend the tmux stub to PATH and prime its env-driven state."""

    def _factory(
        *,
        sessions: str = "",
        new_id: str = "$99",
    ) -> TmuxStub:
        log = tmp_path / "tmux_stub.log"
        monkeypatch.setenv("PATH", f"{_TMUX_STUB_DIR}:{os.environ['PATH']}")
        monkeypatch.setenv("TMUX_STUB_LOG", str(log))
        monkeypatch.setenv("TMUX_STUB_SESSIONS", sessions)
        monkeypatch.setenv("TMUX_STUB_NEW_ID", new_id)
        return TmuxStub(log=log)

    return _factory


@dataclass
class FzfStub:
    """Handle to the fzf stub primed via env for one test."""

    queue: Path
    exit_queue: Path
    stdin_log: Path
    invocation_log: Path

    def respond(self, output: str, exit_code: int = 0) -> None:
        """Append one canned response to the stub's queue.

        Each fzf invocation pops the next block (separated by
        ``\\n###END###\\n``) and the next exit code from the queues.
        """
        with self.queue.open("a") as f:
            f.write(f"{output}\n###END###\n")
        with self.exit_queue.open("a") as f:
            f.write(f"{exit_code}\n")

    def esc(self) -> None:
        """Have the next fzf call exit 130 with empty stdout (Esc)."""
        self.respond("", 130)

    def invocations(self) -> list[list[str]]:
        if not self.invocation_log.exists():
            return []
        return [line.split("\t") for line in self.invocation_log.read_text().splitlines() if line]


@dataclass
class CurlStub:
    """Handle to the curl stub primed via env for one test."""

    log: Path

    def invocations(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [line.split("\t") for line in self.log.read_text().splitlines() if line]

    def text(self) -> str:
        if not self.log.exists():
            return ""
        return self.log.read_text()


@pytest.fixture
def curl_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CurlStub:
    """Prepend the curl stub to PATH and seed an empty log."""
    log = tmp_path / "curl.log"
    log.write_text("")
    monkeypatch.setenv("PATH", f"{_TMUX_STUB_DIR}:{os.environ['PATH']}")
    monkeypatch.setenv("CURL_STUB_LOG", str(log))
    return CurlStub(log=log)


@pytest.fixture
def fzf_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FzfStub:
    """Prepend the fzf stub to PATH and seed empty queues."""
    queue = tmp_path / "fzf.queue"
    exit_queue = tmp_path / "fzf.exit.queue"
    stdin_log = tmp_path / "fzf.stdin.log"
    invocation_log = tmp_path / "fzf.invocations.log"
    for f in (queue, exit_queue, stdin_log, invocation_log):
        f.write_text("")
    monkeypatch.setenv("PATH", f"{_TMUX_STUB_DIR}:{os.environ['PATH']}")
    monkeypatch.setenv("FZF_STUB_QUEUE", str(queue))
    monkeypatch.setenv("FZF_STUB_EXIT_QUEUE", str(exit_queue))
    monkeypatch.setenv("FZF_STUB_STDIN_LOG", str(stdin_log))
    monkeypatch.setenv("FZF_STUB_INVOCATION_LOG", str(invocation_log))
    return FzfStub(
        queue=queue,
        exit_queue=exit_queue,
        stdin_log=stdin_log,
        invocation_log=invocation_log,
    )
