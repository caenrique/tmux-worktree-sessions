"""Pure-layer tests for :mod:`tmux_sessions.fetch_reload`.

The curl stub captures every POST so we can assert on the final
``change-header(...)+reload(cat ...)`` payload, the supplied port, and
the surviving reload when ``git fetch`` fails. Calls run synchronously
in the test process — the spinner thread exits before posting because
tmpdir repos resolve fetch+regen well under its 0.3s start delay.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from tmux_sessions.fetch_reload import fetch_and_reload
from tmux_sessions.picker import IconSet

from .conftest import CurlStub


def test_fetch_reload_posts_final_reload(
    make_repo: Callable[..., Path],
    curl_stub: CurlStub,
    tmp_path: Path,
) -> None:
    repo = make_repo("r", with_remote=True)
    tmpfile = tmp_path / "branch-entries"
    tmpfile.write_text("")

    fetch_and_reload(
        repo,
        tmpfile,
        12345,
        "header-base",
        icons=IconSet.from_style("ascii"),
    )

    log = curl_stub.text()
    assert "localhost:12345" in log
    assert "reload(cat" in log
    assert "header-base" in log


def test_fetch_reload_regenerates_entries_with_new_sentinel(
    make_repo: Callable[..., Path],
    curl_stub: CurlStub,
    tmp_path: Path,
) -> None:
    repo = make_repo("r", branches=("main", "feature"), with_remote=True)
    tmpfile = tmp_path / "branch-entries"
    tmpfile.write_text("")

    fetch_and_reload(
        repo,
        tmpfile,
        12346,
        "h",
        icons=IconSet.from_style("ascii"),
    )

    contents = tmpfile.read_text()
    assert "[new]" in contents
    assert "main" in contents


def test_fetch_reload_uses_supplied_port(
    make_repo: Callable[..., Path],
    curl_stub: CurlStub,
    tmp_path: Path,
) -> None:
    repo = make_repo("r", with_remote=True)
    tmpfile = tmp_path / "branch-entries"
    tmpfile.write_text("")

    fetch_and_reload(
        repo,
        tmpfile,
        59999,
        "h",
        icons=IconSet.from_style("ascii"),
    )

    assert "localhost:59999" in curl_stub.text()


def test_fetch_reload_still_posts_when_fetch_fails(
    make_repo: Callable[..., Path],
    curl_stub: CurlStub,
    tmp_path: Path,
) -> None:
    repo = make_repo("r")
    # Bogus remote forces `git fetch --all` to fail; the final reload
    # POST must still happen so the picker reflects local state.
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "/nonexistent/repo.git"],
        check=True,
        capture_output=True,
        text=True,
    )
    tmpfile = tmp_path / "branch-entries"
    tmpfile.write_text("")

    fetch_and_reload(
        repo,
        tmpfile,
        12348,
        "h",
        icons=IconSet.from_style("ascii"),
    )

    assert "reload(cat" in curl_stub.text()
