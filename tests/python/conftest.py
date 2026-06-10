"""Shared pytest fixtures for the tmux_worktree_sessions Python tests.

``make_repo`` spins up a real git repo (with optional sibling bare
``origin``) under a tmpdir so subprocess-based helpers in
:mod:`tmux_worktree_sessions.git` can be exercised end-to-end. ``tmux_stub``,
``fzf_stub``, and ``curl_stub`` prepend programmable scripts in
``_stubs/`` onto PATH so subprocess calls land on canned responses.

The lightweight git/filesystem helpers (``worktree_add``,
``make_remote_only_branch``, ``touch_fetch_head``, ``entries_file``)
exist so individual tests don't reinvent the same multi-line subprocess
or write_text dance every time. They wrap shell-outs that are not the
behaviour under test, so collapsing them keeps each case focused on its
own assertion.
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


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
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


@pytest.fixture
def worktree_add() -> Callable[..., None]:
    """Return a helper that runs ``git worktree add`` with sensible defaults.

    Pass ``new_branch=True`` to create a brand-new branch (``-b``); pass
    ``detach=True`` for a detached worktree off ``HEAD``. Otherwise the
    branch is checked out as-is (must already exist).
    """

    def _add(
        repo: Path,
        path: Path,
        branch: str | None = None,
        *,
        new_branch: bool = False,
        detach: bool = False,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "-C", str(repo), "worktree", "add", "-q"]
        if detach:
            sha = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            cmd += ["--detach", str(path), sha]
        elif new_branch:
            assert branch, "new_branch=True requires a branch name"
            cmd += ["-b", branch, str(path)]
        else:
            assert branch, "non-detached worktree_add requires a branch name"
            cmd += [str(path), branch]
        subprocess.run(cmd, check=True, capture_output=True)

    return _add


@pytest.fixture
def make_remote_only_branch() -> Callable[[Path, str], None]:
    """Return a helper that creates ``refs/remotes/origin/<name>`` at HEAD.

    Used to simulate a branch that exists on the server only — locally
    unconfigured. The repo must already have an ``origin`` remote (i.e.
    ``make_repo(with_remote=True)``).
    """

    def _make(repo: Path, name: str) -> None:
        sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "-C", str(repo), "update-ref", f"refs/remotes/origin/{name}", sha],
            check=True,
            capture_output=True,
        )

    return _make


@pytest.fixture
def touch_fetch_head() -> Callable[[Path], None]:
    """Return a helper that creates an empty ``FETCH_HEAD`` for ``repo``.

    Used so :func:`fetch_is_stale` returns ``False`` and the picker does
    not spawn its background fetch helper during tests.
    """

    def _touch(repo: Path) -> None:
        common = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        common_path = Path(common) if Path(common).is_absolute() else repo / common
        (common_path / "FETCH_HEAD").touch()

    return _touch


@pytest.fixture
def entries_file(tmp_path: Path) -> Callable[[str], Path]:
    """Return a factory that writes picker entries TSV to a fresh tempfile."""

    def _make(content: str) -> Path:
        path = tmp_path / "entries"
        path.write_text(content)
        return path

    return _make


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set the env block every CLI integration test relies on.

    Pins ``HOME`` to ``tmp_path``, disables icons, points the score file
    at a tmpdir, and clears every ``TWS_*`` knob the parent shell may
    have leaked. Tests that need to override a specific knob still call
    ``monkeypatch.setenv`` directly afterwards. Returns the score-file
    path so tests can assert against it.
    """
    for key in (
        "TWS_PROJECTS_DIRS",
        "TWS_MAX_DEPTH",
        "TWS_STRIP_PREFIXES",
        "TWS_MANUAL_SESSIONS",
        "TWS_SCORE_HALF_LIFE",
        "TWS_SCORE_PATH_BOOST",
        "TWS_SCORES_FILE",
        "TWS_DEFAULT_BRANCH",
        "TWS_WORKTREES_DIR",
        "TWS_DEFAULT_WORKTREE_LAYOUT",
    ):
        monkeypatch.delenv(key, raising=False)
    score_file = tmp_path / "scores.tsv"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TWS_ICON_STYLE", "none")
    monkeypatch.setenv("SCORE_FILE", str(score_file))
    return score_file


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
