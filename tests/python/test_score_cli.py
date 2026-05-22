"""CLI-layer tests for ``score sort``.

Exercises ``tmux_sessions.__main__.main`` with monkeypatched env,
``sys.stdin``, and ``sys.stdout`` plus a real ``tmp_path`` score file.
The pure-layer scenarios live in ``test_score.py``; here we only
verify env wiring, file reading, and stdin/stdout plumbing.
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import pytest
from tmux_sessions.__main__ import main


def _run_score_sort(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdin_text: str,
    boost_path: str,
    score_file: Path | None,
    half_life_days: str = "14",
    path_boost: str = "1.0",
) -> str:
    if score_file is None:
        monkeypatch.delenv("SCORE_FILE", raising=False)
    else:
        monkeypatch.setenv("SCORE_FILE", str(score_file))
    monkeypatch.setenv("TMUX_SESSIONS_SCORE_HALF_LIFE", half_life_days)
    monkeypatch.setenv("TMUX_SESSIONS_SCORE_PATH_BOOST", path_boost)

    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_text))
    monkeypatch.setattr("sys.stdout", stdout)

    rc = main(["score", "sort", boost_path])
    assert rc == 0
    return stdout.getvalue()


def test_cli_reads_score_file_and_orders_by_score(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    score_file = tmp_path / "scores.tsv"
    now = time.time()
    score_file.write_text(f"alpha\t1\t{now}\nbeta\t9\t{now}\n")

    out = _run_score_sort(
        monkeypatch,
        stdin_text="alpha\t/p/a\t/p/a\nbeta\t/p/b\t/p/b\n",
        boost_path="",
        score_file=score_file,
    )

    lines = out.splitlines()
    assert lines[0].startswith("beta")
    assert lines[1].startswith("alpha")


def test_cli_missing_score_file_treats_all_as_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    score_file = tmp_path / "does-not-exist.tsv"

    out = _run_score_sort(
        monkeypatch,
        stdin_text="alpha\t/p/a\t/p/a\nbeta\t/p/b\t/p/b\n",
        boost_path="",
        score_file=score_file,
    )

    assert len(out.splitlines()) == 2


def test_cli_score_update_creates_fresh_file_with_score_one(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    score_file = tmp_path / "scores.tsv"
    monkeypatch.setenv("SCORE_FILE", str(score_file))
    monkeypatch.setenv("TMUX_SESSIONS_SCORE_HALF_LIFE", "14")

    rc = main(["score", "update", "alpha"])
    assert rc == 0

    contents = score_file.read_text()
    assert contents.startswith("alpha\t1\t")


def test_cli_score_update_creates_parent_directory_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    score_file = tmp_path / "nested" / "dir" / "scores.tsv"
    monkeypatch.setenv("SCORE_FILE", str(score_file))
    monkeypatch.setenv("TMUX_SESSIONS_SCORE_HALF_LIFE", "14")

    rc = main(["score", "update", "alpha"])
    assert rc == 0
    assert score_file.is_file()
